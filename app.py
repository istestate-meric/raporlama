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

# --- ÖZEL KURUMSAL STİL & SAĞ ÜST SABİT DÖVİZ KURU WİDGET ENJEKSİYONU ---
st.markdown(f"""
<style>
    .stSelectbox, .stNumberInput, .stSlider {{
        background-color: #ffffff;
        border-radius: 6px;
    }}
    div[data-baseweb="select"] > div {{
        border-radius: 6px;
        border-color: #cbd5e1;
    }}
    .block-container {{
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }}
    
    .currency-float-bar {{
        position: fixed;
        top: 15px;
        right: 25px;
        z-index: 999999;
        background: rgba(15, 23, 42, 0.92);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 10px;
        padding: 10px 14px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        display: flex;
        flex-direction: column;
        gap: 6px;
        color: #ffffff;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        pointer-events: auto;
    }}
    .currency-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    .currency-label {{
        color: #94a3b8;
        font-size: 11px;
    }}
    .currency-val {{
        color: #38bdf8;
        font-family: monospace;
        font-size: 13px;
        font-weight: 700;
    }}
    .currency-divider {{
        width: 100%;
        height: 1px;
        background-color: rgba(255, 255, 255, 0.15);
        margin: 1px 0;
    }}
</style>

<div class="currency-float-bar">
    <div class="currency-item">
        <span class="currency-label">USD/TRY:</span>
        <span class="currency-val">₺{rates['USD']:.2f}</span>
    </div>
    <div class="currency-divider"></div>
    <div class="currency-item">
        <span class="currency-label">EUR/TRY:</span>
        <span class="currency-val">₺{rates['EUR']:.2f}</span>
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
        st.sidebar.error("GitHub Token bulunamadı!")
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
        except Exception as e:
            st.warning(f"Veritabanı okunurken uyarı: {e}")
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
        "ACARLAR": 165000,
        "ANADOLU HİSARI": 150000,
        "KANLICA": 145000,
        "GÖKSU": 130000,
        "GÖRELE": 135000,
        "RİVA": 140000,
        "ÇİFTLİK": 130000,
        "BAKLACI": 115000,
        "KAVACIK": 110000,
        "ÇENGELDERE": 120000,
        "YAVUZ SELİM": 95000,
        "FATİH": 90000,
        "SOĞUKSU": 110000,
        "PAŞABAHÇE": 105000,
        "VARSAYILAN": 115000
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
        pool_options = get_allowed_pool_options(pt)
        for pool in pool_options:
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
    s_str = str(val_str).strip()
    nums = re.findall(r"[\d\.,]+", s_str)
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
        "TERKSİZ", "TERK GEREKMEMEKTEDİR", "İFRAZ GÖRMÜŞ", "TAPU ALANI NET",
        "TERKİ YAPILMIŞ OLAN", "DOP YAPILMIŞ"
    ]
    kesin_terk_yapilmamis = [
        "TERK YAPILMAMIŞ", "TERKİ YAPILMAMIŞ", "TERK YAPILMADAN", "DOP TERKİ YAPILMAMIŞ",
        "YOLA TERK VAR", "KAMUYA TERK VAR", "TERK EDİLECEKTİR", "YOLA TERKİ VARDIR",
        "TERK EDİLMELİDİR", "TERKİ YAPILMIŞTIR DEĞİLDİR", "TERKİ YAPILMAMIŞTIR",
        "TERK EDİLECEK", "YOLA TERK MİKTARI"
    ]
    for kw in kesin_terk_yapilmis:
        if kw in text_upper:
            if "YAPILMAMIŞTIR" not in text_upper and "YAPILMAMIŞ" not in text_upper:
                return True
    for kw in kesin_terk_yapilmamis:
        if kw in text_upper:
            return False
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
                t = page.extract_text() or ""
                full_text += "\n" + t
                
                tables = page.extract_tables() or []
                for table in tables:
                    for r_idx, row in enumerate(table):
                        cells = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
                        
                        if any("Mahalle" in c for c in cells) and any("Ada" in c for c in cells):
                            if r_idx + 1 < len(table):
                                v_row = [str(c).strip().replace("\n", " ") if c is not None else "" for c in table[r_idx + 1]]
                                for idx, head in enumerate(cells):
                                    if idx < len(v_row):
                                        val = v_row[idx]
                                        if "Mahalle" in head and val:
                                            parcel_data["mahalle"] = val.upper()
                                        elif "Ada" in head and val:
                                            parcel_data["ada"] = str(val).strip()
                                        elif "Parsel" in head and val:
                                            parcel_data["parsel"] = str(val).strip()
                                        elif "Alan" in head and val:
                                            parcel_data["toplam_alan"] = parse_tr_float(val)
                                            
                        joined_row_str = " ".join(cells).upper()
                        if any(kw in joined_row_str for kw in ["KONUT", "TİCARET", "TİCARİ", "PARK", "VİLLA", "GELİŞME", "EMSAL", "KAKS", "E:"]):
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
                                    nums = re.findall(r"([\d\.,]+)", c)
                                    for num_str in nums:
                                        val = parse_tr_float(num_str)
                                        if 0 < val <= 1.0:
                                            f_taks = val
                                elif any(k in c_up for k in ["KAKS", "EMSAL", "EMS", "E:", "E="]):
                                    f_kaks = parse_kaks_val(c)
                                    
                                m2_m = re.search(r"([\d\.,]+)\s*(?:M²|M2|%)", c, re.IGNORECASE)
                                if m2_m and "ALAN" not in c_up:
                                    val = parse_tr_float(m2_m.group(1))
                                    if val > 1.0:
                                        f_m2 = val
                                        
                            if f_name:
                                cleaned_check = clean_fonksiyon_adi(f_name)
                                if cleaned_check and not any(x in cleaned_check for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                                    existing_exact = next((f for f in parcel_data["fonksiyonlar"] if f["fonksiyon_adi"] == cleaned_check and f["kaks"] == f_kaks), None)
                                    if existing_exact:
                                        if f_taks > 0:
                                            existing_exact["taks"] = f_taks
                                        if f_m2 > 0:
                                            existing_exact["giren_m2"] += f_m2
                                    else:
                                        parcel_data["fonksiyonlar"].append({
                                            "fonksiyon_adi": cleaned_check,
                                            "taks": f_taks,
                                            "kaks": f_kaks,
                                            "giren_m2": f_m2
                                        })
                                        
                lines = t.split("\n")
                for i, line in enumerate(lines):
                    line_up = line.upper().strip()
                    if any(kw in line_up for kw in ["KONUT ALANI", "TİCARET ALANI", "TİCARET VE KONUT", "GELİŞME KONUT", "VİLLA ALANI"]):
                        clean_n = clean_fonksiyon_adi(line)
                        if clean_n:
                            curr_fonk = clean_n
                            curr_taks = 0.0
                            curr_kaks = 0.0
                            curr_m2 = 0.0
                            
                            for sub_line in lines[max(0, i-5):min(len(lines), i+8)]:
                                sub_up = sub_line.upper()
                                if "TAKS" in sub_up:
                                    num_m = re.search(r"([\d\.,]+)", sub_line)
                                    if num_m:
                                        val = parse_tr_float(num_m.group(1))
                                        if 0 < val <= 1.0:
                                            curr_taks = val
                                            
                                if any(k in sub_up for k in ["KAKS", "EMSAL", "EMS", "E:", "E="]):
                                    val = parse_kaks_val(sub_line)
                                    if val > 0:
                                        curr_kaks = val
                                        
                                m2_m = re.search(r"([\d\.,]+)\s*(?:m²|m2|%)", sub_line, re.IGNORECASE)
                                if m2_m:
                                    val = parse_tr_float(m2_m.group(1))
                                    if val > 0:
                                        curr_m2 = val
                                        
                            if curr_fonk:
                                cleaned_curr_fonk = clean_fonksiyon_adi(curr_fonk)
                                if cleaned_curr_fonk and not any(x in cleaned_curr_fonk for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                                    existing_exact = next((f for f in parcel_data["fonksiyonlar"] if f["fonksiyon_adi"] == cleaned_curr_fonk and f["kaks"] == curr_kaks), None)
                                    if existing_exact:
                                        if curr_taks > 0:
                                            existing_exact["taks"] = curr_taks
                                        if curr_m2 > 0:
                                            existing_exact["giren_m2"] = curr_m2
                                    else:
                                        parcel_data["fonksiyonlar"].append({
                                            "fonksiyon_adi": cleaned_curr_fonk,
                                            "taks": curr_taks,
                                            "kaks": curr_kaks,
                                            "giren_m2": curr_m2
                                        })
                                        
                global_kaks_val = 0.0
                general_kaks_matches = re.findall(r"(?:EMSAL|KAKS|EMS|E)\s*[:=\s]*([\d\.,\s/-]+)", full_text, re.IGNORECASE)
                for gkm in general_kaks_matches:
                    val = parse_kaks_val(gkm)
                    if val > 0:
                        global_kaks_val = val
                        break
                        
                for f in parcel_data["fonksiyonlar"]:
                    if f["kaks"] <= 0 and global_kaks_val > 0:
                        f["kaks"] = global_kaks_val
                        
                if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
                    m_m = re.search(r"Mahalle\s*[:\|]\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
                    a_m = re.search(r"Ada\s*[:\|]\s*(\d+)", full_text)
                    p_m = re.search(r"Parsel\s*[:\|]\s*(\d+)", full_text)
                    al_m = re.search(r"Alan\s*\*?\s*[:\|]\s*([\d\.,]+)\s*m²", full_text)
                    
                    if m_m:
                        parcel_data["mahalle"] = m_m.group(1).upper()
                    if a_m:
                        parcel_data["ada"] = str(a_m.group(1)).strip()
                    if p_m:
                        parcel_data["parsel"] = str(p_m.group(1)).strip()
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
    except Exception as e:
        print(f"PDF işlenirken hata oluştu: {e}")
        
    return parcel_data

def get_parcel_function_breakdown(p, emsal_artis_orani=1.30):
    toplam_arsa_m2 = p.get("toplam_alan", 0.0)
    is_terkli = p.get("terk_yapilmis_mi", False)
    fonks_list = p.get("fonksiyonlar", [])
    
    valid_sub_items = []
    for f in fonks_list:
        fonk_base_name = clean_fonksiyon_adi(f.get("fonksiyon_adi", ""))
        if not fonk_base_name or any(x in fonk_base_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
            continue
        active_kaks = f.get("kaks", 0.0)
        if active_kaks <= 0:
            continue
        valid_sub_items.append((f, fonk_base_name, active_kaks))
        
    if not valid_sub_items:
        return []
        
    sum_giren = sum(f.get("giren_m2", 0.0) for f, _, _ in valid_sub_items)
    net_arsa_toplam = toplam_arsa_m2 if is_terkli else (toplam_arsa_m2 * 0.7)
    
    temp_results = []
    for f, base_fonk_name, active_kaks in valid_sub_items:
        giren_m2 = f.get("giren_m2", 0.0)
        if giren_m2 > 0:
            fonk_giren_payi = giren_m2
        else:
            fonk_giren_payi = (toplam_arsa_m2 / len(valid_sub_items)) if len(valid_sub_items) > 0 else toplam_arsa_m2
            
        bahce_kullanim_alani = fonk_giren_payi
        
        if sum_giren > 0:
            oran = giren_m2 / sum_giren
        else:
            oran = 1.0 / len(valid_sub_items)
            
        net_arsa_payi = net_arsa_toplam * oran
        brut_insaat = net_arsa_payi * active_kaks * emsal_artis_orani
        
        temp_results.append({
            "base_fonksiyon_adi": base_fonk_name,
            "taks": f.get("taks", 0.0),
            "kaks": active_kaks,
            "giren_m2": giren_m2,
            "net_arsa_payi": net_arsa_payi,
            "bahce_kullanim_alani": bahce_kullanim_alani,
            "brut_insaat": brut_insaat
        })
        
    consolidated_dict = {}
    for item in temp_results:
        fn = item["base_fonksiyon_adi"]
        if fn not in consolidated_dict:
            consolidated_dict[fn] = {
                "fonksiyon_adi": fn,
                "base_fonksiyon_adi": fn,
                "taks": item["taks"],
                "giren_m2": 0.0,
                "net_arsa_payi": 0.0,
                "bahce_kullanim_alani": 0.0,
                "brut_insaat": 0.0,
                "kaks_list": []
            }
        consolidated_dict[fn]["giren_m2"] += item["giren_m2"]
        consolidated_dict[fn]["net_arsa_payi"] += item["net_arsa_payi"]
        consolidated_dict[fn]["bahce_kullanim_alani"] += item["bahce_kullanim_alani"]
        consolidated_dict[fn]["brut_insaat"] += item["brut_insaat"]
        consolidated_dict[fn]["kaks_list"].append((item["net_arsa_payi"], item["kaks"]))
        
    final_results = []
    for fn, data in consolidated_dict.items():
        net_arsa_sum = data["net_arsa_payi"]
        if net_arsa_sum > 0:
            weighted_kaks = sum(net_p * k for net_p, k in data["kaks_list"]) / net_arsa_sum
        else:
            weighted_kaks = data["kaks_list"][0][1] if data["kaks_list"] else 0.0
            
        data["kaks"] = weighted_kaks
        del data["kaks_list"]
        final_results.append(data)
        
    return final_results

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
    st.sidebar.success(f"{len(uploaded_files)} Adet Belge Arşive Eklendi ve GitHub Deponuza Kaydedildi!")

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
    
    safe_default = [k for k in just_uploaded_keys if k in filtered_keys]
    selected_keys = st.sidebar.multiselect("Raporlanacak Parselleri Seçin:", options=filtered_keys, default=safe_default)
else:
    st.sidebar.info("Arşivde kayıtlı parsel yok. Sol üstten PDF imar belgesi yükleyin.")
    selected_keys = []

if selected_keys:
    st.sidebar.divider()
    st.sidebar.subheader("⚙ Parsel Terk Durumu Ayarı (Manuel Düzeltme)")
    current_db = st.session_state["parcel_db"]
    any_terk_updated = False
    
    for s_key in selected_keys:
        if s_key in current_db:
            curr_val = current_db[s_key].get("terk_yapilmis_mi", False)
            new_terk_choice = st.sidebar.radio(
                f"Terk Durumu ({s_key}):",
                options=["Terk Yapılmış (Net Alan)", "Terk Yapılmamış (Brüt Alan -> %70 Net)"],
                index=0 if curr_val else 1,
                key=f"terk_override_{s_key}"
            )
            desired_bool = True if "Terk Yapılmış" in new_terk_choice else False
            if current_db[s_key]["terk_yapilmis_mi"] != desired_bool:
                current_db[s_key]["terk_yapilmis_mi"] = desired_bool
                any_terk_updated = True
                
    if any_terk_updated:
        save_persistent_db(current_db)

    active_parcel_db = {k: st.session_state["parcel_db"][k] for k in selected_keys}
    emsal_artis_orani = 1.30
    first_mahalle = list(active_parcel_db.values())[0].get("mahalle", "VARSAYILAN")
    
    st.markdown("""
    <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 18px 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
        <div style="display: flex; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
            <span style="font-size: 18px; margin-right: 8px;">📊</span>
            <div>
                <h3 style="color: #0f172a; margin: 0; font-size: 15px; font-weight: 700;">Gelişmiş Fizibilite ve Fonksiyon Bazlı Proje Optimizasyonu</h3>
                <p style="color: #64748b; margin: 0; font-size: 11px;">İmar fonksiyonlarına özel olarak birleştirilmiş metraj, proje tipleri, havuz seçenekleri ve otomatik m² maliyet/satış ayarları.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        is_modeli = st.selectbox(
            "İş Modeli / Rapor Türü",
            options=["Kat Karşılığı Proje Raporu", "Doğrudan Satılık / Arsa Yatırım Raporu"],
            key="global_is_modeli"
        )
        
    arsa_payi_orani = 0.0
    arsa_maliyeti_usd = 0.0
    if "Kat Karşılığı" in is_modeli:
        with col_m2:
            arsa_payi_orani = st.slider("Arsa Sahibi Payı / Kat Karşılığı Oranı (%)", 0, 70, 50)
    else:
        with col_m2:
            arsa_maliyeti_usd = st.number_input("Arsa Satın Alma Maliyeti ($)", min_value=0.0, value=0.0, step=10000.0, key="global_arsa_maliyeti")
            
    unique_active_functions = set()
    for p in active_parcel_db.values():
        breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
        for item in breakdown:
            if item["brut_insaat"] > 0:
                unique_active_functions.add(item["fonksiyon_adi"])
                
    if not unique_active_functions:
        unique_active_functions = {"KONUT ALANI"}
        
    col_opt1, col_opt2 = st.columns([3, 1])
    with col_opt1:
        st.markdown("<div style='margin-top: 10px; font-weight: 700; color: #0f172a; font-size: 13px;'>⚙️ İmar Fonksiyonuna Göre Birebir Uyumlu Proje Tipi, Birim Havuz Seçeneği ve Otomatik m² Fiyatları</div>", unsafe_allow_html=True)
    with col_opt2:
        auto_select_best_margin = st.toggle("Kar Marjına Göre Otomatik Seç (En Yüksek Verim)", value=True, key="auto_select_margin_toggle")
        
    function_configs = {}
    func_cols = st.columns(len(unique_active_functions) if len(unique_active_functions) > 0 else 1)
    
    for idx, fonk_adi in enumerate(unique_active_functions):
        with func_cols[idx % len(func_cols)]:
            st.markdown(f"**📌 Fonksiyon: {fonk_adi}**")
            
            allowed_p_types = get_allowed_project_types(fonk_adi)
            
            if auto_select_best_margin:
                opt_pt, opt_pool = get_best_project_type_by_margin(fonk_adi, first_mahalle, rates["USD"])
                selected_func_p_type = opt_pt
                selected_func_pool = opt_pool
                st.info(f"💡 **Optimum Seçim:** {selected_func_p_type} ({selected_func_pool})")
            else:
                p_type_key = f"func_p_type_{idx}_{fonk_adi}"
                selected_func_p_type = st.selectbox(f"Proje Tipi", options=allowed_p_types, key=p_type_key)
                
                pool_opts = get_allowed_pool_options(selected_func_p_type)
                pool_key = f"func_pool_{idx}_{fonk_adi}"
                selected_func_pool = st.selectbox(f"Havuz Seçeneği", options=pool_opts, key=pool_key)
                
            custom_pool_m2 = 0.0
            if "İptal" not in selected_func_pool:
                custom_pool_m2 = st.number_input(
                    f"Birim Başı Havuz (m²) - {fonk_adi}",
                    min_value=5.0, max_value=200.0, value=30.0, step=5.0,
                    key=f"custom_pool_m2_{idx}_{fonk_adi}"
                )
                
            auto_satis, auto_maliyet = get_realistic_market_pricing(first_mahalle, selected_func_p_type, selected_func_pool, rates["USD"])
            
            selected_parcels_hash = "_".join(selected_keys)
            cost_key = f"cost_{idx}_{fonk_adi}_{first_mahalle}_{selected_parcels_hash}"
            price_key = f"price_{idx}_{fonk_adi}_{first_mahalle}_{selected_parcels_hash}"
            last_state_key = f"last_state_{idx}_{fonk_adi}_{first_mahalle}_{selected_parcels_hash}"
            current_state_str = f"{selected_func_p_type}_{selected_func_pool}"
            
            if (last_state_key not in st.session_state) or (st.session_state.get(last_state_key) != current_state_str):
                st.session_state[cost_key] = float(auto_maliyet)
                st.session_state[price_key] = float(auto_satis)
                st.session_state[last_state_key] = current_state_str
                
            prc_col1, prc_col2 = st.columns(2)
            with prc_col1:
                custom_maliyet = st.number_input(f"Otomatik m² Maliyet ($)", min_value=300.0, max_value=6000.0, value=float(st.session_state.get(cost_key, auto_maliyet)), step=50.0, key=cost_key)
            with prc_col2:
                custom_satis = st.number_input(f"Otomatik m² Satış ($)", min_value=500.0, max_value=18000.0, value=float(st.session_state.get(price_key, auto_satis)), step=100.0, key=price_key)
                
            for key, p in active_parcel_db.items():
                breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
                for item in breakdown:
                    if item["fonksiyon_adi"] == fonk_adi and item["brut_insaat"] > 0:
                        parsel_fonk_key = f"{key}_{fonk_adi}"
                        eff_sz = 95.0 if "Konut" in selected_func_p_type else 150.0
                        calc_adet = max(1, round(item["brut_insaat"] / eff_sz))
                        function_configs[parsel_fonk_key] = {
                            "proje_tipi": selected_func_p_type,
                            "adet": int(calc_adet),
                            "havuz_mod": selected_func_pool,
                            "havuz_m2": custom_pool_m2,
                            "maliyet": custom_maliyet,
                            "satis": custom_satis,
                            "fonk_hesaba_alinan_m2": item["giren_m2"]
                        }

    valid_active_functions_with_area = list(unique_active_functions)
    function_target_sizes = {}
    
    if valid_active_functions_with_area:
        st.markdown("<div style='margin-top: 12px; font-weight: 700; color: #0f172a; font-size: 13px;'>📐 Seçilen Proje Tiplerine Göre Sınırlandırılmış Bağımsız Bölüm Alanları (m²)</div>", unsafe_allow_html=True)
        fn_cols = st.columns(len(valid_active_functions_with_area))
        
        for idx, fonk_adi in enumerate(valid_active_functions_with_area):
            with fn_cols[idx % len(fn_cols)]:
                parsel_fonk_sample_key = next((k for k in function_configs if fonk_adi in k), None)
                if parsel_fonk_sample_key and parsel_fonk_sample_key in function_configs:
                    chosen_p_type = function_configs[parsel_fonk_sample_key]["proje_tipi"]
                else:
                    chosen_p_type = get_allowed_project_types(fonk_adi)[0]
                    
                min_v, max_v, def_v, step_v = get_project_size_ranges(chosen_p_type)
                
                function_target_sizes[fonk_adi] = st.slider(
                    f"{fonk_adi[:20]}...",
                    min_value=min_v, max_value=max_v, value=def_v, step=step_v,
                    key=f"target_size_{idx}_{fonk_adi}"
                )

    st.markdown("</div>", unsafe_allow_html=True)
    
    for key, p in active_parcel_db.items():
        breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
        for item in breakdown:
            fonk_name = item["fonksiyon_adi"]
            brut_insaat = item["brut_insaat"]
            parsel_fonk_key = f"{key}_{fonk_name}"
            if parsel_fonk_key in function_configs and fonk_name in function_target_sizes:
                t_size = function_target_sizes[fonk_name]
                if t_size > 0:
                    function_configs[parsel_fonk_key]["adet"] = max(1, round(brut_insaat / t_size))

    total_yasal_brut_insaat = 0.0
    total_bodrum_alani = 0.0
    total_bahce_alani_terki = 0.0
    total_ciro_usd = 0.0
    total_maliyet_usd = 0.0
    total_units_sum = 0
    
    for key, p in active_parcel_db.items():
        breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
        
        for item in breakdown:
            fonk_name = item["fonksiyon_adi"]
            brut_insaat = item["brut_insaat"]
            if brut_insaat <= 0:
                continue
                
            parsel_fonk_key = f"{key}_{fonk_name}"
            conf = function_configs.get(parsel_fonk_key)
            if not conf:
                continue
                
            konut_adeti = conf["adet"]
            total_units_sum += konut_adeti
            total_yasal_brut_insaat += brut_insaat
            
            birim_havuz_m2 = conf["havuz_m2"] if "İptal" not in conf["havuz_mod"] else 0.0
            toplam_parsel_havuz_m2 = birim_havuz_m2 * konut_adeti
            
            net_satilabilir_ust_kat = max(0.0, brut_insaat - toplam_parsel_havuz_m2)
            bodrum_m2_parsel = net_satilabilir_ust_kat * 0.50
            
            total_bodrum_alani += bodrum_m2_parsel
            total_bahce_alani_terki += item["bahce_kullanim_alani"]
            
            toplam_parsel_insaat_m2 = brut_insaat + bodrum_m2_parsel
            total_ciro_usd += toplam_parsel_insaat_m2 * conf["satis"]
            
            ust_kat_maliyeti = brut_insaat * conf["maliyet"]
            bodrum_maliyeti = bodrum_m2_parsel * (conf["maliyet"] * 0.60)
            
            toplam_parsel_maliyeti = ust_kat_maliyeti + bodrum_maliyeti
            total_maliyet_usd += toplam_parsel_maliyeti

    if "Doğrudan Satılık" in is_modeli:
        total_maliyet_usd += arsa_maliyeti_usd
        arsa_sahibi_payi_usd = 0.0
        müteahhit_hissesi_ciro = total_ciro_usd
        toplam_net_kar_usd = total_ciro_usd - total_maliyet_usd
    else:
        arsa_sahibi_payi_usd = total_ciro_usd * (arsa_payi_orani / 100.0)
        müteahhit_hissesi_ciro = total_ciro_usd * ((100.0 - arsa_payi_orani) / 100.0)
        toplam_net_kar_usd = müteahhit_hissesi_ciro - total_maliyet_usd

    yg_orani = (toplam_net_kar_usd / total_maliyet_usd * 100) if total_maliyet_usd > 0 else 0

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Seçilen Parseller & İnşaat Alanı",
        "🏛 Mimari Fizibilite (Bodrum + Zemin/Normal)",
        "📑 Proje Raporu & Fizibilite",
        "🖨 Rapor Ön İzleme & PDF",
        "🗄 Veritabanı & Arşiv Yönetimi",
        "📱 Müşteri Sunum Kenti & Reklam Filmi Stüdyosu"
    ])

    with tab1:
        st.subheader("📊 Birleştirilmiş Fonksiyon Bazlı İnşaat Alanı ve Metrajlar")
        table_rows = []
        sum_brut_insaat = 0.0
        sum_bodrum_insaat = 0.0
        sum_emsal_insaat = 0.0
        sum_bahce_alani = 0.0
        sum_alan = sum(p.get("toplam_alan", 0.0) for p in active_parcel_db.values())
        
        for key, p in active_parcel_db.items():
            mahalle = p.get("mahalle", "BİLİNMİYOR")
            ada = p.get("ada", "0")
            parsel = p.get("parsel", "0")
            toplam_arsa_m2 = p.get("toplam_alan", 0.0)
            is_terkli = p.get("terk_yapilmis_mi", False)
            breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
            
            for item in breakdown:
                brut_insaat_arsa = item["brut_insaat"]
                bodrum_arsa = brut_insaat_arsa * 0.50
                emsal_arsa = brut_insaat_arsa
                bahce_m2 = item["bahce_kullanim_alani"]
                if brut_insaat_arsa <= 0:
                    continue
                    
                sum_brut_insaat += brut_insaat_arsa
                sum_bodrum_insaat += bodrum_arsa
                sum_emsal_insaat += emsal_arsa
                sum_bahce_alani += bahce_m2
                
                table_rows.append({
                    "Mahalle": mahalle,
                    "Ada": ada,
                    "Parsel": parsel,
                    "Toplam Arsa m²": f"{toplam_arsa_m2:,.2f}",
                    "Terk Durumu": "Yapılmış (Net)" if is_terkli else "Yapılmamış (Brüt)",
                    "Birleştirilmiş Fonksiyon": item["fonksiyon_adi"],
                    "Ağırlıklı Emsal (KAKS)": f"{item['kaks']:.2f}",
                    "Toplam Bahçe Alanı (m²)": f"{bahce_m2:,.2f}",
                    "Toplam Emsal İnşaat (m²)": f"{emsal_arsa:,.2f}",
                    "Toplam Genel İnşaat (m²)": f"{(brut_insaat_arsa + bodrum_arsa):,.2f}"
                })
                
        if table_rows:
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
            summary_df = pd.DataFrame([{
                "SORGULANAN PARSEL": f"{len(active_parcel_db)} Adet",
                "TOPLAM ARSA (M²)": f"{sum_alan:,.2f}",
                "TOPLAM BAHÇE ALANI (M²)": f"{sum_bahce_alani:,.2f}",
                "TOPLAM EMSAL İNŞAAT (M²)": f"{sum_emsal_insaat:,.2f}",
                "TOPLAM BODRUM İNŞAAT (M²)": f"{sum_bodrum_insaat:,.2f}",
                "GENEL TOPLAM İNŞAAT (M²)": f"{(sum_brut_insaat + sum_bodrum_insaat):,.2f}"
            }])
            st.dataframe(summary_df, use_container_width=True)

    with tab2:
        st.subheader("🏛️ Mimari Fizibilite & Senaryo Dağılım Matrisi (Birim Başına Düşen Alanlar)")
        mimari_rows = []
        total_net_insaat_sum = 0.0
        total_genel_insaat_sum = 0.0
        
        for key, p in active_parcel_db.items():
            mahalle = p.get("mahalle", "BİLİNMİYOR")
            ada = p.get("ada", "0")
            parsel = p.get("parsel", "0")
            breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
            
            for item in breakdown:
                fonk_name = item["fonksiyon_adi"]
                brut_insaat = item["brut_insaat"]
                bahce_m2 = item["bahce_kullanim_alani"]
                if brut_insaat <= 0:
                    continue
                    
                parsel_fonk_key = f"{key}_{fonk_name}"
                conf = function_configs.get(parsel_fonk_key)
                if not conf:
                    continue
                    
                konut_adeti = conf["adet"]
                birim_havuz = conf["havuz_m2"] if "İptal" not in conf["havuz_mod"] else 0.0
                toplam_parsel_havuz_m2 = birim_havuz * konut_adeti
                
                net_konut_insaat = max(0.0, brut_insaat - toplam_parsel_havuz_m2)
                total_net_insaat_sum += net_konut_insaat
                
                bodrum_m2 = net_konut_insaat * 0.50
                
                birim_bahce = bahce_m2 / konut_adeti if konut_adeti > 0 else 0.0
                birim_bodrum = bodrum_m2 / konut_adeti if konut_adeti > 0 else 0.0
                birim_ust_kat = net_konut_insaat / konut_adeti if konut_adeti > 0 else 0.0
                
                birim_toplam_insaat = birim_ust_kat + birim_bodrum + birim_havuz
                genel_parsel_toplam_insaat = net_konut_insaat + bodrum_m2 + toplam_parsel_havuz_m2
                total_genel_insaat_sum += genel_parsel_toplam_insaat
                
                mimari_rows.append({
                    "MAHALLE": mahalle,
                    "ADA/PARSEL": f"{ada}/{parsel}",
                    "FONKSİYON SEGMENTİ": fonk_name,
                    "PROJE TİPİ": f"{conf['proje_tipi']} ({conf['havuz_mod']})",
                    "BAĞIMSIZ BÖLÜM": f"{konut_adeti} Adet",
                    "BİRİM BAHÇE (M²)": f"{birim_bahce:,.1f} m²",
                    "BİRİM HAVUZ (M²)": f"{birim_havuz:,.1f} m²",
                    "BİRİM BODRUM (M²)": f"{birim_bodrum:,.1f} m²",
                    "BİRİM ÜST KAT (Net)": f"{birim_ust_kat:,.1f} m²",
                    "BİRİM TOPLAM İNŞAAT (M²)": f"{birim_toplam_insaat:,.1f} m²"
                })
                
        if mimari_rows:
            st.dataframe(pd.DataFrame(mimari_rows), use_container_width=True)
            avg_unit_m2 = total_genel_insaat_sum / total_units_sum if total_units_sum > 0 else 0.0
            
            st.markdown("---")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("Toplam Bağımsız Bölüm", f"{total_units_sum} Adet")
            m_col2.metric("Ortalama Birim Alanı", f"{avg_unit_m2:,.1f} m²")
            
            if "Kat Karşılığı" in is_modeli:
                exact_arsa_sahibi = total_units_sum * (arsa_payi_orani / 100.0)
                exact_mutaahhit = total_units_sum * ((100 - arsa_payi_orani) / 100.0)
                m_col3.metric("Arsa Sahibi Payı", f"{exact_arsa_sahibi:,.2f} Adet (%{arsa_payi_orani})")
                m_col4.metric("Müteahhit Payı", f"{exact_mutaahhit:,.2f} Adet (%{100 - arsa_payi_orani})")
            else:
                m_col3.metric("İş Modeli", "Doğrudan Satılık")
                m_col4.metric("Müteahhit Payı", f"{float(total_units_sum):,.2f} Adet (%100)")

    with tab3:
        st.subheader("📑 Finansal Fizibilite (3 Para Birimi Sunumu)")
        rate_usd = rates["USD"]
        rate_eur = rates["EUR"]
        
        display_ciro_usd = müteahhit_hissesi_ciro if "Kat Karşılığı" in is_modeli else total_ciro_usd
        total_ciro_tl = display_ciro_usd * rate_usd
        total_ciro_eur = total_ciro_tl / rate_eur
        
        total_maliyet_tl = total_maliyet_usd * rate_usd
        total_maliyet_eur = total_maliyet_tl / rate_eur
        
        toplam_net_kar_tl = toplam_net_kar_usd * rate_usd
        toplam_net_kar_eur = toplam_net_kar_tl / rate_eur
        
        curr_tab1, curr_tab2, curr_tab3 = st.tabs(["💵 USD ($)", "₺ TL (₺)", "💶 EUR (€)"])
        with curr_tab1:
            c1, c2, c3 = st.columns(3)
            c1.metric("Tahmini Ciro", f"${display_ciro_usd:,.2f}")
            c2.metric("Toplam Maliyet", f"${total_maliyet_usd:,.2f}")
            c3.metric("Net Kar", f"${toplam_net_kar_usd:,.2f}", f"%{yg_orani:.1f} YG")
            
        with curr_tab2:
            t1, t2, t3 = st.columns(3)
            t1.metric("Tahmini Ciro", f"₺{total_ciro_tl:,.2f}")
            t2.metric("Toplam Maliyet", f"₺{total_maliyet_tl:,.2f}")
            t3.metric("Net Kar", f"₺{toplam_net_kar_tl:,.2f}", f"%{yg_orani:.1f} YG")
            
        with curr_tab3:
            e1, e2, e3 = st.columns(3)
            e1.metric("Tahmini Ciro", f"€{total_ciro_eur:,.2f}")
            e2.metric("Toplam Maliyet", f"€{total_maliyet_eur:,.2f}")
            e3.metric("Net Kar", f"€{toplam_net_kar_eur:,.2f}", f"%{yg_orani:.1f} YG")

    with tab4:
        st.subheader("🖨 Rapor Ön İzleme ve PDF İndirme Merkezi")
        
        if not WEASYPRINT_AVAILABLE:
            st.error("⚠ PDF oluşturma motoru (WeasyPrint) sisteminizde eksik. Lütfen `packages.txt` dosyasının deponuzda bulunduğundan emin olun.")
        else:
            pdf_logo1_html = f"<div style='background-color: #ffffff; padding: 6px 10px; border-radius: 6px; display: inline-block;'><img src='data:image/png;base64,{img1_base64}' style='max-height: 38px; width: auto; vertical-align: middle;'></div>" if img1_base64 else "<b style='color:#ffffff; font-size:14px;'>İSTESTATE GAYRİMENKUL</b>"
            pdf_logo2_html = f"<div style='background-color: #ffffff; padding: 6px 10px; border-radius: 6px; display: inline-block;'><img src='data:image/png;base64,{img2_base64}' style='max-height: 38px; width: auto; vertical-align: middle;'></div>" if img2_base64 else "<b style='color:#ffffff; font-size:14px;'>MERİÇ İNŞAAT EMLAK</b>"
            
            parcel_rows_html = ""
            all_adas_str, all_parsels_str = [], []
            
            for key, p in active_parcel_db.items():
                mahalle = p.get("mahalle", "BİLİNMİYOR")
                ada = p.get("ada", "0")
                parsel = p.get("parsel", "0")
                
                if ada not in all_adas_str:
                    all_adas_str.append(ada)
                if parsel not in all_parsels_str:
                    all_parsels_str.append(parsel)
                    
                toplam_arsa_m2 = p.get("toplam_alan", 0.0)
                is_terkli = p.get("terk_yapilmis_mi", False)
                breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
                
                for item in breakdown:
                    brut_insaat_arsa = item["brut_insaat"]
                    bodrum_arsa = brut_insaat_arsa * 0.50
                    if brut_insaat_arsa <= 0:
                        continue
                    parcel_rows_html += f"""
                    <tr>
                        <td>{mahalle}</td>
                        <td style="text-align: center;">{ada} / {parsel}</td>
                        <td style="text-align: right;">{toplam_arsa_m2:,.2f} m²</td>
                        <td style="text-align: center;">{'Yapılmış (Net)' if is_terkli else 'Yapılmamış (Brüt)'}</td>
                        <td>{item['fonksiyon_adi']}</td>
                        <td style="text-align: center;">{item['kaks']:.2f} (Ağırlıklı)</td>
                        <td style="text-align: right;">{brut_insaat_arsa:,.2f} m²</td>
                        <td style="text-align: right;">{bodrum_arsa:,.2f} m²</td>
                        <td style="text-align: right; font-weight: bold;">{(brut_insaat_arsa + bodrum_arsa):,.2f} m²</td>
                    </tr>
                    """
                    
            formatted_mahalle = first_mahalle.strip().replace(" ", "_")
            formatted_ada = "_".join(all_adas_str)
            formatted_parsel = "_".join(all_parsels_str)
            dynamic_pdf_filename = f"Istestate_Meric_Fizibilite_Raporu_{formatted_mahalle}_Ada_{formatted_ada}_Parsel_{formatted_parsel}.pdf"
            
            arch_rows_html = ""
            for key, p in active_parcel_db.items():
                breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
                for item in breakdown:
                    fonk_name = item["fonksiyon_adi"]
                    brut_insaat = item["brut_insaat"]
                    bahce_m2 = item["bahce_kullanim_alani"]
                    if brut_insaat <= 0:
                        continue
                        
                    parsel_fonk_key = f"{key}_{fonk_name}"
                    conf = function_configs.get(parsel_fonk_key)
                    if not conf:
                        continue
                        
                    konut_adeti = conf["adet"]
                    birim_havuz = conf["havuz_m2"] if "İptal" not in conf["havuz_mod"] else 0.0
                    toplam_parsel_havuz_m2 = birim_havuz * konut_adeti
                    
                    net_konut_insaat = max(0.0, brut_insaat - toplam_parsel_havuz_m2)
                    bodrum_m2 = net_konut_insaat * 0.50
                    
                    birim_bahce = bahce_m2 / konut_adeti if konut_adeti > 0 else 0.0
                    birim_bodrum = bodrum_m2 / konut_adeti if konut_adeti > 0 else 0.0
                    birim_ust_kat = net_konut_insaat / konut_adeti if konut_adeti > 0 else 0.0
                    birim_toplam = birim_ust_kat + birim_bodrum + birim_havuz
                    
                    arch_rows_html += f"""
                    <tr>
                        <td>{fonk_name}</td>
                        <td>{conf['proje_tipi']} ({conf['havuz_mod']})</td>
                        <td style="text-align: center; font-weight: bold;">{konut_adeti} Adet</td>
                        <td style="text-align: right;">{birim_bahce:,.1f} m²</td>
                        <td style="text-align: right;">{birim_havuz:,.1f} m²</td>
                        <td style="text-align: right;">{birim_bodrum:,.1f} m²</td>
                        <td style="text-align: right;">{birim_ust_kat:,.1f} m²</td>
                        <td style="text-align: right; font-weight: bold;">{birim_toplam:,.1f} m²</td>
                    </tr>
                    """

            report_html_template = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <meta charset="utf-8">
            <style>
                @page {{ size: A4 landscape; margin: 8mm 10mm; }}
                body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #0f172a; font-size: 8.5px; line-height: 1.2; background-color: #ffffff; }}
                .report-banner {{ background-color: #0b1d3a; color: #ffffff; width: 100%; border-collapse: collapse; margin-bottom: 8mm; border-radius: 4px; overflow: hidden; }}
                .report-banner td {{ border: none; padding: 8px 12px; vertical-align: middle; }}
                .section-title {{ font-size: 9.5px; font-weight: bold; color: #0b1d3a; border-left: 4px solid #0b1d3a; padding-left: 6px; background-color: #f1f5f9; margin-top: 8mm; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.3px; }}
                .data-table {{ width: 100%; border-collapse: collapse; margin-top: 2px; margin-bottom: 6px; font-size: 8px; }}
                .data-table th, .data-table td {{ border: 1px solid #cbd5e1; padding: 4px 6px; }}
                .data-table th {{ background-color: #f8fafc; color: #1e293b; font-weight: 700; text-align: left; }}
                .footer {{ font-size: 7.5px; color: #475569; text-align: center; margin-top: 12px; border-top: 1px dashed #cbd5e1; padding-top: 6px; font-weight: 500; line-height: 1.3; }}
                .highlight {{ background-color: #eff6ff; font-weight: bold; }}
            </style>
            </head>
            <body>
                <table class="report-banner">
                    <tr>
                        <td style="width: 30%; text-align: left;">{pdf_logo1_html}</td>
                        <td style="width: 40%; text-align: center;">
                            <div style="font-size: 14px; font-weight: 800; letter-spacing: 0.5px;">GAYRİMENKUL GELİŞTİRME VE FİZİBİLİTE RAPORU</div>
                            <div style="font-size: 9px; opacity: 0.85; margin-top: 2px;">{first_mahalle} Mah. | Ada: {formatted_ada} - Parsel: {formatted_parsel}</div>
                        </td>
                        <td style="width: 30%; text-align: right;">{pdf_logo2_html}</td>
                    </tr>
                </table>

                <div class="section-title">1. PARSEL VE İMAR METRAJ ANALİZİ</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>MAHALLE</th>
                            <th style="text-align: center;">ADA / PARSEL</th>
                            <th style="text-align: right;">ARSA ALANI</th>
                            <th style="text-align: center;">TERK DURUMU</th>
                            <th>İMAR FONKSİYONU</th>
                            <th style="text-align: center;">AĞIRLIKLI EMSAL</th>
                            <th style="text-align: right;">EMSAL İNŞAAT</th>
                            <th style="text-align: right;">BODRUM ALANI</th>
                            <th style="text-align: right;">TOPLAM İNŞAAT</th>
                        </tr>
                    </thead>
                    <tbody>
                        {parcel_rows_html}
                    </tbody>
                </table>

                <div class="section-title">2. MİMARİ VE BİRİM SENARYO DAĞILIMI</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>FONKSİYON</th>
                            <th>PROJE VE HAVUZ KONSEPTİ</th>
                            <th style="text-align: center;">BAĞIMSIZ BÖLÜM</th>
                            <th style="text-align: right;">BİRİM BAHÇE</th>
                            <th style="text-align: right;">BİRİM HAVUZ</th>
                            <th style="text-align: right;">BİRİM BODRUM</th>
                            <th style="text-align: right;">BİRİM ÜST KAT</th>
                            <th style="text-align: right;">BİRİM TOPLAM</th>
                        </tr>
                    </thead>
                    <tbody>
                        {arch_rows_html}
                    </tbody>
                </table>

                <div class="section-title">3. FİNANSAL FİZİBİLİTE VE PROJE KARLILIĞI</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>PARA BİRİMİ</th>
                            <th style="text-align: right;">TAHMİNİ TOPLAM CİRO</th>
                            <th style="text-align: right;">TOPLAM PROJE MALİYETİ</th>
                            <th style="text-align: right;">NET KAR PROJEKSİYONU</th>
                            <th style="text-align: center;">YATIRIM GETİRİSİ (YG)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr class="highlight">
                            <td>USD ($)</td>
                            <td style="text-align: right;">${display_ciro_usd:,.2f}</td>
                            <td style="text-align: right;">${total_maliyet_usd:,.2f}</td>
                            <td style="text-align: right;">${toplam_net_kar_usd:,.2f}</td>
                            <td style="text-align: center;">%{yg_orani:.1f}</td>
                        </tr>
                        <tr>
                            <td>TRY (₺)</td>
                            <td style="text-align: right;">₺{total_ciro_tl:,.2f}</td>
                            <td style="text-align: right;">₺{total_maliyet_tl:,.2f}</td>
                            <td style="text-align: right;">₺{toplam_net_kar_tl:,.2f}</td>
                            <td style="text-align: center;">%{yg_orani:.1f}</td>
                        </tr>
                        <tr>
                            <td>EUR (€)</td>
                            <td style="text-align: right;">€{total_ciro_eur:,.2f}</td>
                            <td style="text-align: right;">€{total_maliyet_eur:,.2f}</td>
                            <td style="text-align: right;">€{toplam_net_kar_eur:,.2f}</td>
                            <td style="text-align: center;">%{yg_orani:.1f}</td>
                        </tr>
                    </tbody>
                </table>

                <div class="footer">
                    İSTESTATE Meriç Gayrimenkul Danışmanlık & Meriç İnşaat Emlak | Otomatik Hazırlanan Kurumsal Fizibilite Raporu<br>
                    Bu rapor TCMB canlı kur verileri ve güncel imar yönetmelikleri baz alınarak oluşturulmuştur.
                </div>
            </body>
            </html>
            """
            
            try:
                pdf_bytes = HTML(string=report_html_template).write_pdf()
                st.download_button(
                    label="📄 4K Kalitesinde Profesyonel PDF Raporu İndir",
                    data=pdf_bytes,
                    file_name=dynamic_pdf_filename,
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"PDF Oluşturulurken Hata Oluştu: {e}")

    with tab5:
        st.subheader("🗄️ Veritabanı ve Arşiv Yönetimi")
        st.write("Sistemde yüklü olan tüm parsel kayıtlarını görüntüleyebilir veya silebilirsiniz:")
        
        db_keys = list(st.session_state["parcel_db"].keys())
        if db_keys:
            key_to_delete = st.selectbox("Silinecek Kaydı Seçin:", options=["Seçiniz..."] + db_keys)
            if key_to_delete != "Seçiniz...":
                if st.button("🗑️ Seçili Parsel Kaydını Sil ve Güncelle"):
                    del st.session_state["parcel_db"][key_to_delete]
                    save_persistent_db(st.session_state["parcel_db"])
                    st.success(f"'{key_to_delete}' veritabanından başarıyla silindi ve GitHub senkronize edildi.")
                    st.rerun()
        else:
            st.info("Veritabanında kayıtlı parsel bulunmuyor.")

    with tab6:
        st.subheader("📱 Müşteri Sunum Kenti & Reklam Filmi Stüdyosu")
        
        st.markdown("""
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 15px;">
            <p style="margin: 0; font-size: 13px; color: #334155;">
                Bu alanda sosyal medya mecraları (Instagram Reel, Shorts, WhatsApp) için HD Logo Kartları üretebilir ve projeleriniz için <b>4K Reklam Filmi Stüdyosu</b> üzerinden animasyonlu tanıtım filmleri sunabilirsiniz.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        sub_tab1, sub_tab2 = st.tabs(["🏷️ HD Logo Kartı Tasarımcısı", "🎬 4K Reklam Filmi Stüdyosu"])
        
        with sub_tab1:
            st.markdown("##### 🎨 Kurumsal HD Logo Kartı Yapılandırması")
            
            col_l1, col_l2, col_l3 = st.columns(3)
            with col_l1:
                logo_width_pct = st.slider("Logo Kart Genişliği (%)", 20, 100, 80, key="hd_logo_width")
                logo_bg_color = st.color_picker("Kart Arka Plan Rengi", "#ffffff", key="hd_logo_bg")
            with col_l2:
                logo_padding = st.slider("İç Boşluk (Padding - px)", 5, 40, 15, key="hd_logo_pad")
                logo_border_radius = st.slider("Köşe Yuvarlama (Radius - px)", 0, 30, 12, key="hd_logo_rad")
            with col_l3:
                logo_show_border = st.checkbox("Çerçeve Ekle", value=True, key="hd_logo_border_check")
                logo_border_color = st.color_picker("Çerçeve Rengi", "#cbd5e1", key="hd_logo_border_col")
                
            border_style_css = f"1px solid {logo_border_color}" if logo_show_border else "none"
            
            logo_preview_html = f"""
            <div style="display: flex; justify-content: center; align-items: center; padding: 20px; background-color: #0f172a; border-radius: 10px;">
                <div style="width: {logo_width_pct}%; background-color: {logo_bg_color}; padding: {logo_padding}px; border-radius: {logo_border_radius}px; border: {border_style_css}; display: flex; justify-content: space-around; align-items: center; box-shadow: 0 10px 25px rgba(0,0,0,0.2);">
                    <div>{img1_tag}</div>
                    <div style="width: 1px; height: 35px; background-color: rgba(0,0,0,0.15);"></div>
                    <div>{img2_tag}</div>
                </div>
            </div>
            """
            st.markdown("###### 👁️ HD Logo Kartı Canlı Ön İzleme")
            st.markdown(logo_preview_html, unsafe_allow_html=True)
            
        with sub_tab2:
            st.markdown("##### 🎬 4K Reklam Filmi Stüdyosu (Her Sahnede Logo & İletişim Sahnesi)")
            
            col_v1, col_v2 = st.columns([2, 1])
            with col_v1:
                video_title = st.text_input("Reklam Filmi Başlığı", value=f"{first_mahalle} Özel Gayrimenkul Yatırım Fırsatı", key="vid_title")
                video_subtitle = st.text_input("Alt Başlık / Vurgu", value=f"Ada: {formatted_ada} - Parsel: {formatted_parsel} | Yüksek Prim Potansiyeli", key="vid_sub")
            with col_v2:
                video_bg_theme = st.selectbox("Video Tema Rengi", options=["Koyu Modern (Dark)", "Lüks Altın (Gold)", "Kurumsal Mavi (Navy)"], key="vid_theme")
                phone_num = st.text_input("İletişim Telefon Numarası", value="0539 451 61 61", key="vid_phone")

            if video_bg_theme == "Koyu Modern (Dark)":
                theme_bg = "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)"
                accent_color = #38bdf8
            elif video_bg_theme == "Lüks Altın (Gold)":
                theme_bg = "linear-gradient(135deg, #1a1600 0%, #3a3200 100%)"
                accent_color = #fbbf24
            else:
                theme_bg = "linear-gradient(135deg, #031525 0%, #0b3052 100%)"
                accent_color = #60a5fa

            # Dinamik Sahne Üretimi (Tüm Sahnelerde HD Logo Kartı Dahil)
            scenes = [
                {
                    "title": video_title,
                    "desc": video_subtitle,
                    "stat1": f"{sum_alan:,.0f} m² Arsa",
                    "stat2": f"{total_units_sum} Bağımsız Bölüm"
                },
                {
                    "title": "Ağaçlandırılmış Bahçe & Sosyal Donatı",
                    "desc": "Yeşil alan entegrasyonu ve üst segment mimari standartlar.",
                    "stat1": f"{sum_bahce_alani:,.0f} m² Bahçe",
                    "stat2": f"%{yg_orani:.1f} Beklenen YG"
                },
                {
                    "title": "İnşaat Metraj & Mimari Fizibilite",
                    "desc": "Emsal ve bodrum alanlarıyla optimize edilmiş maksimum kullanım.",
                    "stat1": f"{sum_emsal_insaat:,.0f} m² Emsal",
                    "stat2": f"{(sum_brut_insaat + sum_bodrum_insaat):,.0f} m² Genel Toplam"
                },
                {
                    "title": "Finansal Projeksiyon & Ciro",
                    "desc": "Bölgesel pazar verileriyle hesaplanmış yüksek karlılık potansiyeli.",
                    "stat1": f"${display_ciro_usd:,.0f} Ciro",
                    "stat2": f"${toplam_net_kar_usd:,.0f} Tahmini Net Kar"
                }
            ]

            # En Entegre Kapanış ve İletişim Sahnesi (Son Sahne)
            contact_scene = {
                "title": "DETAYLI BİLGİ VE SUNUM İÇİN",
                "desc": "İSTESTATE Meriç Gayrimenkul Danışmanlık & Meriç İnşaat Emlak",
                "phone": phone_num,
                "location": f"{first_mahalle} / İSTANBUL",
                "summary": f"Ada: {formatted_ada} - Parsel: {formatted_parsel}"
            }

            # Her Sahnede Üst Bilgi Olarak Gözükecek HD Logo Kartı HTML Kodu
            top_logo_overlay_html = f"""
            <div style="width: {logo_width_pct}%; max-width: 320px; background-color: {logo_bg_color}; padding: {max(4, logo_padding//2)}px {logo_padding}px; border-radius: {logo_border_radius}px; border: {border_style_css}; display: flex; justify-content: space-around; align-items: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); margin: 0 auto 15px auto;">
                <div style="transform: scale(0.75); transform-origin: center;">{img1_tag}</div>
                <div style="width: 1px; height: 22px; background-color: rgba(0,0,0,0.15);"></div>
                <div style="transform: scale(0.75); transform-origin: center;">{img2_tag}</div>
            </div>
            """

            # HTML & CSS Slider/Player Kodu (Her Sahne 4.5s Süre ve Akıcı Geçişler)
            video_player_html = f"""
            <style>
                .video-container {{
                    width: 100%;
                    max-width: 480px;
                    height: 620px;
                    margin: 0 auto;
                    background: {theme_bg};
                    border-radius: 16px;
                    overflow: hidden;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.5);
                    position: relative;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    color: #ffffff;
                }}
                .scene-slide {{
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    padding: 25px 20px;
                    box-sizing: border-box;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                    opacity: 0;
                    animation: slideAnimation {len(scenes) * 4.5 + 5}s infinite;
                }}
                
                /* Sahne Süreleri Ayarları (Her Sahne Etkileyici 4.5 Sn + Son Sahne) */
                .scene-0 {{ animation-delay: 0s; }}
                .scene-1 {{ animation-delay: 4.5s; }}
                .scene-2 {{ animation-delay: 9s; }}
                .scene-3 {{ animation-delay: 13.5s; }}
                .scene-contact {{ animation-delay: 18s; }}

                @keyframes slideAnimation {{
                    0% {{ opacity: 0; transform: scale(0.96); }}
                    3% {{ opacity: 1; transform: scale(1); }}
                    20% {{ opacity: 1; transform: scale(1.02); }}
                    23% {{ opacity: 0; transform: scale(1.05); }}
                    100% {{ opacity: 0; }}
                }}

                .badge {{
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(5px);
                    border: 1px solid rgba(255,255,255,0.2);
                    padding: 6px 12px;
                    border-radius: 20px;
                    font-size: 11px;
                    font-weight: 600;
                    display: inline-block;
                    color: {accent_color};
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }}
                .main-title {{
                    font-size: 20px;
                    font-weight: 800;
                    line-height: 1.3;
                    margin: 10px 0;
                    color: #ffffff;
                }}
                .desc-text {{
                    font-size: 12px;
                    color: #94a3b8;
                    line-height: 1.4;
                }}
                .stat-box {{
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                    padding: 12px;
                    margin-top: 8px;
                    text-align: center;
                }}
                .stat-val {{
                    font-size: 18px;
                    font-weight: 800;
                    color: {accent_color};
                }}
                .stat-lbl {{
                    font-size: 10px;
                    color: #cbd5e1;
                    margin-top: 2px;
                }}
                .contact-card {{
                    background: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 14px;
                    padding: 20px;
                    text-align: center;
                    margin-top: 10px;
                }}
            </style>

            <div class="video-container">
            """

            # 1. Standart İçerik Sahneleri (Her birinde Logo Kartı Mevcut)
            for i, sc in enumerate(scenes):
                video_player_html += f"""
                <div class="scene-slide scene-{i}">
                    <div>
                        {top_logo_overlay_html}
                        <div style="text-align: center; margin-top: 10px;">
                            <span class="badge">SAHNE 0{i+1}</span>
                            <div class="main-title">{sc['title']}</div>
                            <div class="desc-text">{sc['desc']}</div>
                        </div>
                    </div>
                    <div>
                        <div class="stat-box">
                            <div class="stat-val">{sc['stat1']}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-val">{sc['stat2']}</div>
                        </div>
                    </div>
                    <div style="text-align: center; font-size: 10px; color: #64748b; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.1);">
                        İSTESTATE & MERİÇ İNŞAAT PROJE SUNUMU
                    </div>
                </div>
                """

            # 2. Son Sahne: İletişim ve Kapanış Sahnesi (Logo Kartı ve Telefon Dahil)
            video_player_html += f"""
                <div class="scene-slide scene-contact">
                    <div>
                        {top_logo_overlay_html}
                        <div style="text-align: center; margin-top: 10px;">
                            <span class="badge" style="background: {accent_color}; color: #000000;">İLETİŞİM & DETAYLAR</span>
                            <div class="main-title">{contact_scene['title']}</div>
                            <div class="desc-text">{contact_scene['desc']}</div>
                        </div>
                    </div>
                    <div class="contact-card">
                        <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px;">İletişim Hattı</div>
                        <div style="font-size: 22px; font-weight: 800; color: {accent_color}; margin: 8px 0;">📞 {contact_scene['phone']}</div>
                        <div style="font-size: 11px; color: #ffffff; margin-top: 4px;">📍 {contact_scene['location']}</div>
                        <div style="font-size: 10px; color: #cbd5e1; margin-top: 2px;">{contact_scene['summary']}</div>
                    </div>
                    <div style="text-align: center; font-size: 10px; color: #64748b; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.1);">
                        © İSTESTATE MERİÇ GAYRİMENKUL DANIŞMANLIK
                    </div>
                </div>
            </div>
            """

            st.markdown("###### 🎬 4K Tanıtım Filmi Canlı Ön İzleyici (Döngülü Entegre Sunum)")
            components.html(video_player_html, height=640)

else:
    st.info("💡 Lütfen sol menüden raporlama ve fizibilite yapmak istediğiniz parsel(ler)i seçin.")
