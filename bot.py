import feedparser
from google import genai
import json
import os
import re

print("Bot başlatılıyor...")

# API Key kontrolü
GOOGLE_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    print("HATA: GEMINI_API_KEY ortam değişkeni bulunamadı!")
    exit(1)

client = genai.Client(api_key=GOOGLE_API_KEY)
RSS_URL = "https://news.google.com/rss/search?q=finance+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en"

def extract_json(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return match.group(0)
    return text

def fetch_and_process_news():
    print("Google News RSS Feed okunuyor...")
    feed = feedparser.parse(RSS_URL, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
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
        
        if any(item.get('original_link') == link for item in existing_news):
            continue

        print(f"İşleniyor: {title}")
        
        prompt = f"""
        You are a professional financial journalist. Rewrite the following financial news into an engaging, 
        SEO-friendly article in English. Also, extract 1 or 2 relevant market/stock tags (e.g., Stocks, Crypto, Fed, NASDAQ) 
        and write a punchy 1-2 sentence AI summary.

        Original Title: {title}
        Original Summary: {summary}

        Return ONLY a valid JSON object matching this exact schema, without any markdown formatting:
        {{
            "title": "Catchy English Title",
            "tags": ["Tag1", "Tag2"],
            "ai_summary": "1-2 sentences brief summary of the news.",
            "content": "<p>First paragraph.</p><p>Second paragraph.</p>"
        }}
        """
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            json_str = extract_json(response.text)
            processed_news = json.loads(json_str)
            
            new_items.append({
                "original_link": link,
                "title": processed_news.get("title", title),
                "tags": processed_news.get("tags", ["Finance"]),
                "ai_summary": processed_news.get("ai_summary", summary[:150]),
                "content": processed_news.get("content", f"<p>{summary}</p>")
            })
            print(f"Başarıyla işlendi: {title}")
        except Exception as e:
            print(f"Yapay zeka hatası ({e}), ham veri ekleniyor.")
            new_items.append({
                "original_link": link,
                "title": title,
                "tags": ["Market"],
                "ai_summary": summary[:150],
                "content": f"<p>{summary}</p>"
            })

    if new_items:
        combined_news = new_items + existing_news
        final_news = combined_news[:20]
        
        os.makedirs('data', exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(final_news, f, ensure_ascii=False, indent=4)
        print(f"İşlem Tamamlandı: {len(new_items)} yeni haber kaydedildi.")
    else:
        print("Yeni eklenecek haber bulunamadı.")

if __name__ == "__main__":
    fetch_and_process_news()
