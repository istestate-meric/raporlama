import sys
import subprocess

# Eksik kütüphaneleri otomatik yükleme mekanizması
try:
    import reportlab
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab", "pdfplumber"])
    import reportlab

import os
import re
import math
import io
import pandas as pd
import pdfplumber
import requests
import xml.etree.ElementTree as ET
import streamlit as st

# PDF Oluşturma Kütüphaneleri (Müşteri Sunumu İçin)
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# 1. SAYFA YAPILANDIRMASI & CORE AYARLAR
# ==========================================
st.set_page_config(
    page_title="İstestate & Meriç - İmar & Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

# OTURUM BELLEĞİ (MEMORY STATE) BAŞLATMA
if "imar_bellek" not in st.session_state:
    st.session_state["imar_bellek"] = []

# Parsel Veritabanı (Örnek Özel KAKS/Kuşak Haritası)
PARSEL_VERITABANI = {
    "13": {"Nitelik": "Bahçe", "Alan": 2131.58, "Net_Alan": 1593.16, "Kusagı": "Göl Koruma Alanı", "KAKS": 0.30},
    "14": {"Nitelik": "Bahçe", "Alan": 2001.35, "Net_Alan": 1414.76, "Kusagı": "Kontrollü Kullanım Bölgesi", "KAKS": 0.20},
    "15": {"Nitelik": "Bahçe", "Alan": 2174.82, "Net_Alan": 1544.42, "Kusagı": "Yakın Mesafe Koruma Alanı", "KAKS": 0.40},
    "16": {"Nitelik": "Bahçe", "Alan": 6058.42, "Net_Alan": 4075.16, "Kusagı": "Uzak Mesafe Koruma Alanı", "KAKS": 0.45},
    "29": {"Nitelik": "Arsa",  "Alan": 4618.21, "Net_Alan": 3068.47, "Kusagı": "Göl Koruma Alanı", "KAKS": 0.30}
}

BEYKOZ_MAHALLELERI = [
    "Çiftlik", "Acarlar", "Görele", "Rüzgarlıbahçe", "Kavacık", 
    "Çengeldere", "Yavuztürk", "Baklacı", "Fatih", "Yavuzselim"
]

# ==========================================
# 2. YARDIMCI VE CANLI VERİ FONKSİYONLARI
# ==========================================
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

@st.cache_data(ttl=300)
def canlı_doviz_kurlari_getir():
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        usd = float(root.find("./Currency[@CurrencyCode='USD']/BanknoteSelling").text)
        eur = float(root.find("./Currency[@CurrencyCode='EUR']/BanknoteSelling").text)
        return {"USD": usd, "EUR": eur, "Durum": "✅ Canlı (TCMB)"}
    except Exception:
        return {"USD": 38.50, "EUR": 41.20, "Durum": "⚠️ Yedek Kur"}

# ==========================================
# 3. İMAR VE DİNAMİK KAKS MOTORU
# ==========================================
def dinamik_kaks_ve_kusak_belirle(tam_metin, parsel_no, secilen_kusak):
    """Metin veya Parsel Veritabanından Dinamik KAKS Analizi"""
    if "KONTROLLÜ" in tam_metin.upper():
        return 0.20, 0.20, "Kontrollü Kullanım Bölgesi"
    elif "YAKIN MESAFE" in tam_metin.upper():
        return 0.30, 0.40, "Yakın Mesafe Koruma Alanı"
    elif "UZAK MESAFE" in tam_metin.upper():
        return 0.30, 0.45, "Uzak Mesafe Koruma Alanı"

    p_info = PARSEL_VERITABANI.get(str(parsel_no))
    if p_info:
        return 0.30, p_info["KAKS"], p_info["Kusagı"]

    kusak_map = {
        "Kontrollü Kullanım Bölgesi": (0.20, 0.20),
        "Göl Koruma Alanı": (0.30, 0.30),
        "Yakın Mesafe Koruma Alanı": (0.30, 0.40),
        "Uzak Mesafe Koruma Alanı": (0.30, 0.45)
    }
    taks, kaks = kusak_map.get(secilen_kusak, (0.30, 0.30))
    return taks, kaks, secilen_kusak

def tek_pdf_analiz_et(uploaded_file, varsayilan_kusak="Göl Koruma Alanı", yesil_kusaklama=False):
    mahalle = "Çiftlik"
    ada, parsel = "Bilinmiyor", "Bilinmiyor"
    tam_metin = ""

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    tam_metin += text + "\n"
    except Exception as e:
        st.error(f"PDF Okuma hatası ({uploaded_file.name}): {e}")
        return None

    metin_tum = re.sub(r'\s+', ' ', tam_metin)
    match_parsel = re.search(r'(\d+)\s+(\d+)\s+([\d.,]+)\s*m²', metin_tum)
    
    rapor_alani = 0.0
    if match_parsel:
        ada = match_parsel.group(1)
        parsel = match_parsel.group(2)
        rapor_alani = metin_sayi_cevir(match_parsel.group(3))

    taks_val, kaks_val, tespit_edilen_kusak = dinamik_kaks_ve_kusak_belirle(tam_metin, parsel, varsayilan_kusak)

    p_info = PARSEL_VERITABANI.get(str(parsel), None)
    if p_info:
        nitelik = p_info["Nitelik"]
        parsel_alani = p_info["Alan"]
        net_alan = p_info["Net_Alan"]
    else:
        nitelik = "Bahçe"
        parsel_alani = rapor_alani if rapor_alani > 0 else 1000.0
        net_alan = parsel_alani * 0.70

    hesaba_alinan = parsel_alani if yesil_kusaklama else parsel_alani * 0.70
    net_insaat = hesaba_alinan * kaks_val
    brut_insaat = net_insaat * 1.30

    veri = {
        "Rapor_ID": f"{ada}_{parsel}_{len(st.session_state['imar_bellek'])+1}",
        "Mahalle": mahalle,
        "Ada": str(ada),
        "Parsel": str(parsel),
        "Nitelik": nitelik,
        "Kuşak": tespit_edilen_kusak,
        "Parsel_Alani": parsel_alani,
        "Hesaba_Alinan": hesaba_alinan,
        "Net_Alan": net_alan,
        "TAKS": taks_val,
        "KAKS": kaks_val,
        "Brut_Insaat": brut_insaat,
        "Dosya_Adı": uploaded_file.name
    }
    return veri

# ==========================================
# 4. SUNUM PDF ÇIKTI MOTORU (REPORTLAB)
# ==========================================
def pdf_sunum_olustur(veri_dict, proje_tipi, sunum_turu, para_birimi):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1E3A8A'), spaceAfter=12)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#475569'), spaceAfter=8)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=10, leading=14)

    story.append(Paragraph("İSTESTATE & MERİÇ GAYRİMENKUL", title_style))
    story.append(Paragraph(f"<b>GAYRİMENKUL DEĞERLEME VE FİZİBİLİTE SUNUMU</b> ({sunum_turu.upper()})", sub_style))
    story.append(Spacer(1, 10))

    # Tablo 1: Parsel ve İmar
    data_imar = [
        ["Ada / Parsel:", f"{veri_dict['Ada']} / {veri_dict['Parsel']}", "Mahalle:", veri_dict['Mahalle']],
        ["Parsel Alanı:", f"{fmt_tr(veri_dict['Parsel_Alani'])} m²", "Net Arazi Alanı:", f"{fmt_tr(veri_dict['Net_Alan'])} m²"],
        ["Koruma Kuşağı:", veri_dict['Kuşak'], "Uygulanan KAKS:", f"{veri_dict['KAKS']:.2f}"],
        ["Toplam Brüt İnşaat:", f"{fmt_tr(veri_dict['Brut_Insaat'])} m²", "Proje Konsepti:", proje_tipi]
    ]
    t1 = Table(data_imar, colWidths=[120, 140, 120, 140])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t1)
    story.append(Spacer(1, 15))

    # Finansal Özet
    story.append(Paragraph("<b>FINANSAL VE MİMARİ ANALİZ ÖZETİ</b>", sub_style))
    data_finans = [
        ["Finansal Kalem", "Değer / Tutar"],
        ["Müteahhit Payı Brüt İnşaat", f"{fmt_tr(veri_dict['Yuklenici_Brut'])} m²"],
        ["Arsa Sahibi Payı Brüt İnşaat", f"{fmt_tr(veri_dict['Arsa_Brut'])} m²"],
        ["Tahmini Toplam İnşaat Maliyeti", fmt_tr(veri_dict['Toplam_Maliyet'], 0, para_birimi)],
        ["Tahmini Satış Cirosu (Müteahhit)", fmt_tr(veri_dict['Toplam_Ciro'], 0, para_birimi)],
        ["Net Kar Beklentisi", fmt_tr(veri_dict['Net_Kar'], 0, para_birimi)]
    ]
    t2 = Table(data_finans, colWidths=[260, 260])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (1,0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0,0), (1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t2)
    
    story.append(Spacer(1, 20))
    story.append(Paragraph("<i>Bu rapor İstestate & Meriç Gayrimenkul fizibilite motoru tarafından anlık piyasa verileri ile üretilmiştir.</i>", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# 5. SIDEBAR VE CANLI DÖVİZ PANELİ
# ==========================================
st.sidebar.title("🌐 Canlı Piyasa & İmar Paneli")

kurlar = canlı_doviz_kurlari_getir()
st.sidebar.caption(f"Döviz Servisi: {kurlar['Durum']}")
st.sidebar.write(f"💵 **USD:** {kurlar['USD']:.2f} TL | 💶 **EUR:** {kurlar['EUR']:.2f} TL")

para_birimi = st.sidebar.selectbox("💱 Rapor Para Birimi", ["TL", "USD", "EUR"], index=0)
kur_katsayisi = 1.0 / kurlar[para_birimi] if para_birimi in ["USD", "EUR"] else 1.0

st.sidebar.markdown("---")
st.sidebar.subheader("📜 İmar Koruma Kuşağı (Yedek)")
koruma_kusagi_secim = st.sidebar.selectbox(
    "Varsayılan Kuşak (PDF'ten Çekilemezse)",
    ["Göl Koruma Alanı", "Kontrollü Kullanım Bölgesi", "Yakın Mesafe Koruma Alanı", "Uzak Mesafe Koruma Alanı"]
)

yesil_kusaklama = st.sidebar.checkbox("🌿 Göl Yeşil Kuşaklama (%30 DOP İstisnası)")
kat_karsiligi_oran = st.sidebar.slider("Kat Karşılığı Oranı (%)", 10, 90, 50, 1)

# ==========================================
# 6. ANA EKRAN & BELLEK YÖNETİMİ
# ==========================================
st.title("🏢 Beykoz İmar Analizi ve Fizibilite Portalı")

uploaded_pdfs = st.file_uploader("PDF İmar Raporlarını Yükleyin", type=["pdf"], accept_multiple_files=True)

if uploaded_pdfs:
    for pdf in uploaded_pdfs:
        veri = tek_pdf_analiz_et(pdf, varsayilan_kusak=koruma_kusagi_secim, yesil_kusaklama=yesil_kusaklama)
        if veri:
            if not any(b['Dosya_Adı'] == veri['Dosya_Adı'] for b in st.session_state["imar_bellek"]):
                st.session_state["imar_bellek"].append(veri)

# HAS IMAR BELLEK PANELİ
if st.session_state["imar_bellek"]:
    st.markdown("---")
    st.subheader("🗄️ İmar Rapor Belleği (Oturumda Kayıtlı Raporlar)")
    
    bellek_df = pd.DataFrame(st.session_state["imar_bellek"])
    st.dataframe(bellek_df[['Rapor_ID', 'Mahalle', 'Ada', 'Parsel', 'Kuşak', 'KAKS', 'Parsel_Alani', 'Brut_Insaat']], use_container_width=True)

    secili_rapor_id = st.selectbox("Bellekten İşlenecek Raporu Seçin", bellek_df['Rapor_ID'].tolist())
    secili_veri = next(item for item in st.session_state["imar_bellek"] if item["Rapor_ID"] == secili_rapor_id)

    # SECİLİ RAPOR FİZİBİLİTESİ
    st.markdown("---")
    st.subheader(f"📍 Seçili Parsel Analizi: Beykoz / {secili_veri['Mahalle']} - Ada: {secili_veri['Ada']} Parsel: {secili_veri['Parsel']}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tespit Edilen Kuşak", secili_veri['Kuşak'])
    c2.metric("Dinamik KAKS Oranı", f"{secili_veri['KAKS']:.2f}")
    c3.metric("Parsel Alanı", f"{fmt_tr(secili_veri['Parsel_Alani'])} m²")
    c4.metric("Brüt İnşaat Hakkı", f"{fmt_tr(secili_veri['Brut_Insaat'])} m²")

    # Fiyatlandırma
    st.sidebar.markdown("---")
    maliyet_m2 = st.sidebar.number_input(f"İnşaat Maliyeti ({para_birimi}/m²)", value=38000.0 * kur_katsayisi)
    satis_m2 = st.sidebar.number_input(f"Satış Fiyatı ({para_birimi}/m²)", value=145000.0 * kur_katsayisi)

    # Hesaplamaları tamamlama
    brut_insaat = secili_veri['Brut_Insaat']
    yuklenici_brut = brut_insaat * ((100 - kat_karsiligi_oran) / 100.0)
    arsa_brut = brut_insaat * (kat_karsiligi_oran / 100.0)

    toplam_maliyet = brut_insaat * maliyet_m2
    toplam_ciro = yuklenici_brut * satis_m2
    net_kar = toplam_ciro - toplam_maliyet

    # Veri paketini sunum için hazırlama
    secili_veri['Yuklenici_Brut'] = yuklenici_brut
    secili_veri['Arsa_Brut'] = arsa_brut
    secili_veri['Toplam_Maliyet'] = toplam_maliyet
    secili_veri['Toplam_Ciro'] = toplam_ciro
    secili_veri['Net_Kar'] = net_kar

    # SUNUM PDF İNDİRME ALANI
    st.markdown("### 📄 Müşteri Sunum Dosyası (PDF)")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        sunum_turu = st.radio("Sunum Konsepti", ["Kat Karşılığı Teklif Sunumu", "Satılık Portföy Sunumu"])
    with col_p2:
        pdf_bytes = pdf_sunum_olustur(secili_veri, "Villa Projesi", sunum_turu, para_birimi)
        st.download_button(
            label="📥 Müşteri Sunum PDF'ini İndir",
            data=pdf_bytes,
            file_name=f"Istestate_Sunum_Ada_{secili_veri['Ada']}_Parsel_{secili_veri['Parsel']}.pdf",
            mime="application/pdf"
        )

else:
    st.info("👆 Analiz başlatmak ve belleğe kaydetmek için lütfen en az 1 adet PDF imar raporu yükleyin.")
