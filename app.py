import re
import pdfplumber
import pandas as pd

def extract_imar_data(pdf_path):
    """
    İmar durumu PDF'ini analiz eder. Değişken Kaks, Taks, Fonksiyon ve 
    Alan bilgilerini dinamik olarak çeker ve veritabanı formatına dönüştürür.
    """
    parsel_bilgileri = {
        "mahalle": None,
        "ada": None,
        "parsel": None,
        "toplam_alan": None,
        "fonksiyonlar": []
    }
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += "\n" + text
        
        # 1. Temel Arsa/Parsel Bilgilerini Yakalama
        mahalle_match = re.search(r"Mahalle\s*\|\s*([A-ZÇĞİÖŞÜ]+)", full_text)
        ada_match = re.search(r"Ada\s*\|\s*(\d+)", full_text)
        parsel_match = re.search(r"Parsel\s*\|\s*(\d+)", full_text)
        alan_match = re.search(r"Alan\s*\*?\s*\|\s*([\d\.,]+)\s*m²", full_text)
        
        if mahalle_match: parsel_bilgileri["mahalle"] = mahalle_match.group(1)
        if ada_match: parsel_bilgileri["ada"] = ada_match.group(1)
        if parsel_match: parsel_bilgileri["parsel"] = parsel_match.group(1)
        if alan_match: 
            raw_alan = alan_match.group(1).replace(".", "").replace(",", ".")
            parsel_bilgileri["toplam_alan"] = float(raw_alan)

        # 2. Dinamik Fonksiyon, Kaks ve Taks Analizi
        # Tablo veya metin üzerinden Fonksiyon Bloklarını Çekme
        fonksiyon_blocks = re.findall(
            r"Fonksiyon Adı\s*\|\s*([^\n|]+).*?Taks\s*\|\s*([\d\.]+).*?Kaks\s*\(Emsal\)\s*\|\s*([\d\.]+).*?Giren\s*\([^\)]+\)\s*\|\s*([^\n]+)",
            full_text, re.DOTALL
        )
        
        for block in fonksiyon_blocks:
            fonk_adi = block[0].strip()
            taks = float(block[1]) if block[1] else 0.0
            kaks = float(block[2]) if block[2] else 0.0
            giren_alan_raw = block[3].strip()
            
            # M2 hesabı ayrıştırma
            m2_match = re.search(r"([\d\.,]+)\s*m²", giren_alan_raw)
            giren_m2 = float(m2_match.group(1).replace(".", "").replace(",", ".")) if m2_match else 0.0
            
            parsel_bilgileri["fonksiyonlar"].append({
                "fonksiyon_adi": fonk_adi,
                "taks": taks,
                "kaks": kaks,
                "giren_m2": giren_m2
            })
            
    return parsel_bilgileri


class ImarDatabase:
    """
    Her yüklenen imar raporunu belleğe (veya SQLite/JSON'a) kaydeden 
    ve çakışmaları önleyen dinamik veritabanı yöneticisi.
    """
    def __init__(self):
        self.db = {}

    def add_report(self, pdf_path):
        parsed_data = extract_imar_data(pdf_path)
        # Unique Key: Mahalle_Ada_Parsel
        key = f"{parsed_data['mahalle']}_{parsed_data['ada']}_{parsed_data['parsel']}"
        
        # Dinamik Veri Kaydı
        self.db[key] = parsed_data
        return key

    def get_all_as_dataframe(self):
        """Hesaplama ve Streamlit tabloları için veriyi düzleştirir."""
        flat_list = []
        for key, data in self.db.items():
            for fonk in data["fonksiyonlar"]:
                flat_list.append({
                    "Kimlik (Key)": key,
                    "Mahalle": data["mahalle"],
                    "Ada": data["ada"],
                    "Parsel": data["parsel"],
                    "Toplam Arsa (m²)": data["toplam_alan"],
                    "Fonksiyon": fonk["fonksiyon_adi"],
                    "TAKS": fonk["taks"],
                    "KAKS (Emsal)": fonk["kaks"],
                    "Fonksiyon Alanı (m²)": fonk["giren_m2"]
                })
        return pd.DataFrame(flat_list)
