import streamlit as st

st.set_page_config(page_title="Arsa Fizibilite ve Proje Tipi Yönetimi", layout="wide")

st.title("Arsa Fizibilite Hesabı - İmar ve Proje Eşleştirme")

# 1. İmar Fonksiyon Seçimi
imar_fonksiyonu = st.selectbox(
    "İmar Fonksiyon Tipini Seçiniz:",
    [
        "Konut Alanı",
        "Ticaret Alanı",
        "Ticaret + Konut Alanı (TİCK / TCK)",
        "Turizm + Konut Alanı",
        "Turizm + Ticaret Alanı",
        "Sanayi / Depolama Alanı"
    ]
)

# 2. İmar Fonksiyonuna Göre Dinamik Proje Tipi Kuralları
proje_secenekleri = []

if imar_fonksiyonu == "Konut Alanı":
    proje_secenekleri = [
        "Müstakil Villa / İkiz Villa",
        "Toplu Konut / Apartman Blokları"
    ]

elif imar_fonksiyonu == "Ticaret Alanı":
    proje_secenekleri = [
        "Ticaret / Ofis / Dükkan İş Merkezi"
    ]

elif imar_fonksiyonu == "Ticaret + Konut Alanı (TİCK / TCK)":
    proje_secenekleri = [
        "Sadece Konut (Apartman / Site)",
        "Sadece Ticaret (Ofis / Dükkan)",
        "Karma Proje (Zemin Ticaret + Üst Katlar Konut)"
    ]

elif imar_fonksiyonu == "Turizm + Konut Alanı":
    proje_secenekleri = [
        "Sadece Konut",
        "Otel / Turizm Tesisi",
        "Karma (Turizm + Konut / Rezidans)"
    ]

elif imar_fonksiyonu == "Turizm + Ticaret Alanı":
    proje_secenekleri = [
        "Sadece Ticaret / Ofis",
        "Otel / Turizm Tesisi",
        "Karma (Turizm + Ticaret / AVM)"
    ]

elif imar_fonksiyonu == "Sanayi / Depolama Alanı":
    proje_secenekleri = [
        "Fabrika / Üretim Tesisi",
        "Lojistik / Depolama Tesisi"
    ]

# 3. Dinamik Seçim Arayüzü
secilen_proje_tipi = st.selectbox(
    "Geliştirilecek Proje Tipini Seçiniz:",
    options=proje_secenekleri
)

st.divider()

# 4. Seçilen Kombinasyon Özet Görünümü
st.subheader("Seçim Özeti")
col1, col2 = st.columns(2)

with col1:
    st.info(f"**İmar Fonksiyonu:** {imar_fonksiyonu}")

with col2:
    st.success(f"**Seçilen Proje Tipi:** {secilen_proje_tipi}")

# 5. Hesaplama & Mantıksal Kontrol Bloğu
st.write("---")
if st.button("Fizibilite Modelini Çalıştır"):
    st.write(f"**{imar_fonksiyonu}** şartlarına uygun olarak **{secilen_proje_tipi}** modellemesi başlatılıyor...")
    
    # Alt hesaplama detayları mantıksal kırılıma göre buraya eklenebilir
    if "Karma" in secilen_proje_tipi:
        st.caption("Not: Karma projelerde Ticaret ve Konut emsal paylaşımları hesaplamaya dahil edilecektir.")
    elif "Villa" in secilen_proje_tipi:
        st.caption("Not: Villa projelerinde minimum parsel büyüklükleri ve bahçe payları esas alınacaktır.")
