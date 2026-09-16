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

# --- İMAR FONKSİYONUNA GÖRE UYGUN PROJE TİPLERİ FİLTRELEME MOTORU ---
def get_allowed_project_types(fonk_adi):
    f_upper = fonk_adi.upper()
    if any(k in f_upper for k in ["TİCARET", "TICARI", "İŞ MERKEZİ", "MERKEZİ İŞ"]):
        return ["Ticari / Ofis Kompleksi", "Karma Proje (Konut + Ticari)"]
    elif any(k in f_upper for k in ["VİLLA", "VILLA"]):
        return ["Lüks Villa / Müstakil Proje", "Standart Konut / Apartman"]
    elif any(k in f_upper for k in ["KONUT", "MESKEN", "GELİŞME"]):
        return [
            "Standart Konut / Apartman", 
            "Üst Segment Konut / Rezidans", 
            "Lüks Villa / Müstakil Proje", 
            "Karma Proje (Konut + Ticari)"
        ]
    else:
        return [
            "Standart Konut / Apartman", 
            "Üst Segment Konut / Rezidans", 
            "Lüks Villa / Müstakil Proje", 
            "Ticari / Ofis Kompleksi", 
            "Karma Proje (Konut + Ticari)"
        ]

# --- PROJE TİPİNE GÖRE DİNAMİK ALAN ARALIKLARI (MIN, MAX, DEFAULT, STEP) ---
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
    else:  # Standart Konut / Apartman
        return 55, 150, 90, 5

# --- KALICI DOSYA TABANLI VERİTABANI YÖNETİMİ ---
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
        "Lüks Villa / Müstakil Proje": {"satis_mod": 1.55, "maliyet_mod": 1350},
        "Üst Segment Konut / Rezidans": {"satis_mod": 1.25, "maliyet_mod": 1100},
        "Standart Konut / Apartman": {"satis_mod": 1.00, "maliyet_mod": 900},
        "Ticari / Ofis Kompleksi": {"satis_mod": 1.35, "maliyet_mod": 1050},
        "Karma Proje (Konut + Ticari)": {"satis_mod": 1.20, "maliyet_mod": 1000}
    }
    
    p_conf = proje_carpanlari.get(proje_tipi, proje_carpanlari["Standart Konut / Apartman"])
    
    satis_fiyati_usd = round((base_tl * p_conf["satis_mod"]) / usd_rate, 2)
    maliyet_fiyati_usd = float(p_conf["maliyet_mod"])
    
    return satis_fiyati_usd, maliyet_fiyati_usd

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
            if not f"YAPILMAMIŞTIR" in text_upper and not f"YAPILMAMIŞ" in text_upper:
                return True

    for kw in kesin_terk_yapilmamis:
        if kw in text_upper:
            return False
            
    return False

# --- KAPSAMLI İMAR PDF AYRIŞTIRMA MOTORU ---
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

# --- FONKSİYON ALANINA GİREN M² BAZLI DAĞITIM MOTORU ---
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
    st.sidebar.divider()
    st.sidebar.subheader("⚙️ Parsel Terk Durumu Ayarı (Manuel Düzeltme)")
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
                <p style="color: #64748b; margin: 0; font-size: 11px;">İmar fonksiyonlarına özel olarak filtrelenmiş proje tipleri, havuz seçenekleri ve m² maliyet/satış ayarları.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        is_modeli = st.selectbox("İş Modeli / Rapor Türü", options=["Kat Karşılığı Proje Raporu", "Doğrudan Satılık / Arsa Yatırım Raporu"], key="global_is_modeli")
        
    arsa_payi_orani = 0.0
    arsa_bonus_usd = 0.0
    if "Kat Karşılığı" in is_modeli:
        with col_m2:
            arsa_payi_orani = st.slider("Arsa Sahibi Payı / Kat Karşılığı Oranı (%)", 0, 70, 50)
            
    unique_active_functions = set()
    for p in active_parcel_db.values():
        breakdown = get_parcel_function_breakdown(p, emsal_artis_orani)
        for item in breakdown:
            if item["brut_insaat"] > 0:
                unique_active_functions.add(item["fonksiyon_adi"])
                
    if not unique_active_functions:
        unique_active_functions = {"KONUT ALANI"}

    st.markdown("<div style='margin-top: 10px; font-weight: 700; color: #0f172a; font-size: 13px;'>⚙️ İmar Fonksiyonuna Göre Proje Tipi, Havuz Seçimi ve m² Maliyet/Satış Fiyatları</div>", unsafe_allow_html=True)
    
    function_configs = {}
    func_cols = st.columns(len(unique_active_functions) if len(unique_active_functions) > 0 else 1)
    
    for idx, fonk_adi in enumerate(unique_active_functions):
        with func_cols[idx % len(func_cols)]:
            st.markdown(f"**📌 Fonksiyon: {fonk_adi}**")
            
            allowed_p_types = get_allowed_project_types(fonk_adi)
            best_p_type = allowed_p_types[0]
            best_pool = "Standart Ortak Havuzlu Proje"
            max_sim_profit = -999999999.0
            
            for p_t in allowed_p_types:
                pools = ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"] if "Villa" in p_t else (["Havuz İptal / Yapılmayacak"] if "Ticari" in p_t else ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"])
                for pool in pools:
                    satis_f, mal_f = get_realistic_market_pricing(first_mahalle, p_t, rates["USD"])
                    sim_profit = (1000.0 * satis_f) - (1000.0 * mal_f)
                    if sim_profit > max_sim_profit:
                        max_sim_profit = sim_profit
                        best_p_type = p_t
                        best_pool = pools[0]
                        
            default_p_idx = allowed_p_types.index(best_p_type) if best_p_type in allowed_p_types else 0
            
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                selected_func_p_type = st.selectbox(f"Proje Tipi", options=allowed_p_types, index=default_p_idx, key=f"func_p_type_{idx}_{fonk_adi}")
            
            if "Villa" in selected_func_p_type:
                pool_opts = ["Müstakil Özel Havuzlu Villa Projesi", "Ortak Havuzlu Villa Sitesi Konsepti", "Havuz İptal / Yapılmayacak"]
            elif "Ticari" in selected_func_p_type:
                pool_opts = ["Havuz İptal / Yapılmayacak"]
            else:
                pool_opts = ["Standart Ortak Havuzlu Proje", "Havuz İptal / Yapılmayacak"]
                
            with sub_col2:
                selected_func_pool = st.selectbox(f"Havuz Seçeneği", options=pool_opts, key=f"func_pool_{idx}_{fonk_adi}")
            
            custom_pool_m2 = 35.0
            if "İptal" not in selected_func_pool:
                custom_pool_m2 = st.number_input(f"Havuz Alanı (m²) - {fonk_adi}", min_value=10.0, max_value=500.0, value=40.0, step=5.0, key=f"custom_pool_m2_{idx}_{fonk_adi}")
            
            r_satis, r_maliyet = get_realistic_market_pricing(first_mahalle, selected_func_p_type, rates["USD"])
            
            prc_col1, prc_col2 = st.columns(2)
            with prc_col1:
                custom_maliyet = st.number_input(f"m² Maliyet ($)", min_value=300.0, max_value=5000.0, value=float(r_maliyet), step=50.0, key=f"cost_{idx}_{fonk_adi}")
            with prc_col2:
                custom_satis = st.number_input(f"m² Satış ($)", min_value=500.0, max_value=15000.0, value=float(r_satis), step=100.0, key=f"price_{idx}_{fonk_adi}")
            
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
                p_type_key = f"func_p_type_{idx}_{fonk_adi}"
                chosen_p_type = st.session_state.get(p_type_key, get_allowed_project_types(fonk_adi)[0])
                min_v, max_v, def_v, step_v = get_project_size_ranges(chosen_p_type)
                
                function_target_sizes[fonk_adi] = st.slider(
                    f"{fonk_adi[:20]}...",
                    min_value=min_v,
                    max_value=max_v,
                    value=def_v,
                    step=step_v,
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
            bodrum_m2_parsel = brut_insaat * 0.50  
            total_bodrum_alani += bodrum_m2_parsel
            total_bahce_alani_terki += item["bahce_kullanim_alani"]
            
            if "İptal" not in conf["havuz_mod"]:
                if "Müstakil" in conf["havuz_mod"]:
                    havuz_dusum = conf["havuz_m2"] * conf["adet"]
                else:
                    havuz_dusum = conf["havuz_m2"]
            else:
                havuz_dusum = 0.0

            net_konut_insaat = max(0.0, brut_insaat - havuz_dusum)
            
            total_ciro_usd += (net_konut_insaat * conf["satis"])
            toplam_parsel_maliyeti = (brut_insaat * conf["maliyet"] * 0.45) + (bodrum_m2_parsel * (conf["maliyet"] * 0.25))
            total_maliyet_usd += toplam_parsel_maliyeti

    total_maliyet_usd += arsa_bonus_usd
    arsa_sahibi_payi_usd = total_ciro_usd * (arsa_payi_orani / 100) if "Kat Karşılığı" in is_modeli else 0.0
    mutaahhit_net_kar_usd = total_ciro_usd - total_maliyet_usd - arsa_sahibi_payi_usd
    yg_orani = (mutaahhit_net_kar_usd / total_maliyet_usd * 100) if total_maliyet_usd > 0 else 0

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Seçilen Parseller & İnşaat Alanı", 
        "🏛️ Mimari Fizibilite (Bodrum + Zemin/Normal)", 
        "📑 Proje Raporu & Fizibilite", 
        "🖨️ Rapor Ön İzleme & PDF",
        "🗄️ Veritabanı & Arşiv Yönetimi"
    ])

    with tab1:
        st.subheader("📊 Seçilen Parseller & Dinamik Fonksiyon Bazlı İnşaat Alanı")
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
                    "Fonksiyon": item["fonksiyon_adi"],
                    "Kaks/Emsal": f"{item['kaks']:.2f}",
                    "Bahçe Alanı (m²)": f"{bahce_m2:,.2f}",
                    "Emsal İnşaat Alanı (m²)": f"{emsal_arsa:,.2f}",
                    "Toplam İnşaat Alanı (m²)": f"{(brut_insaat_arsa + bodrum_arsa):,.2f}"
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
        st.markdown("<p style='color: #64748b; font-size: 13px; margin-top: -10px;'>Aşağıdaki tablo, seçilen bağımsız bölüm adetleri baz alınarak <strong>her bir birime (daire/villaya)</strong> düşen net ve brüt alan dağılımlarını göstermektedir.</p>", unsafe_allow_html=True)
        
        mimari_rows = []
        total_units_sum = 0
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
                bodrum_m2 = brut_insaat * 0.50
                bahce_m2 = item["bahce_kullanim_alani"]
                if brut_insaat <= 0:
                    continue
                    
                parsel_fonk_key = f"{key}_{fonk_name}"
                conf = function_configs.get(parsel_fonk_key)
                if not conf:
                    continue
                    
                konut_adeti = conf["adet"]
                total_units_sum += konut_adeti
                
                if "İptal" not in conf["havuz_mod"]:
                    if "Müstakil" in conf["havuz_mod"]:
                        havuz_dusum = conf["havuz_m2"] * konut_adeti
                    else:
                        havuz_dusum = conf["havuz_m2"]
                else:
                    havuz_dusum = 0.0

                net_konut_insaat = max(0.0, brut_insaat - havuz_dusum)
                total_net_insaat_sum += net_konut_insaat
                
                genel_parsel_toplam_insaat = brut_insaat + bodrum_m2
                total_genel_insaat_sum += genel_parsel_toplam_insaat
                
                # --- BİRİM BAŞINA DÜŞEN DEĞERLERİN HESAPLANMASI ---
                birim_bahce = bahce_m2 / konut_adeti if konut_adeti > 0 else 0.0
                birim_bodrum = bodrum_m2 / konut_adeti if konut_adeti > 0 else 0.0
                birim_ust_kat = brut_insaat / konut_adeti if konut_adeti > 0 else 0.0
                birim_toplam_insaat = genel_parsel_toplam_insaat / konut_adeti if konut_adeti > 0 else 0.0
                
                mimari_rows.append({
                    "MAHALLE": mahalle,
                    "ADA/PARSEL": f"{ada}/{parsel}",
                    "FONKSİYON": fonk_name,
                    "PROJE TİPİ": f"{conf['proje_tipi']} ({conf['havuz_mod']})",
                    "BAĞIMSIZ BÖLÜM": f"{konut_adeti} Adet",
                    "BİRİM BAHÇE (M²)": f"{birim_bahce:,.1f} m²",
                    "BİRİM BODRUM (M²)": f"{birim_bodrum:,.1f} m²",
                    "BİRİM ÜST KATLAR (M²)": f"{birim_ust_kat:,.1f} m²",
                    "BİRİM TOPLAM İNŞAAT (M²)": f"{birim_toplam_insaat:,.1f} m²"
                })
                
        if mimari_rows:
            st.dataframe(pd.DataFrame(mimari_rows), use_container_width=True)
            
            avg_unit_m2 = total_genel_insaat_sum / total_units_sum if total_units_sum > 0 else 0.0
            
            st.markdown("---")
            st.markdown("#### 📋 Mimari ve Proje Özet Dağılımı (Birim Ortalamaları)")
            
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("Toplam Bağımsız Bölüm", f"{total_units_sum} Adet")
            m_col2.metric("Ortalama Net/Brüt Birim Alanı", f"{avg_unit_m2:,.1f} m²")
            
            if "Kat Karşılığı" in is_modeli:
                exact_arsa_sahibi = total_units_sum * (arsa_payi_orani / 100.0)
                arsa_sahibi_adet = int(round(exact_arsa_sahibi))
                if arsa_sahibi_adet > total_units_sum:
                    arsa_sahibi_adet = total_units_sum
                elif arsa_sahibi_adet < 0:
                    arsa_sahibi_adet = 0
                mutaahhit_adet = total_units_sum - arsa_sahibi_adet
                
                m_col3.metric("Arsa Sahibi Payı (Adet)", f"~{arsa_sahibi_adet} Adet (%{arsa_payi_orani})")
                m_col4.metric("Müteahhit Payı (Adet)", f"~{mutaahhit_adet} Adet (%{100 - arsa_payi_orani})")
            else:
                m_col3.metric("İş Modeli", "Doğrudan Satılık")
                m_col4.metric("Müteahhit Payı", f"{total_units_sum} Adet (%100)")

    with tab3:
        st.subheader("📑 Finansal Fizibilite ve Fonksiyon Dağılımı (3 Para Birimi Sunumu)")
        
        rate_usd = rates["USD"]
        rate_eur = rates["EUR"]
        
        total_ciro_tl = total_ciro_usd * rate_usd
        total_ciro_eur = total_ciro_tl / rate_eur
        
        total_maliyet_tl = total_maliyet_usd * rate_usd
        total_maliyet_eur = total_maliyet_tl / rate_eur
        
        mutaahhit_net_kar_tl = mutaahhit_net_kar_usd * rate_usd
        mutaahhit_net_kar_eur = mutaahhit_net_kar_tl / rate_eur

        curr_tab1, curr_tab2, curr_tab3 = st.tabs(["💵 USD ($) Sunumu", "₺ TL (₺) Sunumu", "💶 EUR (€) Sunumu"])
        
        with curr_tab1:
            c1, c2, c3 = st.columns(3)
            c1.metric("Toplam Tahmini Brüt Ciro", f"${total_ciro_usd:,.2f}")
            c2.metric("Toplam İnşaat Maliyeti (Bodrum Dahil)", f"${total_maliyet_usd:,.2f}")
            c3.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar_usd:,.2f}", f"%{yg_orani:.1f} YG")
            
        with curr_tab2:
            t1, t2, t3 = st.columns(3)
            t1.metric("Toplam Tahmini Brüt Ciro", f"₺{total_ciro_tl:,.2f}")
            t2.metric("Toplam İnşaat Maliyeti (Bodrum Dahil)", f"₺{total_maliyet_tl:,.2f}")
            t3.metric("Müteahhit Net Karı", f"₺{mutaahhit_net_kar_tl:,.2f}", f"%{yg_orani:.1f} YG")
            
        with curr_tab3:
            e1, e2, e3 = st.columns(3)
            e1.metric("Toplam Tahmini Brüt Ciro", f"€{total_ciro_eur:,.2f}")
            e2.metric("Toplam İnşaat Maliyeti (Bodrum Dahil)", f"€{total_maliyet_eur:,.2f}")
            e3.metric("Müteahhit Net Karı", f"€{mutaahhit_net_kar_eur:,.2f}", f"%{yg_orani:.1f} YG")

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
            <div class="section-title">1. Proje ve Lokasyon Künyesi (Bodrum Dahil)</div>
            <table class="data-table">
                <tr><td>Lokasyon / Mahalle</td><td style="text-align: right; font-weight: bold;">{first_mahalle} ({len(active_parcel_db)} Parsel)</td></tr>
                <tr><td>Emsal İnşaat Alanı (Bodrum Hariç)</td><td style="text-align: right; font-weight: bold;">{total_yasal_brut_insaat:,.2f} m²</td></tr>
                <tr><td>Bodrum Kat Alanı (%50)</td><td style="text-align: right; font-weight: bold;">{total_bodrum_alani:,.2f} m²</td></tr>
                <tr><td>Genel Toplam İnşaat Alanı</td><td style="text-align: right; font-weight: bold;">{(total_yasal_brut_insaat + total_bodrum_alani):,.2f} m²</td></tr>
            </table>
            <div class="section-title">2. Finansal Fizibilite Özeti (USD / TL / EUR)</div>
            <table class="data-table">
                <tr><th>Finansal Kalem</th><th style="text-align: right;">Tutar (USD $)</th><th style="text-align: right;">Tutar (TL ₺)</th><th style="text-align: right;">Tutar (EUR €)</th></tr>
                <tr><td>Toplam Tahmini Brüt Ciro</td><td style="text-align: right;">${total_ciro_usd:,.2f}</td><td style="text-align: right;">₺{total_ciro_tl:,.2f}</td><td style="text-align: right;">€{total_ciro_eur:,.2f}</td></tr>
                <tr><td>Toplam İnşaat Maliyeti (Bodrum Dahil)</td><td style="text-align: right;">${total_maliyet_usd:,.2f}</td><td style="text-align: right;">₺{total_maliyet_tl:,.2f}</td><td style="text-align: right;">€{total_maliyet_eur:,.2f}</td></tr>
                <tr style="font-weight: bold;"><td>Müteahhit Net Kârı</td><td style="text-align: right; color:#1e3a8a;">${mutaahhit_net_kar_usd:,.2f}</td><td style="text-align: right; color:#1e3a8a;">₺{mutaahhit_net_kar_tl:,.2f}</td><td style="text-align: right; color:#1e3a8a;">€{mutaahhit_net_kar_eur:,.2f} (%{yg_orani:.1f} YG)</td></tr>
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
                        brut = item['brut_insaat']
                        bod = brut * 0.50
                        bahce_m2 = item['bahce_kullanim_alani']
                        db_detail_rows.append({
                            "Kayıt Anahtarı": k,
                            "Dosya Adı": p_val.get("filename", "-"),
                            "Mahalle": mahalle,
                            "Ada / Parsel": f"{ada} / {parsel}",
                            "Toplam Arsa (m²)": f"{toplam_alan:,.2f}",
                            "Terk Durumu": terk_st,
                            "Fonksiyon": item["fonksiyon_adi"],
                            "Bahçe Alanı (m²)": f"{bahce_m2:,.2f}",
                            "Emsal İnşaat Alanı (m²)": f"{brut:,.2f}",
                            "Bodrum (m²)": f"{bod:,.2f}",
                            "Toplam İnşaat (m²)": f"{(brut + bod):,.2f}"
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
