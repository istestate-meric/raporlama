import re
import os
import json
import base64
import urllib.request
import xml.etree.ElementTree as ET
import pdfplumber
import pandas as pd
import streamlit as st
from weasyprint import HTML, CSS

st.set_page_config(
    page_title="İstestate & Meriç İnşaat - Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

# --- KALICI DOSYA TABANLI VERİTABANI YÖNETİMİ (MUTLAK DİZİN GARANTİSİ) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "imar_veritabani.json")

def load_persistent_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_persistent_db(db_data):
    try:
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
        with open(full_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("utf-8")
    return ""

img1_base64 = get_image_base64("istestate_logo.png")
img2_base64 = get_image_base64("meric_insaat_emlak_logo.png")

img1_tag = f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 75px; width: auto; object-fit: contain;'>" if img1_base64 else "<h2 style='color:#1e3a8a; margin:0;'>İSTESTATE</h2>"
img2_tag = f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 75px; width: auto; object-fit: contain;'>" if img2_base64 else "<h2 style='color:#1e3a8a; margin:0;'>MERİÇ İNŞAAT</h2>"

# --- 1. TCMB CANLI DÖVİZ KURU SERVİSİ ---
@st.cache_data(ttl=300)
def get_live_exchange_rates():
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        usd_rate = 0.0
        eur_rate = 0.0
        
        for currency in root.findall('Currency'):
            code = currency.get('CurrencyCode')
            if code == 'USD':
                usd_rate = float(currency.find('ForexSelling').text)
            elif code == 'EUR':
                eur_rate = float(currency.find('ForexSelling').text)
                
        return {"USD": usd_rate if usd_rate > 0 else 34.00, "EUR": eur_rate if eur_rate > 0 else 37.50}
    except Exception:
        return {"USD": 34.00, "EUR": 37.50}

# --- 2. BEYKOZ GERÇEKÇİ PİYASA VE PROJE TİPİ MATRİSİ ---
def get_realistic_market_pricing(mahalle_adi, proje_tipi, usd_rate):
    mahalle_base_tl = {
        "ACARLAR": 140000,
        "ANADOLU HİSARI": 130000,
        "KANLICA": 125000,
        "GÖKSU": 110000,
        "GÖRELE": 115000,
        "RİVA": 120000,
        "ÇİFTLİK": 115000,
        "BAKLACI": 95000,
        "KAVACIK": 90000,
        "ÇENGELDERE": 105000,
        "YAVUZ SELİM": 80000,
        "FATİH": 75000,
        "SOĞUKSU": 95000,
        "PAŞABAHÇE": 90000,
        "VARSAYILAN": 95000
    }
    
    clean_mahalle = mahalle_adi.upper().strip()
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

def detect_terk_status(text, toplam_alan, fonksiyonlar):
    text_upper = text.upper()
    terksiz_kaliplar = ["YOLA TERK VE KAMUYA AYRILAN KISIMLAR KAMU ELİNE GEÇMEDEN", "TERK YAPILMAMIŞ", "TERKİ YAPILAMIŞ", "TERK YAPILMADAN", "TERKİ YAPILMADAN", "DOP TERKİ YAPILMAMIŞ"]
    for kalip in terksiz_kaliplar:
        if kalip in text_upper:
            return False

    terkli_kaliplar = ["TERKİ YAPILMIŞTIR", "TERKİ YAPILMIŞ", "TERK YAPILMIŞTIR", "KAMUYA TERK EDİLMİŞTİR", "DOP TERKİ YAPILMAMIŞTIR"]
    for kalip in terkli_kaliplar:
        if kalip in text_upper:
            return True

    toplam_fonksiyon_m2 = sum(
        f["giren_m2"] for f in fonksiyonlar 
        if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"])
    )
    
    if toplam_alan > 0 and toplam_fonksiyon_m2 > 0:
        if abs(toplam_alan - toplam_fonksiyon_m2) < 1.0 or (toplam_fonksiyon_m2 / toplam_alan) >= 0.99:
            return True
        else:
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
    
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            t = page.extract_text() or ""
            full_text += "\n" + t
            
            tables = page.extract_tables()
            for table in tables:
                for r_idx, row in enumerate(table):
                    cells = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in row]
                    row_str = " ".join(cells)
                    
                    if any("Mahalle" in c for c in cells) and any("Ada" in c for c in cells):
                        if r_idx + 1 < len(table):
                            v_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[r_idx + 1]]
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

                    if "Fonksiyon Adı" in row_str or any("Fonksiyon" in str(c) for c in cells):
                        fonk_name = ""
                        taks_val = 0.30
                        kaks_val = 0.40
                        giren_m2 = 0.0
                        
                        for sub_idx in range(r_idx, min(r_idx + 5, len(table))):
                            sub_cells = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[sub_idx]]
                            sub_str = " ".join(sub_cells)
                            
                            if "Fonksiyon Adı" in sub_str or "Fonksiyon" in sub_str:
                                for c in sub_cells:
                                    if c and "Fonksiyon" not in c and c != "|":
                                        fonk_name = c.strip()
                                        break
                                        
                            t_m = re.search(r"Taks\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE)
                            k_m = re.search(r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE)
                            if t_m: taks_val = parse_tr_float(t_m.group(1))
                            if k_m: kaks_val = parse_tr_float(k_m.group(1))
                            
                            if "m²" in sub_str or "m2" in sub_str or "%" in sub_str:
                                m2_match = re.search(r"([\d\.,]+)\s*m²?", sub_str)
                                if m2_match:
                                    giren_m2 = parse_tr_float(m2_match.group(1))
                        
                        if fonk_name and not any(f["fonksiyon_adi"] == fonk_name for f in parcel_data["fonksiyonlar"]):
                            parcel_data["fonksiyonlar"].append({
                                "fonksiyon_adi": fonk_name,
                                "taks": taks_val,
                                "kaks": kaks_val,
                                "giren_m2": giren_m2 if giren_m2 > 0 else parcel_data["toplam_alan"]
                            })

    if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
        m_m = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
        a_m = re.search(r"Ada\s*\|\s*(\d+)", full_text)
        p_m = re.search(r"Parsel\s*\|\s*(\d+)", full_text)
        al_m = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", full_text)
        
        if m_m: parcel_data["mahalle"] = m_m.group(1).upper()
        if a_m: parcel_data["ada"] = str(a_m.group(1)).strip()
        if p_m: parcel_data["parsel"] = str(p_m.group(1)).strip()
        if al_m and parcel_data["toplam_alan"] == 0.0:
            parcel_data["toplam_alan"] = parse_tr_float(al_m.group(1))

    if not parcel_data["fonksiyonlar"]:
        parcel_data["fonksiyonlar"].append({
            "fonksiyon_adi": "Konut Alanı",
            "taks": 0.30,
            "kaks": 0.40,
            "giren_m2": parcel_data["toplam_alan"]
        })

    parcel_data["terk_yapilmis_mi"] = detect_terk_status(full_text, parcel_data["toplam_alan"], parcel_data["fonksiyonlar"])
    return parcel_data

# --- KURUMSAL HEADER ---
st.markdown(f"""
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 16px; padding: 30px 40px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.08); margin-bottom: 30px;">
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
        <div style="flex: 1; text-align: center;">{img1_tag}</div>
        <div style="width: 1px; background-color: #cbd5e1; height: 75px; margin: 0 20px;"></div>
        <div style="flex: 1; text-align: center;">{img2_tag}</div>
    </div>
    <hr style="margin: 25px 0 20px 0; border: none; border-top: 1px solid #e2e8f0;">
    <div style="text-align: center;">
        <h1 style='color: #0f172a; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 6px; margin-top: 0;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT EMLAK</h1>
        <p style='color: #475569; font-size: 15px; font-weight: 600; margin: 0;'>Akıllı Gayrimenkul Geliştirme ve Fizibilite Portalı</p>
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
    
    if selected_ada_filter != "Seçiniz...":
        filtered_keys = [
            k for k, p_data in st.session_state["parcel_db"].items() 
            if str(p_data.get("ada", "")).strip() == str(selected_ada_filter).strip()
        ]
    else:
        filtered_keys = []

    default_selection = [k for k in (just_uploaded_keys if just_uploaded_keys else []) if k in filtered_keys]

    selected_keys = st.sidebar.multiselect(
        "Raporlanacak Ada-Parsel Seçin:",
        options=filtered_keys if selected_ada_filter != "Seçiniz..." else [],
        default=default_selection,
        help="Önce yukarıdan Ada filtresi seçin, ardından listelenen parselleri işaretleyin."
    )
else:
    st.sidebar.info("Arşivde henüz kayıtlı parsel yok. Lütfen sol üstten PDF imar belgesi yükleyin.")
    selected_keys = []

if selected_keys:
    active_parcel_db = {k: st.session_state["parcel_db"][k] for k in selected_keys}

    emsal_artis_orani = 1.30
    yasal_max_brut_insaat_alani = 0.0
    toplam_brut_arsa_alani = 0.0
    toplam_net_arsa_alani = 0.0

    for key, p in active_parcel_db.items():
        toplam_brut_m2 = p["toplam_alan"]
        toplam_brut_arsa_alani += toplam_brut_m2
        is_terkli = p["terk_yapilmis_mi"]
        
        # Net arsa alanı doğrudan toplam alan üzerinden hesaplanır (Çift terk önlendi)
        parsel_net_arsa = toplam_brut_m2 if is_terkli else toplam_brut_m2 * 0.70
        toplam_net_arsa_alani += parsel_net_arsa

        toplam_giren_fonk_m2 = sum(
            f["giren_m2"] for f in p["fonksiyonlar"]
            if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"])
        )

        for f in p["fonksiyonlar"]:
            if any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                continue
            if not is_terkli:
                fonk_pay_orani = (f["giren_m2"] / toplam_giren_fonk_m2) if toplam_giren_fonk_m2 > 0 else 1.0
                esas_m2 = toplam_brut_m2 * fonk_pay_orani
                yasal_max_brut_insaat_alani += esas_m2 * 0.70 * f["kaks"] * emsal_artis_orani
            else:
                base_toplab_m2 = f["giren_m2"] if f["giren_m2"] > 0 else toplam_brut_m2
                yasal_max_brut_insaat_alani += base_toplab_m2 * f["kaks"] * emsal_artis_orani

    st.markdown("---")
    st.subheader("⚙️ Küresel Proje Parametreleri ve İş Modeli")
    col_global1, col_global2 = st.columns(2)
    with col_global1:
        selected_proje_tipi = st.selectbox(
            "Proje Tipi (Mimari Yerleşim & Ünite Büyüklüğü Modeli):",
            options=[
                "Lüks Villa / Müstakil Proje",
                "Üst Segment Konut / Rezidans",
                "Standart Konut / Apartman",
                "Ticari / Ofis Kompleksi",
                "Karma Proje (Konut + Ticari)"
            ],
            key="global_proje_tipi"
        )
    with col_global2:
        is_modeli = st.selectbox(
            "İş Modeli / Rapor Türü:",
            options=[
                "Kat Karşılığı Proje Raporu",
                "Doğrudan Satılık / Arsa Yatırım Raporu"
            ],
            key="global_is_modeli"
        )

    arsa_payi_orani = 0.0
    arsa_bonus_usd = 0.0
    if "Kat Karşılığı" in is_modeli:
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        col_gk1, col_gk2, col_gk3 = st.columns([2, 1, 2])
        with col_gk1:
            arsa_payi_orani = st.slider("Arsa Sahibi Payı / Kat Karşılığı Oranı (%)", min_value=0, max_value=70, value=50, key="global_arsa_payi_slider")
        with col_gk2:
            bonus_curr = st.selectbox("Para Birimi", options=["USD ($)", "EUR (€)", "TL (₺)"], key="global_bonus_currency")
        with col_gk3:
            raw_bonus_val = st.number_input("💵 Nakit Bonus / İmza Parası Tutar", min_value=0.0, value=0.0, step=10000.0, format="%.2f", key="global_arsa_bonus_input")
            if "EUR" in bonus_curr:
                arsa_bonus_usd = raw_bonus_val * (rates['EUR'] / rates['USD'])
            elif "TL" in bonus_curr:
                arsa_bonus_usd = raw_bonus_val / rates['USD']
            else:
                arsa_bonus_usd = raw_bonus_val

    st.markdown("---")

    proje_mimari_karakteristigi = {
        "Lüks Villa / Müstakil Proje": {"hedef_alan": 300.0, "bodrum_orani": 0.50, "havuz_mod": "Her Bağımsız Bölüme 1 Özel Havuz", "etiket_bodrum": "Bodrum Payı"},
        "Üst Segment Konut / Rezidans": {"hedef_alan": 180.0, "bodrum_orani": 0.30, "havuz_mod": "Ortak / Sosyal Tesis Havuzu", "etiket_bodrum": "Bodrum Payı"},
        "Standart Konut / Apartman": {"hedef_alan": 125.0, "bodrum_orani": 0.20, "havuz_mod": "Havuz İptal (Küçük Ölçek Kısıtı)", "etiket_bodrum": "Bodrum Payı"},
        "Ticari / Ofis Kompleksi": {"hedef_alan": 250.0, "bodrum_orani": 0.40, "havuz_mod": "Havuz İptal (Küçük Ölçek Kısıtı)", "etiket_bodrum": "Bodrum Payı"},
        "Karma Proje (Konut + Ticari)": {"hedef_alan": 150.0, "bodrum_orani": 0.35, "havuz_mod": "Ortak / Sosyal Tesis Havuzu", "etiket_bodrum": "Bodrum Payı"}
    }
    
    p_spec = proje_mimari_karakteristigi.get(selected_proje_tipi, proje_mimari_karakteristigi["Standart Konut / Apartman"])
    tahmini_ideal_adet = max(1, round(yasal_max_brut_insaat_alani / p_spec["hedef_alan"]))
    tahmini_havuz_modeli = p_spec["havuz_mod"]

    if "last_proje_tipi" not in st.session_state or st.session_state["last_proje_tipi"] != selected_proje_tipi:
        st.session_state["last_proje_tipi"] = selected_proje_tipi
        st.session_state["hedef_bagimsiz_bolum"] = tahmini_ideal_adet
        st.session_state["havuz_tercihi"] = tahmini_havuz_modeli
        st.session_state["hb_input"] = tahmini_ideal_adet

    # --- 5 SEKME YAPISI ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Seçilen Parseller Özeti", 
        "📐 İnşaat Alanı Hesabı", 
        "🏛️ Mimari Fizibilite", 
        "📑 Proje Raporu & Fizibilite",
        "🖨️ Rapor Ön İzleme & PDF"
    ])
    
    with tab1:
        st.subheader("Seçilen Parsellerin İmar ve Fonksiyon Bazlı Arsa Dağılımı")
        st.info("💡 Net arsa alanı doğrudan **Toplam Arsa (m²)** üzerinden (terksizler için %30 kesintiyle) hesaplanarak çift kesinti önlenmiştir.")
        
        table_rows = []
        for key, p in active_parcel_db.items():
            is_terkli = p["terk_yapilmis_mi"]
            toplam_brut = p["toplam_alan"]
            parsel_net_arsa = toplam_brut if is_terkli else toplam_brut * 0.70
            
            toplam_fonk_alan = sum(f["giren_m2"] for f in p["fonksiyonlar"])
            terk_lbl = "Terki Yapılmış (Net)" if is_terkli else "Terki Yapılmamış (%30 Kesintili)"
            
            for f in p["fonksiyonlar"]:
                fonks_m2 = f["giren_m2"]
                fonk_oran = (fonks_m2 / toplam_fonk_alan) if toplam_fonk_alan > 0 else (1.0 / len(p["fonksiyonlar"]))
                net_m2 = parsel_net_arsa * fonk_oran
                
                hedef_bb = st.session_state.get("hedef_bagimsiz_bolum", 1)
                unite_basi_fonk_net = net_m2 / hedef_bb if hedef_bb > 0 else 0
                
                table_rows.append({
                    "Parsel Bilgisi": key,
                    "Mahalle": p["mahalle"],
                    "Toplam Arsa (m²)": f"{toplam_brut:,.2f}",
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Fonksiyon Alanı (m²)": f"{fonks_m2:,.2f}",
                    "Net Arsa (m²)": f"{net_m2:,.2f}",
                    "Ünite Başı Net Arsa Payı": f"{unite_basi_fonk_net:,.2f} m² / Ünite",
                    "TAKS": f"{f['taks']:.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Terk Durumu": terk_lbl
                })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
        st.info(f"💡 **Toplam Arsa Özeti:** Toplam Brüt Arsa: **{toplam_brut_arsa_alani:,.2f} m²** | Parsel Bazlı Toplam Net Arsa: **{toplam_net_arsa_alani:,.2f} m²**")

    with tab2:
        st.subheader("Seçilen Parseller İçin Çoklu Fonksiyon Destekli Brüt İnşaat Kapasite Hesabı")
        st.info("ℹ️ İnşaat hesabı imar belgesindeki fonksiyon kırılımları ve **1.30 Genel Emsal Artış Katsayısı** ile yürütülmektedir.")
        st.markdown("---")
        
        calc_results = []
        for key, p in active_parcel_db.items():
            toplam_brut_m2 = p["toplam_alan"]
            is_terkli = p["terk_yapilmis_mi"]
            
            toplam_giren_fonk_m2 = sum(
                f["giren_m2"] for f in p["fonksiyonlar"]
                if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"])
            )
            for f in p["fonksiyonlar"]:
                if any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                    continue
                if not is_terkli:
                    fonk_pay_orani = (f["giren_m2"] / toplam_giren_fonk_m2) if toplam_giren_fonk_m2 > 0 else 1.0
                    esas_m2 = toplam_brut_m2 * fonk_pay_orani
                    brut_insaat_m2 = esas_m2 * 0.70 * f["kaks"] * emsal_artis_orani
                else:
                    base_toplab_m2 = f["giren_m2"] if f["giren_m2"] > 0 else toplam_brut_m2
                    brut_insaat_m2 = base_toplab_m2 * f["kaks"] * emsal_artis_orani
                
                calc_results.append({
                    "Parsel": key,
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Terk Durumu": "Terksiz (%30 Kesintili)" if not is_terkli else "Terkli (Net Alan)",
                    "Hesaba Esas Arsa Payı (m²)": f"{esas_m2:,.2f}" if not is_terkli else f"{base_toplab_m2:,.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Toplam Brüt İnşaat Alanı (m²)": f"{brut_insaat_m2:,.2f}"
                })

        st.table(pd.DataFrame(calc_results))
        st.metric(label="🏗️ Toplam Brüt İnşaat Alanı", value=f"{yasal_max_brut_insaat_alani:,.2f} m²")

    with tab3:
        st.subheader("🏛️ Mimari Fizibilite ve Bağımsız Bölüm Senaryoları")
        st.info(f"ℹ️ **Aktif Proje Tipi:** {selected_proje_tipi} | Proje tipine göre önerilen otomatik ünite adedi uygulandı.")
        
        col_mims1, col_mims2 = st.columns(2)
        with col_mims1:
            hedef_bagimsiz_bolum = st.number_input(
                "Planlanan Bağımsız Bölüm / Villa Adedi:", 
                min_value=1, 
                value=int(st.session_state["hedef_bagimsiz_bolum"]), 
                step=1, 
                key="hb_input"
            )
            st.session_state["hedef_bagimsiz_bolum"] = hedef_bagimsiz_bolum
            
        with col_mims2:
            havuz_secenekleri = ["Her Bağımsız Bölüme 1 Özel Havuz", "Ortak / Sosyal Tesis Havuzu", "Havuz İptal (Küçük Ölçek Kısıtı)"]
            default_hp_idx = havuz_secenekleri.index(st.session_state["havuz_tercihi"]) if st.session_state["havuz_tercihi"] in havuz_secenekleri else 0
            
            havuz_tercihi = st.selectbox(
                "Havuz Planlama Modeli:", 
                options=havuz_secenekleri,
                index=default_hp_idx,
                key="hp_select"
            )
        st.session_state["havuz_tercihi"] = havuz_tercihi

        havuz_emsele_maliyet_m2 = 30.0 if havuz_tercihi == "Her Bağımsız Bölüme 1 Özel Havuz" else (120.0 if havuz_tercihi == "Ortak / Sosyal Tesis Havuzu" else 0.0)
        net_brut_dusulen_alan = max(0.0, yasal_max_brut_insaat_alani - havuz_emsele_maliyet_m2)
        toplam_brut_kullanim_alani = net_brut_dusulen_alan
        
        ortalama_unite_alani = net_brut_dusulen_alan / hedef_bagimsiz_bolum if hedef_bagimsiz_bolum > 0 else 0
        unite_basi_net_arsa_genel = toplam_net_arsa_alani / hedef_bagimsiz_bolum if hedef_bagimsiz_bolum > 0 else 0
        
        simulated_bodrum_alani = net_brut_dusulen_alan * p_spec["bodrum_orani"]
        ortalama_bodrum_alani = simulated_bodrum_alani / hedef_bagimsiz_bolum if hedef_bagimsiz_bolum > 0 else 0

        st.markdown("---")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Toplam Ünite Alanı (Ortalama Ünite)", f"{net_brut_dusulen_alan:,.2f} m²", f"({ortalama_unite_alani:,.2f} m² / Ünite)")
        m_col2.metric("Ünite Başına Düşen Net Arsa", f"{toplam_net_arsa_alani:,.2f} m²", f"({unite_basi_net_arsa_genel:,.2f} m² / Ünite)")
        m_col3.metric("Bodrum Payı", f"{simulated_bodrum_alani:,.2f} m²", f"({ortalama_bodrum_alani:,.2f} m² / Ünite)")
        
        min_sinir = 150 if "Villa" in selected_proje_tipi else (90 if "Ticari" not in selected_proje_tipi else 60)
        risk_durumu = "⚠️ RİSKLİ (Çok küçük ölçek)" if ortalama_unite_alani < min_sinir and hedef_bagimsiz_bolum > 1 else "✅ Uygun Ölçek"
        m_col4.metric("Mimari Ölçek Uygunluğu", risk_durumu)

        st.markdown("---")
        st.markdown("### 🏷️ Bağımsız Bölüm Başına Detaylı Alan ve Dağılımı")
        st.info("💡 Her bir bağımsız ünitenin yapısal bileşenleri, inşaat alanları ve tamamlayıcı payları aşağıda detaylandırılmıştır.")

        tekil_havuz_payi = 30.0 if havuz_tercihi == "Her Bağımsız Bölüme 1 Özel Havuz" else (120.0 / hedef_bagimsiz_bolum if havuz_tercihi == "Ortak / Sosyal Tesis Havuzu" else 0.0)
        toplam_unite_brut_dahil_eklentiler = ortalama_unite_alani + ortalama_bodrum_alani + tekil_havuz_payi

        tab3_detay_rows_html = f"""<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Ana Ünite İnşaat Alanı (Brüt)</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Ortalama Bağımsız Bölüm Kapalı Alanı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #0f172a; text-align: right; font-weight: 700;">{ortalama_unite_alani:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #1e293b;">Bodrum Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #1e293b;">Ortalama Bodrum Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #1e293b; text-align: right; font-weight: 700;">{ortalama_bodrum_alani:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Havuz Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">{havuz_tercihi}</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #0f172a; text-align: right; font-weight: 700;">{tekil_havuz_payi:,.2f} m²</td>
</tr>
<tr style="font-weight: bold;">
<td style="border: 1px solid #475569; padding: 11px 14px; color: #ffffff; background-color: #1e3a8a;">Toplam Bağımsız Bölüm Brüt Alanı (Eklentiler Dahil)</td>
<td style="border: 1px solid #475569; padding: 11px 14px; color: #ffffff; background-color: #1e3a8a;">Ana Ünite + Bodrum + Havuz Payı</td>
<td style="border: 1px solid #475569; padding: 11px 14px; color: #38bdf8; background-color: #1e3a8a; text-align: right; font-weight: 800;">{toplam_unite_brut_dahil_eklentiler:,.2f} m²</td>
</tr>"""

        st.markdown(f"""<div style="overflow-x: auto; margin-bottom: 20px;"><table style="width: 100%; border-collapse: collapse; font-size: 14px;">
<thead>
<tr style="background-color: #020617; color: #ffffff;">
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: left; font-weight: 700;">Bileşen</th>
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: left; font-weight: 700;">Açıklama / Model</th>
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: right; font-weight: 700;">Birim Değeri</th>
</tr>
</thead>
<tbody>
{tab3_detay_rows_html}
</tbody>
</table></div>""", unsafe_allow_html=True)

    with tab4:
        st.subheader("📑 Proje Raporu ve Finansal Fizibilite Matrisi")
        
        curr_hb = st.session_state["hedef_bagimsiz_bolum"]
        curr_hp = st.session_state["havuz_tercihi"]
        
        net_emsal_tabani_rapor = yasal_max_brut_insaat_alani - (30.0 if curr_hp == "Her Bağımsız Bölüme 1 Özel Havuz" else (120.0 if curr_hp == "Ortak / Sosyal Tesis Havuzu" else 0.0))
        simulated_bodrum_alani = max(0.0, net_emsal_tabani_rapor) * p_spec["bodrum_orani"]

        first_parcel = list(active_parcel_db.values())[0]
        detected_mahalle = first_parcel.get("mahalle", "VARSAYILAN").upper()
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.caption(f"📍 Referans Lokasyon: **{detected_mahalle}** | Proje Tipi: **{selected_proje_tipi}**")
        with col_m2:
            manual_override = st.checkbox("Özel / Manuel Fiyat Girişi Yap", value=False, key="tab4_manual_override")

        real_satis_usd, real_maliyet_usd, otomatik_bodrum_orani = get_realistic_market_pricing(detected_mahalle, selected_proje_tipi, rates["USD"])

        st.success(f"⚡ **Canlı TCMB Kurları:** 1 USD = {rates['USD']:.2f} TL | 1 EUR = {rates['EUR']:.2f} TL | **Toplam Brüt İnşaat Alanı:** {yasal_max_brut_insaat_alani:,.2f} m²")

        st.markdown("---")
        col_f1, col_f2 = st.columns(2)
        
        if manual_override:
            birim_maliyet = col_f1.number_input("İnşaat M² Brüt Maliyeti ($) [Özel]", value=float(real_maliyet_usd), step=50.0, key="tab4_maliyet")
            birim_satis = col_f2.number_input("M² Brüt Satış Fiyatı ($) [Özel]", value=float(real_satis_usd), step=100.0, key="tab4_satis")
        else:
            birim_maliyet = col_f1.number_input("İnşaat M² Brüt Maliyeti ($) [Piyasa]", value=float(real_maliyet_usd), disabled=True, key="tab4_maliyet_dis")
            birim_satis = col_f2.number_input("M² Brüt Satış Fiyatı ($) [Piyasa]", value=float(real_satis_usd), disabled=True, key="tab4_satis_dis")

        toplam_maliyet_usd = (yasal_max_brut_insaat_alani * birim_maliyet) + arsa_bonus_usd
        normal_ciro = net_emsal_tabani_rapor * birim_satis
        bodrum_ciro = simulated_bodrum_alani * birim_satis * otomatik_bodrum_orani
        toplam_ciro_usd = normal_ciro + bodrum_ciro
        
        if "Kat Karşılığı" in is_modeli:
            arsa_sahibi_payi_usd = toplam_ciro_usd * (arsa_payi_orani / 100)
            mutaahhit_net_kar_usd = toplam_ciro_usd - toplam_maliyet_usd - arsa_sahibi_payi_usd
        else:
            arsa_sahibi_payi_usd = 0.0
            mutaahhit_net_kar_usd = toplam_ciro_usd - toplam_maliyet_usd
            
        yg_orani = (mutaahhit_net_kar_usd / toplam_maliyet_usd * 100) if toplam_maliyet_usd > 0 else 0
        toplam_ciro_tl = toplam_ciro_usd * rates['USD']
        toplam_maliyet_tl = toplam_maliyet_usd * rates['USD']
        mutaahhit_net_kar_tl = mutaahhit_net_kar_usd * rates['USD']

        st.markdown("---")
        st.markdown(f"### 📊 Rapor Özeti: {is_modeli} ({selected_proje_tipi})")
        
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        f_col1.metric("Toplam Tahmini Brüt Ciro", f"${toplam_ciro_usd:,.2f}", f"₺{toplam_ciro_tl:,.2f}")
        f_col2.metric("Toplam İnşaat Brüt Maliyeti + Bonus", f"${toplam_maliyet_usd:,.2f}", f"₺{toplam_maliyet_tl:,.2f}")
        if "Kat Karşılığı" in is_modeli:
            f_col3.metric("Arsa Sahibi Payı", f"${arsa_sahibi_payi_usd:,.2f}")
        else:
            f_col3.metric("İş Modeli", "Doğrudan Yatırım")
        f_col4.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar_usd:,.2f}", f"₺{mutaahhit_net_kar_tl:,.2f} (%{yg_orani:.1f} YG)")
        
        st.info("💡 **İpucu:** Raporun kurumsal ön izlemesini incelemek ve PDF olarak indirmek için yandaki **'🖨️ Rapor Ön İzleme & PDF'** sekmesine geçiş yapabilirsiniz.")

    # --- 5. SEKME: RAPOR ÖN İZLEME VE PDF İNDİRME MERKEZİ ---
    with tab5:
        st.subheader("🖨️ Kurumsal Rapor Ön İzleme ve PDF İndirme Merkezi")
        st.write("Aşağıda hazırlanan raporun profesyonel ekran ön izlemesi yer almaktadır. Butona tıklayarak doğrudan **Yatay PDF Olarak İndirebilirsiniz**.")
        st.markdown("---")
        
        tab5_saf_unite_brut = (yasal_max_brut_insaat_alani - (30.0 if curr_hp == "Her Bağımsız Bölüme 1 Özel Havuz" else (120.0 if curr_hp == "Ortak / Sosyal Tesis Havuzu" else 0.0))) / curr_hb if curr_hb > 0 else 0
        tab5_havuz_payi_m2 = 30.0 if curr_hp == "Her Bağımsız Bölüme 1 Özel Havuz" else (120.0 / curr_hb if curr_hp == "Ortak / Sosyal Tesis Havuzu" else 0.0)
        tab5_bodrum_payi_m2 = (net_emsal_tabani_rapor * p_spec["bodrum_orani"]) / curr_hb if curr_hb > 0 else 0
        tab5_toplam_unite_brut_dahil_eklentiler = tab5_saf_unite_brut + tab5_bodrum_payi_m2 + tab5_havuz_payi_m2
        tab5_unite_basi_net_arsa = toplam_net_arsa_alani / curr_hb if curr_hb > 0 else 0

        st.markdown(f"### 🏢 İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT EMLAK")
        st.markdown(f"**Akıllı Gayrimenkul Geliştirme ve Fizibilite Raporu**")
        
        st.markdown("#### 1. Proje ve Lokasyon Künyesi")
        st.markdown(f"- **Seçilen Lokasyon / Mahalle:** {detected_mahalle}")
        st.markdown(f"- **Proje Tipi:** {selected_proje_tipi}")
        st.markdown(f"- **İş Modeli:** {is_modeli}")
        st.markdown(f"- **Toplam Brüt Arsa Alanı:** {toplam_brut_arsa_alani:,.2f} m²")
        st.markdown(f"- **Parsel Bazlı Toplam Net Arsa Alanı:** {toplam_net_arsa_alani:,.2f} m²")
        st.markdown(f"- **Toplam Brüt İnşaat Alanı:** {yasal_max_brut_insaat_alani:,.2f} m²")
        
        st.markdown("#### 2. Mimari ve Bağımsız Bölüm Planlaması")
        st.markdown(f"- **Bağımsız Bölüm / Villa Adedi:** {curr_hb} Adet")
        st.markdown(f"- **Havuz Planlama Modeli:** {curr_hp}")
        st.markdown(f"- **Ünite Başına Düşen Net Arsa Payı:** {toplam_net_arsa_alani:,.2f} m² ({tab5_unite_basi_net_arsa:,.2f} m² / Ünite)")
        
        st.markdown("#### Bağımsız Bölüm Başına Detaylı Alan ve Dağılımı")
        
        preview_detay_rows_html = f"""<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Ana Ünite İnşaat Alanı (Brüt)</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Ortalama Bağımsız Bölüm Kapalı Alanı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #0f172a; text-align: right; font-weight: 700;">{tab5_saf_unite_brut:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #1e293b;">Bodrum Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #1e293b;">Ortalama Bodrum Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #1e293b; text-align: right; font-weight: 700;">{tab5_bodrum_payi_m2:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">Havuz Payı</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #f8fafc; background-color: #0f172a;">{curr_hp}</td>
<td style="border: 1px solid #475569; padding: 10px 14px; color: #38bdf8; background-color: #0f172a; text-align: right; font-weight: 700;">{tab5_havuz_payi_m2:,.2f} m²</td>
</tr>
<tr style="font-weight: bold;">
<td style="border: 1px solid #475569; padding: 11px 14px; color: #ffffff; background-color: #1e3a8a;">Toplam Bağımsız Bölüm Brüt Alanı (Eklentiler Dahil)</td>
<td style="border: 1px solid #475569; padding: 11px 14px; color: #ffffff; background-color: #1e3a8a;">Ana Ünite + Bodrum + Havuz Payı</td>
<td style="border: 1px solid #475569; padding: 11px 14px; color: #38bdf8; background-color: #1e3a8a; text-align: right; font-weight: 800;">{tab5_toplam_unite_brut_dahil_eklentiler:,.2f} m²</td>
</tr>"""

        st.markdown(f"""<div style="overflow-x: auto; margin-bottom: 20px;"><table style="width: 100%; border-collapse: collapse; font-size: 14px;">
<thead>
<tr style="background-color: #020617; color: #ffffff;">
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: left; font-weight: 700;">Bileşen</th>
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: left; font-weight: 700;">Açıklama / Model</th>
<th style="border: 1px solid #475569; padding: 12px 14px; text-align: right; font-weight: 700;">Birim Değeri</th>
</tr>
</thead>
<tbody>
{preview_detay_rows_html}
</tbody>
</table></div>""", unsafe_allow_html=True)
        
        st.markdown("#### 3. Finansal Fizibilite ve Ciro Analizi ($ USD)")
        
        preview_table_data = [
            {"Finansal Kalem": "Toplam Tahmini Brüt Ciro", "Tutar (USD $)": f"${toplam_ciro_usd:,.2f}", "Tutar (TL ₺)": f"₺{toplam_ciro_tl:,.2f}"},
            {"Finansal Kalem": "Toplam İnşaat Maliyeti + Bonus", "Tutar (USD $)": f"${toplam_maliyet_usd:,.2f}", "Tutar (TL ₺)": f"₺{toplam_maliyet_tl:,.2f}"}
        ]
        if "Kat Karşılığı" in is_modeli:
            preview_table_data.append({"Finansal Kalem": "Arsa Sahibi Payı", "Tutar (USD $)": f"${arsa_sahibi_payi_usd:,.2f}", "Tutar (TL ₺)": "-"})
        
        preview_table_data.append({"Finansal Kalem": "Müteahhit Net Kârı", "Tutar (USD $)": f"${mutaahhit_net_kar_usd:,.2f}", "Tutar (TL ₺)": f"₺{mutaahhit_net_kar_tl:,.2f} (%{yg_orani:.1f} YG)"})
        
        st.table(pd.DataFrame(preview_table_data))
        st.markdown("---")
        
        pdf_logo1_html = f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 55px; width: auto; object-fit: contain;'>" if img1_base64 else "<span style='font-size:18px; font-weight:bold; color:#1e3a8a;'>İSTESTATE</span>"
        pdf_logo2_html = f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 55px; width: auto; object-fit: contain;'>" if img2_base64 else "<span style='font-size:18px; font-weight:bold; color:#1e3a8a;'>MERİÇ İNŞAAT</span>"

        pdf_detay_rows_html = f"""<tr>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Ana Ünite İnşaat Alanı (Brüt)</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Ortalama Bağımsız Bölüm Kapalı Alanı</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px; text-align: right; font-weight: 600;">{tab5_saf_unite_brut:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Bodrum Payı</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Ortalama Bodrum Payı</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px; text-align: right; font-weight: 600;">{tab5_bodrum_payi_m2:,.2f} m²</td>
</tr>
<tr>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Havuz Payı</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">{curr_hp}</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px; text-align: right; font-weight: 600;">{tab5_havuz_payi_m2:,.2f} m²</td>
</tr>
<tr style="background-color: #f8fafc; font-weight: bold;">
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Toplam Bağımsız Bölüm Brüt Alanı (Eklentiler Dahil)</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px;">Ana Ünite + Bodrum + Havuz Payı</td>
<td style="border: 1px solid #cbd5e1; padding: 7px 10px; text-align: right; color: #1e3a8a;">{tab5_toplam_unite_brut_dahil_eklentiler:,.2f} m²</td>
</tr>"""

        arsa_sahibi_row_html = ""
        if "Kat Karşılığı" in is_modeli:
            arsa_sahibi_row_html = f"""
                    <tr>
                        <td style="border: 1px solid #cbd5e1; padding: 9px 12px; color: #334155;">Arsa Sahibi Payı</td>
                        <td style="border: 1px solid #cbd5e1; padding: 9px 12px; text-align: right; color: #0f172a; font-weight: 600;">${arsa_sahibi_payi_usd:,.2f}</td>
                        <td style="border: 1px solid #cbd5e1; padding: 9px 12px; text-align: right; color: #64748b;">-</td>
                    </tr>
            """

        report_html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: A4 landscape;
                margin: 15mm;
            }}
            body {{
                font-family: 'Helvetica', 'Arial', sans-serif;
                color: #1e293b;
                background: #ffffff;
                margin: 0;
                padding: 0;
            }}
            .report-container {{
                background: #ffffff;
                padding: 10px;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
                border-bottom: 2px solid #0f172a;
                padding-bottom: 15mm;
                margin-bottom: 20px;
            }}
            .header-table td {{
                border: none;
                padding: 0;
                vertical-align: middle;
            }}
            .title-box {{
                text-align: center;
            }}
            h2 {{
                font-size: 22px;
                font-weight: 800;
                color: #0f172a;
                margin: 0;
                letter-spacing: -0.5px;
            }}
            p.sub {{
                font-size: 13px;
                color: #475569;
                margin: 4px 0 0 0;
                font-weight: 600;
            }}
            .section-title {{
                font-size: 13px;
                font-weight: bold;
                color: #1e3a8a;
                border-bottom: 1.5px solid #cbd5e1;
                padding-bottom: 5px;
                margin-top: 18px;
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .content-line {{
                font-size: 12px;
                margin: 4px 0;
                color: #334155;
            }}
            .data-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 11px;
            }}
            .data-table th {{
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                padding: 8px 12px;
                text-align: left;
                color: #0f172a;
                font-weight: 700;
            }}
            .data-table td {{
                border: 1px solid #cbd5e1;
                padding: 9px 12px;
            }}
            .footer {{
                font-size: 10px;
                color: #64748b;
                text-align: center;
                margin-top: 40px;
                border-top: 1px dashed #cbd5e1;
                padding-top: 10px;
            }}
        </style>
        </head>
        <body>
        <div class="report-container">
            <table class="header-table">
                <tr>
                    <td style="width: 25%; text-align: left;">{pdf_logo1_html}</td>
                    <td style="width: 50%;" class="title-box">
                        <h2>İSTESTATE & MERİÇ İNŞAAT</h2>
                        <p class="sub">Akıllı Gayrimenkul Geliştirme ve Fizibilite Raporu</p>
                    </td>
                    <td style="width: 25%; text-align: right;">{pdf_logo2_html}</td>
                </tr>
            </table>
            
            <div class="section-title">1. Proje ve Lokasyon Künyesi</div>
            <p class="content-line"><b>Seçilen Lokasyon / Mahalle:</b> {detected_mahalle}</p>
            <p class="content-line"><b>Proje Tipi:</b> {selected_proje_tipi}</p>
            <p class="content-line"><b>İş Modeli:</b> {is_modeli}</p>
            <p class="content-line"><b>Toplam Arsa Alanı:</b> {toplam_brut_arsa_alani:,.2f} m²</p>
            <p class="content-line"><b>Parsel Bazlı Toplam Net Arsa Alanı:</b> {toplam_net_arsa_alani:,.2f} m²</p>
            <p class="content-line"><b>Toplam Brüt İnşaat Alanı:</b> {yasal_max_brut_insaat_alani:,.2f} m²</p>
            
            <div class="section-title">2. Mimari ve Bağımsız Bölüm Planlaması</div>
            <p class="content-line"><b>Bağımsız Bölüm / Villa Adedi:</b> {curr_hb} Adet</p>
            <p class="content-line"><b>Havuz Planlama Modeli:</b> {curr_hp}</p>
            <p class="content-line"><b>Ünite Başına Düşen Net Arsa Payı:</b> {toplam_net_arsa_alani:,.2f} m² ({tab5_unite_basi_net_arsa:,.2f} m² / Ünite)</p>
            
            <div style="font-size: 12px; font-weight: bold; color: #0f172a; margin-top: 10px; margin-bottom: 5px;">Bağımsız Bölüm Başına Detaylı Alan ve Dağılımı</div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Bileşen</th>
                        <th>Açıklama / Model</th>
                        <th style="text-align: right;">Birim Değeri</th>
                    </tr>
                </thead>
                <tbody>
                    {pdf_detay_rows_html}
                </tbody>
            </table>
            
            <div class="section-title">3. Finansal Fizibilite ve Ciro Analizi ($ USD)</div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Finansal Kalem</th>
                        <th style="text-align: right;">Tutar (USD $)</th>
                        <th style="text-align: right;">Tutar (TL ₺)</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="color: #334155;">Toplam Tahmini Brüt Ciro</td>
                        <td style="text-align: right; color: #0f172a; font-weight: 600;">${toplam_ciro_usd:,.2f}</td>
                        <td style="text-align: right; color: #334155;">₺{toplam_ciro_tl:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="color: #334155;">Toplam İnşaat Maliyeti + Bonus</td>
                        <td style="text-align: right; color: #0f172a; font-weight: 600;">${toplam_maliyet_usd:,.2f}</td>
                        <td style="text-align: right; color: #334155;">₺{toplam_maliyet_tl:,.2f}</td>
                    </tr>
                    {arsa_sahibi_row_html}
                    <tr style="background-color: #f1f5f9; font-weight: bold;">
                        <td style="color: #0f172a;">Müteahhit Net Kârı</td>
                        <td style="text-align: right; color: #1e3a8a;">${mutaahhit_net_kar_usd:,.2f}</td>
                        <td style="text-align: right; color: #1e3a8a;">₺{mutaahhit_net_kar_tl:,.2f} (%{yg_orani:.1f} YG)</td>
                    </tr>
                </tbody>
            </table>
            
            <div class="footer">
                Bu rapor İstestate Gayrimenkul & Meriç İnşaat Emlak Akıllı Fizibilite Portalı tarafından resmi veriler baz alınarak otomatik olarak üretilmiştir.
            </div>
        </div>
        </body>
        </html>
        """
        
        pdf_bytes = HTML(string=report_html_template).write_pdf()
        
        st.download_button(
            label="📥 Yatay Kurumsal Fizibilite Raporunu PDF Olarak İndir",
            data=pdf_bytes,
            file_name=f"Yatay_Fizibilite_Raporu_{detected_mahalle}_{selected_proje_tipi.replace(' ', '_')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
else:
    st.info("👋 **Hoş Geldiniz!** Raporları görüntülemek için lütfen sol menüden bir **Ada** seçip ilgili parselleri işaretleyin veya yeni bir imar belgesi (PDF) yükleyin.")
