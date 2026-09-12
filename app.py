import re
import urllib.request
import xml.etree.ElementTree as ET
import pdfplumber
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="İstestate & Meriç İnşaat - Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

if "parcel_db" not in st.session_state:
    st.session_state["parcel_db"] = {}

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
    """
    Beykoz bölge dinamiklerine uygun gerçekçi satış ve inşaat maliyeti matrisi.
    """
    # Mahalle bazlı baz arsa/konut prim katsayıları (TL/m² eşdeğer bazları)
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
    
    # Proje Tipi Çarpanları (Satış ve Maliyet için)
    proje_carpanlari = {
        "Lüks Villa / Müstakil Proje": {"satis_mod": 1.55, "maliyet_mod": 1350},
        "Üst Segment Konut / Rezidans": {"satis_mod": 1.25, "maliyet_mod": 1100},
        "Standart Konut / Apartman": {"satis_mod": 1.00, "maliyet_mod": 900},
        "Ticari / Ofis Kompleksi": {"satis_mod": 1.35, "maliyet_mod": 1050},
        "Karma Proje (Konut + Ticari)": {"satis_mod": 1.20, "maliyet_mod": 1000}
    }
    
    p_conf = proje_carpanlari.get(proje_tipi, proje_carpanlari["Standart Konut / Apartman"])
    
    # Canlı USD kuru üzerinden hesaplanan gerçekçi satış fiyatı
    satis_fiyati_usd = round((base_tl * p_conf["satis_mod"]) / usd_rate, 2)
    maliyet_fiyati_usd = float(p_conf["maliyet_mod"])
    
    return satis_fiyati_usd, maliyet_fiyati_usd

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
    terksiz_kaliplar = ["YOLA TERK VE KAMUYA AYRILAN KISIMLAR KAMU ELİNE GEÇMEDEN", "TERK YAPILMAMIŞ", "TERKİ YAPILMAMIŞ", "TERK YAPILMADAN", "TERKİ YAPILMADAN", "DOP TERKİ YAPILMAMIŞ"]
    for kalip in terksiz_kaliplar:
        if kalip in text_upper:
            return False

    terkli_kaliplar = ["TERKİ YAPILMIŞTIR", "TERKİ YAPILMIŞ", "TERK YAPILMIŞTIR", "KAMUYA TERK EDİLMİŞTİR", "DOP TERKİ YAPILMIŞTIR"]
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
                                        parcel_data["ada"] = val
                                    elif "Parsel" in head and val:
                                        parcel_data["parsel"] = val
                                    elif "Alan" in head and val:
                                        parcel_data["toplam_alan"] = parse_tr_float(val)

                    if "Fonksiyon Adı" in row_str:
                        fonk_name = ""
                        taks_val = 0.30
                        kaks_val = 0.40
                        giren_m2 = 0.0
                        
                        for sub_idx in range(r_idx, min(r_idx + 5, len(table))):
                            sub_cells = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[sub_idx]]
                            sub_str = " ".join(sub_cells)
                            
                            if "Fonksiyon Adı" in sub_str:
                                for c in sub_cells:
                                    if c and "Fonksiyon Adı" not in c and c != "|":
                                        fonk_name = c.strip()
                                        break
                                        
                            t_m = re.search(r"Taks\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE)
                            k_m = re.search(r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE)
                            if t_m: taks_val = parse_tr_float(t_m.group(1))
                            if k_m: kaks_val = parse_tr_float(k_m.group(1))
                            
                            if "m²" in sub_str or "m2" in sub_str:
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
        if a_m: parcel_data["ada"] = a_m.group(1)
        if p_m: parcel_data["parsel"] = p_m.group(1)
        if al_m and parcel_data["toplam_alan"] == 0.0:
            parcel_data["toplam_alan"] = parse_tr_float(al_m.group(1))

    parcel_data["terk_yapilmis_mi"] = detect_terk_status(full_text, parcel_data["toplam_alan"], parcel_data["fonksiyonlar"])
    return parcel_data

# --- STREAMLIT ARAYÜZÜ ---
st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT EMLAK</h2>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center; color: #475569;'>Gerçekçi Piyasa Verili Fizibilite Portalı</h4>", unsafe_allow_html=True)
st.divider()

rates = get_live_exchange_rates()

st.sidebar.header("📁 İmar Belgesi Yükleme")
uploaded_files = st.sidebar.file_uploader("İmar Durum Raporu (PDF) Seçin", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    for uploaded_file in uploaded_files:
        p_data = parse_imar_pdf(uploaded_file)
        unique_key = f"{p_data['mahalle']}_{p_data['ada']}_{p_data['parsel']}"
        st.session_state["parcel_db"][unique_key] = p_data
    st.sidebar.success(f"{len(uploaded_files)} Adet Belge İşlendi!")

st.sidebar.subheader("🗄️ Veritabanındaki Parseller")
if st.session_state["parcel_db"]:
    for key in list(st.session_state["parcel_db"].keys()):
        col_s1, col_s2 = st.sidebar.columns([3, 1])
        col_s1.write(f"📍 {key}")
        if col_s2.button("Sil", key=f"del_{key}"):
            del st.session_state["parcel_db"][key]
            st.rerun()
else:
    st.sidebar.info("Henüz belge yüklenmedi.")

if st.session_state["parcel_db"]:
    tab1, tab2, tab3 = st.tabs(["📊 İmar Durumu Özeti", "📐 İnşaat Alanı Hesabı", "💰 Proje Tipi & Piyasa Fizibilitesi"])
    
    with tab1:
        st.subheader("Yüklenen Parsellerin İmar Özet Tablosu")
        table_rows = []
        for key, p in st.session_state["parcel_db"].items():
            terk_lbl = "Terki Yapılmış (Net)" if p["terk_yapilmis_mi"] else "Terki Yapılmamış (Brüt)"
            for f in p["fonksiyonlar"]:
                table_rows.append({
                    "Parsel Bilgisi": key,
                    "Mahalle": p["mahalle"],
                    "Brüt Arsa Alanı (m²)": f"{p['toplam_alan']:,.2f}",
                    "Fonksiyon": f["fonksiyon_adi"],
                    "İmarlı/Net Fonksiyon Alanı (m²)": f"{f['giren_m2']:,.2f}",
                    "TAKS": f"{f['taks']:.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Terk Durumu": terk_lbl
                })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

    with tab2:
        st.subheader("Çoklu Fonksiyon Destekli İnşaat Kapasite Hesabı")
        emsal_artis_orani = 1.30
        st.info("ℹ️ İnşaat hesabı sabit **1.30 Genel Emsal Artış Katsayısı** ile yürütülmektedir.")
        st.markdown("---")
        
        total_inşaat_alani = 0.0
        calc_results = []

        for key, p in st.session_state["parcel_db"].items():
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
                    if toplam_giren_fonk_m2 > 0:
                        fonk_pay_orani = f["giren_m2"] / toplam_giren_fonk_m2
                    else:
                        fonk_pay_orani = 1.0 / len(p["fonksiyonlar"])
                        
                    esas_m2 = toplam_brut_m2 * fonk_pay_orani
                    satilabilir_m2 = esas_m2 * 0.70 * f["kaks"] * emsal_artis_orani
                else:
                    esas_m2 = f["giren_m2"]
                    satilabilir_m2 = esas_m2 * f["kaks"] * emsal_artis_orani
                
                total_inşaat_alani += satilabilir_m2
                calc_results.append({
                    "Parsel": key,
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Terk Durumu": "Terksiz (Brüt Üzerinden %70 Düşülür)" if not is_terkli else "Terkli (Net Üzerinden Birebir)",
                    "Hesaba Esas Arsa Payı (m²)": f"{esas_m2:,.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Toplam Satılabilir Net İnşaat (m²)": f"{satilabilir_m2:,.2f}"
                })

        st.table(pd.DataFrame(calc_results))
        st.metric(label="🏗️ Toplam Satılabilir Net İnşaat Alanı (m²)", value=f"{total_inşaat_alani:,.2f} m²")

    with tab3:
        st.subheader("🏢 Proje Tipi ve Gerçekçi Bölge Fizibilitesi")
        st.success(f"⚡ **Canlı TCMB Dolar Kuru:** 1 USD = {rates['USD']:.2f} TL | **Beykoz Gerçekçi Rayiç Motoru Aktif**")
        
        first_parcel = list(st.session_state["parcel_db"].values())[0]
        detected_mahalle = first_parcel.get("mahalle", "VARSAYILAN").upper()
        
        st.markdown("### 🏗️ Proje Tipi ve Lokasyon Seçimi")
        col_opt1, col_opt2 = st.columns(2)
        
        with col_opt1:
            selected_proje_tipi = st.selectbox(
                "Proje Tipi Seçin:",
                options=[
                    "Lüks Villa / Müstakil Proje",
                    "Üst Segment Konut / Rezidans",
                    "Standart Konut / Apartman",
                    "Ticari / Ofis Kompleksi",
                    "Karma Proje (Konut + Ticari)"
                ],
                index=0
            )
        
        # Seçilen proje tipi ve mahalleye göre gerçekçi piyasa fiyatlarını hesapla
        real_satis_usd, real_maliyet_usd = get_realistic_market_pricing(detected_mahalle, selected_proje_tipi, rates["USD"])

        with col_opt2:
            st.caption(f"📍 Analiz Edilen Mahalle: **{detected_mahalle}**")
            manual_override = st.checkbox("Özel / Manuel Fiyat Girişi Yap (Piyasa verisini ez)", value=False)

        col_f1, col_f2, col_f3 = st.columns(3)
        
        if manual_override:
            birim_maliyet = col_f1.number_input("İnşaat M² Maliyeti ($) [Özel]", value=float(real_maliyet_usd), step=50.0)
            birim_satis = col_f2.number_input("M² Satış Fiyatı ($) [Özel]", value=float(real_satis_usd), step=100.0)
        else:
            birim_maliyet = col_f1.number_input("İnşaat M² Maliyeti ($) [Piyasa]", value=float(real_maliyet_usd), disabled=True)
            birim_satis = col_f2.number_input("M² Satış Fiyatı ($) [Piyasa]", value=float(real_satis_usd), disabled=True)

        arsa_payi_orani = col_f3.slider("Arsa Payı / Kat Karşılığı Oranı (%)", min_value=0, max_value=70, value=40)
        
        # FİNANSAL HESAPLAMALAR
        toplam_maliyet_usd = total_inşaat_alani * birim_maliyet
        toplam_ciro_usd = total_inşaat_alani * birim_satis
        arsa_sahibi_payi_usd = toplam_ciro_usd * (arsa_payi_orani / 100)
        mutaahhit_net_kar_usd = toplam_ciro_usd - toplam_maliyet_usd - arsa_sahibi_payi_usd
        roi = (mutaahhit_net_kar_usd / toplam_maliyet_usd * 100) if toplam_maliyet_usd > 0 else 0
        
        toplam_ciro_tl = toplam_ciro_usd * rates['USD']
        toplam_maliyet_tl = toplam_maliyet_usd * rates['USD']
        mutaahhit_net_kar_tl = mutaahhit_net_kar_usd * rates['USD']

        st.markdown("---")
        st.markdown("### 📊 Gerçekçi Finansal Tablo Özeti (USD & TL)")
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        f_col1.metric("Toplam Tahmini Ciro", f"${toplam_ciro_usd:,.2f}", f"₺{toplam_ciro_tl:,.2f}")
        f_col2.metric("Toplam İnşaat Maliyeti", f"${toplam_maliyet_usd:,.2f}", f"₺{toplam_maliyet_tl:,.2f}")
        f_col3.metric("Arsa Sahibi Payı", f"${arsa_sahibi_payi_usd:,.2f}")
        f_col4.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar_usd:,.2f}", f"₺{mutaahhit_net_kar_tl:,.2f} (%{roi:.1f} ROI)")

        st.caption("İstestate Gayrimenkul & Meriç İnşaat Emlak - Proje Tipi Destekli Gerçekçi Fizibilite Motoru")
