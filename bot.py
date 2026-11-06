import feedparser
import json
import os
from datetime import datetime
import google.generativeai as genai

# Gemini API Ayarı
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

# 1. Çoklu RSS Kaynakları
rss_kaynaklari = [
    "https://www.trthaber.com/ekonomi_articles.rss",
    "https://www.ntv.com.tr/ekonomi.rss"
]

def haberi_yorumla(metin):
    if not API_KEY:
        return {"ozet": "AI beklemede", "piyasa_etkisi": "Nötr", "kategori": "Genel"}
    
    # AI'ı katı bir JSON şemasına zorluyoruz
    prompt = f"""Şu haberi oku ve SADECE JSON formatında yanıt ver. Başka hiçbir metin veya markdown ekleme.
    Format: {{"ozet": "haberin 2 cümlelik özeti", "piyasa_etkisi": "piyasaya olası etkisi", "kategori": "Makro/Borsa/Kripto"}}
    Haber: {metin[:600]}"""
    
    try:
        response = model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_text) # Metni yapılandırılmış veriye dönüştür
    except Exception as e:
        return {"ozet": "Yapay zeka yorumlayamadı.", "piyasa_etkisi": "Belirsiz", "kategori": "Hata"}

yeni_haberler = []

# 2. Kaynakları Tarama ve Hata Toleransı
for url in rss_kaynaklari:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]: # Her kaynaktan en yeni 3 haberi al
            ai_sonuc = haberi_yorumla(entry.summary)
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            yeni_haberler.append({
                "baslik": entry.title,
                "ozet": ai_sonuc.get("ozet", ""),
                "piyasa_etkisi": ai_sonuc.get("piyasa_etkisi", ""),
                "kategori": ai_sonuc.get("kategori", "Ekonomi"),
                "zaman": zaman
            })
    except Exception as e:
        continue # Hatalı kaynağı atla, akışı bozma

# 3. Veri Döngüsü (Rolling Data): Sadece son 50 haberi tut
mevcut_haberler = []
try:
    with open("haberler.json", "r", encoding="utf-8") as f:
        mevcut_haberler = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

# Eski ve yeni veriyi birleştir, başlığa göre tekilleştir (mükerrer kayıtları engelle)
tum_haberler = yeni_haberler + mevcut_haberler
tekil_haberler = {haber["baslik"]: haber for haber in tum_haberler}.values()
final_liste = list(tekil_haberler)[:50] # En güncel 50 kaydı al

# JSON'a geri yaz
with open("haberler.json", "w", encoding="utf-8") as f:
    json.dump(final_liste, f, ensure_ascii=False, indent=4)
