import base64
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import pdfplumber
import streamlit as st
from weasyprint import CSS, HTML

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="İstestate & Meriç İnşaat - Fizibilite Portalı",
    page_icon="🏢",
    layout="wide",
)

# --- ÖZEL KURUMSAL STİL ENJEKSİYONU ---
st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)

# --- FONKSİYON ADI AKILLI TEMİZLEME MOTORU ---
def clean_fonksiyon_adi(name):
    if not name:
        return "KONUT ALANI"
    n = str(name).upper().strip()
    
    # Yüzde veya alan içeren satırlardan gerçek fonksiyon adını ayrıştır
    if "TİCARET" in n and "KONUT" in n:
        return "TİCARET VE KONUT ALANI"
    elif "TİCARET" in n or "TİCARİ" in n:
        return "TİCARET ALANI"
    elif "VİLLA" in n:
        return "VİLLA ALANI"
    elif "KONUT" in n or "MESKEN" in n:
        return "KONUT ALANI"

    # Gereksiz sayısal, yüzde ve m2 kalıplarını temizle
    n_clean = re.sub(r'[%–\-\d\.,]+\s*m²?', '', n).strip()
    n_clean = re.sub(r'\d+', '', n_clean).strip()
    
    if len(n_clean) > 2:
        return n_clean
    return "KONUT ALANI"

# --- KALİCİ DOSYA TABANLI VERİTABANI YÖNETİMİ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "imar_veritabani.json")

def load_persistent_db():
    raw_db = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and len(data) > 0:
                    raw_db = data
        except Exception as e:
            st.warning(f"Veritabanı okunurken uyarı: {e}")

    if "parcel_db" in st.session_state and len(st.session_state["parcel_db"]) > 0:
        return st.session_state["parcel_db"]

    return raw_db

def save_persistent_db(db_data):
    try:
        st.session_state["parcel_db"] = db_data
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Veritabanı kaydedilirken hata oluştu: {e}")

if "parcel_db" not in st.session_state:
    st.session_state["parcel_db"] = load_persistent_db()

# --- GÖRSELİ BASE64'E ÇEVİRME YARDIMCISI ---
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

img1_tag = f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 45px; width: auto; object-fit: contain;'>" if img1_base64 else "<h4 style='color:#1e3a8a; margin:0;'>İSTESTATE</h4>"
img2_tag = f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 45px; width: auto; object-fit: contain;'>" if img2_base64 else "<h4 style='color:#1e3a8a; margin:0;'>MERİÇ İNŞAAT</h4>"

# --- 1. TCMB CANLI DÖVİZ KURU SERVİSİ ---
@st.cache_data(ttl=300)
def get_live_exchange_rates():
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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

# --- 2. BEYKOZ GERÇEKÇİ PİYASA VE PROJE TİPİ MATRİSİ ---
def get_realistic_market_pricing(mahalle_adi, proje_tipi, usd_rate):
    mahalle_base_tl = {
        "ACARLAR": 140000, "ANADOLU HİSARI": 130000, "KANLICA": 125000, 
        "GÖKSU": 110000, "GÖRELE": 115000, "RİVA": 120000, "ÇİFTLİK": 115000, 
        "BAKLACI": 95000, "KAVACIK": 90000, "ÇENGELDERE": 105000, 
        "YAVUZ SELİM": 80000, "FATİH": 75000, "SOĞUKSU": 95000, "PAŞABAHÇE": 90000, "VARSAYILAN": 95000
    }
    
    clean_mahalle = mahalle_adi.upper().replace("İ", "I").replace("Ç", "C").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").strip()
    base_tl = mahalle_base_tl.get(clean_mahalle, mahalle_base_tl["VARSAYILAN"])
    
    proje_carpanlari = {
        "Lüks Villa / Müstakil Proje": {"satis_mod": 1.55, "maliyet_mod": 1350, "bodrum_deger_orani": 0.60},
        "Üst Segment Konut / Rezidans": {"satis_mod": 1.25, "maliyet_mod": 1100, "bodrum_deger_orani": 0.50},
        "Standart Konut / Apartman": {"satis_mod": 1.00, "maliyet_mod": 900, "bodrum_deger_orani": 0.40},
        "Ticari / Ofis Kompleksi": {"satis_mod": 1.35, "maliyet_mod": 1050, "bodrum_deger_orani": 0.70},
        "Karma Proje (Konut + Ticari)": {"satis_mod": 1.20, "maliyet_mod": 1000, "bodrum_deger_orani": 0.50}
    }
    
    p_conf = proje_carpanlari.get(proje_tipi, proje_carpanlari["Standart Konut / Apartman"])
    
    satis_fiyati_usd = round((base_tl * p_conf["satis_mod"]) / usd_rate, 2)
    maliyet_fiyati_usd = float(p_conf["maliyet_mod"])
    bodrum_orani = float(p_conf["bodrum_deger_orani"])
    
    return satis_fiyati_usd, maliyet_fiyati_usd, bodrum_orani

def parse_tr_float(val_str):
    if not val_str:
        return 0.0
    s = str(val_str).strip()
    if "-" in s:
        s = s.split("-")[-1]
    s = re.sub(r'[^\d\.,]', '', s).strip()
    if not s:
        return 0.0
    
    if ',' in s and '.' in s:
        if s.rfind('.') > s.rfind(','):
            s = s.replace(',', '')
        else:
            s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    elif '.' in s:
        parts = s.split('.')
        if len(parts[-1]) == 3 and len(parts) > 1:
            s = s.replace('.', '')
            
    try:
        return float(s)
    except ValueError:
        return 0.0

def detect_terk_status(text, toplam_alan, fonksiyonlar):
    text_upper = text.upper()
    terksiz_kaliplar = [
        "YOLA TERK VE KAMUYA AYRILAN KISIMLAR KAMU ELİNE GEÇMEDEN",
        "TERK YAPILMAMIŞ", "TERKİ YAPILAMIŞ", "TERK YAPILMADAN", "TERKİ YAPILMADAN", "DOP TERKİ YAPILMAMIŞ"
    ]
    if any(k in text_upper for k in terksiz_kaliplar):
        return False
        
    terkli_kaliplar = [
        "TERKİ YAPILMIŞTIR", "TERKİ YAPILMIŞ", "TERK YAPILMIŞTIR", "KAMUYA TERK EDİLMİŞTİR", "DOP TERKİ YAPILMAMIŞTIR"
    ]
    if any(k in text_upper for k in terkli_kaliplar):
        return True
        
    toplam_fonksiyon_m2 = sum(f["giren_m2"] for f in fonksiyonlar if not any(x in f["fonksiyon_adi"].upper() for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
    
    if toplam_alan > 0 and toplam_fonksiyon_m2 > 0:
        if abs(toplam_alan - toplam_fonksiyon_m2) < 1.0 or (toplam_fonksiyon_m2 / toplam_alan) >= 0.99:
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
                t = page.extract_text() or ""
                full_text += "\n" + t
                
                tables = page.extract_tables() or []
                for table in tables:
                    for r_idx, row in enumerate(table):
                        cells = [str(c).strip().replace("\n", " ") if c is not None else "" for c in row]
                        row_str = " ".join(cells)
                        
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
                                            
                        # Tablo içerisindeki TÜM fonksiyon satırlarını eksiksiz toplamak için kontrol
                        if "Fonksiyon Adı" in row_str or any("Fonksiyon" in str(c) for c in cells) or "%" in row_str or "m²" in row_str:
                            fonk_raw = ""
                            taks_val, kaks_val, giren_m2 = 0.30, 0.40, 0.0
                            
                            for sub_idx in range(max(0, r_idx-1), min(r_idx + 3, len(table))):
                                sub_cells = [str(c).strip().replace("\n", " ") if c is not None else "" for c in table[sub_idx]]
                                sub_str = " ".join(sub_cells)
                                
                                for c in sub_cells:
                                    c_upper = c.upper()
                                    if any(k in c_upper for k in ["KONUT", "TİCARET", "TİCARİ", "VİLLA", "MESKEN", "İMAR", "KONUT+TİCAret", "TİCARET+KONUT"]):
                                        if "FONKSİYON" not in c_upper:
                                            fonk_raw = c
                                            break
                                if not fonk_raw and len(sub_cells) > 0 and sub_cells[0] and "FONKSİYON" not in sub_cells[0].upper():
                                    if not any(char.isdigit() for char in sub_cells[0]):
                                        fonk_raw = sub_cells[0]
                                        
                                t_m = re.search(r'Taks\s*\|?\s*([\d\.,]+)', sub_str, re.IGNORECASE)
                                k_m = re.search(r'Kaks\s*\(Emsal\)\s*\|?\s*([\d\.,]+)', sub_str, re.IGNORECASE)
                                if t_m:
                                    taks_val = parse_tr_float(t_m.group(1))
                                if k_m:
                                    kaks_val = parse_tr_float(k_m.group(1))
                                    
                                if "m²" in sub_str or "m2" in sub_str or "%" in sub_str:
                                    m2_match = re.findall(r'([\d\.,]+)\s*m²?', sub_str)
                                    if m2_match:
                                        giren_m2 = parse_tr_float(m2_match[-1])
                                        
                            if fonk_raw:
                                clean_name = clean_fonksiyon_adi(fonk_raw)
                                if clean_name:
                                    # Aynı fonksiyon türü daha önce eklenmediyse veya farklı yüzdelik/alan dağılımı varsa listeye ekle
                                    parcel_data["fonksiyonlar"].append({
                                        "fonksiyon_adi": clean_name,
                                        "taks": taks_val,
                                        "kaks": kaks_val,
                                        "giren_m2": giren_m2
                                    })
                                    
        if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
            m_m = re.search(r'Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)', full_text)
            a_m = re.search(r'Ada\s*\|\s*(\d+)', full_text)
            p_m = re.search(r'Parsel\s*\|\s*(\d+)', full_text)
            al_m = re.search(r'Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²', full_text)
            
            if m_m:
                parcel_data["mahalle"] = m_m.group(1).upper()
            if a_m:
                parcel_data["ada"] = str(a_m.group(1)).strip()
            if p_m:
                parcel_data["parsel"] = str(p_m.group(1)).strip()
            if al_m and parcel_data["toplam_alan"] == 0.0:
                parcel_data["toplam_alan"] = parse_tr_float(al_m.group(1))
                
        # Eğer tablodan fonksiyon yakalanamadıysa metin içerisinden çoklu fonksiyon araması yap
        if not parcel_data["fonksiyonlar"]:
            found_fonks = []
            if "KONUT" in full_text.upper():
                found_fonks.append("KONUT ALANI")
            if "TİCARET" in full_text.upper() or "TICARET" in full_text.upper():
                found_fonks.append("TİCARET ALANI")
            if not found_fonks:
                found_fonks.append("KONUT ALANI")
                
            for idx, fn in enumerate(found_fonks):
                parcel_data["fonksiyonlar"].append({
                    "fonksiyon_adi": fn,
                    "taks": 0.30,
                    "kaks": 0.40,
                    "giren_m2": parcel_data["toplam_alan"] / len(found_fonks)
                })
                
        toplam_f_m2 = sum(f["giren_m2"] for f in parcel_data["fonksiyonlar"])
        if toplam_f_m2 <= 0 and parcel_data["toplam_alan"] > 0:
            for f in parcel_data["fonksiyonlar"]:
                f["giren_m2"] = parcel_data["toplam_alan"] / len(parcel_data["fonksiyonlar"])
                
        parcel_data["terk_yapilmis_mi"] = detect_terk_status(full_text, parcel_data["toplam_alan"], parcel_data["fonksiyonlar"])
    except Exception as e:
        st.error(f"PDF işlenirken bir hata oluştu: {e}")
        
    return parcel_data

# --- KOMPAKT & KURUMSAL HEADER ---
st.markdown(f"""
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; padding: 15px 25px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04); margin-bottom: 20px;">
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
        <div style="flex: 1; text-align: left;">{img1_tag}</div>
        <div style="flex: 2; text-align: center;">
            <h2 style='color: #0f172a; font-size: 18px; font-weight: 800; margin: 0; letter-spacing: -0.3px;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT</h2>
            <p style='color: #475569; font-size: 12px; font-weight: 500; margin: 2px 0 0 0;'>Akıllı Gayrimenkul Geliştirme ve Fizibilite Portalı</p>
        </div>
        <div style="flex: 1; text-align: right;">{img2_tag}</div>
    </div>
</div>
""", unsafe_allow_html=True)

rates = get_live_exchange_rates()

st.sidebar.header("📁 İmar Belgesi Yükleme")
uploaded_files = st.sidebar.file_uploader("İmar Durum Raporu (PDF) Seçin", type=["pdf"], accept_multiple_files=True)

just_uploaded_keys = []
if uploaded_files:
    for uploaded_file in uploaded_files:
        p_data = parse_imar_pdf(uploaded_file)
        unique_key = f"{p_data['mahalle']} | Ada: {p_data['ada']} - Parsel: {p_data['parsel']}"
        st.session_state["parcel_db"][unique_key] = p_data
        just_uploaded_keys.append(unique_key)
        
    save_persistent_db(st.session_state["parcel_db"])
    st.sidebar.success(f"{len(uploaded_files)} Adet Belge Arşive Eklendi!")

st.sidebar.divider()
st.sidebar.subheader("🎯 Rapor İçin Parsel Seçimi & Arama")

all_db_keys = list(st.session_state["parcel_db"].keys())

if all_db_keys:
    unique_adas = sorted(list(set([str(p_data.get("ada", "0")).strip() for p_data in st.session_state["parcel_db"].values()])))
    selected_ada_filter = st.sidebar.selectbox("Ada Numarasına Göre Filtrele:", options=["Seçiniz..."] + unique_adas)
    
    filtered_keys = [k for k, p_data in st.session_state["parcel_db"].items() if str(p_data.get("ada", "")).strip() == str(selected_ada_filter).strip()] if selected_ada_filter != "Seçiniz..." else all_db_keys
    
    default_selection = just_uploaded_keys if just_uploaded_keys else filtered_keys[:min(3, len(filtered_keys))]
    
    selected_keys = st.sidebar.multiselect("Raporlanacak Parselleri Seçin:", options=filtered_keys, default=default_selection)
else:
    st.sidebar.info("Arşivde kayıtlı parsel yok. Sol üstten PDF imar belgesi yükleyin.")
    selected_keys = []

if selected_keys:
    active_parcel_db = {k: st.session_state["parcel_db"][k] for k in selected_keys}
    
    emsal_artis_orani = 1.30
    bahce_terk_orani = st.sidebar.slider("Bahçe Alanı Terk Oranı (%)", 0, 80, 40, step=1)
    
    combined_fonk_text = " ".join([f["fonksiyon_adi"] for p in active_parcel_db.values() for f in p["fonksiyonlar"]])
    
    has_ticaret = any(x in combined_fonk_text for x in ["TICARET", "TICARI"])
    has_konut = any(x in combined_fonk_text for x in ["KONUT", "MESKEN"])
    has_villa = any(x in combined_fonk_text for x in ["VILLA", "AYRIK", "IKIZ"])
    
    if has_ticaret and has_konut:
        allowed_project_types = ["Karma Proje (Konut + Ticari)", "Ticari / Ofis Kompleksi"]
        default_p_idx = 0
    elif has_ticaret:
        allowed_project_types = ["Ticari / Ofis Kompleksi", "Karma Proje (Konut + Ticari)"]
        default_p_idx = 0
    elif has_villa:
        allowed_project_types = ["Lüks Villa / Müstakil Proje", "Üst Segment Konut / Rezidans"]
        default_p_idx = 0
    else:
        allowed_project_types = ["Standart Konut / Apartman", "Üst Segment Konut / Rezidans", "Lüks Villa / Müstakil Proje", "Karma Proje (Konut + Ticari)"]
        default_p_idx = 0

    st.markdown("""
    <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 18px 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
        <div style="display: flex; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
            <span style="font-size: 18px; margin-right: 8px;">⚙️</span>
            <div>
                <h3 style="color: #0f172a; margin: 0; font-size: 15px; font-weight: 700;">Gelişmiş Fizibilite ve Proje Parametreleri</h3>
                <p style="color: #64748b; margin: 0; font-size: 11px;">İmar fonksiyonuna dayalı kısıtlanmış proje tipleri, havuz senaryoları ve iş modelleri.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        is_modeli = st.selectbox("İş Modeli / Rapor Türü", options=["Kat Karşılığı Proje Raporu", "Doğrudan Satılık / Arsa Yatırım Raporu"], key="global_is_modeli")
        
    with col_m2:
        toplu_p_tipi = st.selectbox("Toplu Proje Tipi Seçimi (İmar Kısıtlı)", options=allowed_project_types, index=min(default_p_idx, len(allowed_project_types)-1), key="toplu_p_tipi_master")
        
    if "Villa" in toplu_p_tipi:
        available_pool_options = ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"]
    elif "Ticari" in toplu_p_tipi:
        available_pool_options = ["Havuz İptal / Yapılmayacak"]
    else:
        available_pool_options = ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"]
        
    with col_m3:
        toplu_havuz = st.selectbox("Toplu Havuz ve Site Konsepti", options=available_pool_options, key="toplu_havuz_master")
        
    arsa_payi_orani = 0.0
    arsa_bonus_usd = 0.0
    if "Kat Karşılığı" in is_modeli:
        st.markdown("<div style='margin-top: 10px; border-top: 1px dashed #cbd5e1; padding-top: 10px;'></div>", unsafe_allow_html=True)
        col_gk1, col_gk2, col_gk3 = st.columns([2, 1, 2])
        with col_gk1:
            arsa_payi_orani = st.slider("Arsa Sahibi Payı / Kat Karşılığı Oranı (%)", 0, 70, 50)
        with col_gk2:
            bonus_curr = st.selectbox("Para Birimi", options=["USD ($)", "EUR (€)", "TL (₺)"])
        with col_gk3:
            raw_bonus_val = st.number_input("💵 Nakit Bonus / İmza Tutarı", min_value=0.0, value=0.0, step=10000.0, format="%.2f")
            if "EUR" in bonus_curr:
                arsa_bonus_usd = raw_bonus_val * (rates["EUR"] / rates["USD"])
            elif "TL" in bonus_curr:
                arsa_bonus_usd = raw_bonus_val / rates["USD"]
            else:
                arsa_bonus_usd = raw_bonus_val

    valid_active_functions_with_area = []
    function_total_brut_areas = {}
    function_total_ratios = {}
    
    for key, p in active_parcel_db.items():
        toplam_arsa_m2 = p["toplam_alan"]
        is_terkli = p["terk_yapilmis_mi"]
        fonks_list = p["fonksiyonlar"]
        
        toplam_f_m2 = sum(f["giren_m2"] for f in fonks_list if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
        if toplam_f_m2 <= 0:
            toplam_f_m2 = toplam_arsa_m2 if toplam_arsa_m2 > 0 else 1.0
            
        for f in fonks_list:
            fonk_name = clean_fonksiyon_adi(f["fonksiyon_adi"])
            if any(x in fonk_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                continue
                
            fonk_giren_m2 = f.get("giren_m2", toplam_arsa_m2)
            if fonk_giren_m2 <= 0:
                fonk_giren_m2 = toplam_arsa_m2 / max(1, len(fonks_list))
                
            fonk_alan_orani = fonk_giren_m2 / toplam_f_m2
            parsel_net_arsa = toplam_arsa_m2 if is_terkli else toplam_arsa_m2 * 0.70
            fonk_hesaba_alinan_m2 = parsel_net_arsa * fonk_alan_orani
            fonk_toplam_brut_m2 = fonk_hesaba_alinan_m2 * f["kaks"] * emsal_artis_orani
            
            if fonk_toplam_brut_m2 > 0:
                if fonk_name not in valid_active_functions_with_area:
                    valid_active_functions_with_area.append(fonk_name)
                    function_total_brut_areas[fonk_name] = 0.0
                    function_total_ratios[fonk_name] = 0.0
                function_total_brut_areas[fonk_name] += fonk_toplam_brut_m2
                function_total_ratios[fonk_name] += (fonk_alan_orani * 100.0)

    function_target_sizes = {}
    if valid_active_functions_with_area:
        st.markdown("<div style='margin-top: 12px; font-weight: 700; color: #0f172a; font-size: 13px;'>📐 Fonksiyon Bazlı Hedef Ortalama Bağımsız Bölüm Alanları (m²)</div>", unsafe_allow_html=True)
        fn_cols = st.columns(len(valid_active_functions_with_area))
        
        for idx, fonk_adi in enumerate(valid_active_functions_with_area):
            total_b_m2 = function_total_brut_areas.get(fonk_adi, 0.0)
            
            if "TİCARET" in fonk_adi and "KONUT" in fonk_adi:
                def_sz, min_sz, max_sz, step_sz = 120, 60, 400, 10
                icon_prefix = "🏢🏠"
            elif "TİCARET" in fonk_adi:
                def_sz, min_sz, max_sz, step_sz = 150, 60, 800, 10
                icon_prefix = "🏢"
            elif "VİLLA" in fonk_adi:
                def_sz, min_sz, max_sz, step_sz = 250, 180, 550, 10
                icon_prefix = "🏡"
            else:
                def_sz, min_sz, max_sz, step_sz = 95, 55, 250, 5
                icon_prefix = "🏠"
                
            label_txt = f"{icon_prefix} {fonk_adi} : ( Toplam Brüt: {total_b_m2:,.2f} m² )"
            
            with fn_cols[idx % len(fn_cols)]:
                function_target_sizes[fonk_adi] = st.slider(
                    label_txt,
                    min_value=min_sz,
                    max_value=max_sz,
                    value=def_sz,
                    step=step_sz,
                    key=f"target_size_{fonk_adi}"
                )

    first_mahalle = list(active_parcel_db.values())[0].get("mahalle", "VARSAYILAN")
    auto_satis, auto_maliyet, auto_bodrum_orani = get_realistic_market_pricing(first_mahalle, toplu_p_tipi, rates["USD"])
    
    st.markdown(
        f"<div style='font-size: 12px; color: #334155; margin-top: 10px; background: #f8fafc; padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0;'>"
        f"💡 <b>{toplu_p_tipi} ({toplu_havuz})</b> piyasa maliyet referansı: <b>${auto_maliyet:,.2f}/m²</b> | Satış Fiyatı: <b>${auto_satis:,.2f}/m²</b>"
        f"</div>",
        unsafe_allow_html=True
    )
    st.markdown("</div>", unsafe_allow_html=True)

    function_configs = {}
    for key, p in active_parcel_db.items():
        toplam_arsa_m2 = p["toplam_alan"]
        is_terkli = p["terk_yapilmis_mi"]
        fonks_list = p["fonksiyonlar"]
        
        toplam_f_m2 = sum(f["giren_m2"] for f in fonks_list if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
        if toplam_f_m2 <= 0:
            toplam_f_m2 = toplam_arsa_m2 if toplam_arsa_m2 > 0 else 1.0
            
        for f in fonks_list:
            fonk_name = clean_fonksiyon_adi(f["fonksiyon_adi"])
            if any(x in fonk_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                continue
                
            fonk_giren_m2 = f.get("giren_m2", toplam_arsa_m2)
            if fonk_giren_m2 <= 0:
                fonk_giren_m2 = toplam_arsa_m2 / max(1, len(fonks_list))
                
            fonk_alan_orani = fonk_giren_m2 / toplam_f_m2
            parsel_net_arsa = toplam_arsa_m2 if is_terkli else toplam_arsa_m2 * 0.70
            fonk_hesaba_alinan_m2 = parsel_net_arsa * fonk_alan_orani
            fonk_toplam_brut_m2 = fonk_hesaba_alinan_m2 * f["kaks"] * emsal_artis_orani
            
            if fonk_toplam_brut_m2 <= 0:
                continue
                
            effective_target_size = max(10.0, float(function_target_sizes.get(fonk_name, 95.0)))
            calculated_adet = round(fonk_toplam_brut_m2 / effective_target_size)
            def_adet = max(1, int(calculated_adet))
            
            r_satis, r_maliyet, r_bodrum_orani = get_realistic_market_pricing(first_mahalle, toplu_p_tipi, rates["USD"])
            parsel_fonk_key = f"{key}_{fonk_name}"
            function_configs[parsel_fonk_key] = {
                "proje_tipi": toplu_p_tipi,
                "adet": int(def_adet),
                "havuz_mod": toplu_havuz,
                "maliyet": r_maliyet,
                "satis": r_satis,
                "bodrum_orani": r_bodrum_orani,
                "fonk_hesaba_alinan_m2": fonk_hesaba_alinan_m2
            }

    total_yasal_brut_insaat = 0.0
    total_simulated_bodrum = 0.0
    total_bahce_alani_terki = 0.0
    total_ciro_usd = 0.0
    total_maliyet_usd = 0.0

    for key, p in active_parcel_db.items():
        toplam_arsa_m2 = p["toplam_alan"]
        is_terkli = p["terk_yapilmis_mi"]
        fonks_list = p["fonksiyonlar"]
        
        toplam_f_m2 = sum(f["giren_m2"] for f in fonks_list if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
        if toplam_f_m2 <= 0:
            toplam_f_m2 = toplam_arsa_m2 if toplam_arsa_m2 > 0 else 1.0
            
        for f in fonks_list:
            fonk_adi = clean_fonksiyon_adi(f["fonksiyon_adi"])
            if any(x in fonk_adi for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                continue
                
            parsel_fonk_key = f"{key}_{fonk_adi}"
            conf = function_configs.get(parsel_fonk_key)
            if not conf:
                continue
                
            kaks = f["kaks"]
            fonk_giren_m2 = f.get("giren_m2", toplam_arsa_m2)
            if fonk_giren_m2 <= 0:
                fonk_giren_m2 = toplam_arsa_m2 / max(1, len(fonks_list))
            fonk_alan_orani = fonk_giren_m2 / toplam_f_m2
            
            parsel_net_arsa = toplam_arsa_m2 if is_terkli else toplam_arsa_m2 * 0.70
            fonk_hesaba_alinan_m2 = parsel_net_arsa * fonk_alan_orani
            
            brut_insaat = fonk_hesaba_alinan_m2 * kaks * emsal_artis_orani
            if brut_insaat <= 0:
                continue
                
            total_yasal_brut_insaat += brut_insaat
            bahce_terki = fonk_hesaba_alinan_m2 * (bahce_terk_orani / 100.0)
            total_bahce_alani_terki += bahce_terki
            
            tekil_havuz_payi = 35.0 if "Müstakil Özel Havuzlu" in conf["havuz_mod"] else 0.0
            sim_bodrum = (brut_insaat - (tekil_havuz_payi * conf["adet"])) * conf["bodrum_orani"]
            total_simulated_bodrum += sim_bodrum
            
            normal_c = brut_insaat * conf["satis"]
            bodrum_c = sim_bodrum * conf["satis"] * conf["bodrum_orani"]
            total_ciro_usd += (normal_c + bodrum_c)
            total_maliyet_usd += (brut_insaat * conf["maliyet"])

    total_maliyet_usd += arsa_bonus_usd
    arsa_sahibi_payi_usd = total_ciro_usd * (arsa_payi_orani / 100) if "Kat Karşılığı" in is_modeli else 0.0
    mutaahhit_net_kar_usd = total_ciro_usd - total_maliyet_usd - arsa_sahibi_payi_usd
    yg_orani = (mutaahhit_net_kar_usd / total_maliyet_usd * 100) if total_maliyet_usd > 0 else 0

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Seçilen Parseller & İnşaat Alanı", 
        "🏛️ Mimari Fizibilite", 
        "📑 Proje Raporu & Fizibilite", 
        "🖨️ Rapor Ön İzleme & PDF"
    ])

    with tab1:
        st.subheader("📊 Seçilen Parseller & Fonksiyon Bazlı İnşaat Alanı")
        table_rows = []
        sum_alan = 0.0
        sum_hesaba_alinan = 0.0
        sum_net_alan = 0.0
        sum_brut_insaat = 0.0
        
        for key, p in active_parcel_db.items():
            mahalle = p.get("mahalle", "BİLİNMİYOR")
            ada = p.get("ada", "0")
            parsel = p.get("parsel", "0")
            toplam_arsa_m2 = p.get("toplam_alan", 0.0)
            is_terkli = p.get("terk_yapilmis_mi", False)
            fonks_list = p["fonksiyonlar"]
            
            toplam_f_m2 = sum(f["giren_m2"] for f in fonks_list if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
            if toplam_f_m2 <= 0:
                toplam_f_m2 = toplam_arsa_m2 if toplam_arsa_m2 > 0 else 1.0
                
            for f in fonks_list:
                fonk_name = clean_fonksiyon_adi(f["fonksiyon_adi"])
                if any(x in fonk_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                    continue
                kaks = f["kaks"]
                fonk_giren_m2 = f.get("giren_m2", toplam_arsa_m2)
                if fonk_giren_m2 <= 0:
                    fonk_giren_m2 = toplam_arsa_m2 / max(1, len(fonks_list))
                fonk_alan_orani = fonk_giren_m2 / toplam_f_m2
                
                parsel_net_arsa = toplam_arsa_m2 if is_terkli else toplam_arsa_m2 * 0.70
                hesaba_alinan_m2 = parsel_net_arsa * fonk_alan_orani
                brut_insaat_arsa = hesaba_alinan_m2 * kaks * emsal_artis_orani
                if brut_insaat_arsa <= 0:
                    continue
                    
                sum_alan += (toplam_arsa_m2 * fonk_alan_orani)
                sum_hesaba_alinan += hesaba_alinan_m2
                sum_net_alan += fonk_giren_m2
                sum_brut_insaat += brut_insaat_arsa
                
                table_rows.append({
                    "MAHALLE": mahalle,
                    "ADA": ada,
                    "PARSEL": parsel,
                    "FONKSİYON / NİTELİK": fonk_name,
                    "ARSA PAYI (M²)": f"{toplam_arsa_m2 * fonk_alan_orani:,.2f}",
                    "HESABA ALINAN (M²)": f"{hesaba_alinan_m2:,.2f}",
                    "KAKS": f"{kaks:.2f}",
                    "İNŞAAT ALANI (BRÜT M²)": f"{brut_insaat_arsa:,.2f}"
                })
                
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
        summary_df = pd.DataFrame([{
            "SORGULANAN PARSEL": f"{len(active_parcel_db)} Adet",
            "TOPLAM ARSA PAYI (M²)": f"{sum_alan:,.2f}",
            "HESABA ALINAN (M²)": f"{sum_hesaba_alinan:,.2f}",
            "TOPLAM İNŞAAT (BRÜT M²)": f"{sum_brut_insaat:,.2f}"
        }])
        st.dataframe(summary_df, use_container_width=True)

    with tab2:
        st.subheader("🏛️ Mimari Fizibilite & Potansiyel Senaryo Dağılım Matrisi (Nitelik Bazlı)")
        mimari_rows = []
        mimari_sum_brut = 0.0
        mimari_sum_adet = 0
        mimari_sum_bodrum = 0.0
        
        for key, p in active_parcel_db.items():
            mahalle = p.get("mahalle", "BİLİNMİYOR")
            ada = p.get("ada", "0")
            parsel = p.get("parsel", "0")
            toplam_arsa_m2 = p.get("toplam_alan", 0.0)
            is_terkli = p.get("terk_yapilmis_mi", False)
            fonks_list = p["fonksiyonlar"]
            
            toplam_f_m2 = sum(f["giren_m2"] for f in fonks_list if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
            if toplam_f_m2 <= 0:
                toplam_f_m2 = toplam_arsa_m2 if toplam_arsa_m2 > 0 else 1.0
                
            for f in fonks_list:
                fonk_name = clean_fonksiyon_adi(f["fonksiyon_adi"])
                if any(x in fonk_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                    continue
                    
                parsel_fonk_key = f"{key}_{fonk_name}"
                conf = function_configs.get(parsel_fonk_key)
                if not conf:
                    continue
                    
                kaks = f["kaks"]
                fonk_giren_m2 = f.get("giren_m2", toplam_arsa_m2)
                if fonk_giren_m2 <= 0:
                    fonk_giren_m2 = toplam_arsa_m2 / max(1, len(fonks_list))
                fonk_alan_orani = fonk_giren_m2 / toplam_f_m2
                
                parsel_net_arsa = toplam_arsa_m2 if is_terkli else toplam_arsa_m2 * 0.70
                hesaba_alinan_m2 = parsel_net_arsa * fonk_alan_orani
                brut_insaat = hesaba_alinan_m2 * kaks * emsal_artis_orani
                if brut_insaat <= 0:
                    continue
                    
                konut_adeti = conf["adet"]
                birim_m2 = brut_insaat / konut_adeti if konut_adeti > 0 else brut_insaat
                tekil_havuz_payi = 35.0 if "Müstakil Özel Havuzlu" in conf["havuz_mod"] else 0.0
                sim_bodrum = (brut_insaat - (tekil_havuz_payi * konut_adeti)) * conf["bodrum_orani"]
                
                mimari_sum_brut += brut_insaat
                mimari_sum_adet += konut_adeti
                mimari_sum_bodrum += sim_bodrum
                
                mimari_rows.append({
                    "MAHALLE": mahalle,
                    "ADA/PARSEL": f"{ada}/{parsel}",
                    "FONKSİYON / NİTELİK": fonk_name,
                    "PROJE TİPİ": f"{conf['proje_tipi']} ({conf['havuz_mod']})",
                    "BRÜT İNŞAAT (M²)": f"{brut_insaat:,.2f}",
                    "ADET": konut_adeti,
                    "BİRİM BRÜT (M²)": f"{birim_m2:,.2f}",
                    "BODRUM (M²)": f"{sim_bodrum:,.2f}"
                })
                
        st.dataframe(pd.DataFrame(mimari_rows), use_container_width=True)
        
        st.markdown("### 📋 Toplu Proje ve Mimari Özet Matrisi")
        toplu_ortalama_birim = mimari_sum_brut / mimari_sum_adet if mimari_sum_adet > 0 else 0.0
        toplu_ozet_df = pd.DataFrame([{
            "İNCELENEN PARSEL SAYISI": f"{len(active_parcel_db)} Adet",
            "TOPLAM BAĞIMSIZ BÖLÜM (ADET)": f"{mimari_sum_adet:,} Adet",
            "TOPLAM YASAL BRÜT İNŞAAT (M²)": f"{mimari_sum_brut:,.2f} m²",
            "TOPLAM SİMÜLE BODRUM (M²)": f"{mimari_sum_bodrum:,.2f} m²",
            "GENEL ORTALAMA BİRİM ALAN (M²)": f"{toplu_ortalama_birim:,.2f} m²",
            "SEÇİLEN KONSEPT / HAVUZ": f"{toplu_p_tipi} - {toplu_havuz}"
        }])
        st.dataframe(toplu_ozet_df, use_container_width=True)

    with tab3:
        st.subheader("📑 Finansal Fizibilite ve Fonksiyon Dağılım Matrisi")
        f_col1, f_col2, f_col3 = st.columns(3)
        f_col1.metric("Toplam Tahmini Brüt Ciro", f"${total_ciro_usd:,.2f}")
        f_col2.metric("Toplam İnşaat Maliyeti", f"${total_maliyet_usd:,.2f}")
        f_col3.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar_usd:,.2f}", f"%{yg_orani:.1f} YG")

    with tab4:
        st.subheader("🖨️ Kurumsal Tek Sayfa Rapor Ön İzleme ve PDF İndirme Merkezi")
        
        pdf_logo1_html = f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 32px;'>" if img1_base64 else "<b>İSTESTATE</b>"
        pdf_logo2_html = f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 32px;'>" if img2_base64 else "<b>MERİÇ İNŞAAT</b>"
        
        report_html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4 landscape; margin: 6mm 8mm; }}
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #1e293b; font-size: 8.5px; line-height: 1.12; }}
            .report-banner {{ background-color: #0b1d3a; color: #ffffff; width: 100%; border-collapse: collapse; margin-bottom: 6px; }}
            .report-banner td {{ border: none; padding: 6px 8px; vertical-align: middle; }}
            .section-title {{ font-size: 9px; font-weight: bold; color: #0b1d3a; border-left: 3px solid #0b1d3a; padding-left: 5px; background-color: #f1f5f9; margin-top: 5px; margin-bottom: 2px; text-transform: uppercase; }}
            .data-table {{ width: 100%; border-collapse: collapse; margin-top: 1px; font-size: 8.5px; }}
            .data-table th, .data-table td {{ border: 1px solid #cbd5e1; padding: 3px 5px; }}
            .data-table th {{ background-color: #f8fafc; font-weight: 700; }}
            .footer {{ font-size: 7.5px; color: #64748b; text-align: center; margin-top: 6px; border-top: 1px dashed #cbd5e1; padding-top: 2px; }}
        </style>
        </head>
        <body>
            <table class="report-banner">
                <tr>
                    <td style="width: 25%;">{pdf_logo1_html}</td>
                    <td style="width: 50%; text-align: center;"><h2 style="font-size:10.5px; margin:0; color:#fff;">AKILLI GAYRİMENKUL GELİŞTİRME VE FİZİBİLİTE RAPORU</h2></td>
                    <td style="width: 25%; text-align: right;">{pdf_logo2_html}</td>
                </tr>
            </table>
            <div class="section-title">1. Proje ve Lokasyon Künyesi (Toplu Parsel)</div>
            <table class="data-table">
                <tr><td>Lokasyon / Mahalle</td><td style="text-align: right; font-weight: bold;">{first_mahalle} ({len(active_parcel_db)} Parsel)</td></tr>
                <tr><td>Seçilen Proje Tipi & Konsept</td><td style="text-align: right; font-weight: bold; color: #1e3a8a;">{toplu_p_tipi} - {toplu_havuz}</td></tr>
                <tr><td>Toplam Brüt İnşaat Alanı</td><td style="text-align: right; font-weight: bold;">{total_yasal_brut_insaat:,.2f} m²</td></tr>
                <tr><td>Toplam Bahçe Alanı Terki</td><td style="text-align: right; font-weight: bold;">{total_bahce_alani_terki:,.2f} m²</td></tr>
            </table>
            <div class="section-title">2. Fonksiyon Bazlı Finansal Fizibilite Özeti</div>
            <table class="data-table">
                <tr><th>Finansal Kalem</th><th style="text-align: right;">Tutar (USD $)</th><th style="text-align: right;">Tutar (TL ₺)</th></tr>
                <tr><td>Toplam Tahmini Brüt Ciro</td><td style="text-align: right;">${total_ciro_usd:,.2f}</td><td style="text-align: right;">₺{total_ciro_usd * rates['USD']:,.2f}</td></tr>
                <tr><td>Toplam İnşaat Maliyeti</td><td style="text-align: right;">${total_maliyet_usd:,.2f}</td><td style="text-align: right;">₺{total_maliyet_usd * rates['USD']:,.2f}</td></tr>
                <tr style="font-weight: bold;"><td>Müteahhit Net Kârı</td><td style="text-align: right; color:#1e3a8a;">${mutaahhit_net_kar_usd:,.2f}</td><td style="text-align: right; color:#1e3a8a;">₺{mutaahhit_net_kar_usd * rates['USD']:,.2f} (%{yg_orani:.1f} YG)</td></tr>
            </table>
            <div class="footer">Bu rapor İstestate Gayrimenkul & Meriç İnşaat Emlak Akıllı Fizibilite Portalı tarafından üretilmiştir.</div>
        </body>
        </html>
        """
        
        pdf_bytes = HTML(string=report_html_template).write_pdf()
        st.download_button(
            label="📥 Toplu Parsel Kurumsal Fizibilite Raporunu PDF Olarak İndir",
            data=pdf_bytes,
            file_name=f"Kurumsal_Toplu_Fizibilite_{first_mahalle}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
else:
    st.info("👋 **Hoş Geldiniz!** Raporları görüntülemek için lütfen sol menüden istenilen parselleri çoklu şekilde seçin veya yeni bir imar belgesi (PDF) yükleyin.")
