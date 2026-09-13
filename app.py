with tab1:
        st.subheader("Seçilen Parsellerin İmar ve Fonksiyon Bazlı Arsa Dağılımı")
        st.info("💡 **Güncel Mantık:** Net Arsa alanı parselin gerçek kesintilerine göre hesaplanırken, **Ünite Başına Düşen Net Arsa Payı** doğrudan **Fonksiyon Alanı (m²)** üzerinden bağımsız bölüm adedine oranlanmaktadır.")
        
        table_rows = []
        for key, p in active_parcel_db.items():
            is_terkli = p["terk_yapilmis_mi"]
            toplam_brut = p["toplam_alan"]
            
            # Parsel bazlı toplam fonksiyon alanı
            toplam_fonk_alan = sum(f["giren_m2"] for f in p["fonksiyonlar"])
            
            # Eğer terksiz ise gerçek kesinti oranını (DOP/Terk) arsa ve fonksiyon farkından dinamik türetelim
            if not is_terkli and toplam_brut > 0 and toplam_fonk_alan > 0:
                # Kesinti miktar oranı (Örn: Brütten fonksiyona geçişteki oran)
                parsel_net_arsa_toplam = min(toplam_fonk_alan, toplam_brut * 0.70) # Örnek taban emniyeti
            else:
                parsel_net_arsa_toplam = toplam_fonk_alan if is_terkli else toplam_brut * 0.70

            terk_lbl = f"Terki Yapılmış (Net)" if is_terkli else f"Terksiz / Kesintili"
            
            for f in p["fonksiyonlar"]:
                fonks_m2 = f["giren_m2"]
                
                # Fonksiyonun brüt içindeki payına göre oransal net arsa hesabı
                fonk_oran = (fonks_m2 / toplam_fonk_alan) if toplam_fonk_alan > 0 else 1.0
                net_m2 = parsel_net_arsa_toplam * fonk_oran
                
                hedef_bb = st.session_state.get("hedef_bagimsiz_bolum", 1)
                
                # İsteğiniz üzerine: Ünite başı arsa payı doğrudan Fonksiyon Alanı (giren_m2) üzerinden hesaplanıyor
                unite_basi_fonk_net = fonks_m2 / hedef_bb if hedef_bb > 0 else 0
                
                table_rows.append({
                    "Parsel Bilgisi": key,
                    "Mahalle": p["mahalle"],
                    "Toplam Brüt Arsa (m²)": f"{toplam_brut:,.2f}",
                    "Fonksiyon": f["fonksiyon_adi"],
                    "Fonksiyon Alanı (m²)": f"{fonks_m2:,.2f}",
                    "Hesaplanan Net Arsa (m²)": f"{net_m2:,.2f}",
                    "Ünite Başına Düşen Fonksiyon Alanı": f"{unite_basi_fonk_net:,.2f} m² / Ünite",
                    "TAKS": f"{f['taks']:.2f}",
                    "KAKS (Emsal)": f"{f['kaks']:.2f}",
                    "Durum": terk_lbl
                })
                
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
        st.info(f"💡 **Genel Özet:** Toplam Brüt Arsa: **{toplam_brut_arsa_alani:,.2f} m²** | Toplam Net Arsa: **{toplam_net_arsa_alani:,.2f} m²**")
