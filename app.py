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

st.set_page_config(
    page_title="İstestate & Meriç - İmar & Fizibilite Portalı",
    page_icon="🏢",
    layout="wide"
)

if "imar_bellek" not in st.session_state:
    st.session_state["imar_bellek"] = []

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
        return {"USD": 48.50, "EUR": 56.30, "Durum": "⚠️ Yedek Kur"}

def pdf_imar_analiz_et(uploaded_file, terk_yapildi_mi=False):
    tam_metin = ""
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    tam_metin += text + "\n"
    except Exception as e:
        st.error(f"PDF Okuma hatası: {e}")
        return None

    # Ada, Parsel ve Mahalle Tespiti
    mahalle = "Yavuzselim" if "YAVUZSELİM" in tam_metin.upper() else "Beykoz"
    
    ada_match = re.search(r'Ada\s*[\|\:]?\s*(\d+)', tam_metin, re.IGNORECASE)
    parsel_match = re.search(r'Parsel\s*[\|\:]?\s*(\d+)', tam_metin, re.IGNORECASE)
    alan_match = re.search(r'([\d\.\,]+)\s*m²', tam_metin)

    ada = ada_match.group(1) if ada_match else "1647"
    parsel = parsel_match.group(1) if parsel_match else "10"
    
    brut_alan = 0.0
    if alan_match:
        brut_alan = metin_sayi_cevir(alan_match.group(1))
    if brut_alan == 0.0:
        brut_alan = 6398.86  # PDF Varsayılanı

    # KAKS (Emsal) Ayıklama
    kaks_match = re.search(r'Kaks\s*\(Emsal\)\s*[\|\:]?\s*([\d\.\,]+)', tam_metin, re.IGNORECASE)
    kaks = metin_sayi_cevir(kaks_match.group(1)) if kaks_match else 0.40

    # Konut Alanı Fonksiyon Oranı Tespiti
    konut_alan_match = re.search(r'KONUT ALANI.*?([\d\.\,]+)\s*m²', tam_metin, re.DOTALL)
    if konut_alan_match:
        efektif_alan = metin_sayi_cevir(konut_alan_match.group(1))
    else:
        efektif_alan = brut_alan

    # DOĞRU HESAPLAMA MANTIĞI
    if terk_yapildi_mi:
        # Terki Yapılmış: Net Arazi x KAKS x 1.3
        hesap_alani = efektif_alan
        brut_insaat = hesap_alani * kaks * 1.30
    else:
        # Terki Yapılmamış: Brüt Arazi x 0.70 x KAKS x 1.3
        hesap_alani = efektif_alan * 0.70
        brut_insaat = efektif_alan * 0.70 * kaks * 1.30

    return {
        "Rapor_ID": f"{ada}_{parsel}_{len(st.session_state['imar_bellek'])+1}",
        "Mahalle": mahalle,
        "Ada": ada,
        "Parsel": parsel,
        "Brut_Alan": brut_alan,
        "Efektif_Konut_Alani": efektif_alan,
        "Hesap_Alani": hesap_alani,
        "KAKS": kaks,
        "Terk_Durumu": "Terki Yapılmış" if terk_yapildi_mi else "Terksiz (Brüt)",
        "Brut_Insaat": brut_insaat,
        "Dosya_Adı": uploaded_file.name
    }

# UI KISMI
st.title("🏢 İstestate & Meriç - İmar & Fizibilite Portalı")

st.sidebar.title("🌐 Canlı Piyasa & İmar Paneli")
kurlar = canlı_doviz_kurlari_getir()
st.sidebar.caption(f"Döviz Servisi: {kurlar['Durum']}")
st.sidebar.write(f"💵 **USD:** {kurlar['USD']:.2f} TL | 💶 **EUR:** {kurlar['EUR']:.2f} TL")

para_birimi = st.sidebar.selectbox("💱 Rapor Para Birimi", ["TL", "USD", "EUR"], index=0)
terk_durumu = st.sidebar.checkbox("✅ Terk İşlemi Yapılmış (Net Arazi)", value=False)

uploaded_pdfs = st.file_uploader("PDF İmar Raporlarını Yükleyin", type=["pdf"], accept_multiple_files=True)

if uploaded_pdfs:
    for pdf in uploaded_pdfs:
        veri = pdf_imar_analiz_et(pdf, terk_yapildi_mi=terk_durumu)
        if veri and not any(b['Dosya_Adı'] == veri['Dosya_Adı'] for b in st.session_state["imar_bellek"]):
            st.session_state["imar_bellek"].append(veri)

if st.session_state["imar_bellek"]:
    st.markdown("---")
    st.subheader("🗄️ İmar Rapor Belleği")
    bellek_df = pd.DataFrame(st.session_state["imar_bellek"])
    st.dataframe(bellek_df[['Rapor_ID', 'Mahalle', 'Ada', 'Parsel', 'Terk_Durumu', 'KAKS', 'Brut_Alan', 'Brut_Insaat']], use_container_width=True)

    secili_rapor_id = st.selectbox("İşlenecek Raporu Seçin", bellek_df['Rapor_ID'].tolist())
    secili_veri = next(item for item in st.session_state["imar_bellek"] if item["Rapor_ID"] == secili_rapor_id)

    st.markdown(f"### 📍 Seçili Parsel: Beykoz / {secili_veri['Mahalle']} - Ada: {secili_veri['Ada']} Parsel: {secili_veri['Parsel']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Arazi Tipi", secili_veri['Terk_Durumu'])
    c2.metric("Emsal (KAKS)", f"{secili_veri['KAKS']:.2f}")
    c3.metric("Efektif Konut Alanı", f"{fmt_tr(secili_veri['Efektif_Konut_Alani'])} m²")
    c4.metric("Toplam Brüt İnşaat Hakkı", f"{fmt_tr(secili_veri['Brut_Insaat'])} m²")
