import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="İstestate & Meriç - İmar Portalı", layout="wide")

# ==========================================
# GÜÇLENDİRİLMİŞ PDF AYRIŞTIRICI
# ==========================================
def parse_imar_pdf(pdf_file):
    mahalle, ada, parsel = "Bilinmiyor", "0", "0"
    kaks, brut_alan = 0.40, 0.0

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            
            # 1. Metin İçi Taramalar
            m_match = re.search(r'(YAVUZSELİM|ÇİFTLİK|GÖRELE|BAKLACI|ÇENGELDERE|FATİH|YAVUZ SELİM)', text, re.IGNORECASE)
            if m_match:
                mahalle = m_match.group(1).upper()

            ada_match = re.search(r'Ada\s*[:\|]?\s*(\d+)', text, re.IGNORECASE)
            if ada_match:
                ada = ada_match.group(1)

            parsel_match = re.search(r'Parsel\s*[:\|]?\s*(\d+)', text, re.IGNORECASE)
            if parsel_match:
                parsel = parsel_match.group(1)

            kaks_match = re.search(r'Kaks\s*\(Emsal\)\s*[:\|]?\s*([0-9\.]+)', text, re.IGNORECASE)
            if kaks_match:
                try:
                    kaks = float(kaks_match.group(1))
                except ValueError:
                    pass

            # 2. Tablo Hücrelerinden Hassas Veri Çekme
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    row_str = " ".join([str(cell) for cell in row if cell])
                    
                    # Mahalle / Ada / Parsel / Alan Hücresi Taraması
                    if "Mahalle" in row_str or "YAVUZSELİM" in row_str or "ÇİFTLİK" in row_str:
                        for idx, cell in enumerate(row):
                            if cell and any(m in str(cell).upper() for m in ["YAVUZSELİM", "ÇİFTLİK", "GÖRELE", "BAKLACI", "ÇENGELDERE", "FATİH"]):
                                mahalle = str(cell).strip().upper()
                    
                    if "Alan" in row_str or "m²" in row_str:
                        alan_find = re.search(r'([\d\.,]+)\s*m²', row_str)
                        if alan_find:
                            val = alan_find.group(1).replace('.', '').replace(',', '.')
                            try:
                                brut_alan = float(val)
                            except ValueError:
                                pass

            # Metin İçinde Alan Araması (Yedek)
            if brut_alan == 0.0:
                alan_find = re.search(r'([\d\.,]+)\s*m²', text)
                if alan_find:
                    val = alan_find.group(1).replace('.', '').replace(',', '.')
                    try:
                        brut_alan = float(val)
                    except ValueError:
                        pass

    return {
        "Mahalle": mahalle,
        "Ada": ada,
        "Parsel": parsel,
        "KAKS": kaks,
        "Brut_Alan": brut_alan
    }

# ==========================================
# YAN PANEL (SIDEBAR)
# ==========================================
st.sidebar.title("🌐 Canlı Piyasalar & İmar Paneli")

terk_yapilmis = st.sidebar.checkbox("Terk İşlemi Yapılmış (DOP Kesintisiz Net)", value=False)
terk_durumu_str = "Terkli (Net)" if terk_yapilmis else "Terksiz (Brüt)"

kat_karsiligi_orani = st.sidebar.slider("Kat Karşılığı Oranı (% Arsa Sahibi)", min_value=0, max_value=100, value=50)

if st.sidebar.button("🗑️ Belleği Sıfırla"):
    st.session_state["pdf_data_store"] = {}
    st.rerun()

if "pdf_data_store" not in st.session_state:
    st.session_state["pdf_data_store"] = {}

# ==========================================
# ANA SAYFA
# ==========================================
st.title("🏢 İstestate & Meriç - İmar & Fizibilite Portalı")

uploaded_files = st.file_uploader("PDF İmar Raporlarını Yükleyin", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    for pdf_file in uploaded_files:
        parsed_info = parse_imar_pdf(pdf_file)
        
        rapor_id = f"{parsed_info['Ada']}_{parsed_info['Parsel']}"
        
        brut_alan = parsed_info["Brut_Alan"]
        kaks = parsed_info["KAKS"]
        
        # Formül Mantığı
        if terk_yapilmis:
            net_alan = brut_alan
            brut_insaat = net_alan * kaks * 1.30
        else:
            net_alan = brut_alan * 0.70
            brut_insaat = brut_alan * 0.70 * kaks * 1.30

        st.session_state["pdf_data_store"][rapor_id] = {
            "Rapor_ID": rapor_id,
            "Mahalle": parsed_info["Mahalle"],
            "Ada": parsed_info["Ada"],
            "Parsel": parsed_info["Parsel"],
            "Terk_Durumu": terk_durumu_str,
            "KAKS": kaks,
            "Brut_Alan": round(brut_alan, 2),
            "Net_Alan": round(net_alan, 2),
            "Brut_Insaat": round(brut_insaat, 2)
        }

# ==========================================
# İMAR RAPOR BELLEĞİ & FİZİBİLİTE
# ==========================================
st.subheader("📊 İmar Rapor Belleği")

if st.session_state["pdf_data_store"]:
    df_bellek = pd.DataFrame(list(st.session_state["pdf_data_store"].values()))
    st.dataframe(df_bellek, use_container_width=True)

    st.markdown("---")
    st.subheader("⚙️ İşlenecek Raporu Seçin")
    
    rapor_listesi = list(st.session_state["pdf_data_store"].keys())
    secilen_id = st.selectbox("Rapor Seçin", options=rapor_listesi)
    secilen_data = st.session_state["pdf_data_store"][secilen_id]
    
    st.markdown(f"### 📍 Seçili Parsel Analizi: Beykoz / {secilen_data['Mahalle']} - Ada: {secilen_data['Ada']} Parsel: {secilen_data['Parsel']}")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arazi Terk Durumu", secilen_data["Terk_Durumu"])
    col2.metric("Emsal (KAKS)", f"{secilen_data['KAKS']:.2f}")
    col3.metric("Hesaplanan Net Alan", f"{secilen_data['Net_Alan']:,.2f} m²")
    col4.metric("Brüt İnşaat Hakkı", f"{secilen_data['Brut_Insaat']:,.2f} m²")

    st.markdown("---")
    st.subheader("💰 Finansal Fizibilite ve Kar-Zarar Analizi")
    
    col_maliyet, col_satis = st.columns(2)
    birim_maliyet = col_maliyet.number_input("Birim İnşaat Maliyeti (TL/m²)", value=38000.0, step=1000.0)
    birim_satis = col_satis.number_input("Birim Satış Fiyatı (TL/m²)", value=145000.0, step=5000.0)
    
    toplam_insaat_alani = secilen_data["Brut_Insaat"]
    muteahhit_payi_m2 = toplam_insaat_alani * ((100 - kat_karsiligi_orani) / 100)
    arsa_sahibi_payi_m2 = toplam_insaat_alani * (kat_karsiligi_orani / 100)
    
    toplam_maliyet = toplam_insaat_alani * birim_maliyet
    toplam_ciro = muteahhit_payi_m2 * birim_satis
    net_kar = toplam_ciro - toplam_maliyet
    kar_marji = (net_kar / toplam_ciro * 100) if toplam_ciro > 0 else 0
    
    finansal_data = {
        "Kalem": [
            "Toplam Brüt İnşaat Alanı",
            f"Müteahhit Payı (%{100 - kat_karsiligi_orani})",
            f"Arsa Sahibi Payı (%{kat_karsiligi_orani})",
            "Toplam Proje İnşaat Maliyeti",
            "Müteahhit Toplam Satış Cirosu",
            "Net Kar / Zarar",
            "Kar Marjı (%)"
        ],
        "Metrik / Tutar": [
            f"{toplam_insaat_alani:,.2f} m²",
            f"{muteahhit_payi_m2:,.2f} m²",
            f"{arsa_sahibi_payi_m2:,.2f} m²",
            f"{toplam_maliyet:,.2f} TL",
            f"{toplam_ciro:,.2f} TL",
            f"{net_kar:,.2f} TL",
            f"%{kar_marji:.1f}"
        ]
    }
    
    st.table(pd.DataFrame(finansal_data))
else:
    st.info("Lütfen analiz etmek için yukarıdaki alandan bir veya birden fazla imar PDF dosyası yükleyin.")
