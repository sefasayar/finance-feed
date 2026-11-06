import feedparser
import json
import os
from datetime import datetime
from google import genai
from google.genai import types

# Yeni Gemini API Bağlantısı
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

# Çoklu RSS Kaynakları
rss_kaynaklari = [
    "https://www.trthaber.com/ekonomi_articles.rss",
    "https://www.ntv.com.tr/ekonomi.rss"
]

def haberi_yorumla(metin):
    if not client:
        print("KRİTİK HATA: GEMINI_API_KEY bulunamadı!")
        return {"ozet": "API Anahtarı eksik.", "piyasa_etkisi": "Sistem Hatası", "kategori": "Sistem"}
    
    if not metin or len(metin.strip()) < 10:
        return {"ozet": "Haber detayı bulunamadı.", "piyasa_etkisi": "Nötr", "kategori": "Kısa Haber"}

    prompt = f"Şu haberi oku ve analiz et. Haber: {metin[:600]}"
    
    try:
        # Yeni kütüphane yapısı ve güncel model (gemini-2.5-flash)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
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
        print(f"Yapay Zeka Hatası: {str(e)}")
        return {"ozet": "Yorumlama hatası, detaylar logda.", "piyasa_etkisi": "Belirsiz", "kategori": "Hata"}

yeni_haberler = []

# Kaynakları Tarama
for url in rss_kaynaklari:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            ham_metin = getattr(entry, 'summary', getattr(entry, 'description', entry.title))
            ai_sonuc = haberi_yorumla(ham_metin)
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            yeni_haberler.append({
                "baslik": entry.title,
                "ozet": ai_sonuc.get("ozet", ""),
                "piyasa_etkisi": ai_sonuc.get("piyasa_etkisi", ""),
                "kategori": ai_sonuc.get("kategori", "Ekonomi"),
                "zaman": zaman
            })
    except Exception as e:
        print(f"RSS Kaynak Hatası ({url}): {str(e)}")
        continue

# Veri Döngüsü (Sadece son 50 haberi tut)
mevcut_haberler = []
try:
    with open("haberler.json", "r", encoding="utf-8") as f:
        mevcut_haberler = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

tum_haberler = yeni_haberler + mevcut_haberler
tekil_haberler = {haber["baslik"]: haber for haber in tum_haberler}.values()
final_liste = list(tekil_haberler)[:50]

with open("haberler.json", "w", encoding="utf-8") as f:
    json.dump(final_liste, f, ensure_ascii=False, indent=4)
