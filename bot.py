import feedparser
from google import genai
import json
import os
import re

# 1. Yeni Google GenAI SDK Kurulumu
GOOGLE_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

# Yahoo yerine CNBC RSS adresi kullanıyoruz (GitHub engeline takılmaz)
RSS_URL = "https://search.cnbc.com/rs/search/combinedrenderer/view.xml?partnerId=2000&keywords=finance&target=all"

def extract_json(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return match.group(0)
    return text

def fetch_and_process_news():
    print("RSS Feed okunuyor...")
    
    # User-Agent ekleyerek Yahoo Finance engellemesini aşıyoruz
    feed = feedparser.parse(RSS_URL, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    print(f"Çekilen haber sayısı: {len(feed.entries)}")
    
    file_path = 'data/news.json'
    existing_news = []
    
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_news = json.load(f)
        except Exception:
            existing_news = []

    new_items = []
    
    for entry in feed.entries[:5]:
        title = entry.title
        summary = getattr(entry, 'summary', title)
        link = entry.link
        
        # Mükerrer haber kontrolü
        if any(item.get('original_link') == link for item in existing_news):
            print(f"Zaten mevcut, atlanıyor: {title}")
            continue

        print(f"İşleniyor: {title}")
        
        prompt = f"""
        You are a professional financial journalist. Rewrite the following financial news into an engaging, 
        SEO-friendly, high-quality 2-paragraph article in English.
        Do not copy the original text word-for-word.

        Original Title: {title}
        Original Summary: {summary}

        Return ONLY a valid JSON object matching this schema, without any markdown formatting:
        {{
            "title": "Catchy English Title",
            "content": "<p>First paragraph of the news.</p><p>Second paragraph of the news.</p>"
        }}
        """
        
        try:
            # Yeni SDK ile Gemini API çağrısı
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            json_str = extract_json(response.text)
            processed_news = json.loads(json_str)
            
            new_items.append({
                "original_link": link,
                "title": processed_news.get("title", title),
                "content": processed_news.get("content", f"<p>{summary}</p>")
            })
            print(f"Başarıyla işlendi: {title}")
        except Exception as e:
            print(f"Yapay zeka ayrıştırma uyarısı ({e}), ham haber ekleniyor.")
            new_items.append({
                "original_link": link,
                "title": title,
                "content": f"<p>{summary}</p>"
            })

    # Verileri birleştir ve yaz
    if new_items:
        combined_news = new_items + existing_news
        final_news = combined_news[:20]
        
        os.makedirs('data', exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(final_news, f, ensure_ascii=False, indent=4)
        print(f"İşlem Tamamlandı: {len(new_items)} yeni haber kaydedildi.")
    else:
        print("Yeni haber bulunamadı veya RSS boş döndü.")

if __name__ == "__main__":
    fetch_and_process_news()
