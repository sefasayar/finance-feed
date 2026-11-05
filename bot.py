import feedparser
import json
import os
from datetime import datetime
import google.generativeai as genai

# Gemini Yapay Zeka Ayarları (API Anahtarını GitHub Secrets'tan alacak)
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

def haberi_yorumla(metin):
    if not API_KEY:
        return f"AI yorumu bekleniyor... Haber detayı: {metin[:150]}..."
    
    prompt = f"Şu ekonomi haberini finansal okuryazarlığı olan bir kitle için bülten tarzında özetle. Haberin piyasaya olası etkisini 1-2 cümleyle yorumla. Uzatmadan, çok net ve profesyonel bir dil kullan. Haber: {metin}"
    try:
        response = model.generate_content(prompt)
        return response.text.replace('\n', ' ').strip()
    except Exception as e:
        return "Yapay zeka özeti şu an oluşturulamıyor."

# Haberleri Çekme (TRT Ekonomi RSS)
rss_url = "https://www.trthaber.com/ekonomi_articles.rss"
feed = feedparser.parse(rss_url)

haberler = []
# Sadece en güncel 5 haberi alıyoruz
for entry in feed.entries[:5]:
    baslik = entry.title
    ham_metin = entry.summary
    
    # Haberi yapay zekaya gönderip yorumlatıyoruz
    ai_yorum = haberi_yorumla(ham_metin)
    
    zaman = datetime.now().strftime("%H:%M")
    
    haberler.append({
        "baslik": baslik,
        "ozet": ai_yorum,
        "kategori": "Makro Ekonomi",
        "zaman": zaman
    })

# Yeni verileri JSON dosyasına yaz
with open("haberler.json", "w", encoding="utf-8") as f:
    json.dump(haberler, f, ensure_ascii=False, indent=4)
