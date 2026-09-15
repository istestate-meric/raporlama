import re
import pdfplumber
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Meriç & İstestate | İmar Durumu ve Fizibilite Otomasyonu",
    layout="wide",
)


def parse_imar_durumu_gelismis(pdf_file):
  parsed_data = {
      "mahalle": None,
      "ada": None,
      "parsel": None,
      "tapu_alani": 0.0,
      "fonksiyonlar": [],
  }

  full_text = ""

  with pdfplumber.open(pdf_file) as pdf:
    for page in pdf.pages:
      text = page.extract_text()
      if text:
        full_text += text + "\n"

  # 1. Temel Parsel Bilgileri
  mahalle_match = re.search(
      r"Mahalle\s*[:\-]?\s*([A-ZÇĞİÖŞÜ\s]+)", full_text, re.IGNORECASE
  )
  ada_match = re.search(r"Ada\s*[:\-]?\s*(\d+)", full_text)
  parsel_match = re.search(r"Parsel\s*[:\-]?\s*(\d+)", full_text)
  alan_match = re.search(r"Alan\s*\*?\s*[:\-]?\s*([\d,\.]+)\s*m²", full_text)

  if mahalle_match:
    parsed_data["mahalle"] = mahalle_match.group(1).strip()
  if ada_match:
    parsed_data["ada"] = ada_match.group(1)
  if parsel_match:
    parsed_data["parsel"] = parsel_match.group(1)
  if alan_match:
    parsed_data["tapu_alani"] = float(
        alan_match.group(1).replace(".", "").replace(",", ".")
    )

  # 2. Fonksiyon Bazlı Yapılaşma Şartları Analizi
  bloklar = re.split(r"Fonksiyon\s*Adı", full_text, flags=re.IGNORECASE)

  for blok in bloklar[1:]:
    fonk_info = {}
    satirlar = [s.strip() for s in blok.split("\n") if s.strip()]

    if not satirlar:
      continue

    fonk_adi_aday = satirlar[0].replace(":", "").strip()
    fonk_info["fonksiyon_adi"] = fonk_adi_aday

    blok_metni = " ".join(satirlar)

    # Kat Adedi (Tire ve boşluk yönetimi)
    kat_match = re.search(
        r"Kat\s*Adedi\s*[:\-]?\s*([-\d]+)", blok_metni, re.IGNORECASE
    )
    if kat_match:
      val = kat_match.group(1).strip()
      fonk_info["kat_adedi"] = None if val in ["-", ""] else int(val)
    else:
      fonk_info["kat_adedi"] = None

    # Yençok (m)
    yencok_match = re.search(
        r"Yençok\s*\(m\)\s*[:\-]?\s*([-\d,\.]+)", blok_metni, re.IGNORECASE
    )
    if yencok_match:
      val = yencok_match.group(1).strip()
      fonk_info["yencok_m"] = (
          None if val in ["-", ""] else float(val.replace(",", "."))
      )
    else:
      fonk_info["yencok_m"] = None

    # Taks ve Kaks
    taks_match = re.search(r"Taks\s*[:\-]?\s*([\d,\.-]+)", blok_metni, re.IGNORECASE)
    kaks_match = re.search(
        r"(?:Kaks|Emsal)\s*[:\-]?\s*([\d,\.-]+)", blok_metni, re.IGNORECASE
    )

    if taks_match:
      t_val = taks_match.group(1).strip()
      fonk_info["taks"] = (
          0.0 if t_val in ["-", "0.00", "0", ""] else float(t_val.replace(",", "."))
      )
    else:
      fonk_info["taks"] = 0.0

    if kaks_match:
      k_val = kaks_match.group(1).strip()
      fonk_info["kaks"] = (
          0.0 if k_val in ["-", "0.00", "0", ""] else float(k_val.replace(",", "."))
      )
    else:
      fonk_info["kaks"] = 0.0

    parsed_data["fonksiyonlar"].append(fonk_info)

  return parsed_data, full_text


# --- STREAMLIT ARAYÜZÜ ---
st.title("Meriç & İstestate | Kurumsal Portföy Analiz ve Fizibilite Otomasyonu")
st.markdown("---")

uploaded_file = st.file_uploader(
    "Belediye İmar Durumu PDF Belgesini Yükleyin", type=["pdf"]
)

if uploaded_file is not None:
  with st.spinner("İmar belgesi analiz ediliyor..."):
    sonuc, raw_text = parse_imar_durumu_gelismis(uploaded_file)

  st.success("İmar durumu başarıyla analiz edildi!")

  # Özet Bilgiler
  col1, col2, col3, col4 = st.columns(4)
  col1.metric("Mahalle", sonuc["mahalle"] or "Belirtilmemiş")
  col2.metric("Ada / Parsel", f"{sonuc['ada']} / {sonuc['parsel']}")
  col3.metric("Tapu Alanı (m²)", f"{sonuc['tapu_alani']:,.2f}")
  col4.metric(
      "Fonksiyon Sayısı", len(sonuc["fonksiyonlar"])
  )

  st.markdown("### 🏗️ Fonksiyon ve Yapılaşma Şartları")
  if sonuc["fonksiyonlar"]:
    df_fonk = pd.DataFrame(sonuc["fonksiyonlar"])
    st.dataframe(df_fonk, use_container_width=True)
  else:
    st.warning(
        "Metin bloklarında otomatik fonksiyon ayrıntısı bulunamadı. Lütfen"
        " ham metin sekmesini kontrol edin."
    )

  # Fizibilite Hesaplama Paneli
  st.markdown("---")
  st.markdown("### 📊 Temel İnşaat ve Proje Fizibilite Simülasyonu")

  selected_kaks = st.number_input(
      "Baz Alınacak KAKS (Emsal)",
      min_value=0.0,
      max_value=5.0,
      value=sonuc["fonksiyonlar"][0]["kaks"]
      if sonuc["fonksiyonlar"]
      else 1.0,
      step=0.05,
  )

  insaat_orani = st.slider(
      "Satılabilir Alan / Toplam İnşaat Alanı Oranı (Katsayı)", 0.70, 0.90, 0.80
  )

  toplam_insaat_alani = sonuc["tapu_alani"] * selected_kaks
  satilabilir_alan = toplam_insaat_alani * insaat_orani

  col_f1, col_f2 = st.columns(2)
  col_f1.metric("Toplam İnşaat Alanı (T.İ.A.)", f"{toplam_insaat_alani:,.2f} m²")
  col_f2.metric("Tahmini Satılabilir Alan", f"{satilabilir_alan:,.2f} m²")

  with st.expander("Ham PDF Metnini Görüntüle"):
    st.text_area("Metin İçeriği", raw_text, height=200)
