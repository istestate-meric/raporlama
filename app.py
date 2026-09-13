import base64
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import pdfplumber
import streamlit as st
from weasyprint import CSS, HTML

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="İstestate & Meriç İnşaat - Fizibilite Portalı",
    page_icon="🏢",
    layout="wide",
)

# --- KALICI DOSYA TABANLI VERİTABANI YÖNETİMİ ---
BASE_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in locals()
    else os.getcwd()
)
DB_FILE = os.path.join(BASE_DIR, "imar_veritabani.json")


def load_persistent_db():
  if os.path.exists(DB_FILE):
    try:
      with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}
  return {}


def save_persistent_db(db_data):
  try:
    with open(DB_FILE, "w", encoding="utf-8") as f:
      json.dump(db_data, f, ensure_ascii=False, indent=4)
  except Exception as e:
    st.error(f"Veritabanı kaydedilirken hata oluştu: {e}")


if "parcel_db" not in st.session_state:
  st.session_state["parcel_db"] = load_persistent_db()

# --- GÖRSELİ BASE64'E ÇEVİRME YARDIMCISI ---


def get_image_base64(path):
  full_path = os.path.join(BASE_DIR, path)
  if os.path.exists(full_path):
    try:
      with open(full_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
      return ""
  return ""


img1_base64 = get_image_base64("istestate_logo.png")
img2_base64 = get_image_base64("meric_insaat_emlak_logo.png")

img1_tag = (
    f"<img src='data:image/png;base64,{img1_base64}' style='max-height: 65px;"
    " width: auto; object-fit: contain;'>"
    if img1_base64
    else "<h2 style='color:#1e3a8a; margin:0;'>İSTESTATE</h2>"
)
img2_tag = (
    f"<img src='data:image/png;base64,{img2_base64}' style='max-height: 65px;"
    " width: auto; object-fit: contain;'>"
    if img2_base64
    else "<h2 style='color:#1e3a8a; margin:0;'>MERİÇ İNŞAAT</h2>"
)


# --- 1. TCMB CANLI DÖVİZ KURU SERVİSİ ---
@st.cache_data(ttl=300)
def get_live_exchange_rates():
  try:
    url = "https://www.tcmb.gov.tr/kurlar/today.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
      xml_data = response.read()

    root = ET.fromstring(xml_data)
    usd_rate, eur_rate = 0.0, 0.0

    for currency in root.findall("Currency"):
      code = currency.get("CurrencyCode")
      if code == "USD":
        usd_rate = float(currency.find("ForexSelling").text)
      elif code == "EUR":
        eur_rate = float(currency.find("ForexSelling").text)

    return {
        "USD": usd_rate if usd_rate > 0 else 34.00,
        "EUR": eur_rate if eur_rate > 0 else 37.50,
    }
  except Exception:
    return {"USD": 34.00, "EUR": 37.50}


# --- 2. BEYKOZ GERÇEKÇİ PİYASA VE PROJE TİPİ MATRİSİ (CANLI OTOMATİK) ---
def get_realistic_market_pricing(mahalle_adi, proje_tipi, usd_rate):
  mahalle_base_tl = {
      "ACARLAR": 140000,
      "ANADOLU HİSARI": 130000,
      "KANLICA": 125000,
      "GÖKSU": 110000,
      "GÖRELE": 115000,
      "RİVA": 120000,
      "ÇİFTLİK": 115000,
      "BAKLACI": 95000,
      "KAVACIK": 90000,
      "ÇENGELDERE": 105000,
      "YAVUZ SELİM": 80000,
      "FATİH": 75000,
      "SOĞUKSU": 95000,
      "PAŞABAHÇE": 90000,
      "VARSAYILAN": 95000,
  }

  clean_mahalle = mahalle_adi.upper().strip()
  base_tl = mahalle_base_tl.get(clean_mahalle, mahalle_base_tl["VARSAYILAN"])

  proje_carpanlari = {
      "Lüks Villa / Müstakil Proje": {
          "satis_mod": 1.55,
          "maliyet_mod": 1350,
          "bodrum_deger_orani": 0.60,
      },
      "Üst Segment Konut / Rezidans": {
          "satis_mod": 1.25,
          "maliyet_mod": 1100,
          "bodrum_deger_orani": 0.50,
      },
      "Standart Konut / Apartman": {
          "satis_mod": 1.00,
          "maliyet_mod": 900,
          "bodrum_deger_orani": 0.40,
      },
      "Ticari / Ofis Kompleksi": {
          "satis_mod": 1.35,
          "maliyet_mod": 1050,
          "bodrum_deger_orani": 0.70,
      },
      "Karma Proje (Konut + Ticari)": {
          "satis_mod": 1.20,
          "maliyet_mod": 1000,
          "bodrum_deger_orani": 0.50,
      },
  }

  p_conf = proje_carpanlari.get(
      proje_tipi, proje_carpanlari["Standart Konut / Apartman"]
  )

  satis_fiyati_usd = round((base_tl * p_conf["satis_mod"]) / usd_rate, 2)
  maliyet_fiyati_usd = float(p_conf["maliyet_mod"])
  bodrum_orani = float(p_conf["bodrum_deger_orani"])

  return satis_fiyati_usd, maliyet_fiyati_usd, bodrum_orani


def parse_tr_float(val_str):
  if not val_str:
    return 0.0
  s = str(val_str).strip()
  if "-" in s:
    s = s.split("-")[-1]
  s = re.sub(r"[^\d\.,]", "", s).strip()
  if not s:
    return 0.0

  if "," in s and "." in s:
    if s.rfind(".") > s.rfind(","):
      s = s.replace(",", "")
    else:
      s = s.replace(".", "").replace(",", ".")
  elif "," in s:
    s = s.replace(",", ".")
  elif "." in s:
    parts = s.split(".")
    if len(parts[-1]) == 3 and len(parts) > 1:
      s = s.replace(".", "")

  try:
    return float(s)
  except ValueError:
    return 0.0


def detect_terk_status(text, toplam_alan, fonksiyonlar):
  text_upper = text.upper()
  terksiz_kaliplar = [
      "YOLA TERK VE KAMUYA AYRILAN KISIMLAR KAMU ELİNE GEÇMEDEN",
      "TERK YAPILMAMIŞ",
      "TERKİ YAPILAMIŞ",
      "TERK YAPILMADAN",
      "TERKİ YAPILMADAN",
      "DOP TERKİ YAPILMAMIŞ",
  ]
  if any(k in text_upper for k in terksiz_kaliplar):
    return False

  terkli_kaliplar = [
      "TERKİ YAPILMIŞTIR",
      "TERKİ YAPILMIŞ",
      "TERK YAPILMIŞTIR",
      "KAMUYA TERK EDİLMİŞTİR",
      "DOP TERKİ YAPILMAMIŞTIR",
  ]
  if any(k in text_upper for k in terkli_kaliplar):
    return True

  toplam_fonksiyon_m2 = sum(
      f["giren_m2"]
      for f in fonksiyonlar
      if not any(
          x in f["fonksiyon_adi"]
          for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]
      )
  )

  if toplam_alan > 0 and toplam_fonksiyon_m2 > 0:
    if (
        abs(toplam_alan - toplam_fonksiyon_m2) < 1.0
        or (toplam_fonksiyon_m2 / toplam_alan) >= 0.99
    ):
      return True

  return False


def parse_imar_pdf(uploaded_file):
  parcel_data = {
      "filename": uploaded_file.name,
      "mahalle": "BİLİNMİYOR",
      "ada": "0",
      "parsel": "0",
      "toplam_alan": 0.0,
      "terk_yapilmis_mi": False,
      "fonksiyonlar": [],
  }

  try:
    with pdfplumber.open(uploaded_file) as pdf:
      full_text = ""
      for page in pdf.pages:
        t = page.extract_text() or ""
        full_text += "\n" + t

        tables = page.extract_tables() or []
        for table in tables:
          for r_idx, row in enumerate(table):
            cells = [
                str(c).strip().replace("\n", " ") if c is not None else ""
                for c in row
            ]
            row_str = " ".join(cells)

            if any("Mahalle" in c for c in cells) and any(
                "Ada" in c for c in cells
            ):
              if r_idx + 1 < len(table):
                v_row = [
                    str(c).strip().replace("\n", " ") if c is not None else ""
                    for c in table[r_idx + 1]
                ]
                for idx, head in enumerate(cells):
                  if idx < len(v_row):
                    val = v_row[idx]
                    if "Mahalle" in head and val:
                      parcel_data["mahalle"] = val.upper()
                    elif "Ada" in head and val:
                      parcel_data["ada"] = str(val).strip()
                    elif "Parsel" in head and val:
                      parcel_data["parsel"] = str(val).strip()
                    elif "Alan" in head and val:
                      parcel_data["toplam_alan"] = parse_tr_float(val)

            if "Fonksiyon Adı" in row_str or any(
                "Fonksiyon" in str(c) for c in cells
            ):
              fonk_name = ""
              taks_val, kaks_val, giren_m2 = 0.30, 0.40, 0.0

              for sub_idx in range(r_idx, min(r_idx + 5, len(table))):
                sub_cells = [
                    str(c).strip().replace("\n", " ") if c is not None else ""
                    for c in table[sub_idx]
                ]
                sub_str = " ".join(sub_cells)

                if "Fonksiyon Adı" in sub_str or "Fonksiyon" in sub_str:
                  for c in sub_cells:
                    if c and "Fonksiyon" not in c and c != "|":
                      fonk_name = c.strip()
                      break

                t_m = re.search(
                    r"Taks\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE
                )
                k_m = re.search(
                    r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.,]+)",
                    sub_str,
                    re.IGNORECASE,
                )
                if t_m:
                  taks_val = parse_tr_float(t_m.group(1))
                if k_m:
                  kaks_val = parse_tr_float(k_m.group(1))

                if "m²" in sub_str or "m2" in sub_str or "%" in sub_str:
                  m2_match = re.search(r"([\d\.,]+)\s*m²?", sub_str)
                  if m2_match:
                    giren_m2 = parse_tr_float(m2_match.group(1))

              if fonk_name and not any(
                  f["fonksiyon_adi"] == fonk_name
                  for f in parcel_data["fonksiyonlar"]
              ):
                parcel_data["fonksiyonlar"].append({
                    "fonksiyon_adi": fonk_name,
                    "taks": taks_val,
                    "kaks": kaks_val,
                    "giren_m2": (
                        giren_m2 if giren_m2 > 0 else parcel_data["toplam_alan"]
                    ),
                })

    if parcel_data["mahalle"] == "BİLİNMİYOR" or parcel_data["ada"] == "0":
      m_m = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", full_text)
      a_m = re.search(r"Ada\s*\|\s*(\d+)", full_text)
      p_m = re.search(r"Parsel\s*\|\s*(\d+)", full_text)
      al_m = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", full_text)

      if m_m:
        parcel_data["mahalle"] = m_m.group(1).upper()
      if a_m:
        parcel_data["ada"] = str(a_m.group(1)).strip()
      if p_m:
        parcel_data["parsel"] = str(p_m.group(1)).strip()
      if al_m and parcel_data["toplam_alan"] == 0.0:
        parcel_data["toplam_alan"] = parse_tr_float(al_m.group(1))

    if not parcel_data["fonksiyonlar"]:
      parcel_data["fonksiyonlar"].append({
          "fonksiyon_adi": "Konut Alanı",
          "taks": 0.30,
          "kaks": 0.40,
          "giren_m2": parcel_data["toplam_alan"],
      })

    parcel_data["terk_yapilmis_mi"] = detect_terk_status(
        full_text, parcel_data["toplam_alan"], parcel_data["fonksiyonlar"]
    )
  except Exception as e:
    st.error(f"PDF işlenirken bir hata oluştu: {e}")

  return parcel_data


def get_allowed_project_types(fonksiyon_adi):
  f_upper = fonksiyon_adi.upper()
  if "TİCARET" in f_upper and ("KONUT" in f_upper or "MESKEN" in f_upper):
    return ["Karma Proje (Konut + Ticari)"]
  elif "TİCARET" in f_upper or "TİCARİ" in f_upper:
    return ["Ticari / Ofis Kompleksi"]
  elif "KONUT" in f_upper or "MESKEN" in f_upper:
    return [
        "Lüks Villa / Müstakil Proje",
        "Üst Segment Konut / Rezidans",
        "Standart Konut / Apartman",
    ]
  else:
    return [
        "Lüks Villa / Müstakil Proje",
        "Üst Segment Konut / Rezidans",
        "Standart Konut / Apartman",
        "Ticari / Ofis Kompleksi",
        "Karma Proje (Konut + Ticari)",
    ]


# --- KURUMSAL HEADER ---
st.markdown(
    f"""
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 16px; padding: 30px 40px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.08); margin-bottom: 30px;">
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
        <div style="flex: 1; text-align: center;">{img1_tag}</div>
        <div style="width: 1px; background-color: #cbd5e1; height: 75px; margin: 0 20px;"></div>
        <div style="flex: 1; text-align: center;">{img2_tag}</div>
    </div>
    <hr style="margin: 25px 0 20px 0; border: none; border-top: 1px solid #e2e8f0;">
    <div style="text-align: center;">
        <h1 style='color: #0f172a; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 6px; margin-top: 0;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT</h1>
        <p style='color: #475569; font-size: 15px; font-weight: 600; margin: 0;'>Akıllı Gayrimenkul Geliştirme ve Fizibilite Portalı</p>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

rates = get_live_exchange_rates()

st.sidebar.header("📁 İmar Belgesi Yükleme")
uploaded_files = st.sidebar.file_uploader(
    "İmar Durum Raporu (PDF) Seçin", type=["pdf"], accept_multiple_files=True
)

just_uploaded_keys = []
if uploaded_files:
  for uploaded_file in uploaded_files:
    p_data = parse_imar_pdf(uploaded_file)
    unique_key = (
        f"{p_data['mahalle']} | Ada: {p_data['ada']} - Parsel:"
        f" {p_data['parsel']}"
    )
    st.session_state["parcel_db"][unique_key] = p_data
    just_uploaded_keys.append(unique_key)

  save_persistent_db(st.session_state["parcel_db"])
  st.sidebar.success(f"{len(uploaded_files)} Adet Belge Arşive Eklendi!")

st.sidebar.divider()
st.sidebar.subheader("🎯 Rapor İçin Parsel Seçimi & Arama")

all_db_keys = list(st.session_state["parcel_db"].keys())

if all_db_keys:
  unique_adas = sorted(
      list(
          set([
              str(p_data.get("ada", "0")).strip()
              for p_data in st.session_state["parcel_db"].values()
          ])
      )
  )
  selected_ada_filter = st.sidebar.selectbox(
      "Ada Numarasına Göre Filtrele:", options=["Seçiniz..."] + unique_adas
  )

  filtered_keys = (
      [
          k
          for k, p_data in st.session_state["parcel_db"].items()
          if str(p_data.get("ada", "")).strip()
          == str(selected_ada_filter).strip()
      ]
      if selected_ada_filter != "Seçiniz..."
      else []
  )

  default_selection = [
      k
      for k in (just_uploaded_keys if just_uploaded_keys else [])
      if k in filtered_keys
  ]

  selected_keys = st.sidebar.multiselect(
      "Raporlanacak Ada-Parsel Seçin:",
      options=filtered_keys if selected_ada_filter != "Seçiniz..." else [],
      default=default_selection,
  )
else:
  st.sidebar.info(
      "Arşivde henüz kayıtlı parsel yok. Lütfen sol üstten PDF imar belgesi"
      " yükleyin."
  )
  selected_keys = []

if selected_keys:
  active_parcel_db = {
      k: st.session_state["parcel_db"][k] for k in selected_keys
  }

  emsal_artis_orani = 1.30

  st.markdown("---")
  st.subheader("⚙️ İş Modeli ve Genel Parametreler")
  col_global1, _ = st.columns(2)
  with col_global1:
    is_modeli = st.selectbox(
        "İş Modeli / Rapor Türü:",
        options=[
            "Kat Karşılığı Proje Raporu",
            "Doğrudan Satılık / Arsa Yatırım Raporu",
        ],
        key="global_is_modeli",
    )

  arsa_payi_orani = 0.0
  arsa_bonus_usd = 0.0
  if "Kat Karşılığı" in is_modeli:
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    col_gk1, col_gk2, col_gk3 = st.columns([2, 1, 2])
    with col_gk1:
      arsa_payi_orani = st.slider(
          "Arsa Sahibi Payı / Kat Karşılığı Oranı (%)", 0, 70, 50
      )
    with col_gk2:
      bonus_curr = st.selectbox(
          "Para Birimi", options=["USD ($)", "EUR (€)", "TL (₺)"]
      )
    with col_gk3:
      raw_bonus_val = st.number_input(
          "💵 Nakit Bonus / İmza Parası Tutar",
          min_value=0.0,
          value=0.0,
          step=10000.0,
          format="%.2f",
      )
      if "EUR" in bonus_curr:
        arsa_bonus_usd = raw_bonus_val * (rates["EUR"] / rates["USD"])
      elif "TL" in bonus_curr:
        arsa_bonus_usd = raw_bonus_val / rates["USD"]
      else:
        arsa_bonus_usd = raw_bonus_val

  st.markdown("---")

  # --- MİNİMALİZE VE KURUMSAL AKORDEON YAPISI ---
  all_functions_map = {}
  for key, p in active_parcel_db.items():
    for f in p["fonksiyonlar"]:
      f_name = f["fonksiyon_adi"]
      if any(
          x in f_name.upper()
          for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]
      ):
        continue
      if f_name not in all_functions_map:
        all_functions_map[f_name] = []
      all_functions_map[f_name].append((key, f))

  function_configs = {}

  with st.expander(
      "🏛️ Fonksiyona Özel Mimari ve Finansal Parametreler (Canlı Otomatik"
      " Matris)",
      expanded=False,
  ):
    st.markdown(
        "<p style='color: #64748b; font-size: 13px; margin-bottom: 15px;'>Seçilen"
        " bölgeye ve proje konseptine ait birim maliyet ve satış değerleri"
        " piyasa verilerine göre otomatik optimize edilir. İhtiyaç halinde"
        " özelleştirebilirsiniz.</p>",
        unsafe_allow_html=True,
    )

    for fonk_name, items in all_functions_map.items():
      st.markdown(f"#### 📌 Fonksiyon: `{fonk_name}`")
      allowed_types = get_allowed_project_types(fonk_name)

      f_col1, f_col2, f_col3 = st.columns(3)
      with f_col1:
        sel_p_tipi = st.selectbox(
            f"Proje Tipi ({fonk_name})",
            options=allowed_types,
            key=f"p_tipi_{fonk_name}",
        )
      with f_col2:
        fonk_toplam_brut_m2 = sum(
            item[1]["giren_m2"]
            if item[1]["giren_m2"] > 0
            else active_parcel_db[item[0]]["toplam_alan"]
            for item in items
        )
        def_hedef_alan = (
            300.0
            if "Villa" in sel_p_tipi
            else (150.0 if "Karma" in sel_p_tipi else 125.0)
        )
        def_adet = max(1, round(fonk_toplam_brut_m2 / def_hedef_alan))

        adet = st.number_input(
            f"Planlanan Bağımsız Bölüm Adedi",
            min_value=1,
            value=int(def_adet),
            step=1,
            key=f"adet_{fonk_name}",
        )
      with f_col3:
        havuz_mod = st.selectbox(
            f"Havuz Modeli",
            options=[
                "Özel / Ortak Havuzlu",
                "Havuz İptal (Küçük Ölçek Kısıtı)",
            ],
            key=f"havuz_{fonk_name}",
        )

      first_mahalle = list(active_parcel_db.values())[0].get(
          "mahalle", "VARSAYILAN"
      )
      r_satis, r_maliyet, r_bodrum_orani = get_realistic_market_pricing(
          first_mahalle, sel_p_tipi, rates["USD"]
      )

      p_col1, p_col2 = st.columns(2)
      with p_col1:
        fonk_maliyet = st.number_input(
            f"M² Brüt Maliyet ($) [{fonk_name}]",
            value=float(r_maliyet),
            step=50.0,
            key=f"mal_{fonk_name}",
        )
      with p_col2:
        fonk_satis = st.number_input(
            f"M² Brüt Satış ($) [{fonk_name}]",
            value=float(r_satis),
            step=100.0,
            key=f"sat_{fonk_name}",
        )

      function_configs[fonk_name] = {
          "proje_tipi": sel_p_tipi,
          "adet": adet,
          "havuz_mod": havuz_mod,
          "maliyet": fonk_maliyet,
          "satis": fonk_satis,
          "bodrum_orani": r_bodrum_orani,
      }
      st.markdown("---")

  # Eğer akordeon kapalıysa veya o an render edilmediyse varsayılan değerleri besle
  for fonk_name, items in all_functions_map.items():
    if fonk_name not in function_configs:
      first_mahalle = list(active_parcel_db.values())[0].get(
          "mahalle", "VARSAYILAN"
      )
      allowed_types = get_allowed_project_types(fonk_name)
      def_p_tipi = allowed_types[0]
      r_satis, r_maliyet, r_bodrum_orani = get_realistic_market_pricing(
          first_mahalle, def_p_tipi, rates["USD"]
      )
      function_configs[fonk_name] = {
          "proje_tipi": def_p_tipi,
          "adet": 1,
          "havuz_mod": "Havuz İptal",
          "maliyet": r_maliyet,
          "satis": r_satis,
          "bodrum_orani": r_bodrum_orani,
      }

  # --- GENEL HESAPLAMA MOTORU ---
  total_yasal_brut_insaat = 0.0
  total_simulated_bodrum = 0.0
  total_ciro_usd = 0.0
  total_maliyet_usd = 0.0

  function_results_detail = []

  for key, p in active_parcel_db.items():
    toplam_brut_m2 = p["toplam_alan"]
    is_terkli = p["terk_yapilmis_mi"]
    net_arsa_m2 = toplam_brut_m2 if is_terkli else toplam_brut_m2 * 0.70

    toplam_giren_fonk_m2 = sum(
        f["giren_m2"]
        for f in p["fonksiyonlar"]
        if not any(
            x in f["fonksiyon_adi"]
            for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]
        )
    )

    for f in p["fonksiyonlar"]:
      fonk_adi = f["fonksiyon_adi"]
      if any(
          x in fonk_adi.upper()
          for x in ["PARK", "TEKNİK ALTYAPI", "LİSE", "KÜLTÜREL", "ANAOKULU"]
      ):
        continue

      conf = function_configs.get(fonk_adi)

      giren_m2 = f["giren_m2"] if f["giren_m2"] > 0 else toplam_brut_m2
      if not is_terkli:
        fonk_pay_orani = (
            (giren_m2 / toplam_giren_fonk_m2) if toplam_giren_fonk_m2 > 0 else 1.0
        )
        esas_m2 = toplam_brut_m2 * fonk_pay_orani
        brut_insaat = esas_m2 * 0.70 * f["kaks"] * emsal_artis_orani
      else:
        esas_m2 = giren_m2
        brut_insaat = esas_m2 * f["kaks"] * emsal_artis_orani

      total_yasal_brut_insaat += brut_insaat

      tekil_havuz_payi = 30.0 if "Özel" in conf["havuz_mod"] else 0.0
      sim_bodrum = (
          brut_insaat - (tekil_havuz_payi * conf["adet"])
      ) * conf["bodrum_orani"]
      total_simulated_bodrum += sim_bodrum

      normal_c = brut_insaat * conf["satis"]
      bodrum_c = sim_bodrum * conf["satis"] * conf["bodrum_orani"]
      fonk_ciro = normal_c + bodrum_c
      fonk_maliyet_tot = brut_insaat * conf["maliyet"]

      total_ciro_usd += fonk_ciro
      total_maliyet_usd += fonk_maliyet_tot

      function_results_detail.append({
          "Parsel": key,
          "Fonksiyon": fonk_adi,
          "Brüt İnşaat (m²)": brut_insaat,
          "Tahmini Ciro ($)": fonk_ciro,
          "Tahmini Maliyet ($)": fonk_maliyet_tot,
      })

  total_maliyet_usd += arsa_bonus_usd
  arsa_sahibi_payi_usd = (
      total_ciro_usd * (arsa_payi_orani / 100)
      if "Kat Karşılığı" in is_modeli
      else 0.0
  )
  mutaahhit_net_kar_usd = (
      total_ciro_usd - total_maliyet_usd - arsa_sahibi_payi_usd
  )
  yg_orani = (
      (mutaahhit_net_kar_usd / total_maliyet_usd * 100)
      if total_maliyet_usd > 0
      else 0
  )

  # --- SEKME YAPISI ---
  tab1, tab2, tab3, tab4, tab5 = st.tabs([
      "📊 Seçilen Parseller Özeti",
      "📐 İnşaat Alanı Hesabı",
      "🏛️ Mimari Fizibilite",
      "📑 Proje Raporu & Fizibilite",
      "🖨️ Rapor Ön İzleme & PDF",
  ])

  with tab1:
    st.subheader("Seçilen Parsellerin İmar ve Alan Bazlı Dağılımı")
    table_rows = []
    for key, p in active_parcel_db.items():
      is_terkli = p["terk_yapilmis_mi"]
      toplam_brut = p["toplam_alan"]
      terk_lbl = (
          "Terki Yapılmış (Net)"
          if is_terkli
          else "Terki Yapılmamış (%30 Kesintili İmar Hesabı)"
      )

      for f in p["fonksiyonlar"]:
        fonks_m2 = f["giren_m2"] if f["giren_m2"] > 0 else toplam_brut
        net_m2 = fonks_m2 if is_terkli else toplam_brut * 0.70
        table_rows.append({
            "Parsel Bilgisi": key,
            "Mahalle": p["mahalle"],
            "Toplam Arsa (m²)": f"{toplam_brut:,.2f}",
            "Alan Adı (Bahçe/Kullanım Alanı)": f["fonksiyon_adi"],
            "Alan Miktarı (m²)": f"{fonks_m2:,.2f}",
            "Net Arsa (m²)": f"{net_m2:,.2f}",
            "TAKS": f"{f['taks']:.2f}",
            "KAKS (Emsal)": f"{f['kaks']:.2f}",
            "Terk Durumu": terk_lbl,
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

  with tab2:
    st.subheader("Fonksiyon Bazlı Brüt İnşaat Kapasite Hesabı")
    calc_results = []
    for item in function_results_detail:
      calc_results.append({
          "Parsel": item["Parsel"],
          "Fonksiyon": item["Fonksiyon"],
          "Toplam Brüt İnşaat Alanı (m²)": f"{item['Brüt İnşaat (m²)']:,.2f}",
      })
    st.table(pd.DataFrame(calc_results))
    st.metric(
        label="🏗️ Toplam Brüt İnşaat Alanı",
        value=f"{total_yasal_brut_insaat:,.2f} m²",
    )

  with tab3:
    st.subheader("🏛️ Fonksiyona Özel Mimari Fizibilite Sonuçları")
    for fonk_name, conf in function_configs.items():
      st.markdown(f"**Fonksiyon: {fonk_name}**")
      m_col1, m_col2, m_col3 = st.columns(3)
      m_col1.metric("Proje Tipi", conf["proje_tipi"])
      m_col2.metric("Bağımsız Bölüm Adedi", f"{conf['adet']} Adet")
      m_col3.metric("Havuz Tercihi", conf["havuz_mod"])
      st.markdown("---")

  with tab4:
    st.subheader("📑 Finansal Fizibilite ve Fonksiyon Dağılım Matrisi")
    f_col1, f_col2, f_col3 = st.columns(3)
    f_col1.metric("Toplam Tahmini Brüt Ciro", f"${total_ciro_usd:,.2f}")
    f_col2.metric("Toplam İnşaat Maliyeti", f"${total_maliyet_usd:,.2f}")
    f_col3.metric(
        "Müteahhit Net Karı",
        f"${mutaahhit_net_kar_usd:,.2f}",
        f"%{yg_orani:.1f} YG",
    )

  with tab5:
    st.subheader(
        "🖨️ Kurumsal Tek Sayfa Rapor Ön İzleme ve PDF İndirme Merkezi"
    )

    pdf_logo1_html = (
        f"<img src='data:image/png;base64,{img1_base64}' style='max-height:"
        " 38px;'>"
        if img1_base64
        else "<b>İSTESTATE</b>"
    )
    pdf_logo2_html = (
        f"<img src='data:image/png;base64,{img2_base64}' style='max-height:"
        " 38px;'>"
        if img2_base64
        else "<b>MERİÇ İNŞAAT</b>"
    )
    first_mahalle = list(active_parcel_db.values())[0].get("mahalle", "BEYKOZ")

    report_html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4 landscape; margin: 6mm 8mm; }}
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #1e293b; font-size: 8.5px; line-height: 1.12; }}
            .report-banner {{ background-color: #0b1d3a; color: #ffffff; width: 100%; border-collapse: collapse; margin-bottom: 6px; }}
            .report-banner td {{ border: none; padding: 8px 10px; vertical-align: middle; }}
            .section-title {{ font-size: 9px; font-weight: bold; color: #0b1d3a; border-left: 3px solid #0b1d3a; padding-left: 5px; background-color: #f1f5f9; margin-top: 5px; margin-bottom: 2px; text-transform: uppercase; }}
            .data-table {{ width: 100%; border-collapse: collapse; margin-top: 1px; font-size: 8.5px; }}
            .data-table th, .data-table td {{ border: 1px solid #cbd5e1; padding: 3px 5px; }}
            .data-table th {{ background-color: #f8fafc; font-weight: 700; }}
            .footer {{ font-size: 7.5px; color: #64748b; text-align: center; margin-top: 6px; border-top: 1px dashed #cbd5e1; padding-top: 2px; }}
        </style>
        </head>
        <body>
            <table class="report-banner">
                <tr>
                    <td style="width: 25%;">{pdf_logo1_html}</td>
                    <td style="width: 50%; text-align: center;"><h2 style="font-size:11px; margin:0; color:#fff;">AKILLI GAYRİMENKUL GELİŞTİRME VE FİZİBİLİTE RAPORU</h2></td>
                    <td style="width: 25%; text-align: right;">{pdf_logo2_html}</td>
                </tr>
            </table>
            <div class="section-title">1. Proje ve Lokasyon Künyesi</div>
            <table class="data-table">
                <tr><td>Lokasyon / Mahalle</td><td style="text-align: right; font-weight: bold;">{first_mahalle}</td></tr>
                <tr><td>Toplam Brüt İnşaat Alanı</td><td style="text-align: right; font-weight: bold; color: #1e3a8a;">{total_yasal_brut_insaat:,.2f} m²</td></tr>
            </table>
            <div class="section-title">2. Fonksiyon Bazlı Finansal Fizibilite Özeti</div>
            <table class="data-table">
                <tr><th>Finansal Kalem</th><th style="text-align: right;">Tutar (USD $)</th><th style="text-align: right;">Tutar (TL ₺)</th></tr>
                <tr><td>Toplam Tahmini Brüt Ciro</td><td style="text-align: right;">${total_ciro_usd:,.2f}</td><td style="text-align: right;">₺{total_ciro_usd * rates['USD']:,.2f}</td></tr>
                <tr><td>Toplam İnşaat Maliyeti</td><td style="text-align: right;">${total_maliyet_usd:,.2f}</td><td style="text-align: right;">₺{total_maliyet_usd * rates['USD']:,.2f}</td></tr>
                <tr style="font-weight: bold;"><td>Müteahhit Net Kârı</td><td style="text-align: right; color:#1e3a8a;">${mutaahhit_net_kar_usd:,.2f}</td><td style="text-align: right; color:#1e3a8a;">₺{mutaahhit_net_kar_usd * rates['USD']:,.2f} (%{yg_orani:.1f} YG)</td></tr>
            </table>
            <div class="footer">Bu rapor İstestate Gayrimenkul & Meriç İnşaat Emlak Akıllı Fizibilite Portalı tarafından üretilmiştir.</div>
        </body>
        </html>
        """

    pdf_bytes = HTML(string=report_html_template).write_pdf()
    st.download_button(
        label="📥 Tek Sayfa Yatay Kurumsal Fizibilite Raporunu PDF Olarak İndir",
        data=pdf_bytes,
        file_name=(
            f"Kurumsal_Fizibilite_{first_mahalle}_Fonksiyonel.pdf"
        ),
        mime="application/pdf",
        use_container_width=True,
    )
else:
  st.info(
      "👋 **Hoş Geldiniz!** Raporları görüntülemek için lütfen sol menüden bir"
      " **Ada** seçip ilgili parselleri işaretleyin veya yeni bir imar belgesi"
      " (PDF) yükleyin."
  )
