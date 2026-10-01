import base64
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from github import Github
import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components

# --- GITHUB KONFİGÜRASYONU & TOKEN YÖNETİMİ ---
DEFAULT_GITHUB_TOKEN = "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"

if "GITHUB_TOKEN" in st.secrets:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
elif os.environ.get("GITHUB_TOKEN"):
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
else:
    GITHUB_TOKEN = DEFAULT_GITHUB_TOKEN

GITHUB_REPO = "istestate-meric/raporlama"
DB_FILE_NAME = "imar_veritabani.json"

# WeasyPrint kütüphanesinin import kontrolü
try:
    from weasyprint import CSS, HTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="Fizibilite Portalı",
    page_icon="🏢",
    layout="wide",
)

# --- TCMB CANLI DÖVİZ KURU SERVİSİ ---
@st.cache_data(ttl=300)
def get_live_exchange_rates():
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        usd_rate, eur_rate = 0.0, 0.0
        
        for currency in root.findall('Currency'):
            code = currency.get('CurrencyCode')
            if code == 'USD':
                usd_rate = float(currency.find('ForexSelling').text)
            elif code == 'EUR':
                eur_rate = float(currency.find('ForexSelling').text)
                
        return {
            "USD": usd_rate if usd_rate > 0 else 34.00,
            "EUR": eur_rate if eur_rate > 0 else 37.50
        }
    except Exception:
        return {"USD": 34.00, "EUR": 37.50}

rates = get_live_exchange_rates()

# --- ÖZEL KURUMSAL STİL ---
st.markdown("""
<style>
    .stSelectbox, .stNumberInput, .stSlider {
        background-color: #ffffff;
        border-radius: 6px;
    }
    div[data-baseweb="select"] > div {
        border-radius: 6px;
        border-color: #cbd5e1;
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- SİDEBAR: EN ÜST KISIM CANLI DÖVİZ KURLARI ---
st.sidebar.markdown(f"""
<div style="background: rgba(15, 23, 42, 0.95); border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 10px; padding: 12px 14px; margin-bottom: 15px; color: #ffffff; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
    <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px; display: flex; align-items: center; justify-content: space-between;">
        <span>💱 Canlı Döviz Kurları</span>
        <span style="font-size: 9px; color: #38bdf8; font-weight: 600;">TCMB</span>
    </div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="font-size: 12px; font-weight: 600; color: #e2e8f0;">USD / TRY:</span>
        <span style="font-size: 13px; font-weight: 700; color: #38bdf8; font-family: monospace;">₺{rates['USD']:.2f}</span>
    </div>
    <div style="width: 100%; height: 1px; background-color: rgba(255, 255, 255, 0.15); margin: 2px 0 6px 0;"></div>
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; font-weight: 600; color: #e2e8f0;">EUR / TRY:</span>
        <span style="font-size: 13px; font-weight: 700; color: #38bdf8; font-family: monospace;">₺{rates['EUR']:.2f}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# --- DİNAMİK FONKSİYON ADI ÇÖZÜMLEME VE FİLTRELEME MOTORU ---
def clean_fonksiyon_adi(name):
    if not name:
        return ""
    n = str(name).upper().strip()
    n = n.replace("FONKSİYON ADI", "").replace("FONKSIYON ADI", "").strip()
    
    gecersiz_ifadeler = [
        "-", "--", ".", ",", "0", "N/A", "İMAR DURUMU", "İMAR DURUMU BİLGİLERİ",
        "PARK", "PARK ALANI", "ÇOCUK PARKI", "YEŞİL ALAN", "TEKNİK ALTYAPI", "TRAFO",
        "CAMİ", "İBADET YERİ", "OKUL", "LİSE", "İLKÖĞRETİM", "ANAOKULU",
        "KÜLTÜREL", "SOSYAL TESİS", "BELEDİYE HİZMET ALANI", "YOL", "AÇIK OTOPARK", ""
    ]
    
    if n in gecersiz_ifadeler or any(x in n for x in ["PARK", "YEŞİL", "TEKNİK", "İBADET", "OKUL", "YOL", "TESİS", "TRAFO"]):
        return ""
    if "%" in n or "M²" in n or "M2" in n:
        return ""
    if re.match(r"^[\d\.,\s\-%]+$", n):
        return ""
    return n

def get_allowed_project_types(fonk_adi):
    f_upper = fonk_adi.upper()
    if ("TİCARET" in f_upper or "TICARI" in f_upper) and ("KONUT" in f_upper or "MESKEN" in f_upper):
        return ["Karma Proje (Eşit Oranlı Ticari + Konut)"]
    elif "TURİZM" in f_upper or "TURIZM" in f_upper:
        if "KONUT" in f_upper:
            return ["Otel + Konut Karma Proje", "Otel / Turizm Tesisi"]
        elif "TİCARET" in f_upper or "TICARI" in f_upper:
            return ["Otel + Ticari AVM Kompleksi", "Otel / Turizm Tesisi"]
        else:
            return ["Otel / Turizm Tesisi"]
    elif any(k in f_upper for k in ["TİCARET", "TICARI", "İŞ MERKEZİ", "MERKEZİ İŞ"]):
        return ["Ticari / Ofis Kompleksi"]
    elif any(k in f_upper for k in ["VİLLA", "VILLA"]):
        return ["Lüks Villa / Müstakil Proje"]
    elif any(k in f_upper for k in ["KONUT", "MESKEN", "GELİŞME"]):
        return ["Standart Konut / Apartman", "Üst Segment Konut / Rezidans", "Lüks Villa / Müstakil Proje"]
    else:
        return ["Standart Konut / Apartman", "Üst Segment Konut / Rezidans", "Ticari / Ofis Kompleksi"]

def get_allowed_pool_options(project_type):
    if "Villa" in project_type:
        return ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"]
    elif "Ticari" in project_type or "AVM" in project_type:
        return ["Havuz İptal / Yapılmayacak"]
    else:
        return ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"]

def get_project_size_ranges(project_type):
    p_up = project_type.upper()
    if "VİLLA" in p_up or "VILLA" in p_up:
        return 180, 600, 280, 10
    elif "REZİDANS" in p_up or "REZIDANS" in p_up or "ÜST SEGMENT" in p_up:
        return 90, 250, 130, 5
    elif "TİCARİ" in p_up or "TICARI" in p_up or "OFİS" in p_up:
        return 40, 500, 120, 10
    elif "KARMA" in p_up:
        return 75, 200, 110, 5
    else:
        return 55, 150, 90, 5

BASE_DIR = os.path.abspath(os.getcwd())
DB_FILE = os.path.join(BASE_DIR, DB_FILE_NAME)

def pull_from_github():
    if not GITHUB_TOKEN:
        return None
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        file_content = repo.get_contents(DB_FILE_NAME, ref="main")
        decoded_content = base64.b64decode(file_content.content).decode("utf-8")
        data = json.loads(decoded_content)
        if isinstance(data, dict):
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data
    except Exception:
        pass
    return None

def push_to_github(data_dict):
    if not GITHUB_TOKEN:
        return
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        json_str = json.dumps(data_dict, ensure_ascii=False, indent=4)
        try:
            contents = repo.get_contents(DB_FILE_NAME, ref="main")
            repo.update_file(
                path=contents.path,
                message="Otomatik veritabanı güncellemesi [Streamlit App]",
                content=json_str,
                sha=contents.sha,
                branch="main"
            )
        except Exception:
            repo.create_file(
                path=DB_FILE_NAME,
                message="Otomatik veritabanı oluşturuldu [Streamlit App]",
                content=json_str,
                branch="main"
            )
    except Exception as e:
        st.sidebar.error(f"GitHub Sync Hatası: {e}")

def load_persistent_db():
    remote_data = pull_from_github()
    if remote_data is not None:
        return remote_data
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_persistent_db(db_data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db_data, f, ensure_ascii=False, indent=4)
        st.session_state["parcel_db"] = db_data
        push_to_github(db_data)
    except Exception as e:
        st.error(f"Veritabanı kaydedilirken hata oluştu: {e}")

if "parcel_db" not in st.session_state:
    st.session_state["parcel_db"] = load_persistent_db()

def get_image_base64(path):
    full_path = os.path.join(BASE_DIR, path)
    if os.path.exists(full_path):
        try:
            with open(full_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""
    return ""

img1_base64 = get_image_base64("istestate_logo.png")
img2_base64 = get_image_base64("meric_insaat_emlak_logo.png")

img1_tag = f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 55px; width: auto; object-fit: contain;'>" if img1_base64 else "<h4 style='color:#1e3a8a; margin:0;'>İSTESTATE</h4>"
img2_tag = f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 55px; width: auto; object-fit: contain;'>" if img2_base64 else "<h4 style='color:#1e3a8a; margin:0;'>MERİÇ İNŞAAT</h4>"

def get_realistic_market_pricing(mahalle_adi, proje_tipi, havuz_secenegi, usd_rate):
    mahalle_base_tl = {
        "ACARLAR": 165000, "ANADOLU HİSARI": 150000, "KANLICA": 145000,
        "GÖKSU": 130000, "GÖRELE": 135000, "RİVA": 140000, "ÇİFTLİK": 130000,
        "BAKLACI": 115000, "KAVACIK": 110000, "ÇENGELDERE": 120000,
        "YAVUZ SELİM": 95000, "FATİH": 90000, "SOĞUKSU": 110000,
        "PAŞABAHÇE": 105000, "VARSAYILAN": 115000
    }
    clean_mahalle = mahalle_adi.upper().replace("İ", "I").replace("Ç", "C").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").strip()
    base_tl = mahalle_base_tl.get(clean_mahalle, mahalle_base_tl["VARSAYILAN"])
    
    proje_carpanlari = {
        "Lüks Villa / Müstakil Proje": {"satis_mod": 1.65, "maliyet_mod": 1450},
        "Üst Segment Konut / Rezidans": {"satis_mod": 1.30, "maliyet_mod": 1200},
        "Standart Konut / Apartman": {"satis_mod": 1.00, "maliyet_mod": 950},
        "Ticari / Ofis Kompleksi": {"satis_mod": 1.40, "maliyet_mod": 1150},
        "Karma Proje (Eşit Oranlı Ticari + Konut)": {"satis_mod": 1.35, "maliyet_mod": 1180},
        "Otel + Konut Karma Proje": {"satis_mod": 1.45, "maliyet_mod": 1300},
        "Otel + Ticari AVM Kompleksi": {"satis_mod": 1.50, "maliyet_mod": 1350},
        "Otel / Turizm Tesisi": {"satis_mod": 1.55, "maliyet_mod": 1400},
    }
    p_conf = proje_carpanlari.get(proje_tipi, proje_carpanlari["Standart Konut / Apartman"])
    
    pool_cost_addon = 0.0
    pool_price_addon = 0.0
    if "İptal" not in havuz_secenegi:
        if "Müstakil" in havuz_secenegi:
            pool_cost_addon = 60.0
            pool_price_addon = 300.0
        else:
            pool_cost_addon = 35.0
            pool_price_addon = 180.0
            
    satis_fiyati_usd = round(((base_tl * p_conf["satis_mod"]) / usd_rate) + pool_price_addon, 2)
    maliyet_fiyati_usd = float(p_conf["maliyet_mod"]) + pool_cost_addon
    return satis_fiyati_usd, maliyet_fiyati_usd

def get_best_project_type_by_margin(fonk_adi, mahalle_adi, usd_rate):
    allowed_types = get_allowed_project_types(fonk_adi)
    best_pt = allowed_types[0]
    best_pool = get_allowed_pool_options(best_pt)[0]
    max_margin = -9999.0
    for pt in allowed_types:
        for pool in get_allowed_pool_options(pt):
            s_price, c_cost = get_realistic_market_pricing(mahalle_adi, pt, pool, usd_rate)
            if c_cost > 0:
                margin = (s_price - c_cost) / c_cost
                if margin > max_margin:
                    max_margin = margin
                    best_pt = pt
                    best_pool = pool
    return best_pt, best_pool

def parse_tr_float(val_str):
    if not val_str:
        return 0.0
    s = str(val_str).strip()
    if "-" in s and not re.match(r"^\d+[\.,]\d+\s*-\s*\d+[\.,]\d+$", s):
        s = s.split("-")[-1]
    s = re.sub(r"[^\d\.,]", "", s).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(".") > s.rfind(","):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_kaks_val(val_str):
    if not val_str:
        return 0.0
    nums = re.findall(r"[\d\.,]+", str(val_str))
    parsed_vals = []
    for num_s in nums:
        v = parse_tr_float(num_s)
        if 0.05 <= v <= 10.0:
            parsed_vals.append(v)
    return max(parsed_vals) if parsed_vals else 0.0

def detect_terk_status(text, toplam_alan, fonksiyonlar):
    text_upper = text.upper()
    kesin_terk_yapilmis = [
        "TERKİ YAPILMIŞTIR", "TERKİ YAPILMIŞ", "TERK YAPILMIŞTIR", "TERK YAPILMIŞ",
        "KAMUYA TERK EDİLMİŞTİR", "YOLA TERKİ YAPILMIŞTIR", "TERK EDİLMİŞTİR",
        "TERK: YOK", "TERK YOK", "YOLA TERK: 0", "TERK MİKTARI: 0", "NET PARSEL",
        "TERKSİZ", "TERK GEREKMEMEKTEDİR", "İFRAZ GÖRMÜŞ", "TAPU ALANI NET"
    ]
    for kw in kesin_terk_yapilmis:
        if kw in text_upper and "YAPILMAMIŞTIR" not in text_upper:
            return True
    return False

def parse_imar_pdf(uploaded_file):
    parcel_data = {
        "filename": uploaded_file.name,
        "mahalle": "BİLİNMİYOR",
        "ada": "0",
        "parsel": "0",
        "toplam_alan": 0.0,
        "terk_yapilmis_mi": False,
        "fonksiyonlar": []
    }
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += "\n" + (page.extract_text() or "")
                tables = page.extract_tables() or []
                for table in tables:
                    for r_idx, row in enumerate(table):
                        cells = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
                        joined_row_str = " ".join(cells).upper()
                        if any(kw in joined_row_str for kw in ["KONUT", "TİCARET", "TİCARİ", "PARK", "VİLLA", "GELİŞME", "EMSAL", "KAKS"]):
                            f_name = ""
                            f_taks = 0.0
                            f_kaks = 0.0
                            f_m2 = 0.0
                            for c in cells:
                                c_up = c.upper()
                                if any(x in c_up for x in ["KONUT", "TİCARET", "TİCARİ", "PARK", "VİLLA", "GELİŞME"]):
                                    cleaned = clean_fonksiyon_adi(c)
                                    if cleaned:
                                        f_name = cleaned
                                elif "TAKS" in c_up:
                                    for num_str in re.findall(r"([\d\.,]+)", c):
                                        val = parse_tr_float(num_str)
                                        if 0 < val <= 1.0:
                                            f_taks = val
                                elif any(k in c_up for k in ["KAKS", "EMSAL", "EMS", "E:"]):
                                    f_kaks = parse_kaks_val(c)
                            if f_name:
                                parcel_data["fonksiyonlar"].append({
                                    "fonksiyon_adi": f_name,
                                    "taks": f_taks,
                                    "kaks": f_kaks,
                                    "giren_m2": f_m2
                                })
                
                global_kaks_val = 0.0
                for gkm in re.findall(r"(?:EMSAL|KAKS|EMS|E)\s*[:=\s]*([\d\.,\s/-]+)", full_text, re.IGNORECASE):
                    val = parse_kaks_val(gkm)
                    if val > 0:
                        global_kaks_val = val
                        break
                        
                for f in parcel_data["fonksiyonlar"]:
                    if f["kaks"] <= 0 and global_kaks_val > 0:
                        f["kaks"] = global_kaks_val
                        
                m_m = re.search(r"Mahalle\s*[:\|]\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
                a_m = re.search(r"Ada\s*[:\|]\s*(\d+)", full_text)
                p_m = re.search(r"Parsel\s*[:\|]\s*(\d+)", full_text)
                al_m = re.search(r"Alan\s*\*?\s*[:\|]\s*([\d\.,]+)\s*m²", full_text)
                
                if m_m: parcel_data["mahalle"] = m_m.group(1).upper()
                if a_m: parcel_data["ada"] = str(a_m.group(1)).strip()
                if p_m: parcel_data["parsel"] = str(p_m.group(1)).strip()
                if al_m and parcel_data["toplam_alan"] == 0.0:
                    parcel_data["toplam_alan"] = parse_tr_float(al_m.group(1))
                    
                if not parcel_data["fonksiyonlar"]:
                    parcel_data["fonksiyonlar"].append({
                        "fonksiyon_adi": "KONUT ALANI",
                        "taks": 0.0,
                        "kaks": global_kaks_val,
                        "giren_m2": parcel_data["toplam_alan"]
                    })
                parcel_data["terk_yapilmis_mi"] = detect_terk_status(full_text, parcel_data["toplam_alan"], parcel_data["fonksiyonlar"])
    except Exception:
        pass
    return parcel_data

def get_parcel_function_breakdown(p, emsal_artis_orani=1.30):
    toplam_arsa_m2 = p.get("toplam_alan", 0.0)
    is_terkli = p.get("terk_yapilmis_mi", False)
    fonks_list = p.get("fonksiyonlar", [])
    
    valid_sub_items = []
    for f in fonks_list:
        fn = clean_fonksiyon_adi(f.get("fonksiyon_adi", ""))
        if not fn or any(x in fn for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
            continue
        active_kaks = f.get("kaks", 0.0)
        if active_kaks <= 0:
            continue
        valid_sub_items.append((f, fn, active_kaks))
        
    if not valid_sub_items:
        return []
        
    net_arsa_toplam = toplam_arsa_m2 if is_terkli else (toplam_arsa_m2 * 0.7)
    temp_results = []
    for f, base_fonk_name, active_kaks in valid_sub_items:
        net_arsa_payi = net_arsa_toplam / len(valid_sub_items)
        brut_insaat = net_arsa_payi * active_kaks * emsal_artis_orani
        temp_results.append({
            "base_fonksiyon_adi": base_fonk_name,
            "taks": f.get("taks", 0.0),
            "kaks": active_kaks,
            "net_arsa_payi": net_arsa_payi,
            "bahce_kullanim_alani": net_arsa_payi,
            "brut_insaat": brut_insaat
        })
    return temp_results

# --- HEADER BANNER ---
st.markdown(f"""
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; padding: 20px 25px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04); margin-bottom: 20px;">
    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 15px; width: 100%;">
        <div style="display: flex; align-items: center; justify-content: center; gap: 40px; width: 100%;">
            <div>{img1_tag}</div>
            <div>{img2_tag}</div>
        </div>
        <div style="text-align: center; border-top: 1px solid #f1f5f9; padding-top: 12px; width: 100%;">
            <p style='color: #0f172a; font-size: 20px; font-weight: 800; margin: 0; letter-spacing: 0.5px;'>Akıllı Gayrimenkul Geliştirme ve Fizibilite Portalı</p>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

st.sidebar.header("📁 İmar Belgesi Yükleme")
uploaded_files = st.sidebar.file_uploader("İmar Durum Raporu (PDF) Seçin", type=["pdf"], accept_multiple_files=True)

just_uploaded_keys = []
if uploaded_files:
    current_db = st.session_state["parcel_db"]
    for uploaded_file in uploaded_files:
        p_data = parse_imar_pdf(uploaded_file)
        unique_key = f"{p_data['mahalle']} | Ada: {p_data['ada']} - Parsel: {p_data['parsel']}"
        current_db[unique_key] = p_data
        just_uploaded_keys.append(unique_key)
    save_persistent_db(current_db)

st.sidebar.divider()
st.sidebar.subheader("🎯 Rapor İçin Parsel Seçimi & Arama")
all_db_keys = list(st.session_state["parcel_db"].keys())

if all_db_keys:
    unique_adas = sorted(list(set([str(p_data.get("ada", "0")).strip() for p_data in st.session_state["parcel_db"].values()])))
    selected_ada_filter = st.sidebar.selectbox("Ada Numarasına Göre Filtrele:", options=["Seçiniz..."] + unique_adas)
    
    filtered_keys = [
        k for k, p_data in st.session_state["parcel_db"].items()
        if str(p_data.get("ada", "")).strip() == str(selected_ada_filter).strip()
    ] if selected_ada_filter != "Seçiniz..." else all_db_keys
    
    selected_keys = st.sidebar.multiselect("Raporlanacak Parselleri Seçin:", options=filtered_keys, default=[k for k in just_uploaded_keys if k in filtered_keys] or filtered_keys[:1])
else:
    selected_keys = []

if selected_keys:
    active_parcel_db = {k: st.session_state["parcel_db"][k] for k in selected_keys}
    emsal_artis_orani = 1.30
    first_mahalle = list(active_parcel_db.values())[0].get("mahalle", "VARSAYILAN")
    
    is_modeli = st.selectbox("İş Modeli / Rapor Türü", options=["Kat Karşılığı Proje Raporu", "Doğrudan Satılık / Arsa Yatırım Raporu"], key="global_is_modeli")
    
    unique_active_functions = set()
    for p in active_parcel_db.values():
        for item in get_parcel_function_breakdown(p, emsal_artis_orani):
            if item["brut_insaat"] > 0:
                unique_active_functions.add(item["base_fonksiyon_adi"])
    if not unique_active_functions:
        unique_active_functions = {"KONUT ALANI"}

    function_configs = {}
    for idx, fonk_adi in enumerate(unique_active_functions):
        opt_pt, opt_pool = get_best_project_type_by_margin(fonk_adi, first_mahalle, rates["USD"])
        auto_satis, auto_maliyet = get_realistic_market_pricing(first_mahalle, opt_pt, opt_pool, rates["USD"])
        for key, p in active_parcel_db.items():
            for item in get_parcel_function_breakdown(p, emsal_artis_orani):
                if item["base_fonksiyon_adi"] == fonk_adi and item["brut_insaat"] > 0:
                    calc_adet = max(1, round(item["brut_insaat"] / 120))
                    function_configs[f"{key}_{fonk_adi}"] = {
                        "proje_tipi": opt_pt,
                        "adet": int(calc_adet),
                        "havuz_mod": opt_pool,
                        "havuz_m2": 30.0,
                        "maliyet": auto_maliyet,
                        "satis": auto_satis
                    }

    total_ciro_usd = 0.0
    total_maliyet_usd = 0.0
    müteahhit_hissesi_ciro = 0.0
    arsa_payi_orani = 50.0

    for key, p in active_parcel_db.items():
        for item in get_parcel_function_breakdown(p, emsal_artis_orani):
            brut = item["brut_insaat"]
            conf = function_configs.get(f"{key}_{item['base_fonksiyon_adi']}")
            if brut > 0 and conf:
                total_ciro_usd += (brut * 1.5) * conf["satis"]
                total_maliyet_usd += brut * conf["maliyet"]

    müteahhit_hissesi_ciro = total_ciro_usd * 0.5
    toplam_net_kar_usd = müteahhit_hissesi_ciro - total_maliyet_usd
    yg_orani = (toplam_net_kar_usd / total_maliyet_usd * 100) if total_maliyet_usd > 0 else 0

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Seçilen Parseller & İnşaat Alanı",
        "🏛 Mimari Fizibilite",
        "📑 Proje Raporu & Fizibilite",
        "🖨 Rapor Ön İzleme & PDF",
        "🗄 Veritabanı & Arşiv",
        "📱 Sosyal Medya Stüdyosu"
    ])

    with tab1:
        st.subheader("📊 Metraj Özeti")
        st.info(f"Seçili Parsel Sayısı: {len(active_parcel_db)}")

    with tab2:
        st.subheader("🏛 Mimari Fizibilite")

    with tab3:
        st.subheader("📑 Finansal Fizibilite")

    with tab4:
        st.subheader("🖨 Rapor Ön İzleme")

    with tab5:
        st.subheader("🗄 Arşiv")

    # =========================================================================
    # TAB 6: 📱 SOSYAL MEDYA STÜDYOSU (YAPAY ZEKA DESTEKLİ .PNG & .MP4 ÜRETİCİ)
    # =========================================================================
    with tab6:
        st.subheader("📱 Yapay Zeka Destekli Sosyal Medya Stüdyosu")
        st.markdown("Sosyal medya hesaplarınızda doğrudan paylaşabileceğiniz **.png** formatında fotoğraf kartları ve **.mp4** formatında çok sahneli dinamik dikey reklam filmleri üretin. Finansal bilgiler gizlenmiş olup arazi metrajları yalnızca **dönüm** cinsinden gösterilmektedir.")

        if active_parcel_db:
            first_p_key = list(active_parcel_db.keys())[0]
            p_sample = active_parcel_db[first_p_key]
            mahalle_adi = p_sample.get("mahalle", "BİLİNMİYOR")
            toplam_m2 = sum(p.get("toplam_alan", 0.0) for p in active_parcel_db.values())
            
            donum_tam_sayi = max(1, round(toplam_m2 / 1000.0))
            toplam_donum_str = f"Yaklaşık {donum_tam_sayi} Dönüm"
            
            sample_project_type = "Lüks Konut / Arsa Geliştirme Projesi"
            sample_pool_mod = "Havuzlu Konsept"
            for k, conf in function_configs.items():
                sample_project_type = conf.get("proje_tipi", sample_project_type)
                sample_pool_mod = conf.get("havuz_mod", sample_pool_mod)
                break

            render_col1, render_col2 = st.columns([1, 2])
            with render_col1:
                render_style = st.selectbox(
                    "Mimari Render Stili:",
                    options=[
                        "Modern Minimalist & Cam",
                        "Ultra-Lüks Neo-Klasik",
                        "Doğayla Uyumlu Ahşap & Taş",
                        "Dramatik Akşam İllüminasyonu"
                    ],
                    key="global_render_style_select"
                )

            style_details = {
                "Modern Minimalist & Cam": {
                    "bg": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?q=80&w=1200&auto=format&fit=crop",
                    "prompt": "modern minimalist architecture, floor-to-ceiling glass windows, slick concrete finishes, open floor plans, linear LED lighting, realistic photography"
                },
                "Ultra-Lüks Neo-Klasik": {
                    "bg": "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?q=80&w=1200&auto=format&fit=crop",
                    "prompt": "ultra-luxury neo-classical mansion, elegant stone pillars, symmetrical facade, ornate moldings, marble fountains, majestic entrance, high-end architectural photo"
                },
                "Doğayla Uyumlu Ahşap & Taş": {
                    "bg": "https://images.unsplash.com/photo-1500382017468-9049fed747ef?q=80&w=1200&auto=format&fit=crop",
                    "prompt": "biophilic organic architecture, natural wood siding, raw stone walls, lush green roofs, integrated forest landscape, warm ambient sunlight"
                },
                "Dramatik Akşam İllüminasyonu": {
                    "bg": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?q=80&w=1200&auto=format&fit=crop",
                    "prompt": "dramatic twilight dusk render, warm architectural spot lighting, glowing swimming pool reflections, starry sky backdrop, cinematic atmosphere"
                }
            }

            curr_style = style_details.get(render_style, style_details["Modern Minimalist & Cam"])
            midjourney_prompt = f"Architectural rendering of a {sample_project_type} in Beykoz Istanbul on a {toplam_donum_str} plot, {curr_style['prompt']}, ultra-realistic, 8k resolution, photorealistic photography, cinematic lighting, --ar 9:16 --v 6.0"

            with render_col2:
                st.text_area("🎯 Kopyalanabilir Midjourney / DALL-E 3 Promptu:", value=midjourney_prompt, height=85)

            st.divider()

            st.markdown("### 2. 🎬 Canlı İndirilebilir 9:16 Medya Stüdyosu (.png & .mp4)")
            
            logo1_data = f"data:image/png;base64,{img1_base64}" if img1_base64 else ""
            logo2_data = f"data:image/png;base64,{img2_base64}" if img2_base64 else ""

            studio_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <meta charset="utf-8">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
            <style>
                * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                body {{ margin: 0; padding: 0; background: #0f172a; color: #ffffff; display: flex; flex-direction: column; align-items: center; }}
                
                .studio-container {{ width: 100%; max-width: 420px; margin: 0 auto; }}
                .tabs-header {{ display: flex; gap: 8px; margin-bottom: 12px; }}
                .tab-btn {{
                    flex: 1; padding: 10px; background: #1e293b; color: #94a3b8; border: 1px solid #334155;
                    font-weight: 700; border-radius: 8px; cursor: pointer; font-size: 12px; text-align: center;
                }}
                .tab-btn.active {{ background: #2563eb; color: #ffffff; border-color: #3b82f6; }}
                
                .tab-content {{ display: none; }}
                .tab-content.active {{ display: block; }}

                /* 9:16 CARD STYLES */
                #render-card {{
                    width: 360px; height: 640px; margin: 0 auto;
                    background: linear-gradient(rgba(15, 23, 42, 0.75), rgba(15, 23, 42, 0.90)), url('{curr_style['bg']}') center/cover no-repeat;
                    border-radius: 16px; padding: 20px; display: flex; flex-direction: column; justify-content: space-between;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2);
                }}

                .card-header {{ display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.95); padding: 6px 10px; border-radius: 6px; }}
                .card-header img {{ max-height: 22px; object-fit: contain; }}
                .card-header span {{ font-size: 10px; font-weight: 800; color: #0f172a; }}

                .badge {{ background: #2563eb; color: #fff; font-size: 9px; font-weight: 800; padding: 3px 8px; border-radius: 4px; display: inline-block; text-transform: uppercase; }}
                .title {{ font-size: 16px; font-weight: 800; color: #ffffff; margin: 4px 0; }}
                .subtitle {{ font-size: 11px; color: #38bdf8; font-weight: 600; margin: 0; }}

                .info-box {{ background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; padding: 12px; }}
                .info-row {{ display: flex; justify-content: space-between; font-size: 11px; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.08); }}
                .info-row:last-child {{ border-bottom: none; }}
                .info-label {{ color: #94a3b8; }}
                .info-val {{ color: #ffffff; font-weight: 700; }}

                .footer-txt {{ text-align: center; font-size: 9px; color: #cbd5e1; border-top: 1px solid rgba(255,255,255,0.15); padding-top: 8px; }}

                .download-btn {{
                    width: 360px; margin: 12px auto 0 auto; display: block; padding: 12px;
                    background: #10b981; color: #ffffff; border: none; border-radius: 8px;
                    font-weight: 800; cursor: pointer; font-size: 13px; text-align: center; box-shadow: 0 4px 12px rgba(16,185,129,0.3);
                }}
                .download-btn:hover {{ background: #059669; }}

                #video-preview {{ width: 360px; height: 640px; margin: 0 auto; border-radius: 16px; display: block; box-shadow: 0 15px 35px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); background: #0f172a; }}
            </style>
            </head>
            <body>
                <div class="studio-container">
                    <div class="tabs-header">
                        <button class="tab-btn active" onclick="switchTab('photo')">📸 Fotoğraf Kartı (.png)</button>
                        <button class="tab-btn" onclick="switchTab('video')">🎥 Dikey Reklam Filmi (.mp4)</button>
                    </div>

                    <!-- FOTOĞRAF TABİ -->
                    <div id="tab-photo" class="tab-content active">
                        <div id="render-card">
                            <div class="card-header">
                                <img src="{logo1_data}" onerror="this.style.display='none'">
                                <span>İSTESTATE & MERİÇ</span>
                                <img src="{logo2_data}" onerror="this.style.display='none'">
                            </div>
                            <div>
                                <div class="badge">Yapay Zeka Mimari Vizyonu</div>
                                <div class="title">Beykoz / {mahalle_adi}</div>
                                <p class="subtitle">{sample_project_type}</p>
                            </div>
                            <div class="info-box">
                                <div class="info-row">
                                    <span class="info-label">Arazi Büyüklüğü:</span>
                                    <span class="info-val">{toplam_donum_str}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Mimari Konsept:</span>
                                    <span class="info-val">{sample_project_type}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Tasarım Stili:</span>
                                    <span class="info-val">{render_style}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Sosyal Donatı:</span>
                                    <span class="info-val">{sample_pool_mod}</span>
                                </div>
                            </div>
                            <div class="footer-txt">
                                İstestate Gayrimenkul & Meriç İnşaat Stüdyo Altyapısı
                            </div>
                        </div>
                        <button class="download-btn" onclick="downloadPNG()">📥 Fotoğrafı İndir (.png)</button>
                    </div>

                    <!-- VİDEO TABİ (5 SAHNE + İLETİŞİM + SABİT LOGOLAR) -->
                    <div id="tab-video" class="tab-content">
                        <canvas id="video-preview"></canvas>
                        <button class="download-btn" id="v-action-btn" onclick="startVideoRecord()">🎬 MP4 Video Üret & İndir (.mp4)</button>
                    </div>
                </div>

                <script>
                    function switchTab(t) {{
                        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
                        if(t === 'photo') {{
                            document.getElementById('tab-photo').classList.add('active');
                            event.currentTarget.classList.add('active');
                        }} else {{
                            document.getElementById('tab-video').classList.add('active');
                            event.currentTarget.classList.add('active');
                            initVideoAnimation();
                        }}
                    }}

                    function downloadPNG() {{
                        const card = document.getElementById('render-card');
                        html2canvas(card, {{ scale: 2, useCORS: true }}).then(canvas => {{
                            const link = document.createElement('a');
                            link.download = 'Sosyal_Medya_Mimari_Gorsel_{mahalle_adi}.png';
                            link.href = canvas.toDataURL('image/png');
                            link.click();
                        }});
                    }}

                    let canvas, ctx;
                    let animTimer = null;

                    function initVideoAnimation() {{
                        canvas = document.getElementById('video-preview');
                        ctx = canvas.getContext('2d');
                        canvas.width = 360;
                        canvas.height = 640;
                        
                        if(animTimer) clearInterval(animTimer);
                        
                        let currentScene = 1;
                        let sceneDuration = 120; // Her sahne ~4 saniye (30fps)
                        let frameCounter = 0;

                        function renderLoop() {{
                            ctx.clearRect(0, 0, 360, 640);
                            
                            // 1. Arka Plan Gradyanı & Simüle Edilmiş Yapay Zeka Render Görseli Atmosferi
                            let grad = ctx.createLinearGradient(0, 0, 360, 640);
                            grad.addColorStop(0, '#0f172a');
                            grad.addColorStop(1, '#1e293b');
                            ctx.fillStyle = grad;
                            ctx.fillRect(0, 0, 360, 640);

                            // 2. Her Sahnede Sabit Görüntülenen Üst Logo / Marka Alanı
                            ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
                            ctx.beginPath();
                            ctx.roundRect(20, 20, 320, 45, 8);
                            ctx.fill();
                            
                            ctx.fillStyle = '#0f172a';
                            ctx.font = 'bold 11px sans-serif';
                            ctx.textAlign = 'center';
                            ctx.fillText('İSTESTATE & MERİÇ İNŞAAT STÜDYO', 180, 48);

                            // 3. 5 Farklı Sahne İçerik Dağılımı
                            ctx.textAlign = 'left';
                            if (currentScene === 1) {{
                                // Sahne 1: Bölgesel Konum & Giriş
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = '12px sans-serif';
                                ctx.fillText('1 / 5 • BÖLGESEL VİZYON', 30, 100);
                                ctx.fillStyle = '#ffffff';
                                ctx.font = 'bold 22px sans-serif';
                                ctx.fillText('Beykoz / {mahalle_adi}', 30, 135);
                                ctx.fillStyle = '#cbd5e1';
                                ctx.font = '14px sans-serif';
                                ctx.fillText('Değer kazanan lokasyonda', 30, 165);
                                ctx.fillText('geleceğin yatırımı sizi bekliyor.', 30, 190);
                            }} else if (currentScene === 2) {{
                                // Sahne 2: Arazi Ölçüsü (Dönüm)
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = '12px sans-serif';
                                ctx.fillText('2 / 5 • ARSA BÜYÜKLÜĞÜ', 30, 100);
                                ctx.fillStyle = '#ffffff';
                                ctx.font = 'bold 22px sans-serif';
                                ctx.fillText('{toplam_donum_str}', 30, 135);
                                ctx.fillStyle = '#cbd5e1';
                                ctx.font = '14px sans-serif';
                                ctx.fillText('Geniş parsel yapısı ve', 30, 165);
                                ctx.fillText('ferah yerleşim avantajı.', 30, 190);
                            }} else if (currentScene === 3) {{
                                // Sahne 3: Mimari Konsept
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = '12px sans-serif';
                                ctx.fillText('3 / 5 • MİMARİ KONSEPT', 30, 100);
                                ctx.fillStyle = '#ffffff';
                                ctx.font = 'bold 20px sans-serif';
                                ctx.fillText('{sample_project_type}', 30, 135);
                                ctx.fillStyle = '#cbd5e1';
                                ctx.font = '14px sans-serif';
                                ctx.fillText('Yapay zeka destekli estetik', 30, 165);
                                ctx.fillText('ve modern çizgiler.', 30, 190);
                            }} else if (currentScene === 4) {{
                                // Sahne 4: Tasarım & Donatı
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = '12px sans-serif';
                                ctx.fillText('4 / 5 • YAŞAM STANDARTLARI', 30, 100);
                                ctx.fillStyle = '#ffffff';
                                ctx.font = 'bold 22px sans-serif';
                                ctx.fillText('{render_style}', 30, 135);
                                ctx.fillStyle = '#cbd5e1';
                                ctx.font = '14px sans-serif';
                                ctx.fillText('Sosyal donatılar ve', 30, 165);
                                ctx.fillText('{sample_pool_mod}.', 30, 190);
                            }} else if (currentScene === 5) {{
                                // Sahne 5: Son Sahne (İletişim Bilgileri)
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = '12px sans-serif';
                                ctx.fillText('5 / 5 • İLETİŞİM & REZERVASYON', 30, 100);
                                ctx.fillStyle = '#ffffff';
                                ctx.font = 'bold 20px sans-serif';
                                ctx.fillText('Umutcan K. MERİÇ', 30, 135);
                                ctx.fillStyle = '#38bdf8';
                                ctx.font = 'bold 15px sans-serif';
                                ctx.fillText('📞 0539 451 61 61', 30, 175);
                                ctx.fillStyle = '#cbd5e1';
                                ctx.font = '13px sans-serif';
                                ctx.fillText('İstestate & Meriç İnşaat Emlak', 30, 210);
                            }}

                            // Orta Alan Dekoratif Render Çerçevesi
                            ctx.strokeStyle = 'rgba(56, 189, 248, 0.3)';
                            ctx.lineWidth = 1.5;
                            ctx.beginPath();
                            ctx.roundRect(30, 240, 300, 320, 12);
                            ctx.stroke();

                            ctx.fillStyle = 'rgba(255,255,255,0.05)';
                            ctx.fill();

                            ctx.fillStyle = '#94a3b8';
                            ctx.font = '11px sans-serif';
                            ctx.textAlign = 'center';
                            ctx.fillText('Yapay Zeka Destekli Proje Görselleştirme', 180, 400);

                            frameCounter++;
                            if (frameCounter >= sceneDuration) {{
                                frameCounter = 0;
                                currentScene++;
                                if (currentScene > 5) currentScene = 1;
                            }}
                        }}

                        animTimer = setInterval(renderLoop, 33);
                    }

                    function startVideoRecord() {{
                        const btn = document.getElementById('v-action-btn');
                        btn.innerText = "⏳ 5 Sahneli Video Kaydediliyor (.mp4)...";
                        btn.disabled = true;

                        const stream = canvas.captureStream(30);
                        let recorder;
                        try {{
                            recorder = new MediaRecorder(stream, {{ mimeType: 'video/mp4' }});
                        }} catch (e) {{
                            recorder = new MediaRecorder(stream, {{ mimeType: 'video/webm' }});
                        }}

                        let chunks = [];
                        recorder.ondataavailable = e => chunks.push(e.data);
                        recorder.onstop = e => {{
                            let blob = new Blob(chunks, {{ type: 'video/mp4' }});
                            let url = URL.createObjectURL(blob);
                            let a = document.createElement('a');
                            a.href = url;
                            a.download = 'Sosyal_Medya_Reklam_Filmi_{mahalle_adi}.mp4';
                            a.click();
                            btn.innerText = "🎬 MP4 Video Üret & İndir (.mp4)";
                            btn.disabled = false;
                        }};

                        recorder.start();
                        // 5 sahne x 4 saniye = 20 saniye kayıt süresi
                        setTimeout(() => {{
                            recorder.stop();
                        }}, 20000);
                    }}
                </script>
            </body>
            </html>
            """
            components.html(studio_html, height=740)
