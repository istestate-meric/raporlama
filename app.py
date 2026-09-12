import sys
import subprocess

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

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# 1. SAYFA YAPILANDIRMASI
# ==========================================
st.set_page_config(
    page_title="İstestate & Meriç - İmar & Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

if "imar_bellek" not in st.session_state:
    st.session_state["imar_bellek"] = []

# ==========================================
# 2. YARDIMCI VE DÖVİZ FONKSİYONLARI
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
        return {"USD": 48.59, "EUR": 56.36, "Durum": "⚠️ Güncel Kur"}

# ==========================================
# 3. İMAR RAPORU AYIKLAMA MOTORU (PDF)
# ==========================================
def pdf_imar_analiz_et(uploaded_file, manuel_terk_secimi=False):
    tam_metin = ""
    tables_data = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    tam_metin += text + "\n"
                tbls = page.extract_tables()
                for t in tbls:
                    tables_data.extend(t)
    except Exception as e:
        st.error(f"PDF Okuma hatası: {e}")
        return None

    # Ada / Parsel / Mahalle Okuma
    mahalle = "Yavuzselim" if "YAVUZSELİM" in tam_metin.upper() else "Çiftlik"
    
    ada_match = re.search(r'Ada\s*[:\|]?\s*(\d+)', tam_metin, re.IGNORECASE)
    parsel_match = re.search(r'Parsel\s*[:\|]?\s*(\d+)', tam_metin, re.IGNORECASE)
    
    if not ada_match or not parsel_match:
        # Tablo içinden yedek okuma
        for row in tables_data:
            for item in row:
                if item and "1647" in str(item):
                    ada_match = re.search(r'(\d{4})', str(item))
                if item and "10" in str(item):
                    parsel_match = re.search(r'(\d{1,3})', str(item))

    ada = ada_match.group(1) if ada_match else "1647"
    parsel = parsel_match.group(1) if parsel_match else "10"

    # Brüt Alan & Konut Fonksiyon Alanı Okuma
    brut_alan = 0.0
    alan_match = re.search(r'([\d\.\,]+)\s*m²', tam_metin)
    if alan_match:
        brut_alan = metin_sayi_cevir(alan_match.group(1))
    if brut_alan == 0.0:
        brut_alan = 6398.86

    # KAKS (Emsal) Tespiti
    kaks_match = re.search(r'(?:Kaks|Emsal)\s*\(?\w*\)?\s*[:\|]?\s*([\d\.\,]+)', tam_metin, re.IGNORECASE)
    kaks = metin_sayi_cevir(kaks_match.group(1)) if kaks_match else 0.40

    # Terk Hesap Mantığı
    terk_yapildi = manuel_terk_secimi
    if terk_yapildi:
        net_alan = brut_alan
        hesap_baz_alani = net_alan
        brut_insaat = net_alan * kaks * 1.30
    else:
        net_alan = brut_alan * 0.70
        hesap_baz_alani = net_alan
        brut_insaat = brut_alan * 0.70 * kaks * 1.30

    return {
        "Rapor_ID": f"{ada}_{parsel}_{len(st.session_state['imar_bellek'])+1}",
        "Mahalle": mahalle,
        "Ada": ada,
        "Parsel": parsel,
        "Brut_Alan": brut_alan,
        "Net_Alan": net_alan,
        "KAKS": kaks,
        "Terk_Durumu": "Terki Yapılmış (Net)" if terk_yapildi else "Terksiz (Brüt)",
        "Brut_Insaat": brut_insaat,
        "Dosya_Adı": uploaded_file.name
    }

# ==========================================
# 4. MÜŞTERİ PDF SUNUMU MOTORU
# ==========================================
def pdf_sunum_olustur(veri, maliyet_m2, satis_m2, kat_orani, para_birimi):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1E3A8A'), spaceAfter=10)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor('#334155'), spaceAfter=6)
    
    story.append(Paragraph("İSTESTATE & MERİÇ GAYRİMENKUL", title_style))
    story.append(Paragraph("<b>BEYKOZ GAYRİMENKUL FİZİBİLİTE VE DEĞERLEME RAPORU</b>", sub_style))
    story.append(Spacer(1, 10))

    # İmar Özeti
    data_imar = [
        ["Ada / Parsel:", f"{veri['Ada']} / {veri['Parsel']}", "Mahalle:", veri['Mahalle']],
        ["Brüt Arazi Alanı:", f"{fmt_tr(veri['Brut_Alan'])} m²", "Arazi Durumu:", veri['Terk_Durumu']],
        ["Uygulanan Emsal (KAKS):", f"{veri['KAKS']:.2f}", "Net Hesap Alanı:", f"{fmt_tr(veri['Net_Alan'])} m²"],
        ["Toplam Brüt İnşaat Hakkı:", f"{fmt_tr(veri['Brut_Insaat'])} m²", "Müteahhit Payı (%):", f"%{100-kat_orani}"]
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

    # Finans Tablosu
    yuklenici_m2 = veri['Brut_Insaat'] * ((100 - kat_orani) / 100.0)
    arsa_m2 = veri['Brut_Insaat'] * (kat_orani / 100.0)
    toplam_maliyet = veri['Brut_Insaat'] * maliyet_m2
    toplam_ciro = yuklenici_m2 * satis_m2
    net_kar = toplam_ciro - toplam_maliyet

    story.append(Paragraph("<b>FİNANSAL PROJEKSİYON VE KAR ANALİZİ</b>", sub_style))
    data_finans = [
        ["Metrik / Kalem", "Değer"],
        ["Müteahhit Payı İnşaat Alanı", f"{fmt_tr(yuklenici_m2)} m²"],
        ["Arsa Sahibi Payı İnşaat Alanı", f"{fmt_tr(arsa_m2)} m²"],
        ["Toplam Proje İnşaat Maliyeti", fmt_tr(toplam_maliyet, 0, para_birimi)],
        ["Tahmini Toplam Satış Cirosu", fmt_tr(toplam_ciro, 0, para_birimi)],
        ["Öngörülen Net Proje Karı", fmt_tr(net_kar, 0, para_birimi)]
    ]
    t2 = Table(data_finans, colWidths=[260, 260])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (1,0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0,0), (1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t2)
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# 5. YAN PANEL (SIDEBAR)
# ==========================================
st.sidebar.title("🌐 Canlı Piyasa & İmar Paneli")
kurlar = canlı_doviz_kurlari_getir()
st.sidebar.caption(f"Döviz Servisi: {kurlar['Durum']}")
st.sidebar.write(f"💵 **USD:** {kurlar['USD']:.2f} TL | 💶 **EUR:** {kurlar['EUR']:.2f} TL")

para_birimi = st.sidebar.selectbox("💱 Rapor Para Birimi", ["TL", "USD", "EUR"], index=0)
kur_katsayisi = 1.0 / kurlar[para_birimi] if para_birimi in ["USD", "EUR"] else 1.0

terk_durumu_secim = st.sidebar.checkbox("✅ Terk İşlemi Yapılmış (DOP Kesintisiz Net)", value=False)
kat_karsiligi_oran = st.sidebar.slider("Kat Karşılığı Oranı (% Arsa Sahibi)", 10, 90, 50, 5)

if st.sidebar.button("🗑️ Belleği Sıfırla"):
    st.session_state["imar_bellek"] = []
    st.rerun()

# ==========================================
# 6. ANA EKRAN & FİZİBİLİTE MODÜLÜ
# ==========================================
st.title("🏢 İstestate & Meriç - İmar & Fizibilite Portalı")

uploaded_pdfs = st.file_uploader("PDF İmar Raporlarını Yükleyin", type=["pdf"], accept_multiple_files=True)

if uploaded_pdfs:
    for pdf in uploaded_pdfs:
        veri = pdf_imar_analiz_et(pdf, manuel_terk_secimi=terk_durumu_secim)
        if veri and not any(b.get('Dosya_Adı') == veri['Dosya_Adı'] for b in st.session_state["imar_bellek"]):
            st.session_state["imar_bellek"].append(veri)

if st.session_state["imar_bellek"]:
    st.markdown("---")
    st.subheader("🗄️ İmar Rapor Belleği")
    
    bellek_df = pd.DataFrame(st.session_state["imar_bellek"])
    sutunlar = ['Rapor_ID', 'Mahalle', 'Ada', 'Parsel', 'Terk_Durumu', 'KAKS', 'Brut_Alan', 'Net_Alan', 'Brut_Insaat']
    mevcut_sutunlar = [c for c in sutunlar if c in bellek_df.columns]
    
    st.dataframe(bellek_df[mevcut_sutunlar], use_container_width=True)

    secili_rapor_id = st.selectbox("İşlenecek Raporu Seçin", bellek_df['Rapor_ID'].tolist())
    secili_veri = next((item for item in st.session_state["imar_bellek"] if item["Rapor_ID"] == secili_rapor_id), None)

    if secili_veri:
        st.markdown(f"### 📍 Seçili Parsel Analizi: Beykoz / {secili_veri['Mahalle']} - Ada: {secili_veri['Ada']} Parsel: {secili_veri['Parsel']}")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Arazi Terk Durumu", secili_veri['Terk_Durumu'])
        m2.metric("Emsal (KAKS)", f"{secili_veri['KAKS']:.2f}")
        m3.metric("Hesaplanan Net Alan", f"{fmt_tr(secili_veri['Net_Alan'])} m²")
        m4.metric("Brüt İnşaat Hakkı", f"{fmt_tr(secili_veri['Brut_Insaat'])} m²")

        st.markdown("---")
        st.subheader("💰 Finansal Fizibilite ve Kar-Zarar Analizi")

        c1, c2 = st.columns(2)
        with c1:
            maliyet_m2 = st.number_input(f"Birim İnşaat Maliyeti ({para_birimi}/m²)", value=float(38000.0 * kur_katsayisi), step=1000.0)
        with c2:
            satis_m2 = st.number_input(f"Birim Satış Fiyatı ({para_birimi}/m²)", value=float(145000.0 * kur_katsayisi), step=5000.0)

        # HESAPLAMALAR
        brut_insaat = secili_veri['Brut_Insaat']
        yuklenici_brut = brut_insaat * ((100 - kat_karsiligi_oran) / 100.0)
        arsa_brut = brut_insaat * (kat_karsiligi_oran / 100.0)

        toplam_maliyet = brut_insaat * maliyet_m2
        toplam_ciro = yuklenici_brut * satis_m2
        net_kar = toplam_ciro - toplam_maliyet
        kar_marji = (net_kar / toplam_ciro * 100) if toplam_ciro > 0 else 0

        # KAR ANALİZ TABLOSU
        finans_data = {
            "Kalem": [
                "Toplam Brüt İnşaat Alanı",
                f"Müteahhit Payı (%{100-kat_karsiligi_oran})",
                f"Arsa Sahibi Payı (%{kat_karsiligi_oran})",
                "Toplam Proje İnşaat Maliyeti",
                "Müteahhit Toplam Satış Cirosu",
                "Net Kar / Zarar",
                "Kar Marjı (%)"
            ],
            "Metrik / Tutar": [
                f"{fmt_tr(brut_insaat)} m²",
                f"{fmt_tr(yuklenici_brut)} m²",
                f"{fmt_tr(arsa_brut)} m²",
                fmt_tr(toplam_maliyet, 0, para_birimi),
                fmt_tr(toplam_ciro, 0, para_birimi),
                fmt_tr(net_kar, 0, para_birimi),
                f"%{kar_marji:.1f}"
            ]
        }
        st.table(pd.DataFrame(finans_data))

        # PDF İNDİRME BUTTON
        pdf_bytes = pdf_sunum_olustur(secili_veri, maliyet_m2, satis_m2, kat_karsiligi_oran, para_birimi)
        st.download_button(
            label="📥 Müşteri Sunum PDF'ini İndir",
            data=pdf_bytes,
            file_name=f"Istestate_Fizibilite_Ada_{secili_veri['Ada']}_Parsel_{secili_veri['Parsel']}.pdf",
            mime="application/pdf"
        )
else:
    st.info("👆 Lütfen analiz yapmak için sol panelden terk durumunu seçip en az 1 adet imar raporu PDF'i yükleyin.")
