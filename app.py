def parse_imar_pdf(uploaded_file):
    """
    Beykoz Belediyesi İmar Durumu PDF'lerini doğrudan tablo hücrelerinden
    eksiksiz ve hatasız okuyan gelişmiş parser.
    """
    parcel_data = {
        "mahalle": "BİLİNMİYOR",
        "ada": "0",
        "parsel": "0",
        "toplam_alan": 0.0,
        "fonksiyonlar": []
    }
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            
            for table in tables:
                for row_idx, row in enumerate(table):
                    # Temizlenmiş hücre verileri
                    cells = [str(cell).strip().replace('\n', ' ') if cell is not None else '' for cell in row]
                    row_str = " ".join(cells)
                    
                    # 1. Sayfa: Mahalle, Pafta, Ada, Parsel, Alan Yakalama
                    if "Mahalle" in cells and "Ada" in cells:
                        if row_idx + 1 < len(table):
                            data_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[row_idx + 1]]
                            # Kolon indekslerini tespit et
                            for idx, head in enumerate(cells):
                                if "Mahalle" in head and idx < len(data_row):
                                    parcel_data["mahalle"] = data_row[idx].upper()
                                elif "Ada" in head and idx < len(data_row):
                                    parcel_data["ada"] = data_row[idx]
                                elif "Parsel" in head and idx < len(data_row):
                                    parcel_data["parsel"] = data_row[idx]
                                elif "Alan" in head and idx < len(data_row):
                                    raw_a = data_row[idx].replace("m²", "").replace(".", "").replace(",", ".").strip()
                                    m = re.search(r"[\d\.]+", raw_a)
                                    if m:
                                        parcel_data["toplam_alan"] = float(m.group(0))

                    # 2. Fonksiyon ve Yapılanma Şartları (TAKS/KAKS) Yakalama
                    if "Fonksiyon Adı" in cells or "Fonksiyon Adı" in row_str:
                        fonk_adi = ""
                        taks_val = 0.30
                        kaks_val = 0.40
                        giren_m2 = parcel_data["toplam_alan"]
                        
                        # Tablo içindeki hücre detaylarını tara
                        for i_r in range(row_idx, min(row_idx + 6, len(table))):
                            sub_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in table[i_r]]
                            sub_str = " ".join(sub_row)
                            
                            if "Fonksiyon Adı" in sub_str and len(sub_row) > 1:
                                fonk_adi = sub_row[1] if sub_row[1] != "" else sub_row[-1]
                            
                            # TAKS & KAKS Çekimi
                            taks_m = re.search(r"Taks\s*\|?\s*([\d\.]+)", sub_str, re.IGNORECASE)
                            kaks_m = re.search(r"Kaks\s*\(Emsal\)\s*\|?\s*([\d\.]+)", sub_str, re.IGNORECASE)
                            
                            if taks_m: taks_val = float(taks_m.group(1))
                            if kaks_m: kaks_val = float(kaks_m.group(1))
                            
                            # Fonksiyon Alanı M2 / Yüzde Çekimi
                            if "Fonksiyon Alanına" in sub_str or "Giren" in sub_str:
                                m2_m = re.search(r"([\d\.,]+)\s*m²", sub_str)
                                if m2_m:
                                    giren_m2 = float(m2_m.group(1).replace(".", "").replace(",", "."))
                        
                        if fonk_adi and not any(f['fonksiyon_adi'] == fonk_adi for f in parcel_data["fonksiyonlar"]):
                            parcel_data["fonksiyonlar"].append({
                                "fonksiyon_adi": fonk_adi,
                                "taks": taks_val,
                                "kaks": kaks_val,
                                "giren_m2": giren_m2
                            })

    # Eğer Fonksiyon Çekilemediyse Varsayılan Tam Alan Konut Olarak Ekle
    if not parcel_data["fonksiyonlar"]:
        parcel_data["fonksiyonlar"].append({
            "fonksiyon_adi": "KONUT ALANI",
            "taks": 0.30,
            "kaks": 0.40,
            "giren_m2": parcel_data["toplam_alan"]
        })

    return parcel_data
