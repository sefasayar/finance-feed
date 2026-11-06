import feedparser
import json
import os
import time
from datetime import datetime
from google import genai
from google.genai import types

MODEL = "gemini-3.8-flash"
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

rss_kaynaklari = [
    "https://www.trthaber.com/ekonomi_articles.rss",
    "https://www.ntv.com.tr/ekonomi.rss"
]

def haberi_yorumla(metin):
    """Başarılıysa sözlük, başarısızsa None döner (None kaydedilmez)."""
    if not client:
        print("HATA: GEMINI_API_KEY bulunamadı")
        return None
    if not metin or len(metin.strip()) < 10:
        return None

    prompt = f"Şu haberi oku ve analiz et. Haber: {metin[:600]}"
    for deneme in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "ozet": {"type": "STRING", "description": "Haberin 2 cümlelik özeti"},
                            "piyasa_etkisi": {"type": "STRING", "description": "Piyasaya olası etkisi"},
                            "kategori": {"type": "STRING", "description": "Makro, Borsa veya Kripto"}
                        },
                        "required": ["ozet", "piyasa_etkisi", "kategori"]
                    }
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"   -> AI hatası (deneme {deneme+1}/3): {e}")
            time.sleep(8)
    return None

# Mevcut haberleri önce yükle
mevcut_haberler = []
try:
    with open("haberler.json", "r", encoding="utf-8") as f:
        mevcut_haberler = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

# Hatalı eski kayıtları temizle
HATALI = {"Hata", "Sistem", "Sistem Yoğun", "Kısa Haber"}
mevcut_haberler = [h for h in mevcut_haberler if h.get("kategori") not in HATALI]
bilinen = {h["baslik"] for h in mevcut_haberler}

yeni_haberler = []
for url in rss_kaynaklari:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            if entry.title in bilinen:
                continue  # zaten işlenmiş, kota harcama
            ham_metin = getattr(entry, "summary", getattr(entry, "description", entry.title))
            ai_sonuc = haberi_yorumla(ham_metin)
            if not ai_sonuc:
                continue  # başarısızsa kaydetme, sonraki saatte tekrar dene
            yeni_haberler.append({
                "baslik": entry.title,
                "ozet": ai_sonuc["ozet"],
                "piyasa_etkisi": ai_sonuc["piyasa_etkisi"],
                "kategori": ai_sonuc["kategori"],
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            time.sleep(4)  # ücretsiz katman dakikalık limitine saygı
    except Exception as e:
        print(f"RSS Kaynak Hatası ({url}): {e}")

final_liste = (yeni_haberler + mevcut_haberler)[:50]

with open("haberler.json", "w", encoding="utf-8") as f:
    json.dump(final_liste, f, ensure_ascii=False, indent=4)

print(f"Tamam: {len(yeni_haberler)} yeni haber eklendi.")
