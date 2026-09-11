import os
import re
import math
import pandas as pd
import pdfplumber
import requests
import xml.etree.ElementTree as ET
import streamlit as st

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

BEYKOZ_MAHALLELERI = [
    "Çiftlik", "Acarlar", "Görele", "Rüzgarlıbahçe", "Kavacık", 
    "Çengeldere", "Yavuztürk", "Baklacı", "Fatih", "Yavuzselim"
]

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

def fmt_tr(val, decimals=2, para_birimi=""):
    try:
        if val is None or val == "" or val == "-":
            return "-"
        v = float(val)
        formatted = f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if para_birimi == "":
            return formatted
        simge_map = {"TL": "TL", "USD": "$", "EUR": "€"}
        simge = simge_map.get(para_birimi, para_birimi)
        return f"{formatted} {simge}" if para_birimi == "TL" else f"{simge}{formatted}"
    except:
        return str(val)

@st.cache_data(ttl=14400)
def tcmb_kurlari_getir():
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        usd = float(root.find("./Currency[@CurrencyCode='USD']/BanknoteSelling").text)
        eur = float(root.find("./Currency[@CurrencyCode='EUR']/BanknoteSelling").text)
        return {"USD": usd, "EUR": eur}
    except Exception:
        return {"USD": 38.50, "EUR": 41.20}

@st.cache_data(ttl=86400)
def mahalle_piyasa_verisi_getir(mahalle_adi):
    MAHALLE_VERITABANI = {
        "Çiftlik": {
            "villa": {"maliyet": 38000.0, "satis": 145000.0},
            "daire": {"maliyet": 30000.0, "satis": 95000.0},
            "ticari": {"maliyet": 35000.0, "satis": 130000.0}
        },
        "Acarlar": {
            "villa": {"maliyet": 48000.0, "satis": 210000.0},
            "daire": {"maliyet": 36000.0, "satis": 130000.0},
            "ticari": {"maliyet": 42000.0, "satis": 180000.0}
        },
        "Görele": {
            "villa": {"maliyet": 40000.0, "satis": 160000.0},
            "daire": {"maliyet": 31000.0, "satis": 100000.0},
            "ticari": {"maliyet": 36000.0, "satis": 140000.0}
        },
        "Bilinmiyor": {
            "villa": {"maliyet": 36000.0, "satis": 130000.0},
            "daire": {"maliyet": 28000.0, "satis": 85000.0},
            "ticari": {"maliyet": 33000.0, "satis": 115000.0}
        }
    }
    for key in MAHALLE_VERITABANI.keys():
        if key.lower() in mahalle_adi.lower():
            return MAHALLE_VERITABANI[key]
    return MAHALLE_VERITABANI["Bilinmiyor"]

def tek_pdf_analiz_et(uploaded_file):
    mahalle = "Bilinmiyor"
    ada = "Bilinmiyor"
    parsel = "Bilinmiyor"
    fonksiyon = "KONUT ALANI"
    rapor_alani = 0.0

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            tam_metin = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    tam_metin += text + "\n"

            imar_bolumu = tam_metin
            if "İmar Durumu Bilgileri" in tam_metin:
                imar_bolumu = tam_metin.split("İmar Durumu Bilgileri")[-1]
            imar_bolumu_ust = imar_bolumu.split("İdari Mahalle")[0] if "İdari Mahalle" in imar_bolumu else imar_bolumu

            for m_adi in BEYKOZ_MAHALLELERI:
                if re.search(rf'\b{m_adi}\b', imar_bolumu_ust, re.IGNORECASE):
                    mahalle = m_adi.capitalize()
                    break

            if "TİCARET" in tam_metin.upper():
                fonksiyon = "TİCARİ ALAN"

    except Exception as e:
        st.error(f"Okuma hatası ({uploaded_file.name}): {e}")
        return []

    metin_tum = re.sub(r'\s+', ' ', tam_metin)
    match_parsel = re.search(r'(\d+)\s+(\d+)\s+([\d.,]+)\s*m²', metin_tum)
    if match_parsel:
        ada = match_parsel.group(1)
        parsel = match_parsel.group(2)
        rapor_alani = metin_sayi_cevir(match_parsel.group(3))

    kaks_val = 0.3
    match_kaks = re.search(r'(?:Kaks|Emsal)[^\d]*([\d.,]+)', metin_tum, re.IGNORECASE)
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
        "Fonksiyon": fonksiyon,
        "KAKS": kaks_val,
        "Net_Insaat": net_insaat,
        "Brut_Insaat": brut_insaat,
        "Dosya_Adı": uploaded_file.name
    }]

def tam_otomatik_villa_mimarisi(toplam_m2):
    MIN_VILLA_BRUT = 150.0
    MIN_HAVUZ_M2 = 30.0

    if toplam_m2 < MIN_VILLA_BRUT:
        return 1, toplam_m2, 0.0, "Özel Ölçekli Tek Villa (Min. Sınır Altı Metraj)"

    if toplam_m2 < 300.0:
        adet = 1
        villa_brut = toplam_m2
        havuz_m2 = 0.0
        not_str = "Dar Metraj: Havuz Yerine Geniş Villa Alanı Tercih Edildi"
    elif toplam_m2 < 800.0:
        hedef_paket = 180.0 + MIN_HAVUZ_M2
        adet = math.floor(toplam_m2 / hedef_paket)
        if adet < 1:
            adet = 1
        
        kalan_m2 = toplam_m2 - (adet * MIN_HAVUZ_M2)
        villa_brut = kalan_m2 / adet

        if villa_brut >= MIN_VILLA_BRUT:
            havuz_m2 = MIN_HAVUZ_M2
            not_str = "Optimum Denge: Standardize Villa + 30 m² Havuz"
        else:
            villa_brut = toplam_m2 / adet
            havuz_m2 = 0.0
            not_str = "Villa Boyutunu Korumak İçin Havuz İptal Edildi"
    else:
        hedef_paket = 220.0 + 40.0
        adet = math.floor(toplam_m2 / hedef_paket)
        if adet < 1:
            adet = 1

        kalan_m2 = toplam_m2 - (adet * 40.0)
        villa_brut = kalan_m2 / adet
        havuz_m2 = 40.0
        not_str = "Geniş Metraj: Lüks Segment Villa + 40 m² Havuz"

    return adet, villa_brut, havuz_m2, not_str

# OTOMATİK PAZARLAMA & ŞANTİYE GİDERİ HESAPLAMA
def otomatik_gider_orani_hesapla(toplam_brut_m2):
    if toplam_brut_m2 < 1000.0:
        return 8.0
    elif toplam_brut_m2 <= 3000.0:
        return 6.0
    else:
        return 4.0

# SIDEBAR
if os.path.exists("assets/istestate_logo.png"):
    st.sidebar.image("assets/istestate_logo.png", use_container_width=True)

st.sidebar.title("⚙️ Analiz Parametreleri")

para_birimi = st.sidebar.selectbox("💱 Raporlama Para Birimi", ["TL", "USD", "EUR"], index=0)
kurlar = tcmb_kurlari_getir()

kur_katsayisi = 1.0
if para_birimi == "USD":
    kur_katsayisi = 1.0 / kurlar["USD"]
elif para_birimi == "EUR":
    kur_katsayisi = 1.0 / kurlar["EUR"]

st.sidebar.subheader("🤝 Kat Karşılığı & Paylaşım Oranı")
kat_karsiligi_oran = st.sidebar.slider(
    "Arsa Payı / Kat Karşılığı Oranı (%)", 
    min_value=10, 
    max_value=90, 
    value=50, 
    step=1,
    help="Arsa sahibinin kesin inşaat ve arsa payı yüzdesi."
)

st.sidebar.subheader("📐 Mimari Modelleme")
proje_tipi = st.sidebar.radio("Konut Proje Konsepti", ["Villa Projesi (Tam Otomatik)", "Konut / Daire Projesi"])

# MAIN APP
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
        otomatik_mahalle = df['Mahalle'].iloc[0]
        ana_fonksiyon = df['Fonksiyon'].iloc[0]

        toplam_brut_insaat = df['Brut_Insaat'].sum()
        toplam_net_alan = df['Net_Alan'].sum()

        # Otomatik Pazarlama & Şantiye Gideri Hesaplama
        hesaplanan_gider_orani = otomatik_gider_orani_hesapla(toplam_brut_insaat)
        
        st.sidebar.subheader("🏗️ Gider Parametreleri")
        ozel_gider_aktif = st.sidebar.checkbox("✏️ Şantiye/Pazarlama Giderini Manuel Düzenle", value=False)
        if ozel_gider_aktif:
            genel_gider_orani = st.sidebar.slider("Pazarlama & Şantiye Gideri (%)", min_value=0.0, max_value=15.0, value=hesaplanan_gider_orani, step=0.5)
        else:
            genel_gider_orani = hesaplanan_gider_orani
            st.sidebar.info(f"🤖 Otomatik Şantiye/Pazarlama Gideri: **%{genel_gider_orani:.1f}**")

        if ana_fonksiyon == "TİCARİ ALAN":
            yapi_kategorisi = "ticari"
            yapi_etiketi = "Ticari Ünite"
        else:
            yapi_kategorisi = "villa" if "Villa" in proje_tipi else "daire"
            yapi_etiketi = "Villa" if yapi_kategorisi == "villa" else "Daire"

        # --- ARSA VE İNŞAAT PAYI DAĞITIMI ---
        arsa_sahibi_payi_m2 = toplam_brut_insaat * (kat_karsiligi_oran / 100.0)
        yuklenici_payi_m2 = toplam_brut_insaat - arsa_sahibi_payi_m2

        arsa_sahibi_net_arsa_m2 = toplam_net_alan * (kat_karsiligi_oran / 100.0)
        yuklenici_net_arsa_m2 = toplam_net_alan - arsa_sahibi_net_arsa_m2

        if yapi_kategorisi == "villa":
            yuk_adet, yuk_brut_m2, yuk_havuz_m2, yuk_not = tam_otomatik_villa_mimarisi(yuklenici_payi_m2)
            arsa_adet, arsa_brut_m2, arsa_havuz_m2, arsa_not = tam_otomatik_villa_mimarisi(arsa_sahibi_payi_m2)
        else:
            hedef_daire_m2 = 120.0
            yuk_adet = max(1, math.floor(yuklenici_payi_m2 / hedef_daire_m2))
            yuk_brut_m2 = yuklenici_payi_m2 / yuk_adet
            yuk_havuz_m2 = 0.0
            yuk_not = "Standart Daire Konsepti"

            arsa_adet = max(1, math.floor(arsa_sahibi_payi_m2 / hedef_daire_m2))
            arsa_brut_m2 = arsa_sahibi_payi_m2 / arsa_adet
            arsa_havuz_m2 = 0.0
            arsa_not = "Standart Daire Konsepti"

        # --- FİNANSAL HESAPLAMALAR ---
        mahalle_veri = mahalle_piyasa_verisi_getir(otomatik_mahalle)[yapi_kategorisi]
        oto_maliyet_tl = mahalle_veri["maliyet"]
        oto_satis_tl = mahalle_veri["satis"]

        st.sidebar.subheader("📍 Piyasa Değerleri")
        ozel_giris_aktif = st.sidebar.checkbox("✏️ Özel Fiyat Girişi Yap", value=False)

        if ozel_giris_aktif:
            maliyet_m2 = st.sidebar.number_input(f"İnşaat Bp. Maliyeti ({para_birimi}/m²)", value=float(oto_maliyet_tl * kur_katsayisi), step=100.0)
            satis_m2 = st.sidebar.number_input(f"Tahmini Satış Fiyatı ({para_birimi}/m²)", value=float(oto_satis_tl * kur_katsayisi), step=500.0)
        else:
            maliyet_m2 = oto_maliyet_tl * kur_katsayisi
            satis_m2 = oto_satis_tl * kur_katsayisi

        toplam_insaat_maliyeti = toplam_brut_insaat * maliyet_m2
        pazarlama_operasyon_maliyet = toplam_insaat_maliyeti * (genel_gider_orani / 100.0)
        toplam_proje_maliyeti = toplam_insaat_maliyeti + pazarlama_operasyon_maliyet

        toplam_yuklenici_ciro = yuklenici_payi_m2 * satis_m2
        net_kar = toplam_yuklenici_ciro - toplam_proje_maliyeti
        roi = (net_kar / toplam_proje_maliyeti * 100) if toplam_proje_maliyeti > 0 else 0

        tab1, tab2, tab3 = st.tabs(["📊 Parsel & İmar Özeti", "📐 Kat Karşılığı & Mimari", "💵 Finansal Fizibilite"])

        with tab1:
            st.subheader(f"Konum: {otomatik_mahalle} Mahallesi | İmar: {ana_fonksiyon}")
            st.dataframe(df[['Mahalle', 'Ada', 'Parsel', 'Nitelik', 'Parsel_Alani', 'Hesaba_Alinan', 'Net_Alan', 'KAKS', 'Brut_Insaat']], use_container_width=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Toplam Arazi (m²)", fmt_tr(df['Parsel_Alani'].sum(), 2))
            c2.metric("Toplam Net Arazi (m²)", fmt_tr(toplam_net_alan, 2))
            c3.metric("Ortalama KAKS", f"{df['KAKS'].mean():.2f}")
            c4.metric("Toplam Brüt İnşaat (m²)", fmt_tr(toplam_brut_insaat, 2))

        with tab2:
            st.subheader("Kat Karşılığı & Anlaşma Dağıtım Modeli")
            st.info(f"🤝 Anlaşma Oranı (Kesin): **%{100-kat_karsiligi_oran} Müteahhit / %{kat_karsiligi_oran} Arsa Sahibi**")
            
            k1, k2 = st.columns(2)

            with k1:
                st.write(f"### 🏗️ Müteahhit Payı (%{100-kat_karsiligi_oran})")
                st.metric("Müteahhit Toplam İnşaat Alanı", f"{fmt_tr(yuklenici_payi_m2, 2)} m²")
                st.write(f"• **Net Arsa Payı:** **{fmt_tr(yuklenici_net_arsa_m2, 2)} m²**")
                st.success(f"**Otomatik Sonuç:** {yuk_adet} Adet {yapi_etiketi}")
                st.write(f"• Ünite Başı Brüt İnşaat: **{fmt_tr(yuk_brut_m2, 2)} m²**")
                if yapi_kategorisi == "villa":
                    st.write(f"• Taban Oturumu (2 Kat): **{fmt_tr(yuk_brut_m2 / 2, 2)} m²**")
                    st.write(f"• Otomatik Havuz Durumu: **{f'{yuk_adet} Adet ({fmt_tr(yuk_havuz_m2, 2)} m²)' if yuk_havuz_m2 > 0 else 'Havuzsuz'}**")
                    st.caption(f"🤖 *Yapay Zeka Kararı: {yuk_not}*")

            with k2:
                st.write(f"### 🏡 Arsa Sahibi Payı (%{kat_karsiligi_oran})")
                st.metric("Arsa Sahibi Toplam İnşaat Alanı", f"{fmt_tr(arsa_sahibi_payi_m2, 2)} m²")
                st.write(f"• **Net Arsa Payı:** **{fmt_tr(arsa_sahibi_net_arsa_m2, 2)} m²**")
                st.success(f"**Otomatik Sonuç:** {arsa_adet} Adet {yapi_etiketi}")
                st.write(f"• Ünite Başı Brüt İnşaat: **{fmt_tr(arsa_brut_m2, 2)} m²**")
                if yapi_kategorisi == "villa":
                    st.write(f"• Taban Oturumu (2 Kat): **{fmt_tr(arsa_brut_m2 / 2, 2)} m²**")
                    st.write(f"• Otomatik Havuz Durumu: **{f'{arsa_adet} Adet ({fmt_tr(arsa_havuz_m2, 2)} m²)' if arsa_havuz_m2 > 0 else 'Havuzsuz'}**")
                    st.caption(f"🤖 *Yapay Zeka Kararı: {arsa_not}*")

            st.markdown("---")
            st.caption(f"💡 *Sistem, net arsa alanını ve toplam inşaat alanını belirlenen kat karşılığı oranına göre tam yetkiyle hesaplayıp entegre eder.*")

        with tab3:
            st.subheader(f"Fizibilite Özeti ({para_birimi} Cinsinden)")

            f1, f2, f3 = st.columns(3)
            f1.metric("Toplam Proje Maliyeti", fmt_tr(toplam_proje_maliyeti, 0, para_birimi))
            f2.metric("Müteahhit Satış Cirosu", fmt_tr(toplam_yuklenici_ciro, 0, para_birimi))
            f3.metric("Net Kar", fmt_tr(net_kar, 0, para_birimi), delta=f"%{roi:.1f} ROI")

            st.markdown("---")
            fizibilite_data = {
                "Kalem": [
                    f"Birim İnşaat Maliyeti ({yapi_etiketi})",
                    f"Pazarlama ve Şantiye Giderleri (%{genel_gider_orani:.1f})",
                    "Toplam Yatırım Maliyeti",
                    "Yükleniciye Kalan Brüt Satış Alanı",
                    f"Hesaplanan Toplam Ciro ({yapi_etiketi})",
                    "Net Proje Karı"
                ],
                "Tutar / Değer": [
                    f"{fmt_tr(toplam_insaat_maliyeti, 0, para_birimi)} ({fmt_tr(maliyet_m2, 0, para_birimi)}/m²)",
                    f"{fmt_tr(pazarlama_operasyon_maliyet, 0, para_birimi)}",
                    f"{fmt_tr(toplam_proje_maliyeti, 0, para_birimi)}",
                    f"{fmt_tr(yuklenici_payi_m2, 2)} m² ({yuk_adet} Adet)",
                    f"{fmt_tr(toplam_yuklenici_ciro, 0, para_birimi)} ({fmt_tr(satis_m2, 0, para_birimi)}/m²)",
                    f"{fmt_tr(net_kar, 0, para_birimi)}"
                ]
            }
            st.table(pd.DataFrame(fizibilite_data))

else:
    st.info("👆 Lütfen analiz yapmak istediğiniz imar raporu PDF dosyalarını yükleyin.")
