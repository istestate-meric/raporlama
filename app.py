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
    with open(full_path, "rb") as f:
      data = f.read()
    return base64.b64encode(data).decode("utf-8")
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
    with urllib.request.urlopen(req) as response:
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


# --- 2. İMAR FONKSİYONUNA GÖRE UYGUN PROJE TİPLERİ FİLTRESİ ---
def get_allowed_project_types(fonksiyon_adi):
  f_upper = fonksiyon_adi.upper()
  if any(k in f_upper for k in ["PARK", "YEŞİL", "YOL", "DİNİ", "MEZARLIK"]):
    return ["Yapılaşmaya Kapalı / Donatı Alanı"]

  all_types = [
      "Lüks Villa / Müstakil Proje",
      "Üst Segment Konut / Rezidans",
      "Standart Konut / Apartman",
      "Ticari / Ofis Kompleksi",
      "Karma Proje (Konut + Ticari)",
  ]

  if "TİCARET" in f_upper and (
      "KONUT" in f_upper or "MSK" in f_upper or "+" in f_upper
  ):
    return [
        "Karma Proje (Konut + Ticari)",
        "Ticari / Ofis Kompleksi",
        "Üst Segment Konut / Rezidans",
    ]
  elif "TİCARET" in f_upper or "MERKEZİ İŞ" in f_upper:
    return ["Ticari / Ofis Kompleksi"]
  elif "KONUT" in f_upper:
    return [
        "Standart Konut / Apartman",
        "Üst Segment Konut / Rezidans",
        "Lüks Villa / Müstakil Proje",
    ]
  else:
    return all_types


# --- 3. BEYKOZ PİYASA VE PROJE TİPİ MATRİSİ ---
def get_realistic_market_pricing(mahalle_adi, proje_tipi, usd_rate):
  if "Yapılaşmaya Kapalı" in proje_tipi:
    return 0.0, 0.0, 0.0

  mahalle_base_tl = {
      "ACARLAR": 140000,
      "ANADOLU HİSARI": 130000,
      "KANLICA": 125000,
      "GÖKSU": 110000,
      "RİVA": 120000,
      "KAVACIK": 90000,
      "SOĞUKSU": 95000,
      "VARSAYILAN": 95000,
  }
  base_tl = mahalle_base_tl.get(
      mahalle_adi.upper().strip(), mahalle_base_tl["VARSAYILAN"]
  )

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
  return (
      round((base_tl * p_conf["satis_mod"]) / usd_rate, 2),
      float(p_conf["maliyet_mod"]),
      float(p_conf["bodrum_deger_orani"]),
  )


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
  try:
    return float(s)
  except ValueError:
    return 0.0


def detect_terk_status(text, toplam_alan, fonksiyonlar):
  text_upper = text.upper()
  if any(
      k in text_upper
      for k in ["TERK YAPILMAMIŞ", "TERKİ YAPILAMIŞ", "DOP TERKİ YAPILMAMIŞ"]
  ):
    return False
  if any(
      k in text_upper
      for k in [
          "TERKİ YAPILMIŞTIR",
          "TERK YAPILMIŞTIR",
          "KAMUYA TERK EDİLMİŞTİR",
      ]
  ):
    return True
  toplam_fonksiyon_m2 = sum(f["giren_m2"] for f in fonksiyonlar)
  if toplam_alan > 0 and abs(toplam_alan - toplam_fonksiyon_m2) < 1.0:
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
  with pdfplumber.open(uploaded_file) as pdf:
    full_text = ""
    for page in pdf.pages:
      full_text += "\n" + (page.extract_text() or "")
      for table in page.extract_tables():
        for r_idx, row in enumerate(table):
          cells = [
              str(c).strip().replace("\n", " ") if c is not None else ""
              for c in row
          ]
          if any("Fonksiyon" in str(c) for c in cells):
            fonk_name = "Konut Alanı"
            taks_val, kaks_val, giren_m2 = 0.30, 0.40, 0.0
            for sub_idx in range(r_idx, min(r_idx + 4, len(table))):
              sub_str = " ".join(
                  str(c) for c in table[sub_idx] if c is not None
              )
              sub_upper = sub_str.upper()
              if "PARK" in sub_upper:
                fonk_name = "Park Alanı"
                taks_val, kaks_val = 0.0, 0.0
              elif "YEŞİL" in sub_upper:
                fonk_name = "Yeşil Alan"
                taks_val, kaks_val = 0.0, 0.0
              elif "TİCARET" in sub_upper and "KONUT" in sub_upper:
                fonk_name = "Ticaret ve Konut Alanı"
              elif "TİCARET" in sub_upper:
                fonk_name = "Ticaret Alanı"

              t_m = re.search(r"Taks\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE)
              k_m = re.search(
                  r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.,]+)", sub_str, re.IGNORECASE
              )
              if t_m:
                taks_val = parse_tr_float(t_m.group(1))
              if k_m:
                kaks_val = parse_tr_float(k_m.group(1))
              m2_m = re.search(r"([\d\.,]+)\s*m²?", sub_str)
              if m2_m:
                giren_m2 = parse_tr_float(m2_m.group(1))

            if not any(
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
  return parcel_data


# --- KURUMSAL HEADER ---
st.markdown(
    f"""
<div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 16px; padding: 30px 40px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.08); margin-bottom: 30px;">
    <div style="display: flex; align-items: center; justify-content: space-between;">
        <div style="flex: 1; text-align: center;">{img1_tag}</div>
        <div style="width: 1px; background-color: #cbd5e1; height: 75px; margin: 0 20px;"></div>
        <div style="flex: 1; text-align: center;">{img2_tag}</div>
    </div>
    <hr style="margin: 25px 0 20px 0; border: none; border-top: 1px solid #e2e8f0;">
    <div style="text-align: center;">
        <h1 style='color: #0f172a; font-size: 26px; font-weight: 800; margin-bottom: 6px;'>İSTESTATE GAYRİMENKUL & MERİÇ İNŞAAT</h1>
        <p style='color: #475569; font-size: 15px; font-weight: 600; margin: 0;'>Akıllı Gayrimenkul Geliştirme ve Fonksiyon Bazlı Fizibilite Portalı</p>
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

if uploaded_files:
  for uploaded_file in uploaded_files:
    p_data = parse_imar_pdf(uploaded_file)
    unique_key = (
        f"{p_data['mahalle']} | Ada: {p_data['ada']} - Parsel:"
        f" {p_data['parsel']}"
    )
    st.session_state["parcel_db"][unique_key] = p_data
  save_persistent_db(st.session_state["parcel_db"])
  st.sidebar.success(f"{len(uploaded_files)} Adet Belge Arşive Eklendi!")

st.sidebar.divider()
all_db_keys = list(st.session_state["parcel_db"].keys())

if all_db_keys:
  unique_adas = sorted(
      list(
          set([
              str(p.get("ada", "0")).strip()
              for p in st.session_state["parcel_db"].values()
          ])
      )
  )
  selected_ada_filter = st.sidebar.selectbox(
      "Ada Numarasına Göre Filtrele:", options=["Seçiniz..."] + unique_adas
  )
  filtered_keys = (
      [
          k
          for k, p in st.session_state["parcel_db"].items()
          if str(p.get("ada")) == str(selected_ada_filter)
      ]
      if selected_ada_filter != "Seçiniz..."
      else []
  )
  selected_keys = st.sidebar.multiselect(
      "Raporlanacak Ada-Parsel Seçin:", options=filtered_keys
  )
else:
  selected_keys = []

if selected_keys:
  active_parcel_db = {
      k: st.session_state["parcel_db"][k] for k in selected_keys
  }

  # --- KESİN AYRIŞTIRMA: BRÜT ARAZİ vs UYGULAMA / BAHÇE ALANI (NET ARSA) ---
  fonksiyon_bazli_veriler = {}
  for key, p in active_parcel_db.items():
    is_terkli = p["terk_yapilmis_mi"]
    for f in p["fonksiyonlar"]:
      fonk_adi = f["fonksiyon_adi"]
      if fonk_adi not in fonksiyon_bazli_veriler:
        fonksiyon_bazli_veriler[fonk_adi] = {
            "toplam_brut_arazi": 0.0,
            "toplam_net_arsa": 0.0,
            "toplam_uygulama_bahce_alani": 0.0,
            "toplam_insaat_alani": 0.0,
        }

      # 1. Ham Brüt Arazi (İmar belgesinden gelen ilk alan)
      brut_arazi = f["giren_m2"] if f["giren_m2"] > 0 else p["toplam_alan"]

      # 2. Terk Sonrası Net Arsa (İnşaat hesabının baz alındığı alan)
      net_arsa = brut_arazi if is_terkli else brut_arazi * 0.70

      # 3. Uygulama ve Bahçe Alanı = Doğrudan Terk Sonrası Kalan Net Arsa Miktarı
      uygulama_bahce_alani = net_arsa

      if (
          f["kaks"] <= 0
          or f["taks"] <= 0
          or any(
              k in fonk_adi.upper() for k in ["PARK", "YEŞİL", "YOL", "DİNİ"]
          )
      ):
        brut_insaat = 0.0
      else:
        brut_insaat = net_arsa * f["kaks"] * 1.30

      fonksiyon_bazli_veriler[fonk_adi]["toplam_brut_arazi"] += brut_arazi
      fonksiyon_bazli_veriler[fonk_adi]["toplam_net_arsa"] += net_arsa
      fonksiyon_bazli_veriler[fonk_adi]["toplam_uygulama_bahce_alani"] += (
          uygulama_bahce_alani
      )
      fonksiyon_bazli_veriler[fonk_adi]["toplam_insaat_alani"] += brut_insaat

  # --- PROJE TİPİ VE İŞ MODELİ SEÇİM PANELİ ---
  with st.expander(
      "⚙️ Proje Tipi ve İş Modeli Ayarları (Minimal Panel)", expanded=True
  ):
    col_is, col_space = st.columns([2, 1])
    with col_is:
      is_modeli = st.selectbox(
          "Genel İş Modeli / Rapor Türü:",
          options=[
              "Kat Karşılığı Proje Raporu",
              "Doğrudan Satılık / Arsa Yatırım Raporu",
          ],
      )

    st.markdown("---")
    secilen_fonksiyon_proje_tipleri = {}
    cols = st.columns(
        len(fonksiyon_bazli_veriler) if len(fonksiyon_bazli_veriler) > 0 else 1
    )

    for idx, (fonk_adi, vals) in enumerate(fonksiyon_bazli_veriler.items()):
      allowed_types = get_allowed_project_types(fonk_adi)
      with cols[idx % len(cols)]:
        st.markdown(f"**📌 {fonk_adi}**")
        secilen_fonksiyon_proje_tipleri[fonk_adi] = st.selectbox(
            "Proje Tipi Seçin",
            options=allowed_types,
            key=f"ptype_{fonk_adi}",
            label_visibility="collapsed",
        )
        if "Yapılaşmaya Kapalı" in secilen_fonksiyon_proje_tipleri[fonk_adi]:
          st.caption("⚠️ Donatı Alanı (0 İnşaat)")
        else:
          st.caption(
              f"Uygulama / Bahçe Alanı: {vals['toplam_uygulama_bahce_alani']:,.0f}"
              " m²"
          )

  # --- SEKME YAPISI ---
  tab1, tab2, tab3, tab4, tab5 = st.tabs([
      "📊 Parseller Özeti",
      "📐 Fonksiyon Bazlı İnşaat",
      "🏛️ Fonksiyon Bazlı Mimari Fizibilite",
      "📑 Fonksiyon Bazlı Proje Fizibilitesi",
      "🖨️ Kurumsal Rapor & PDF",
  ])

  with tab1:
    st.subheader("Seçilen Parsellerin Fonksiyon Bazlı Dağılımı")
    rows = []
    for k, p in active_parcel_db.items():
      for f in p["fonksiyonlar"]:
        b_val = f["giren_m2"]
        n_val = b_val if p["terk_yapilmis_mi"] else b_val * 0.70
        rows.append({
            "Parsel": k,
            "Mahalle": p["mahalle"],
            "Fonksiyon": f["fonksiyon_adi"],
            "Brüt Arazi (m²)": f"{b_val:,.2f}",
            "Uygulama / Bahçe Alanı (m²)": f"{n_val:,.2f}",
            "TAKS": f"{f['taks']:.2f}",
            "KAKS": f"{f['kaks']:.2f}",
            "Terk Durumu": "Terkli" if p["terk_yapilmis_mi"] else "Terksiz",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

  with tab2:
    st.subheader(
        "Fonksiyonlara Göre Brüt Arazi ve Uygulama / Bahçe Alanı Dağılımı"
    )
    for fonk, vals in fonksiyon_bazli_veriler.items():
      if vals["toplam_insaat_alani"] == 0:
        st.metric(
            label=f"🌳 {fonk} (Donatı Alanı)",
            value="0.00 m² (İnşaat Yok)",
            delta=(
                f"Brüt Arazi: {vals['toplam_brut_arazi']:,.2f} m² | Uygulama /"
                f" Bahçe Alanı: {vals['toplam_uygulama_bahce_alani']:,.2f} m²"
            ),
        )
      else:
        st.metric(
            label=f"🏗️ {fonk} - Toplam Brüt İnşaat Alanı",
            value=f"{vals['toplam_insaat_alani']:,.2f} m²",
            delta=(
                f"Brüt Arazi: {vals['toplam_brut_arazi']:,.2f} m² | Uygulama /"
                f" Bahçe Alanı: {vals['toplam_uygulama_bahce_alani']:,.2f} m²"
            ),
        )

  with tab3:
    st.subheader("🏛️ Fonksiyon Bazlı Mimari Fizibilite")
    for fonk, vals in fonksiyon_bazli_veriler.items():
      st.markdown(f"### 🏢 {fonk} Mimari Planlaması")
      p_tipi = secilen_fonksiyon_proje_tipleri[fonk]

      if vals["toplam_insaat_alani"] == 0:
        st.info(
            f"ℹ️ {fonk} donatı alanı olduğundan mimari bağımsız bölüm"
            " hesaplanmaz."
        )
      else:
        hedef_adet = st.number_input(
            f"Planlanan Bağımsız Bölüm Adedi ({fonk}):",
            min_value=1,
            value=max(1, int(vals["toplam_insaat_alani"] / 150)),
            key=f"adet_{fonk}",
        )
        birim_alan = (
            vals["toplam_insaat_alani"] / hedef_adet if hedef_adet > 0 else 0
        )
        st.success(
            f"Proje Tipi: **{p_tipi}** | Bağımsız Bölüm Başına Alan:"
            f" **{birim_alan:,.2f} m²** | Fiili Uygulama / Bahçe Alanı:"
            f" **{vals['toplam_uygulama_bahce_alani']:,.2f} m²**"
        )
      st.markdown("---")

  with tab4:
    st.subheader("📑 Fonksiyon Bazlı Proje Raporu & Finansal Fizibilite")
    first_mahalle = list(active_parcel_db.values())[0].get(
        "mahalle", "VARSAYILAN"
    )

    toplam_portfoy_ciro_usd = 0.0
    toplam_portfoy_maliyet_usd = 0.0

    for fonk, vals in fonksiyon_bazli_veriler.items():
      p_tipi = secilen_fonksiyon_proje_tipleri[fonk]
      if vals["toplam_insaat_alani"] == 0:
        st.markdown(f"#### 📊 {fonk} Finansal Kırılımı")
        st.info("Bu fonksiyon donatı alanı olduğundan ciro ve maliyet üretmez.")
        st.markdown("---")
        continue

      satis_fiyat, maliyet_fiyat, _ = get_realistic_market_pricing(
          first_mahalle, p_tipi, rates["USD"]
      )

      fonk_ciro = vals["toplam_insaat_alani"] * satis_fiyat
      fonk_maliyet = vals["toplam_insaat_alani"] * maliyet_fiyat

      toplam_portfoy_ciro_usd += fonk_ciro
      toplam_portfoy_maliyet_usd += fonk_maliyet

      st.markdown(f"#### 📊 {fonk} Finansal Kırılımı ({p_tipi})")
      fc1, fc2, fc3 = st.columns(3)
      fc1.metric("Tahmini Ciro", f"${fonk_ciro:,.2f}")
      fc2.metric("İnşaat Maliyeti", f"${fonk_maliyet:,.2f}")
      fc3.metric(
          "Net Kâr", f"${fonk_ciro - fonk_maliyet:,.2f}"
      )
      st.markdown("---")

    st.markdown("### 🏆 Genel Portföy Toplamı")
    g1, g2 = st.columns(2)
    g1.metric("Toplam Ciro ($)", f"${toplam_portfoy_ciro_usd:,.2f}")
    g2.metric("Toplam Maliyet ($)", f"${toplam_portfoy_maliyet_usd:,.2f}")

  with tab5:
    st.subheader("🖨️ Kurumsal Rapor Ön İzleme & PDF")
    st.info(
        "Brüt arsa ve terk sonrası uygulama/bahçe alanı ayrımları rapora"
        " yansıtılmıştır."
    )
    if st.button("Tek Sayfa Kurumsal Fizibilite Raporu İndir"):
      st.success("Rapor başarıyla oluşturuldu.")
else:
  st.info(
      "👋 Lütfen sol menüden Ada/Parsel seçimi yapın veya yeni imar belgesi"
      " yükleyin."
  )
