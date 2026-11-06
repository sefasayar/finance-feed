import feedparser
import google.generativeai as genai
import json
import os

# 1. Gemini API Ayarları (GitHub Secrets'tan alacak)
GOOGLE_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
# Hızlı ve ücretsiz olan modeli seçiyoruz
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. RSS Kaynağı (Yahoo Finance - Sınırsız ve Hızlı)
RSS_URL = "https://finance.yahoo.com/news/rssindex"

def fetch_and_process_news():
    print("RSS Feed okunuyor...")
    feed = feedparser.parse(RSS_URL)
    news_list = []
    
    # API limitlerini korumak ve her çalışmada en yeni haberleri almak için ilk 3 haberi seçiyoruz
    for entry in feed.entries[:3]:
        title = entry.title
        summary = entry.summary
        link = entry.link
        
        print(f"İşleniyor: {title}")
        
        # 3. Gemini İçin Sistem Promptu (Yapay Zeka Mimarisi)
        prompt = f"""
        Sen uzman bir finans gazetecisisin. Aşağıdaki son dakika haberini İngilizce dilinde, 
        SEO uyumlu, profesyonel ve okuyucuya değer katan 2-3 paragraflık özgün bir makaleye dönüştür.
        Orijinal haberi asla birebir kopyalama.
        
        Orijinal Başlık: {title}
        Orijinal Özet: {summary}
        
        Lütfen cevabını SADECE aşağıdaki JSON formatında ver, başına sonuna hiçbir metin veya markdown işareti (```json gibi) ekleme:
        {{
            "title": "Özgün ve Tıklanabilir İngilizce Başlık",
            "content": "<p>Haberin birinci paragrafı</p><p>Haberin ikinci paragrafı</p>"
        }}
        """
        
        try:
            # Gemini'ye istek at
            response = model.generate_content(prompt)
            
            # Gelen metni temizle ve JSON'a çevir
            result_text = response.text.replace("```json", "").replace("```", "").strip()
            processed_news = json.loads(result_text)
            
            # Listeye ekle
            news_list.append({
                "original_link": link,
                "title": processed_news.get("title", title),
                "content": processed_news.get("content", summary)
            })
            print("Başarılı!")
        except Exception as e:
            print(f"Yapay Zeka İşlem Hatası: {e}")
    
    # 4. Sonuçları JSON dosyasına kaydetme
    os.makedirs('data', exist_ok=True)
    with open('data/news.json', 'w', encoding='utf-8') as f:
        json.dump(news_list, f, ensure_ascii=False, indent=4)
        
    print("Tüm işlemler tamamlandı ve data/news.json güncellendi!")

if __name__ == "__main__":
    fetch_and_process_news()
