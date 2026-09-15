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

# --- DİNAMİK FONKSİYON ADI ÇÖZÜMLEME VE FİLTRELEME MOTORU ---
def clean_fonksiyon_adi(name):
    if not name:
        return ""
    n = str(name).upper().strip()
    n = n.replace("FONKSİYON ADI", "").replace("FONKSIYON ADI", "").strip()
    
    gecersiz_ifadeler = [
        "-", "--", ".", ",", "0", "N/A", "İMAR DURUMU", "İMAR DURUMU BİLGİLERİ",
        "PARK", "PARK ALANI", "ÇOCUK PARKI", "YEŞİL ALAN", "TEKNİK ALTYAPI", 
        "TRAFO", "CAMİ", "İBADET YERİ", "OKUL", "LİSE", "İLKÖĞRETİM", "ANAOKULU", 
        "KÜLTÜREL", "SOSYAL TESİS", "BELEDİYE HİZMET ALANI", "YOL", "AÇIK OTOPARK", ""
    ]
    
    if n in gecersiz_ifadeler or any(x in n for x in ["PARK", "YEŞİL", "TEKNİK", "İBADET", "OKUL", "YOL", "TESİS", "TRAFO"]):
        return ""
    if "%" in n or "M²" in n or "M2" in n:
        return ""
    if re.match(r'^[\d\.,\s\-%]+$', n):
        return ""
    return n

# --- KALICI DOSYA TABANLI VERİTABANI YÖNETİMİ (GÜÇLENDİRİLMİŞ) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "imar_veritabani.json")

def load_persistent_db():
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
    except Exception as e:
        st.error(f"Veritabanı kaydedilirken hata oluştu: {e}")

# Oturum başlatılırken veritabanını diskten güvenli bir şekilde yükle
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

# --- TCMB CANLI DÖVİZ KURU SERVİSİ ---
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

# --- PİYASA VE PROJE TİPİ MATRİSİ ---
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
    if "-" in s and not re.match(r'^\d+[\.,]\d+\s*-\s*\d+[\.,]\d+$', s):
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

def parse_kaks_val(val_str):
    if not val_str:
        return 0.0
    s_str = str(val_str).strip()
    nums = re.findall(r'[\d\.,]+', s_str)
    parsed_vals = []
    for num_s in nums:
        v = parse_tr_float(num_s)
        if 0.05 <= v <= 10.0:
            parsed_vals.append(v)
    return max(parsed_vals) if parsed_vals else 0.0

# --- TERK ALGILAMA MOTORU ---
def detect_terk_status(text, toplam_alan, fonksiyonlar):
    text_upper = text.upper()
    
    terk_yapilmamis_kw = [
        "TERK YAPILMAMIŞ", "TERKİ YAPILMAMIŞ", "TERK YAPILMADAN", "DOP TERKİ YAPILMAMIŞ",
        "YOLA TERK VAR", "KAMUYA TERK VAR", "TERK EDİLECEKTİR", "YOLA TERKİ VARDIR",
        "YOLA TERK VE KAMUYA AYRILAN KISIMLAR KAMU ELİNE GEÇMEDEN", "TERK EDİLMELİDİR"
    ]
    
    terk_yapilmis_kw = [
        "TERKİ YAPILMIŞTIR", "TERKİ YAPILMIŞ", "TERK YAPILMIŞTIR", "TERK YAPILMIŞ",
        "KAMUYA TERK EDİLMİŞTİR", "YOLA TERKİ YAPILMIŞTIR", "TERK EDİLMİŞTİR",
        "TERK: YOK", "TERK YOK", "YOLA TERK: 0", "TERK MİKTARI: 0", "NET PARSEL",
        "TERKSİZ", "TERK GEREKMEMEKTEDİR"
    ]
    
    for kw in terk_yapilmamis_kw:
        if kw in text_upper:
            return False

    for kw in terk_yapilmis_kw:
        if kw in text_upper:
            return True
            
    terk_var_match = re.search(r'(?:YOLA|KAMUYA)?\s*TERK\s*[:=-]\s*(VAR|YAPILACAK|VARDIR)', text_upper)
    if terk_var_match:
        return False

    terk_yok_match = re.search(r'(?:YOLA|KAMUYA)?\s*TERK\s*[:=-]\s*(YOK|YAPILMIŞ|0)', text_upper)
    if terk_yok_match:
        return True

    toplam_fonksiyon_m2 = sum(f.get("giren_m2", 0.0) for f in fonksiyonlar if not any(x in f.get("fonksiyon_adi", "") for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]))
    if toplam_alan > 0 and toplam_fonksiyon_m2 > 0:
        if abs(toplam_alan - toplam_fonksiyon_m2) < 0.5 or (toplam_fonksiyon_m2 / toplam_alan) >= 0.995:
            return True
    return False

# --- KAPSAMLI VE TAM OTOMATİK İMAR PDF AYRIŞTIRMA MOTORU ---
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
                                        if "Mahalle" in head and val: parcel_data["mahalle"] = val.upper()
                                        elif "Ada" in head and val: parcel_data["ada"] = str(val).strip()
                                        elif "Parsel" in head and val: parcel_data["parsel"] = str(val).strip()
                                        elif "Alan" in head and val: parcel_data["toplam_alan"] = parse_tr_float(val)

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
                                    if cleaned: f_name = cleaned
                                elif "TAKS" in c_up:
                                    nums = re.findall(r'([\d\.,]+)', c)
                                    for num_str in nums:
                                        val = parse_tr_float(num_str)
                                        if 0 < val <= 1.0: f_taks = val
                                elif any(k in c_up for k in ["KAKS", "EMSAL", "EMS", "E:", "E="]):
                                    f_kaks = parse_kaks_val(c)
                                
                                m2_m = re.search(r'([\d\.,]+)\s*(?:M²|M2|%)', c, re.IGNORECASE)
                                if m2_m and not "ALAN" in c_up:
                                    val = parse_tr_float(m2_m.group(1))
                                    if val > 1.0: f_m2 = val

                            if f_kaks > 0 and not f_name and parcel_data["fonksiyonlar"]:
                                parcel_data["fonksiyonlar"][-1]["kaks"] = f_kaks
                                if f_taks > 0: parcel_data["fonksiyonlar"][-1]["taks"] = f_taks
                            elif f_name:
                                cleaned_check = clean_fonksiyon_adi(f_name)
                                if cleaned_check and not any(x in cleaned_check for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                                    if not any(f["fonksiyon_adi"] == cleaned_check for f in parcel_data["fonksiyonlar"]):
                                        parcel_data["fonksiyonlar"].append({
                                            "fonksiyon_adi": cleaned_check,
                                            "taks": f_taks,
                                            "kaks": f_kaks,
                                            "giren_m2": f_m2
                                        })

                lines = t.split('\n')
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
                                    num_m = re.search(r'([\d\.,]+)', sub_line)
                                    if num_m:
                                        val = parse_tr_float(num_m.group(1))
                                        if 0 < val <= 1.0: curr_taks = val
                                        
                                if any(k in sub_up for k in ["KAKS", "EMSAL", "EMS", "E:", "E="]):
                                    val = parse_kaks_val(sub_line)
                                    if val > 0: curr_kaks = val
                                        
                                m2_m = re.search(r'([\d\.,]+)\s*(?:m²|m2|%)', sub_line, re.IGNORECASE)
                                if m2_m:
                                    val = parse_tr_float(m2_m.group(1))
                                    if val > 0: curr_m2 = val

                            if curr_kaks <= 0:
                                kaks_match = re.search(r'(?:EMSAL|KAKS|EMS|E)\s*[:=\s]*([\d\.,\s/-]+)', line_up)
                                if kaks_match:
                                    curr_kaks = parse_kaks_val(kaks_match.group(1))

                            if curr_fonk:
                                cleaned_curr_fonk = clean_fonksiyon_adi(curr_fonk)
                                if cleaned_curr_fonk and not any(x in cleaned_curr_fonk for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                                    existing_f = next((f for f in parcel_data["fonksiyonlar"] if f["fonksiyon_adi"] == cleaned_curr_fonk), None)
                                    if existing_f:
                                        if curr_kaks > 0: existing_f["kaks"] = curr_kaks
                                        if curr_taks > 0: existing_f["taks"] = curr_taks
                                        if curr_m2 > 0: existing_f["giren_m2"] = curr_m2
                                    else:
                                        parcel_data["fonksiyonlar"].append({
                                            "fonksiyon_adi": cleaned_curr_fonk,
                                            "taks": curr_taks,
                                            "kaks": curr_kaks,
                                            "giren_m2": curr_m2
                                        })

        global_kaks_val = 0.0
        general_kaks_matches = re.findall(r'(?:EMSAL|KAKS|EMS|E)\s*[:=\s]*([\d\.,\s/-]+)', full_text, re.IGNORECASE)
        for gkm in general_kaks_matches:
            val = parse_kaks_val(gkm)
            if val > 0:
                global_kaks_val = val
                break

        for f in parcel_data["fonksiyonlar"]:
            if f["kaks"] <= 0 and global_kaks_val > 0:
                f["kaks"] = global_kaks_val

        if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
            m_m = re.search(r'Mahalle\s*[:\|]\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)', full_text)
            a_m = re.search(r'Ada\s*[:\|]\s*(\d+)', full_text)
            p_m = re.search(r'Parsel\s*[:\|]\s*(\d+)', full_text)
            al_m = re.search(r'Alan\s*\*?\s*[:\|]\s*([\d\.,]+)\s*m²', full_text)
            
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
    except Exception as e:
        print(f"PDF işlenirken hata oluştu: {e}")
        
    return parcel_data

# --- FONKSİYON ALANINA GİREN M² BAZLI NET ARSA VE BAHÇE DAĞITIM MOTORU ---
def get_parcel_function_breakdown(p, emsal_artis_orani=1.30):
    toplam_arsa_m2 = p.get("toplam_alan", 0.0)
    is_terkli = p.get("terk_yapilmis_mi", False)
    fonks_list = p.get("fonksiyonlar", [])
    
    valid_fonks = []
    for f in fonks_list:
        fonk_name = clean_fonksiyon_adi(f.get("fonksiyon_adi", ""))
        if not fonk_name or any(x in fonk_name for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
            continue
        active_kaks = f.get("kaks", 0.0)
        if active_kaks <= 0:
            continue
        valid_fonks.append((f, fonk_name, active_kaks))
        
    if not valid_fonks:
        return []
        
    sum_giren = sum(f.get("giren_m2", 0.0) for f, _, _ in valid_fonks)
    net_arsa_toplam = toplam_arsa_m2 if is_terkli else (toplam_arsa_m2 * 0.7)
    
    results = []
    for f, fonk_name, active_kaks in valid_fonks:
        giren_m2 = f.get("giren_m2", 0.0)
        
        if giren_m2 > 0:
            fonk_giren_payi = giren_m2
        else:
            fonk_giren_payi = toplam_arsa_m2 / len(valid_fonks) if len(valid_fonks) > 0 else toplam_arsa_m2
            
        bahce_kullanim_alani = fonk_giren_payi
        
        if sum_giren > 0:
            oran = giren_m2 / sum_giren
        else:
            oran = 1.0 / len(valid_fonks)
            
        net_arsa_payi = net_arsa_toplam * oran
        brut_insaat = net_arsa_payi * active_kaks * emsal_artis_orani
            
        results.append({
            "fonksiyon_adi": fonk_name,
            "taks": f.get("taks", 0.0),
            "kaks": active_kaks,
            "giren_m2": giren_m2,
            "net_arsa_payi": net_arsa_payi,
            "bahce_kullanim_alani": bahce_kullanim_alani,
            "brut_insaat": brut_insaat
        })
    return results

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
    current_db = st.session_state["parcel_db"]
    for uploaded_file in uploaded_files:
        p_data = parse_imar_pdf(uploaded_file)
        unique_key = f"{p_data['mahalle']} | Ada: {p_data['ada']} - Parsel: {p_data['parsel']}"
        current_db[unique_key] = p_data
        just_uploaded_keys.append(unique_key)
        
    save_persistent_db(current_db)
    st.sidebar.success(f"{len(uploaded_files)} Adet Belge Arşive Eklendi!")

st.sidebar.divider()
st.sidebar.subheader("🎯 Rapor İçin Parsel Seçimi & Arama")

all_db_keys = list(st.session_state["parcel_db"].keys())

if all_db_keys:
    unique_adas = sorted(list(set([str(p_data.get("ada", "0")).strip() for p_data in st.session_state["parcel_db"].values()])))
    selected_ada_filter = st.sidebar.selectbox("Ada Numarasına Göre Filtrele:", options=["Seçiniz..."] + unique_adas)
    
    filtered_keys = [k for k, p_data in st.session_state["parcel_db"].items() if str(p_data.get("ada", "")).strip() == str(selected_ada_filter).strip()] if selected_ada_filter != "Seçiniz..." else all_db_keys
    
    raw_default = just_uploaded_keys if just_uploaded_keys else filtered_keys[:min(3, len(filtered_keys))]
    safe_default = [k for k in raw_default if k in filtered_keys]
    
    selected_keys = st.sidebar.multiselect("Raporlanacak Parselleri Seçin:", options=filtered_keys, default=safe_default)
else:
    st.sidebar.info("Arşivde kayıtlı parsel yok. Sol üstten PDF imar belgesi yükleyin.")
    selected_keys = []

if selected_keys:
    active_parcel_db = {k: st.session_state["parcel_db"][k] for k in selected_keys}
    emsal_artis_orani = 1.30
    first_mahalle = list(active_parcel_db.values())[0].get("mahalle", "VARSAYILAN")

    st.markdown("""
    <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 18px 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
        <div style="display: flex; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
            <span style="font-size: 18px; margin-right: 8px;">📊</span>
            <div>
                <h3 style="color: #0f172a; margin: 0; font-size: 15px; font-weight: 700;">Gelişmiş Fizibilite ve Fonksiyon Bazlı Proje Tipi Yönetimi</h3>
                <p style="color: #64748b; margin: 0; font-size: 11px;">İmar fonksiyonlarına göre proje tiplerini ve havuz konseptlerini manuel belirleyin veya sistemin net kâr bazlı otomatik optimize etmesini sağlayın.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        is_modeli = st.selectbox("İş Modeli / Rapor Türü", options=["Kat Karşılığı Proje Raporu", "Doğrudan Satılık / Arsa Yatırım Raporu"], key="global_is_modeli")
    with col_m2:
        secim_modu = st.radio("Proje Tipi Seçim Modu", options=["Otomatik (Net Kâra Göre Maksimum Verimlilik)", "Manuel / Fonksiyon Bazlı Özelleştirme"], horizontal=True)

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

    # Tüm geçerli fonksiyonları topla
    all_unique_functions = set()
    for key, p in active_parcel_db.items():
        breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
        for item in breakdown:
            if item["brut_insaat"] > 0:
                all_unique_functions.add(item["fonksiyon_adi"])

    all_project_types = [
        "Standart Konut / Apartman", 
        "Üst Segment Konut / Rezidans", 
        "Lüks Villa / Müstakil Proje", 
        "Ticari / Ofis Kompleksi", 
        "Karma Proje (Konut + Ticari)"
    ]

    function_configurations = {}

    if secim_modu.startswith("Otomatik"):
        # Net kârı maksimize eden proje tipini otomatik seçme simülasyonu
        for key, p in active_parcel_db.items():
            breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
            for item in breakdown:
                fonk_name = item["fonksiyon_adi"]
                brut_insaat = item["brut_insaat"]
                if brut_insaat <= 0:
                    continue
                
                best_net_kar = -float('inf')
                best_p_type = "Standart Konut / Apartman"
                best_pool = "Standart Ortak Havuzlu Proje"
                best_satis, best_maliyet, best_bodrum = 0, 0, 0
                best_adet = max(1, round(brut_insaat / 95.0))

                pool_options_candidate = ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"]
                if "VİLLA" in fonk_name:
                    pool_options_candidate = ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"]
                elif any(t in fonk_name for t in ["TİCARET", "TİCARİ"]):
                    pool_options_candidate = ["Havuz İptal / Yapılmayacak"]

                for pt in all_project_types:
                    for pool in pool_options_candidate:
                        r_satis, r_maliyet, r_bodrum = get_realistic_market_pricing(first_mahalle, pt, rates["USD"])
                        tekil_havuz_payi = 35.0 if "Müstakil Özel Havuzlu" in pool else 0.0
                        sim_bodrum = (brut_insaat - (tekil_havuz_payi * best_adet)) * r_bodrum
                        
                        ciro = (brut_insaat * r_satis) + (sim_bodrum * r_satis * r_bodrum)
                        maliyet = (brut_insaat * r_maliyet) + arsa_bonus_usd
                        arsa_pay = ciro * (arsa_payi_orani / 100) if "Kat Karşılığı" in is_modeli else 0.0
                        net_kar = ciro - maliyet - arsa_pay
                        
                        if net_kar > best_net_kar:
                            best_net_kar = net_kar
                            best_p_type = pt
                            best_pool = pool
                            best_satis = r_satis
                            best_maliyet = r_maliyet
                            best_bodrum = r_bodrum

                parsel_fonk_key = f"{key}_{fonk_name}"
                function_configs[parsel_fonk_key] = {
                    "proje_tipi": best_p_type,
                    "adet": int(best_adet),
                    "havuz_mod": best_pool,
                    "maliyet": best_maliyet,
                    "satis": best_satis,
                    "bodrum_orani": best_bodrum,
                    "fonk_hesaba_alinan_m2": item["giren_m2"]
                }
        st.markdown("<div style='font-size: 12px; color: #047857; background: #ecfdf5; padding: 8px 12px; border-radius: 6px; border: 1px solid #a7f3d0; margin-top: 10px;'>✨ Sistem, net kârı (müteahhit kârlılığını) en üst düzeye çıkaran en uygun proje tiplerini ve havuz konseptlerini otomatik olarak belirledi.</div>", unsafe_allow_html=True)

    else:
        st.markdown("<div style='margin-top: 10px; font-weight: 700; color: #0f172a; font-size: 13px;'>⚙️ İmar Fonksiyonlarına Göre Proje Tipi ve Havuz Konsepti Yapılandırması</div>", unsafe_allow_html=True)
        func_tabs = st.tabs(list(all_unique_functions))
        
        func_user_choices = {}
        for idx, fonk_adi in enumerate(all_unique_functions):
            with func_tabs[idx]:
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    sel_pt = st.selectbox(f"Proje Tipi ({fonk_adi})", options=all_project_types, key=f"manual_pt_{idx}_{fonk_adi}")
                with fc2:
                    if "VİLLA" in fonk_adi:
                        pool_opts = ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"]
                    elif any(t in fonk_adi for t in ["TİCARET", "TİCARİ"]):
                        pool_opts = ["Havuz İptal / Yapılmayacak"]
                    else:
                        pool_opts = ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"]
                    sel_pool = st.selectbox(f"Havuz / Donatı Konsepti ({fonk_adi})", options=pool_opts, key=f"manual_pool_{idx}_{fonk_adi}")
                with fc3:
                    def_unit_sz = 250 if "VİLLA" in fonk_adi else (120 if "TİCARET" in fonk_adi else 95)
                    sel_sz = st.number_input(f"Ortalama Bağımsız Bölüm Boyutu (m²)", min_value=40.0, max_value=800.0, value=float(def_unit_sz), step=5.0, key=f"manual_sz_{idx}_{fonk_adi}")
                
                func_user_choices[fonk_adi] = {
                    "proje_tipi": sel_pt,
                    "havuz_mod": sel_pool,
                    "birim_boyut": sel_sz
                }

        for key, p in active_parcel_db.items():
            breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
            for item in breakdown:
                fonk_name = item["fonksiyon_adi"]
                brut_insaat = item["brut_insaat"]
                if brut_insaat <= 0:
                    continue
                
                uc = func_user_choices.get(fonk_name, {"proje_tipi": "Standart Konut / Apartman", "havuz_mod": "Standart Ortak Havuzlu Proje", "birim_boyut": 95.0})
                r_satis, r_maliyet, r_bodrum = get_realistic_market_pricing(first_mahalle, uc["proje_tipi"], rates["USD"])
                calc_adet = max(1, round(brut_insaat / uc["birim_boyut"]))

                parsel_fonk_key = f"{key}_{fonk_name}"
                function_configs[parsel_fonk_key] = {
                    "proje_tipi": uc["proje_tipi"],
                    "adet": int(calc_adet),
                    "havuz_mod": uc["havuz_mod"],
                    "maliyet": r_maliyet,
                    "satis": r_satis,
                    "bodrum_orani": r_bodrum,
                    "fonk_hesaba_alinan_m2": item["giren_m2"]
                }

    st.markdown("</div>", unsafe_allow_html=True)

    # Finansal metrikleri hesaplama
    total_yasal_brut_insaat = 0.0
    total_simulated_bodrum = 0.0
    total_bahce_alani_terki = 0.0
    total_ciro_usd = 0.0
    total_maliyet_usd = 0.0
    primary_project_type_display = "Karma / Çoklu Proje"

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
                
            total_yasal_brut_insaat += brut_insaat
            total_bahce_alani_terki += item["bahce_kullanim_alani"]
            primary_project_type_display = conf["proje_tipi"]
            
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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Seçilen Parseller & İnşaat Alanı", 
        "🏛️ Mimari Fizibilite", 
        "📑 Proje Raporu & Fizibilite", 
        "🖨️ Rapor Ön İzleme & PDF",
        "🗄️ Veritabanı & Arşiv Yönetimi"
    ])

    with tab1:
        st.subheader("📊 Seçilen Parseller & Dinamik Fonksiyon Bazlı İnşaat Alanı")
        table_rows = []
        sum_brut_insaat = 0.0
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
                bahce_m2 = item["bahce_kullanim_alani"]
                if brut_insaat_arsa <= 0:
                    continue
                    
                sum_brut_insaat += brut_insaat_arsa
                sum_bahce_alani += bahce_m2
                
                table_rows.append({
                    "MAHALLE": mahalle,
                    "ADA": ada,
                    "PARSEL": parsel,
                    "TERK DURUMU": "Yapılmış (Net)" if is_terkli else "Yapılmamış (Brüt)",
                    "FONKSİYON": item["fonksiyon_adi"],
                    "TAKS": f"{item['taks']:.2f}" if item['taks'] > 0 else "-",
                    "KAKS / EMSAL": f"{item['kaks']:.2f}",
                    "BRÜT PARSEL (M²)": f"{toplam_arsa_m2:,.2f}",
                    "FONKSİYON GİREN (M²)": f"{item['giren_m2']:,.2f}" if item['giren_m2'] > 0 else "-",
                    "BAHÇE KULLANIM ALANI (M²)": f"{bahce_m2:,.2f}",
                    "İNŞAAT ALANI (M²)": f"{brut_insaat_arsa:,.2f}"
                })
                
        if table_rows:
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
            summary_df = pd.DataFrame([{
                "SORGULANAN PARSEL": f"{len(active_parcel_db)} Adet",
                "TOPLAM BRÜT ARSA (M²)": f"{sum_alan:,.2f}",
                "TOPLAM BAHÇE KULLANIM ALANI (M²)": f"{sum_bahce_alani:,.2f}",
                "TOPLAM İNŞAAT (BRÜT M²)": f"{sum_brut_insaat:,.2f}"
            }])
            st.dataframe(summary_df, use_container_width=True)
        else:
            st.warning("Seçilen parseller için veritabanında KAKS değeri okunmuş geçerli fonksiyon bulunamadı.")

    with tab2:
        st.subheader("🏛️ Mimari Fizibilite & Senaryo Dağılım Matrisi")
        mimari_rows = []
        
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
                birim_m2 = brut_insaat / konut_adeti if konut_adeti > 0 else brut_insaat
                tekil_havuz_payi = 35.0 if "Müstakil Özel Havuzlu" in conf["havuz_mod"] else 0.0
                sim_bodrum = (brut_insaat - (tekil_havuz_payi * konut_adeti)) * conf["bodrum_orani"]
                
                mimari_rows.append({
                    "MAHALLE": mahalle,
                    "ADA/PARSEL": f"{ada}/{parsel}",
                    "FONKSİYON": fonk_name,
                    "PROJE TİPİ": f"{conf['proje_tipi']} ({conf['havuz_mod']})",
                    "BAHÇE KULLANIM (M²)": f"{bahce_m2:,.2f}",
                    "BRÜT İNŞAAT (M²)": f"{brut_insaat:,.2f}",
                    "ADET": konut_adeti,
                    "BİRİM BRÜT (M²)": f"{birim_m2:,.2f}",
                    "BODRUM (M²)": f"{sim_bodrum:,.2f}"
                })
                
        if mimari_rows:
            st.dataframe(pd.DataFrame(mimari_rows), use_container_width=True)

    with tab3:
        st.subheader("📑 Finansal Fizibilite ve Fonksiyon Dağılımı")
        f_col1, f_col2, f_col3 = st.columns(3)
        f_col1.metric("Toplam Tahmini Brüt Ciro", f"${total_ciro_usd:,.2f}")
        f_col2.metric("Toplam İnşaat Maliyeti", f"${total_maliyet_usd:,.2f}")
        f_col3.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar_usd:,.2f}", f"%{yg_orani:.1f} YG")

    with tab4:
        st.subheader("🖨️ Kurumsal Rapor Ön İzleme ve PDF İndirme Merkezi")
        
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
            <div class="section-title">1. Proje ve Lokasyon Künyesi</div>
            <table class="data-table">
                <tr><td>Lokasyon / Mahalle</td><td style="text-align: right; font-weight: bold;">{first_mahalle} ({len(active_parcel_db)} Parsel)</td></tr>
                <tr><td>Seçilen Proje Tipi & Konsept</td><td style="text-align: right; font-weight: bold; color: #1e3a8a;">{primary_project_type_display}</td></tr>
                <tr><td>Toplam Brüt İnşaat Alanı</td><td style="text-align: right; font-weight: bold;">{total_yasal_brut_insaat:,.2f} m²</td></tr>
                <tr><td>Toplam Bahçe Kullanım Alanı</td><td style="text-align: right; font-weight: bold;">{total_bahce_alani_terki:,.2f} m²</td></tr>
            </table>
            <div class="section-title">2. Finansal Fizibilite Özeti</div>
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
            label="📥 Kurumsal Fizibilite Raporunu PDF Olarak İndir",
            data=pdf_bytes,
            file_name=f"Kurumsal_Toplu_Fizibilite_{first_mahalle}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    with tab5:
        st.subheader("🗄️ Veritabanı Detaylı Arşiv Tablosu (`imar_veritabani.json`)")
        db_items = st.session_state["parcel_db"]
        if db_items:
            db_detail_rows = []
            for k, p_val in db_items.items():
                mahalle = p_val.get("mahalle", "-")
                ada = p_val.get("ada", "-")
                parsel = p_val.get("parsel", "-")
                toplam_alan = p_val.get("toplam_alan", 0.0)
                is_terk = p_val.get("terk_yapilmis_mi", False)
                terk_st = "Terk Yapılmış (Net)" if is_terk else "Terk Yapılmamış (Brüt)"
                
                breakdown = get_parcel_function_breakdown(p_val, 1.30)
                if breakdown:
                    for item in breakdown:
                        db_detail_rows.append({
                            "Kayıt Anahtarı": k,
                            "Dosya Adı": p_val.get("filename", "-"),
                            "Mahalle": mahalle,
                            "Ada / Parsel": f"{ada} / {parsel}",
                            "Toplam Arsa (m²)": f"{toplam_alan:,.2f}",
                            "Terk Durumu": terk_st,
                            "Fonksiyon Adı": item["fonksiyon_adi"],
                            "Fonks. Giren (m²)": f"{item['giren_m2']:,.2f}" if item['giren_m2'] > 0 else "-",
                            "TAKS": f"{item['taks']:.2f}" if item['taks'] > 0 else "-",
                            "KAKS / Emsal": f"{item['kaks']:.2f}",
                            "Bahçe Kullanım Alanı (m²)": f"{item['bahce_kullanim_alani']:,.2f}",
                            "Tahmini Brüt İnşaat (m²)": f"{item['brut_insaat']:,.2f}"
                        })
                else:
                    db_detail_rows.append({
                        "Kayıt Anahtarı": k,
                        "Dosya Adı": p_val.get("filename", "-"),
                        "Mahalle": mahalle,
                        "Ada / Parsel": f"{ada} / {parsel}",
                        "Toplam Arsa (m²)": f"{toplam_alan:,.2f}",
                        "Terk Durumu": terk_st,
                        "Fonksiyon Adı": "-",
                        "Fonks. Giren (m²)": "-",
                        "TAKS": "-",
                        "KAKS / Emsal": "-",
                        "Bahçe Kullanım Alanı (m²)": "-",
                        "Tahmini Brüt İnşaat (m²)": "-"
                    })
            
            st.dataframe(pd.DataFrame(db_detail_rows), use_container_width=True)
            
            st.markdown("---")
            col_db1, col_db2 = st.columns(2)
            with col_db1:
                st.markdown("#### 🔍 Ham JSON Veri Yapısı")
                st.json(db_items)
            with col_db2:
                st.markdown("#### ⚙️ Veritabanı İşlemleri")
                selected_del_key = st.selectbox("Arşivden kaldırılacak parseli seçin:", options=list(db_items.keys()))
                if st.button("🗑️ Seçili Parseli Arşivden Kaldır", type="primary"):
                    if selected_del_key in st.session_state["parcel_db"]:
                        current_db = st.session_state["parcel_db"]
                        del current_db[selected_del_key]
                        save_persistent_db(current_db)
                        st.success(f"'{selected_del_key}' başarıyla silindi ve veritabanı güncellendi!")
                        st.rerun()
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("⚠️ Tüm Veritabanını Temizle (Sıfırla)", type="secondary"):
                    save_persistent_db({})
                    st.success("Veritabanı tamamen sıfırlandı!")
                    st.rerun()
        else:
            st.info("Veritabanında (`imar_veritabani.json`) henüz kayıtlı parsel bulunmuyor.")

else:
    st.info("👋 **Hoş Geldiniz!** Raporları görüntülemek için lütfen sol menüden istenilen parselleri seçin veya yeni bir imar belgesi (PDF) yükleme yapın.")
