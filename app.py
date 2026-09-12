import re
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

def clean_turkish_number(val_str):
    """
    Türkçe sayı formatlarını (örn: 5.051,15 veya 762,54) float sayı tipine hatasız dönüştürür.
    """
    if not val_str:
        return 0.0
    # Sadece sayı, nokta ve virgülü tut
    val_str = re.sub(r'[^\d\.,]', '', str(val_str)).strip()
    if not val_str:
        return 0.0
    
    # 5.051,15 -> 5051.15 dönüşümü
    if "." in val_str and "," in val_str:
        val_str = val_str.replace(".", "").replace(",", ".")
    elif "," in val_str:
        val_str = val_str.replace(",", ".")
    elif "." in val_str:
        # Binlik nokta kontrolü (örn: 5.051 -> 5051)
        parts = val_str.split(".")
        if len(parts) > 1 and len(parts[-1]) != 2:
            val_str = val_str.replace(".", "")
            
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def parse_imar_pdf(uploaded_file):
    parcel_data = {
        "mahalle": "BİLİNMİYOR",
        "ada": "0",
        "parsel": "0",
        "toplam_alan": 0.0,
        "fonksiyonlar": []
    }
    
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += "\n" + t
                
        # 1. Mahalle, Ada, Parsel, Toplam Arsa Alanı Parsing
        mah_m = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
        ada_m = re.search(r"Ada\s*\|\s*(\d+)", full_text)
        par_m = re.search(r"Parsel\s*\|\s*(\d+)", full_text)
        alan_m = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", full_text)
        
        if mah_m: parcel_data["mahalle"] = mah_m.group(1).upper()
        if ada_m: parcel_data["ada"] = ada_m.group(1)
        if par_m: parcel_data["parsel"] = par_m.group(1)
        if alan_m: parcel_data["toplam_alan"] = clean_turkish_number(alan_m.group(1))

        # 2. Sayfa Sayfa Tablo Analizi (Multi-Zone & Dynamic KAKS/TAKS)
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                table_text = " ".join([" ".join([str(c) for c in row if c]) for row in table])
                
                if "Fonksiyon Adı" in table_text:
                    fonk_adi = ""
                    taks_val = 0.30
                    kaks_val = 0.40
                    giren_m2 = parcel_data["toplam_alan"]
                    
                    for row in table:
                        row_str = " ".join([str(c) for c in row if c])
                        
                        # Fonksiyon Adı Çekimi
                        if "Fonksiyon Adı" in row_str:
                            for c in row:
                                clean_c = str(c).strip()
                                if clean_c and "Fonksiyon Adı" not in clean_c and clean_c != "|":
                                    fonk_adi = clean_c
                                    break
                        
                        # TAKS / KAKS Çekimi
                        taks_m = re.search(r"Taks\s*\|?\s*([\d\.]+)", row_str, re.IGNORECASE)
                        kaks_m = re.search(r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.]+)", row_str, re.IGNORECASE)
                        if taks_m: taks_val = float(taks_m.group(1))
                        if kaks_m: kaks_val = float(kaks_m.group(1))
                        
                        # Fonksiyon Alanı M2 Çekimi (örn: %78.94 - 5.051,15 m² veya 762,54 m²)
                        if "m²" in row_str or "Fonksiyon Alanına" in row_str:
                            m2_m = re.search(r"([\d\.,]+)\s*m²", row_str)
                            if m2_m:
                                giren_m2 = clean_turkish_number(m2_m.group(1))
                    
                    if fonk_adi and not any(f['fonksiyon_adi'] == fonk_adi for f in parcel_data["fonksiyonlar"]):
                        parcel_data["fonksiyonlar"].append({
                            "fonksiyon_adi": fonk_adi,
                            "taks": taks_val,
                            "kaks": kaks_val,
                            "giren_m2": giren_m2
                        })

    if not parcel_data["fonksiyonlar"]:
        parcel_data["fonksiyonlar"].append({
            "fonksiyon_adi": "KONUT ALANI",
            "taks": 0.30,
            "kaks": 0.40,
            "giren_m2": parcel_data["toplam_alan"]
        })

    return parcel_data

# --- APP UI ---
st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT EMLAK</h2>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center; color: #475569;'>İmar Durumu Analizi & Gayrimenkul Fizibilite Portalı</h4>", unsafe_allow_html=True)
st.divider()

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
    tab1, tab2, tab3 = st.tabs(["📊 İmar Durumu Özeti", "📐 İnşaat Alanı Hesabı", "💰 Gelir / Gider Fizibilitesi"])
    
    with tab1:
        st.subheader("Yüklenen Parsellerin Detaylı İmar Listesi")
        table_rows = []
        for key, p in st.session_state["parcel_db"].items():
            for f in p["fonksiyonlar"]:
                table_rows.append({
                    "Kimlik": key,
                    "Mahalle": p["mahalle"],
                    "Ada": p["ada"],
                    "Parsel": p["parsel"],
                    "Toplam Arsa (m²)": f"{p['toplam_alan']:,.2f}",
                    "Fonksiyon": f["fonksiyon_adi"],
                    "TAKS": f["taks"],
                    "KAKS (Emsal)": f["kaks"],
                    "Fonksiyon Alanı (m²)": f"{f['giren_m2']:,.2f}"
                })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

    with tab2:
        st.subheader("İnşaat Kapasite Hesabı")
        col_c1, col_c2 = st.columns(2)
        terk_durumu = col_c1.radio("Terkin Durumu Seçiniz:", ["Terki Yapılmamış Arazi (Brüt)", "Terki Yapılmış Arazi (Net)"])
        emsal_artis_orani = col_c2.number_input("Emsal Artış Katsayısı (Örn: 1.30)", value=1.30, step=0.05)
        
        st.markdown("---")
        total_inşaat_alani = 0.0
        calc_results = []

        for key, p in st.session_state["parcel_db"].items():
            for f in p["fonksiyonlar"]:
                if any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]):
                    satilabilir_m2 = 0.0
                else:
                    if terk_durumu == "Terki Yapılmamış Arazi (Brüt)":
                        satilabilir_m2 = f["giren_m2"] * 0.70 * f["kaks"] * emsal_artis_orani
                    else:
                        satilabilir_m2 = f["giren_m2"] * f["kaks"] * emsal_artis_orani
                
                total_inşaat_alani += satilabilir_m2
                calc_results.append({
                    "Parsel": key,
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Esas Alan (m²)": f"{f['giren_m2']:,.2f}",
                    "Emsal (KAKS)": f["kaks"],
                    "Toplam İnşaat Alanı (m²)": f"{satilabilir_m2:,.2f}"
                })

        st.table(pd.DataFrame(calc_results))
        st.metric(label="🏗️ Toplam Satılabilir Net İnşaat Alanı (m²)", value=f"{total_inşaat_alani:,.2f} m²")

    with tab3:
        st.subheader("Finansal Analiz ve Proje Fizibilitesi")
        col_f1, col_f2, col_f3 = st.columns(3)
        birim_maliyet = col_f1.number_input("İnşaat M² Maliyeti ($)", value=800, step=50)
        birim_satis = col_f2.number_input("M² Satış Fiyatı ($)", value=2500, step=100)
        arsa_payi_orani = col_f3.slider("Arsa Payı / Kat Karşılığı Oranı (%)", min_value=0, max_value=70, value=40)
        
        toplam_maliyet = total_inşaat_alani * birim_maliyet
        toplam_ciro = total_inşaat_alani * birim_satis
        arsa_sahibi_payi = toplam_ciro * (arsa_payi_orani / 100)
        mutaahhit_net_kar = toplam_ciro - toplam_maliyet - arsa_sahibi_payi
        roi = (mutaahhit_net_kar / toplam_maliyet * 100) if toplam_maliyet > 0 else 0
        
        st.markdown("### 📊 Finansal Tablo Özeti")
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        f_col1.metric("Toplam Tahmini Ciro", f"${toplam_ciro:,.2f}")
        f_col2.metric("Toplam İnşaat Maliyeti", f"${toplam_maliyet:,.2f}")
        f_col3.metric("Arsa Sahibi Payı", f"${arsa_sahibi_payi:,.2f}")
        f_col4.metric("Müteahhit Net Karı", f"${mutaahhit_net_kar:,.2f}", delta=f"%{roi:.1f} ROI")

        st.markdown("---")
        st.caption("İstestate Gayrimenkul & Meriç İnşaat Emlak - Otomatik Fizibilite Raporlama Motoru")
