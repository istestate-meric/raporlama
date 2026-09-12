import re
import io
import pdfplumber
import pandas as pd
import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="İstestate & Meriç İnşaat - Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

# Initialize Session State Database
if "parcel_db" not in st.session_state:
    st.session_state["parcel_db"] = {}

# --- PDF PARSER ENGINE ---
def parse_imar_pdf(uploaded_file):
    """
    Parses Beykoz zoning PDFs dynamically.
    Extracts parcel IDs, land area, functions, TAKS, and KAKS correctly.
    """
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
            text = page.extract_text()
            if text:
                full_text += "\n" + text
                
        # Parse Parcel Metadata
        mahalle_m = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
        ada_m = re.search(r"Ada\s*\|\s*(\d+)", full_text)
        parsel_m = re.search(r"Parsel\s*\|\s*(\d+)", full_text)
        alan_m = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", full_text)
        
        if mahalle_m: parcel_data["mahalle"] = mahalle_m.group(1).upper()
        if ada_m: parcel_data["ada"] = ada_m.group(1)
        if parsel_m: parcel_data["parsel"] = parsel_m.group(1)
        if alan_m:
            raw_alan = alan_m.group(1).replace(".", "").replace(",", ".")
            parcel_data["toplam_alan"] = float(raw_alan)
            
        # Parse Multi-Zone & Dynamic KAKS/TAKS Blocks
        # Standard Beykoz zoning PDF format matching
        lines = full_text.split('\n')
        current_func = None
        
        for i, line in enumerate(lines):
            if "Fonksiyon Adı" in line:
                parts = line.split("|")
                if len(parts) > 1:
                    current_func = parts[1].strip()
            
            if "Kaks (Emsal)" in line and current_func:
                taks_val = 0.30
                kaks_val = 0.40
                
                # Extract TAKS / KAKS numbers
                taks_m = re.search(r"Taks\s*\|\s*([\d\.]+)", line)
                kaks_m = re.search(r"Kaks\s*\(Emsal\)\s*\|\s*([\d\.]+)", line)
                
                if taks_m: taks_val = float(taks_m.group(1))
                if kaks_m: kaks_val = float(kaks_m.group(1))
                
                # Check next line for M2/Percentage
                giren_m2 = parcel_data["toplam_alan"]
                if i + 1 < len(lines) and "Fonksiyon Alanına" in lines[i+1]:
                    m2_match = re.search(r"([\d\.,]+)\s*m²", lines[i+1])
                    if m2_match:
                        giren_m2 = float(m2_match.group(1).replace(".", "").replace(",", "."))
                
                # Deduplicate function assignment
                if not any(f['fonksiyon_adi'] == current_func for f in parcel_data["fonksiyonlar"]):
                    parcel_data["fonksiyonlar"].append({
                        "fonksiyon_adi": current_func,
                        "taks": taks_val,
                        "kaks": kaks_val,
                        "giren_m2": giren_m2
                    })
                current_func = None

    return parcel_data

# --- APP HEADER ---
st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT EMLAK</h2>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center; color: #475569;'>İmar Durumu Analizi & Gayrimenkul Fizibilite Portalı</h4>", unsafe_allow_html=True)
st.divider()

# --- SIDEBAR: PDF UPLOAD & PARCEL MANAGEMENT ---
st.sidebar.header("📁 İmar Belgesi Yükleme")
uploaded_files = st.sidebar.file_uploader(
    "İmar Durum Raporu (PDF) Seçin", 
    type=["pdf"], 
    accept_multiple_files=True
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        p_data = parse_imar_pdf(uploaded_file)
        unique_key = f"{p_data['mahalle']}_{p_data['ada']}_{p_data['parsel']}"
        st.session_state["parcel_db"][unique_key] = p_data
    st.sidebar.success(f"{len(uploaded_files)} Adet Belge İşlendi!")

# Display Database Status
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

# --- MAIN DASHBOARD ---
if not st.session_state["parcel_db"]:
    st.info("👋 Başlamak için sol menüden en az bir adet İmar Durum Raporu (PDF) yükleyiniz.")
else:
    tab1, tab2, tab3 = st.tabs(["📊 İmar Durumu Özeti", "📐 İnşaat Alanı Hesabı", "💰 Gelir / Gider Fizibilitesi"])
    
    # TAB 1: PARCEL DATABASE & ZONING SUMMARY
    with tab1:
        st.subheader("Yüklenen Parsellerin Detaylı İmar Listesi")
        
        table_rows = []
        for key, p in st.session_state["parcel_db"].items():
            if not p["fonksiyonlar"]:
                table_rows.append({
                    "Kimlik": key, "Mahalle": p["mahalle"], "Ada": p["ada"], "Parsel": p["parsel"],
                    "Toplam Arsa (m²)": p["toplam_alan"], "Fonksiyon": "KONUT ALANI",
                    "TAKS": 0.30, "KAKS": 0.40, "Fonksiyon Alanı (m²)": p["toplam_alan"]
                })
            else:
                for f in p["fonksiyonlar"]:
                    table_rows.append({
                        "Kimlik": key, "Mahalle": p["mahalle"], "Ada": p["ada"], "Parsel": p["parsel"],
                        "Toplam Arsa (m²)": p["toplam_alan"], "Fonksiyon": f["fonksiyon_adi"],
                        "TAKS": f["taks"], "KAKS": f["kaks"], "Fonksiyon Alanı (m²)": f["giren_m2"]
                    })
        
        df_summary = pd.DataFrame(table_rows)
        st.dataframe(df_summary, use_container_width=True)

    # TAB 2: CONSTRUCTION AREA CALCULATOR
    with tab2:
        st.subheader("İnşaat Kapasite Hesabı")
        
        col_c1, col_c2 = st.columns(2)
        terk_durumu = col_c1.radio(
            "Terkin Durumu Seçiniz:",
            ["Terki Yapılmamış Arazi (Brüt)", "Terki Yapılmış Arazi (Net)"]
        )
        emsal_artis_orani = col_c2.number_input("Emsal Artış Katsayısı (Örn: 1.30)", value=1.30, step=0.05)
        
        st.markdown("---")
        
        total_inşaat_alani = 0.0
        calc_results = []

        for key, p in st.session_state["parcel_db"].items():
            for f in p["fonksiyonlar"]:
                # Ignore non-construction zones in calculations
                if any(x in f["fonksiyon_adi"] for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL"]):
                    satilabilir_m2 = 0.0
                else:
                    if terk_durumu == "Terki Yapılmamış Arazi (Brüt)":
                        # Formula: Brüt X 0.70 X KAKS X 1.30
                        satilabilir_m2 = f["giren_m2"] * 0.70 * f["kaks"] * emsal_artis_orani
                    else:
                        # Formula: Net X KAKS X 1.30 (DOP done)
                        satilabilir_m2 = f["giren_m2"] * f["kaks"] * emsal_artis_orani
                
                total_inşaat_alani += satilabilir_m2
                calc_results.append({
                    "Parsel": key,
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Esas Alan (m²)": f["giren_m2"],
                    "Emsal (KAKS)": f["kaks"],
                    "Toplam İnşaat Alanı (m²)": round(satilabilir_m2, 2)
                })

        st.table(pd.DataFrame(calc_results))
        st.metric(label="🏗️ Toplam Satılabilir Net İnşaat Alanı (m²)", value=f"{total_inşaat_alani:,.2f} m²")

    # TAB 3: FINANCIAL FEASIBILITY & PROFITABILITY
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
