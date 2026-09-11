import os
import re
import tempfile
from datetime import datetime, timedelta
import pandas as pd
import pdfplumber
import requests
import xml.etree.ElementTree as ET
import streamlit as st
from weasyprint import HTML

# Page Setup
st.set_page_config(
    page_title="İstestate & Meriç - İmar ve Fizibilite Analizi",
    page_icon="🏢",
    layout="wide"
)

# Parsel Veritabanı
PARSEL_VERITABANI = {
    "13": {"Nitelik": "Bahçe", "Alan": 2131.58, "Net_Alan": 1593.16},
    "14": {"Nitelik": "Bahçe", "Alan": 2001.35, "Net_Alan": 1414.76},
    "15": {"Nitelik": "Bahçe", "Alan": 2174.82, "Net_Alan": 1544.42},
    "16": {"Nitelik": "Bahçe", "Alan": 6058.42, "Net_Alan": 4075.16},
    "17": {"Nitelik": "Arsa",  "Alan": 712.18,  "Net_Alan": 565.80},
    "18": {"Nitelik": "Bahçe", "Alan": 1094.78, "Net_Alan": 734.92},
    "19": {"Nitelik": "Bahçe", "Alan": 974.59,  "Net_Alan": 911.21},
    "20": {"Nitelik": "Bahçe", "Alan": 1358.34, "Net_Alan": 927.86},
    "21": {"Nitelik": "Bahçe", "Alan": 1645.15, "Net_Alan": 1217.72},
    "22": {"Nitelik": "Bahçe", "Alan": 537.82,  "Net_Alan": 449.11},
    "23": {"Nitelik": "Bahçe", "Alan": 459.96,  "Net_Alan": 376.65},
    "24": {"Nitelik": "Bahçe", "Alan": 906.26,  "Net_Alan": 666.03},
    "25": {"Nitelik": "Bahçe", "Alan": 552.28,  "Net_Alan": 381.35},
    "26": {"Nitelik": "Bahçe", "Alan": 1115.07, "Net_Alan": 924.81},
    "27": {"Nitelik": "Bahçe", "Alan": 819.15,  "Net_Alan": 642.92},
    "29": {"Nitelik": "Arsa",  "Alan": 4618.21, "Net_Alan": 3068.47},
    "33": {"Nitelik": "Arsa",  "Alan": 675.30,  "Net_Alan": 664.22}
}

# --- HELPER FUNCTIONS ---
def metin_sayi_cevir(val_str):
    if not val_str:
        return 0.0
    val_str = str(val_str).strip()
    last_comma = val_str.rfind(',')
    last_dot = val_str.rfind('.')

    try:
        if last_comma == -1 and last_dot == -1:
            return float(val_str)
        elif last_comma > last_dot:
            return float(val_str.replace('.', '').replace(',', '.'))
        else:
            return float(val_str.replace(',', ''))
    except ValueError:
        return 0.0

def fmt_tr(val, decimals=2, para_birimi="TL"):
    try:
        if val is None or val == "" or val == "-":
            return "-"
        v = float(val)
        formatted = f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        simge_map = {"TL": "TL", "USD": "$", "EUR": "€"}
        simge = simge_map.get(para_birimi, "TL")
        
        return f"{formatted} {simge}" if para_birimi == "TL" else f"{simge}{formatted}"
    except:
        return str(val)

# --- DÖVİZ KURLARI VE MAHALLE VERİSİ MOTORU ---
@st.cache_data(ttl=14400)
def tcmb_kurlari_getir():
    """TCMB canlı kurlarını çeker, hata alırsa güncel sabit kur verir."""
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        
        usd = float(root.find("./Currency[@CurrencyCode='USD']/BanknoteSelling").text)
        eur = float(root.find("./Currency[@CurrencyCode='EUR']/BanknoteSelling").text)
        return {"USD": usd, "EUR": eur}
    except Exception:
        return {"USD": 38.50, "EUR": 41.20} # Yedek güncel kurlar

@st.cache_data(ttl=86400)
def mahalle_piyasa_verisi_getir(mahalle_adi):
    """Mahalle bazlı imalat maliyeti ve gayrimenkul m² satış değerleri (TL)"""
    MAHALLE_VERITABANI = {
        "Çiftlik": {"maliyet": 32500.0, "satis": 110000.0},
        "Acarlar": {"maliyet": 42000.0, "satis": 175000.0},
        "Görele": {"maliyet": 35000.0, "satis": 130000.0},
        "Rüzgarlıbahçe": {"maliyet": 31000.0, "satis": 95000.0},
        "Kavacık": {"maliyet": 33000.0, "satis": 105000.0},
        "Çengeldere": {"maliyet": 30000.0, "satis": 85000.0},
        "Yavuztürk": {"maliyet": 29000.0, "satis": 78000.0},
        "Bilinmiyor": {"maliyet": 32000.0, "satis": 100000.0}
    }
    
    # Kısmi isim eşleşmesi kontrolü (Örn: "Çiftlik Mah." -> "Çiftlik")
    for key in MAHALLE_VERITABANI.keys():
        if key.lower() in mahalle_adi.lower():
            return MAHALLE_VERITABANI[key]
            
    return MAHALLE_VERITABANI["Bilinmiyor"]

# --- PDF METİN VE MAHALLE OKUMA MOTORU ---
def tek_pdf_analiz_et(uploaded_file):
    mahalle = "Bilinmiyor"
    ada = "Bilinmiyor"
    parsel = "Bilinmiyor"
    rapor_alani = 0.0

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            tam_metin = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    tam_metin += text + "\n"
    except Exception as e:
        st.error(f"Okuma hatası ({uploaded_file.name}): {e}")
        return []

    metin_tek_satir = re.sub(r'\s+', ' ', tam_metin)

    # Otomatik Mahalle Tespiti
    match_mahalle = re.search(r'Mahalles?i?\s*:?\s*([A-Za-zÇĞİÖŞÜçğıöşü]+)', metin_tek_satir, re.IGNORECASE)
    if match_mahalle:
        mahalle = match_mahalle.group(1).capitalize()

    match_parsel = re.search(r'(\d+)\s+(\d+)\s+([\d.,]+)\s*m²', metin_tek_satir)
    if match_parsel:
        ada = match_parsel.group(1)
        parsel = match_parsel.group(2)
        rapor_alani = metin_sayi_cevir(match_parsel.group(3))

    kaks_val = 0.3
    match_kaks = re.search(r'(?:Kaks|Emsal)[^\d]*([\d.,]+)', metin_tek_satir, re.IGNORECASE)
    if match_kaks:
        kaks_val = metin_sayi_cevir(match_kaks.group(1))

    p_info = PARSEL_VERITABANI.get(str(parsel), None)

    if p_info:
        nitelik = p_info["Nitelik"]
        parsel_alani = p_info["Alan"]
        net_alan = p_info["Net_Alan"]
    else:
        nitelik = "Bahçe"
        parsel_alani = rapor_alani
        net_alan = parsel_alani * 0.70

    hesaba_alinan = parsel_alani * 0.70
    net_insaat = hesaba_alinan * kaks_val
    brut_insaat = net_insaat * 1.30

    return [{
        "Mahalle": mahalle,
        "Ada": str(ada),
        "Parsel": str(parsel),
        "Nitelik": nitelik,
        "Parsel_Alani": parsel_alani,
        "Hesaba_Alinan": hesaba_alinan,
        "Net_Alan": net_alan,
        "Fonksiyon": "KONUT ALANI",
        "KAKS": kaks_val,
        "Net_Insaat": net_insaat,
        "Brut_Insaat": brut_insaat,
        "Dosya_Adı": uploaded_file.name
    }]

# --- UI SIDEBAR ---
if os.path.exists("assets/istestate_logo.png"):
    st.sidebar.image("assets/istestate_logo.png", use_container_width=True)

st.sidebar.title("⚙️ Analiz Parametreleri")

# Para Birimi Seçimi
para_birimi = st.sidebar.selectbox("💱 Raporlama Para Birimi", ["TL", "USD", "EUR"], index=0)
kurlar = tcmb_kurlari_getir()

# Para birimi katsayısı hesabı
kur_katsayisi = 1.0
if para_birimi == "USD":
    kur_katsayisi = 1.0 / kurlar["USD"]
elif para_birimi == "EUR":
    kur_katsayisi = 1.0 / kurlar["EUR"]

if para_birimi != "TL":
    st.sidebar.caption(f"ℹ️ Canlı Kur: 1 USD = {kurlar['USD']:.2f} TL | 1 EUR = {kurlar['EUR']:.2f} TL")

st.sidebar.subheader("📐 Mimari Metraj Ayarları")
v_m2 = st.sidebar.number_input("Villa Brüt m²", value=250, step=10)
d_m2 = st.sidebar.number_input("Daire Brüt m²", value=120, step=5)
h_ekle = st.sidebar.checkbox("Villalara Havuz Ekle", value=True)
h_m2 = st.sidebar.number_input("Havuz m² (Villa Başı)", value=35, step=5) if h_ekle else 0

st.sidebar.subheader("🤝 Kat Karşılığı & Paylaşım")
kat_karsiligi_oran = st.sidebar.slider("Arsa Payı / Kat Karşılığı Oranı (%)", min_value=20, max_value=70, value=50, step=5)

genel_gider_orani = st.sidebar.slider("Pazarlama & Şantiye Gideri (%)", min_value=0, max_value=15, value=5)

# --- MAIN APP LAYOUT ---
st.title("🏢 Beykoz İmar Analizi ve Fizibilite Portalı")

col_left, col_right = st.columns([1, 1])

with col_left:
    uploaded_pdfs = st.file_uploader("PDF İmar Raporlarını Yükleyin", type=["pdf"], accept_multiple_files=True)

with col_right:
    tkgm_img = st.file_uploader("Parsel / Uydu Haritası (Görsel)", type=["png", "jpg", "jpeg"])
    imar_img = st.file_uploader("İmar Planı Haritası (Görsel)", type=["png", "jpg", "jpeg"])

if uploaded_pdfs:
    tum_veriler = []
    for pdf in uploaded_pdfs:
        res = tek_pdf_analiz_et(pdf)
        if res:
            tum_veriler.extend(res)

    if tum_veriler:
        df = pd.DataFrame(tum_veriler)
        
        # PDF'ten TESPİT EDİLEN MAHALLE
        otomatik_mahalle = df['Mahalle'].iloc[0]
        st.sidebar.subheader(f"📍 Otomatik Tespit Edilen Konum")
        st.sidebar.success(f"**Mahalle:** {otomatik_mahalle}")

        # Mahalle Fiyat Verilerini Çek
        mahalle_veri = mahalle_piyasa_verisi_getir(otomatik_mahalle)
        oto_maliyet_tl = mahalle_veri["maliyet"]
        oto_satis_tl = mahalle_veri["satis"]

        # Özel Proje Girişi Onay Kutusu
        ozel_giris_aktif = st.sidebar.checkbox(
            "✏️ Özel Proje Girişi Yap (Veriyi Ez)", 
            value=False
        )

        if ozel_giris_aktif:
            maliyet_m2 = st.sidebar.number_input(
                f"İnşaat Bp. Maliyeti ({para_birimi}/m²)", 
                value=float(oto_maliyet_tl * kur_katsayisi), 
                step=100.0
            )
            satis_m2 = st.sidebar.number_input(
                f"Tahmini Satış Fiyatı ({para_birimi}/m²)", 
                value=float(oto_satis_tl * kur_katsayisi), 
                step=500.0
            )
        else:
            maliyet_m2 = oto_maliyet_tl * kur_katsayisi
            satis_m2 = oto_satis_tl * kur_katsayisi
            st.sidebar.info(
                f"• İnşaat Maliyeti: **{fmt_tr(maliyet_m2, 0, para_birimi)}/m²**\n\n"
                f"• Satış Fiyatı: **{fmt_tr(satis_m2, 0, para_birimi)}/m²**"
            )

        df['Ada_Num'] = pd.to_numeric(df['Ada'], errors='coerce').fillna(0)
        df['Parsel_Num'] = pd.to_numeric(df['Parsel'], errors='coerce').fillna(0)
        df = df.sort_values(by=['Ada_Num', 'Parsel_Num']).reset_index(drop=True)

        toplam_brut_insaat = df['Brut_Insaat'].sum()
        toplam_net_alan = df['Net_Alan'].sum()

        # Mimari Hesaplamalar
        hedef_v_m2 = v_m2 + h_m2
        v_adet = int(toplam_brut_insaat // hedef_v_m2) if hedef_v_m2 > 0 else 0
        d_adet = int(toplam_brut_insaat // d_m2) if d_m2 > 0 else 0

        # Kat Karşılığı Dağılım
        yuklenici_payi_m2 = toplam_brut_insaat * ((100 - kat_karsiligi_oran) / 100)
        arsa_sahibi_payi_m2 = toplam_brut_insaat * (kat_karsiligi_oran / 100)

        yuklenici_v_adet = int(v_adet * ((100 - kat_karsiligi_oran) / 100))
        arsa_sahibi_v_adet = v_adet - yuklenici_v_adet

        # Finansal Fizibilite Hesapları (Seçilen Para Birimiyle)
        toplam_insaat_maliyeti = toplam_brut_insaat * maliyet_m2
        pazarlama_operasyon_maliyet = toplam_insaat_maliyeti * (genel_gider_orani / 100)
        toplam_proje_maliyeti = toplam_insaat_maliyeti + pazarlama_operasyon_maliyet

        toplam_yuklenici_ciro = yuklenici_payi_m2 * satis_m2
        net_kar = toplam_yuklenici_ciro - toplam_proje_maliyeti
        roi = (net_kar / toplam_proje_maliyeti * 100) if toplam_proje_maliyeti > 0 else 0

        # --- SEKMELER ---
        tab1, tab2, tab3 = st.tabs(["📊 Parsel & İmar Özeti", "📐 Kat Karşılığı & Mimari", "💵 Finansal Fizibilite"])

        with tab1:
            st.subheader(f"Otomatik Tespit Edilen Konum: {otomatik_mahalle} Mahallesi")
            st.dataframe(
                df[['Mahalle', 'Ada', 'Parsel', 'Nitelik', 'Parsel_Alani', 'Hesaba_Alinan', 'Net_Alan', 'KAKS', 'Brut_Insaat']],
                use_container_width=True
            )

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Toplam Arazi (m²)", fmt_tr(df['Parsel_Alani'].sum()))
            c2.metric("Toplam Net Arazi (m²)", fmt_tr(toplam_net_alan))
            c3.metric("Ortalama KAKS", fmt_tr(df['KAKS'].mean(), 2))
            c4.metric("Toplam Brüt İnşaat (m²)", fmt_tr(toplam_brut_insaat))

        with tab2:
            st.subheader("Kat Karşılığı & Paylaşım Modeli")
            k1, k2 = st.columns(2)

            with k1:
                st.info(f"**Yüklenici Payı (%{100-kat_karsiligi_oran}):** {fmt_tr(yuklenici_payi_m2)} m²")
                st.write(f"• Müteahhit Villa Adedi: **{yuklenici_v_adet} Adet**")
                st.write(f"• Müteahhit Daire Adedi: **{int(d_adet * ((100-kat_karsiligi_oran)/100))} Adet**")

            with k2:
                st.success(f"**Arsa Sahibi Payı (%{kat_karsiligi_oran}):** {fmt_tr(arsa_sahibi_payi_m2)} m²")
                st.write(f"• Arsa Sahibi Villa Adedi: **{arsa_sahibi_v_adet} Adet**")
                st.write(f"• Arsa Sahibi Daire Adedi: **{d_adet - int(d_adet * ((100-kat_karsiligi_oran)/100))} Adet**")

        with tab3:
            st.subheader(f"Fizibilite Özeti ({para_birimi} Cinsinden)")

            f1, f2, f3 = st.columns(3)
            f1.metric("Toplam Proje Maliyeti", fmt_tr(toplam_proje_maliyeti, 0, para_birimi))
            f2.metric("Müteahhit Satış Cirosu", fmt_tr(toplam_yuklenici_ciro, 0, para_birimi))
            f3.metric("Net Kar", fmt_tr(net_kar, 0, para_birimi), delta=f"%{roi:.1f} ROI")

            st.markdown("---")
            st.markdown(f"#### Maliyet ve Gelir Detay Kırılımı ({para_birimi})")
            fizibilite_data = {
                "Kalem": [
                    f"Birim İnşaat Maliyeti ({otomatik_mahalle})",
                    "Pazarlama, Ruhsat ve Şantiye Giderleri",
                    "Toplam Yatırım Maliyeti",
                    "Yükleniciye Kalan Brüt Satış Alanı",
                    f"Hesaplanan Toplam Ciro ({otomatik_mahalle})",
                    "Net Proje Karı"
                ],
                "Tutar / Değer": [
                    f"{fmt_tr(toplam_insaat_maliyeti, 0, para_birimi)} ({fmt_tr(maliyet_m2, 0, para_birimi)}/m²)",
                    f"{fmt_tr(pazarlama_operasyon_maliyet, 0, para_birimi)}",
                    f"{fmt_tr(toplam_proje_maliyeti, 0, para_birimi)}",
                    f"{fmt_tr(yuklenici_payi_m2)} m²",
                    f"{fmt_tr(toplam_yuklenici_ciro, 0, para_birimi)} ({fmt_tr(satis_m2, 0, para_birimi)}/m²)",
                    f"{fmt_tr(net_kar, 0, para_birimi)}"
                ]
            }
            st.table(pd.DataFrame(fizibilite_data))

else:
    st.info("👆 Lütfen analiz yapmak istediğiniz imar raporu PDF dosyalarını yükleyin.")
