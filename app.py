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

# --- KALICI DOSYA TABANLI VERİTABANI YÖNETİMİ ---
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

# --- TCMB CANLI DÖVİZ KURU SERVİSİ ---
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

# --- BEYKOZ GERÇEKÇİ PİYASA VE PROJE TİPİ MATRİSİ ---
def get_realistic_market_pricing(mahalle_adi, proje_tipi, usd_rate):
    mahalle_base_tl = {
        "ACARLAR": 140000, "ANADOLU HİSARI": 130000, "KANLICA": 125000,
        "GÖKSU": 110000, "GÖRELE": 115000, "RİVA": 120000,
        "ÇİFTLİK": 115000, "BAKLACI": 95000, "KAVACIK": 90000,
        "ÇENGELDERE": 105000, "YAVUZ SELİM": 80000, "FATİH": 75000,
        "SOĞUKSU": 95000, "PAŞABAHÇE": 90000, "VARSAYILAN": 95000
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
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 16px; padding: 30px 40px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08); margin-bottom: 30px;">
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

        toplam_giren_fonk_m2 = sum(
            f["giren_m2"] for f in p["fonksiyonlar"]
            if not any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"])
        )

        for f in p["fonksiyonlar"]:
            fonk_net_m2 = f["giren_m2"] if is_terkli else f["giren_m2"] * 0.70
            toplam_net_arsa_alani += fonk_net_m2

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

    # --- SEKME YAPISI (Doğru Girintiyle if selected_keys bloğunun içinde) ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Seçilen Parseller Özeti", 
        "📐 İnşaat Alanı Hesabı", 
        "🏛️ Mimari Fizibilite", 
        "📑 Proje Raporu & Fizibilite",
        "🖨️ Rapor Ön İzleme & PDF"
    ])
    
    with tab1:
        st.subheader("Seçilen Parsellerin İmar ve Fonksiyon Bazlı Arsa Dağılımı")
        st.info("💡 **Güncel Mantık:** Net Arsa alanı parselin gerçek kesintilerine göre hesaplanırken, **Ünite Başına Düşen Fonksiyon Alanı** doğrudan **Fonksiyon Alanı (m²)** üzerinden bağımsız bölüm adedine oranlanmaktadır.")
        
        table_rows = []
        for key, p in active_parcel_db.items():
            is_terkli = p["terk_yapilmis_mi"]
            toplam_brut = p["toplam_alan"]
            
            toplam_fonk_alan = sum(f["giren_m2"] for f in p["fonksiyonlar"])
            
            if not is_terkli and toplam_brut > 0 and toplam_fonk_alan > 0:
                parsel_net_arsa_toplam = min(toplam_fonk_alan, toplam_brut * 0.70)
            else:
                parsel_net_arsa_toplam = toplam_fonk_alan if is_terkli else toplam_brut * 0.70

            terk_lbl = f"Terki Yapılmış (Net)" if is_terkli else f"Terksiz / Kesintili"
            
            for f in p["fonksiyonlar"]:
                fonks_m2 = f["giren_m2"]
                
                fonk_oran = (fonks_m2 / toplam_fonk_alan) if toplam_fonk_alan > 0 else 1.0
                net_m2 = parsel_net_arsa_toplam * fonk_oran
                
                hedef_bb = st.session_state.get("hedef_bagimsiz_bolum", 1)
                unite_basi_fonk_net = fonks_m2 / hedef_bb if hedef_bb > 0 else 0
                
                table_rows.append({
                    "Parsel Bilgisi": key,
                    "Mahalle": p["mahalle"],
                    "Toplam Brüt Arsa (m²)": f"{toplam_brut:,.2f}",
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Fonksiyon Alanı (m²)": f"{fonks_m2:,.2f}",
                    "Hesaplanan Net Arsa (m²)": f"{net_m2:,.2f}",
                    "Ünite Başına Düşen Fonksiyon Alanı": f"{unite_basi_fonk_net:,.2f} m² / Ünite",
                    "TAKS": f"{f['taks']:.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Durum": terk_lbl
                })
                
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
        st.info(f"💡 **Genel Özet:** Toplam Brüt Arsa: **{toplam_brut_arsa_alani:,.2f} m²** | Toplam Net Arsa: **{toplam_net_arsa_alani:,.2f} m²**")

    with tab2:
        st.subheader("İnşaat Alanı ve Emsal Hesaplama Paneli")
        st.metric("Yasal Maksimum Brüt İnşaat Alanı (Emsal + Artışlar)", f"{yasal_max_brut_insaat_alani:,.2f} m²")

    with tab3:
        st.subheader("Mimari Fizibilite ve Ünite Dağılımı")
        st.write("Bağımsız bölüm ve mimari yerleşim parametreleri.")
        st.session_state["hedef_bagimsiz_bolum"] = st.number_input("Hedef Bağımsız Bölüm Adedi", min_value=1, value=int(st.session_state.get("hedef_bagimsiz_bolum", 1)))

    with tab4:
        st.subheader("Proje Raporu ve Finansal Fizibilite")
        st.write("Maliyet, satış ve kârlılık analizleri.")

    with tab5:
        st.subheader("Rapor Ön İzleme ve PDF Çıktısı")
        st.write("WeasyPrint tabanlı kurumsal PDF rapor çıktısı.")
