with tab3:
        st.subheader("🏛️ Mimari Fizibilite ve Bağımsız Bölüm Senaryoları")
        st.info("ℹ️ **İmar Kuralı:** Havuz veya sosyal tesisler yasal emsal tavanını aşamaz. Seçilen havuz alanı toplam yasal emsal hakkından düşülerek net konut/villa alanları otomatik olarak daraltılır.")
        
        # Proje tipine göre ideal ortalama bağımsız bölüm büyüklüğü hedefi (m²)
        hedef_birim_alanlar = {
            "Lüks Villa / Müstakil Proje": 250.0,
            "Üst Segment Konut / Rezidans": 150.0,
            "Standart Konut / Apartman": 100.0,
            "Ticari / Ofis Kompleksi": 200.0,
            "Karma Proje (Konut + Ticari)": 130.0
        }
        secilen_hedef_alan = hedef_birim_alanlar.get(selected_proje_tipi, 120.0)
        
        # Otomatik ideal bağımsız bölüm adedini hesapla (Minimum 1 olacak şekilde)
        tahmini_ideal_adet = max(1, round(yasal_max_emsal_alani / secilen_hedef_alan))

        # Eğer kullanıcı daha önce değiştirdiyse veya ilk kez giriliyorsa otomatik değeri ata
        if "hedef_bagimsiz_bolum" not in st.session_state:
            st.session_state["hedef_bagimsiz_bolum"] = tahmini_ideal_adet

        col_mims1, col_mims2 = st.columns(2)
        with col_mims1:
            hedef_bagimsiz_bolum = st.number_input(
                "Planlanan Bağımsız Bölüm / Villa Adedi:", 
                min_value=1, 
                value=int(st.session_state["hedef_bagimsiz_bolum"]), 
                step=1, 
                key="hb_input",
                help=f"Seçilen '{selected_proje_tipi}' tipi için piyasa bazlı önerilen ideal ünite adedi: {tahmini_ideal_adet}"
            )
            st.session_state["hedef_bagimsiz_bolum"] = hedef_bagimsiz_bolum
            
        with col_mims2:
            havuz_tercihi = st.selectbox(
                "Havuz Planlama Modeli:", 
                options=["Her Bağımsız Bölüme 1 Özel Havuz", "Ortak / Sosyal Tesis Havuzu", "Havuz İptal (Küçük Ölçek Kısıtı)"],
                index=["Her Bağımsız Bölüme 1 Özel Havuz", "Ortak / Sosyal Tesis Havuzu", "Havuz İptal (Küçük Ölçek Kısıtı)"].index(st.session_state["havuz_tercihi"]),
                key="hp_select"
            )
        st.session_state["havuz_tercihi"] = havuz_tercihi
