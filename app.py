import io
import os
from datetime import datetime
import pandas as pd
import pdfplumber
import streamlit as st
from weasyprint import HTML

# Sayfa Yapılandırması
st.set_page_config(
    page_title="İSTESTATE & MERİÇ İNŞAAT - İmar ve Fizibilite Portal",
    page_icon="🏢",
    layout="wide",
)

# Stil ve Arayüz Düzenlemeleri
st.markdown(
    """
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; background-color: #1f4e78; color: white; font-weight: bold; }
    .stButton>button:hover { background-color: #16385c; color: white; }
    .metric-card { background-color: #ffffff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 4px solid #1f4e78; }
    </style>
""",
    unsafe_allow_html=True,
)


# Başlık ve Logo Alanı
col_logo1, col_logo2 = st.columns([1, 5])
with col_logo1:
    if os.path.exists("istestate_logo.png"):
        st.image("istestate_logo.png", width=120)
    else:
        st.markdown("### 🏢 İSTESTATE")

with col_logo2:
    st.title("Beykoz Gayrimenkul Proje ve İmar Fizibilite Portalı")
    st.markdown(
        "*İSTESTATE Gayrimenkul & MERİÇ İnşaat Emlak Ortak Çözüm Platformu*"
    )

st.markdown("---")

# Yan Menü / Proje Parametreleri
st.sidebar.header("⚙️ Proje ve Bölge Parametreleri")
secilen_mahalle = st.sidebar.selectbox(
    "Beykoz Mahalle Seçimi",
    [
        "Anadoluhisarı",
        "Kanlıca",
        "Çubuklu",
        "Paşabahçe",
        "Beykoz Merkez",
        "Acarkent / Çavuşbaşı",
        "Göksu",
    ],
)

proje_tipi = st.sidebar.selectbox(
    "Proje Konsepti",
    ["Lüks Villa / Müstakil", "Butik Apartman", "Karma Proje (Ticaret + Konut)"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 İmar ve Alan Parametreleri")
arsa_alani = st.sidebar.number_input(
    "Arsa Tapu Alanı (m²)", min_value=100.0, max_value=50000.0, value=1200.0, step=50.0
)
kaks_oran = st.sidebar.number_input(
    "KAKS (Emsal)", min_value=0.05, max_value=3.00, value=0.60, step=0.05
)
taks_oran = st.sidebar.number_input(
    "TAKS (Taban Alanı Oranı)",
    min_value=0.05,
    max_value=1.00,
    value=0.20,
    step=0.05,
)
terk_orani = (
    st.sidebar.slider("Yol / Yeşil Alan Terk Oranı (%)", 0, 40, 15) / 100.0
)

st.sidebar.markdown("---")
st.sidebar.subheader("💰 Finansal ve Maliyet Parametreleri")
insaat_maliyet_m2 = st.sidebar.number_input(
    "Ortalama İnşaat Maliyeti (USD / m²)",
    min_value=300.0,
    max_value=3000.0,
    value=750.0,
    step=50.0,
)
satis_fiyat_m2 = st.sidebar.number_input(
    "Beklenen Ortalama Satış Fiyatı (USD / m²)",
    min_value=500.0,
    max_value=10000.0,
    value=2500.0,
    step=100.0,
)
kat_karsiligi_orani = (
    st.sidebar.slider("Arsa Sahibi Payı Oranı (Kat Karşılığı %)", 30, 60, 50)
    / 100.0
)

# Sekmeler Oluşturma
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📄 İmar PDF Analizi",
        "📐 Alan & İnşaat Hesabı",
        "💵 Finansal Fizibilite",
        "📊 Kurumsal Rapor Çıktısı",
    ]
)

# --- SEKME 1: İmar PDF Analizi ---
with tab1:
    st.subheader("Belediye / Plan Notu PDF Veri Ayıklama Aracı")
    st.markdown(
        "Belediyeden alınan resmi imar durum belgesini veya plan notu PDF dosyasını yükleyerek otomatik parametre çekebilirsiniz."
    )

    uploaded_pdf = st.file_uploader(
        "İmar Durum Belgesi Seçin (PDF)", type=["pdf"]
    )

    if uploaded_pdf is not None:
        with st.spinner("PDF taranıyor ve metinler çözümleniyor..."):
            extracted_text = ""
            try:
                with pdfplumber.open(uploaded_pdf) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            extracted_text += text + "\n"

                st.success("PDF başarıyla analiz edildi!")
                with st.expander("Çözümlenen Ham Metni Görüntüle"):
                    st.text_area(
                        "Metin Çıktısı", extracted_text, height=200
                    )
            except Exception as e:
                st.error(
                    f"PDF okunurken bir hata oluştu: {str(e)}"
                )
    else:
        st.info(
            "Analiz için yukarıdan bir PDF dosyası yükleyin veya sol menüdeki manuel parametreleri kullanın."
        )

# --- SEKME 2: Alan & İnşaat Hesabı ---
with tab2:
    st.subheader("Net/Brüt Alan ve Yapılaşma Kapasitesi")

    net_arsa = arsa_alani * (1 - terk_orani)
    toplam_insaat_alani = net_arsa * kaks_oran
    taban_alani = net_arsa * taks_oran
    tahmini_kat_sayisi = (
        round(toplam_insaat_alani / taban_alani) if taban_alani > 0 else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            label="Net Arsa Alanı",
            value=f"{net_arsa:,.1f} m²",
            delta=f"-{int(terk_orani*100)}% Terk",
        )
    with col2:
        st.metric(
            label="Toplam İnşaat Alanı (EMSAL)",
            value=f"{toplam_insaat_alani:,.1f} m²",
        )
    with col3:
        st.metric(label="Maksimum Taban Alanı", value=f"{taban_alani:,.1f} m²")
    with col4:
        st.metric(label="Öngörülen Kat Adedi", value=f"{tahmini_kat_sayisi} Kat")

    st.markdown("---")
    st.markdown("#### 🏗️ Bağımsız Bölüm Dağılım Tahmini")
    ortalama_daire_alani = st.slider(
        "Ortalama Bağımsız Bölüm Brüt Alanı (m²)", 90, 300, 150
    )
    tahmini_bagimsiz_bolum = (
        int(toplam_insaat_alani / ortalama_daire_alani)
        if ortalama_daire_alani > 0
        else 0
    )

    st.info(
        f"Bu imar koşullarında yaklaşık **{tahmini_bagimsiz_bolum} adet** bağımsız bölüm (ortalama {ortalama_daire_alani} m² brüt) üretilebileceği öngörülmektedir."
    )

# --- SEKME 3: Finansal Fizibilite ---
with tab3:
    st.subheader("Maliyet ve Hasılat Analizi")

    toplam_maliyet = toplam_insaat_alani * insaat_maliyet_m2
    toplam_potansiyel_hasilat = toplam_insaat_alani * satis_fiyat_m2

    arsa_sahibi_payi_degeri = toplam_potansiyel_hasilat * kat_karsiligi_orani
    muteahhit_hasilati = toplam_potansiyel_hasilat - arsa_sahibi_payi_degeri
    brut_kar = muteahhit_hasilati - toplam_maliyet
    kar_marji = (
        (brut_kar / toplam_maliyet) * 100 if toplam_maliyet > 0 else 0
    )

    f1, f2, f3 = st.columns(3)
    with f1:
        st.metric(
            label="Toplam İnşaat Maliyeti",
            value=f"${toplam_maliyet:,.0f}",
            delta=f"${insaat_maliyet_m2}/m²",
        )
    with f2:
        st.metric(
            label="Toplam Proje Hasılatı",
            value=f"${toplam_potansiyel_hasilat:,.0f}",
            delta=f"${satis_fiyat_m2}/m²",
        )
    with f3:
        st.metric(
            label="Müteahhit Brüt Kârı",
            value=f"${brut_kar:,.0f}",
            delta=f"%{kar_marji:.1f} Kâr",
        )

    st.markdown("---")
    st.markdown("#### 📋 Finansal Özet Tablosu")

    finans_data = {
        "Finansal Kalem": [
            "Arsa Net Alanı",
            "Toplam İnşaat Alanı (m²)",
            "İnşaat Maliyeti Birim ($/m²)",
            "Toplam İnşaat Maliyeti ($)",
            "Satış Fiyatı Birim ($/m²)",
            "Toplam Proje Satış Değeri ($)",
            "Arsa Sahibi Payı Oranı",
            "Müteahhit Hasılat Payı ($)",
            "Tahmini Brüt Kâr ($)",
        ],
        "Değer": [
            f"{net_arsa:,.1f} m²",
            f"{toplam_insaat_alani:,.1f} m²",
            f"${insaat_maliyet_m2:,.2f}",
            f"${toplam_maliyet:,.2f}",
            f"${satis_fiyat_m2:,.2f}",
            f"${toplam_potansiyel_hasilat:,.2f}",
            f"%{int(kat_karsiligi_orani*100)}",
            f"${muteahhit_hasilati:,.2f}",
            f"${brut_kar:,.2f}",
        ],
    }
    df_finans = pd.DataFrame(finans_data)
    st.dataframe(df_finans, use_container_width=True)

# --- SEKME 4: Kurumsal Rapor Çıktısı ---
with tab4:
    st.subheader("Kurumsal PDF Rapor Üretimi")
    st.markdown(
        "Yapılan analizleri ve finansal fizibiliteyi **İSTESTATE & MERİÇ İNŞAAT** antetli kurumsal formatında PDF olarak dışa aktarabilirsiniz."
    )

    rapor_tarihi = datetime.now().strftime("%d.%m.%Y")
    proje_adi = st.text_input("Proje / Parsel Tanımı", "Beykoz Örnek Parsel Analizi")

    if st.button("Kurumsal PDF Raporu Oluştur"):
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #333; margin: 30px; }}
                .header {{ border-bottom: 2px solid #1f4e78; padding-bottom: 10px; margin-bottom: 20px; }}
                .title {{ color: #1f4e78; font-size: 22px; font-weight: bold; }}
                .subtitle {{ color: #555; font-size: 14px; }}
                .section {{ margin-top: 20px; font-size: 16px; font-weight: bold; color: #1f4e78; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .footer {{ margin-top: 40px; font-size: 11px; text-align: center; color: #777; border-top: 1px solid #eee; padding-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="title">İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT</div>
                <div class="subtitle">Gayrimenkul Geliştirme ve İmar Fizibilite Raporu | Tarih: {rapor_tarihi}</div>
            </div>
            
            <div class="section">1. Proje ve Lokasyon Bilgileri</div>
            <p><b>Proje Adı / Parsel:</b> {proje_adi}<br>
            <b>Bölge / Mahalle:</b> Beykoz / {secilen_mahalle}<br>
            <b>Konsept:</b> {proje_tipi}</p>
            
            <div class="section">2. İmar ve Alan Ölçüleri</div>
            <table>
                <tr><th>Parametre</th><th>Değer</th></tr>
                <tr><td>Tapu Arsa Alanı</td><td>{arsa_alani:,.1f} m²</td></tr>
                <tr><td>Net Arsa Alanı (Terkler Sonrası)</td><td>{net_arsa:,.1f} m²</td></tr>
                <tr><td>KAKS (Emsal) / TAKS</td><td>{kaks_oran} / {taks_oran}</td></tr>
                <tr><td>Toplam İnşaat Alanı (EMSAL)</td><td>{toplam_insaat_alani:,.1f} m²</td></tr>
                <tr><td>Tahmini Bağımsız Bölüm Sayısı</td><td>{tahmini_bagimsiz_bolum} Adet</td></tr>
            </table>

            <div class="section">3. Finansal Fizibilite ve Maliyetler</div>
            <table>
                <tr><th>Finansal Kalem</th><th>Tutar (USD)</th></tr>
                <tr><td>Toplam İnşaat Maliyeti</td><td>${toplam_maliyet:,.2f}</td></tr>
                <tr><td>Toplam Proje Satış Hasılatı</td><td>${toplam_potansiyel_hasilat:,.2f}</td></tr>
                <tr><td>Arsa Sahibi Payı (%{int(kat_karsiligi_orani*100)})</td><td>${arsa_sahibi_payi_degeri:,.2f}</td></tr>
                <tr><td>Müteahhit Brüt Kârı</td><td>${brut_kar:,.2f} (%{kar_marji:.1f})</td></tr>
            </table>

            <div class="footer">
                Bu rapor İSTESTATE Gayrimenkul & Meriç İnşaat Emlak ortak veri analiz altyapısı ile otomatik olarak üretilmiştir.
            </div>
        </body>
        </html>
        """

        try:
            pdf_bytes = HTML(string=html_content).write_pdf()
            st.download_button(
                label="📥 PDF Raporunu Bilgisayara İndir",
                data=pdf_bytes,
                file_name=f"Fizibilite_Raporu_{secilen_mahalle}.pdf",
                mime="application/pdf",
            )
            st.success("Kurumsal PDF raporu başarıyla hazırlandı!")
        except Exception as e:
            st.error(
                f"PDF oluşturulurken sistem hatası oluştu (WeasyPrint bağımlılıklarını kontrol edin): {str(e)}"
            )
