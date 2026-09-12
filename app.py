import re
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

# --- TABLE-BASED PDF PARSER ENGINE ---
def parse_imar_pdf(uploaded_file):
    """
    Beykoz Belediyesi İmar Durumu PDF'lerini doğrudan tablo hücrelerinden
    eksiksiz ve hatasız okuyan gelişmiş parser.
    """
    parcel_data = {
        "mahalle": "BİLİNMİYOR",
        "ada": "0",
        "parsel": "0",
        "toplam_alan": 0.0,
        "fonksiyonlar": []
    }
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            
            for table in tables:
                for row_idx, row in enumerate(table):
                    cells = [str(cell).strip().replace('\n', ' ') if cell is not None else '' for cell in row]
                    row_str = " ".join(cells)
                    
                    # 1. Mahalle, Ada, Parsel, Alan Yakalama
                    if any("Mahalle" in c for c in cells) and any("Ada" in c for c in cells):
                        if row_idx + 1 < len(table):
                            data_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[row_idx + 1]]
                            for idx, head in enumerate(cells):
                                if "Mahalle" in head and idx < len(data_row):
                                    val = data_row[idx].upper()
                                    if val and val != "MAHALLE":
                                        parcel_data["mahalle"] = val
                                elif "Ada" in head and idx < len(data_row):
                                    val = data_row[idx]
                                    if val and val != "ADA":
                                        parcel_data["ada"] = val
                                elif "Parsel" in head and idx < len(data_row):
                                    val = data_row[idx]
                                    if val and val != "PARSEL":
                                        parcel_data["parsel"] = val
                                elif "Alan" in head and idx < len(data_row):
                                    raw_a = data_row[idx].replace("m²", "").replace(".", "").replace(",", ".").strip()
                                    m = re.search(r"[\d\.]+", raw_a)
                                    if m:
                                        parcel_data["toplam_alan"] = float(m.group(0))

                    # 2. Fonksiyon, TAKS ve KAKS (Emsal) Yakalama
                    if "Fonksiyon Adı" in row_str:
                        fonk_adi = ""
                        taks_val = 0.30
                        kaks_val = 0.40
                        giren_m2 = parcel_data["toplam_alan"]
                        
                        for i_r in range(row_idx, min(row_idx + 6, len(table))):
                            sub_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[i_r]]
                            sub_str = " ".join(sub_row)
                            
                            if "Fonksiyon Adı" in sub_str and len(sub_row) > 1:
                                for cell in sub_row:
                                    if cell and "Fonksiyon Adı" not in cell and ":" not in cell:
                                        fonk_adi = cell
                                        break
                            
                            taks_m = re.search(r"Taks\s*\|?\s*([\d\.]+)", sub_str, re.IGNORECASE)
                            kaks_m = re.search(r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.]+)", sub_str, re.IGNORECASE)
                            
                            if taks_m: taks_val = float(taks_m.group(1))
                            if kaks_m: kaks_val = float(kaks_m.group(1))
                            
                            if "Fonksiyon Alanına" in sub_str or "Giren" in sub_str or "m²" in sub_str:
                                m2_m = re.search(r"([\d\.,]+)\s*m²", sub_str)
                                if m2_m:
                                    giren_m2 = float(m2_m.group(1).replace(".", "").replace(",", "."))
                        
                        if fonk_adi and not any(f['fonksiyon_adi'] == fonk_adi for f in parcel_data["fonksiyonlar"]):
                            parcel_data["fonksiyonlar"].append({
                                "fonksiyon_adi": fonk_adi,
                                "taks": taks_val,
                                "kaks": kaks_val,
                                "giren_m2": giren_m2
                            })

    # Yedek Kontrol: Eğer regex/tablo ile Mahalle/Ada okunamadıysa düz metinden dene
    if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
        with pdfplumber.open(uploaded_file) as pdf:
            text = "\n".join([p.extract_text() or "" for p in pdf.pages])
            m_m = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", text)
            a_m = re.search(r"Ada\s*\|\s*(\d+)", text)
            p_m = re.search(r"Parsel\s*\|\s*(\d+)", text)
            al_m = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", text)
            
            if m_m: parcel_data["mahalle"] = m_m.group(1).upper()
            if a_m: parcel_data["ada"] = a_m.group(1)
            if p_m: parcel_data["parsel"] = p_m.group(1)
            if al_m and parcel_data["toplam_alan"] == 0.0:
                parcel_data["toplam_alan"] = float(al_m.group(1).replace(".", "").replace(",", "."))

    # Fonksiyon Boş Kaldıysa Varsayılan Ekle
    if not parcel_data["fonksiyonlar"]:
        parcel_data["fonksiyonlar"].append({
            "fonksiyon_adi": "KONUT ALANI",
            "taks": 0.30,
            "kaks": 0.40,
            "giren_m2": parcel_data["toplam_alan"]
        })

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
            for f in p["fonksiyonlar"]:
                table_rows.append({
                    "Kimlik": key,
                    "Mahalle": p["mahalle"],
                    "Ada": p["ada"],
                    "Parsel": p["parsel"],
                    "Toplam Arsa (m²)": p["toplam_alan"],
                    "Fonksiyon": f["fonksiyon_adi"],
                    "TAKS": f["taks"],
                    "KAKS (Emsal)": f["kaks"],
                    "Fonksiyon Alanı (m²)": f["giren_m2"]
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
                # Don't calculate construction area for public / green zones
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
