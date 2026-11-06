import feedparser
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher

from google import genai
from google.genai import types

print("Finance Feed bot starting...")

SITE_URL = "https://sefasayar.github.io/finance-feed/"
NEWS_FILE = "data/news.json"

# Tried in order. If one is out of quota (429) or missing (404), the next one is used.
MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]

# Sources that include a real description in the RSS entry (Google News does not).
FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
]

PER_SOURCE = 2       # new stories taken per source per run (6 total, 1 AI request)
MAX_KEEP = 25        # stories kept in news.json
MIN_SNIPPET = 80     # ignore entries whose description is too short to summarize
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ALLOWED_TAGS = ["STOCKS", "FED", "CRYPTO", "TECH", "ECONOMY", "COMMODITIES", "FOREX", "EARNINGS"]
ALLOWED_SENTIMENT = {"BULLISH", "BEARISH", "NEUTRAL"}

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER"},
            "title": {"type": "STRING"},
            "tag": {"type": "STRING"},
            "sentiment": {"type": "STRING"},
            "summary": {"type": "STRING"},
            "impact": {"type": "STRING"},
            "analysis": {"type": "STRING"},
        },
        "required": ["id", "title", "tag", "sentiment", "summary", "impact", "analysis"],
    },
}

INSTRUCTIONS = f"""You are a careful financial news editor.
For each story below, write original English text based ONLY on the facts in its title and snippet.
Rules:
- Do not invent numbers, names, causes, dates or quotes that are not in the story.
- Never give investment advice. Never say buy, sell or hold.
- Use cautious wording for effects (could, may, suggests).
Fields for each story:
- id: the number in square brackets, unchanged
- title: a clear headline under 90 characters, rewritten in your own words
- tag: exactly one of {", ".join(ALLOWED_TAGS)}
- sentiment: BULLISH, BEARISH or NEUTRAL (the likely tone for markets)
- summary: 2 sentences explaining what happened. It must NOT repeat or paraphrase the title.
- impact: 1 to 3 words on the likely market effect
- analysis: 2 to 3 sentences on why this matters to markets and what to watch
"""


def clean(text):
    """Strip HTML tags and extra whitespace from RSS text."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def echoes_title(summary, title):
    """True when a summary is too short or just repeats the title."""
    s, t = summary.lower().strip(), title.lower().strip()
    if len(s) < 40:
        return True
    if t and t in s:
        return True
    return SequenceMatcher(None, s, t).ratio() > 0.75


def is_bad(item):
    """Detects old raw-fallback entries and empty summaries so they get removed."""
    if item.get("tag") == "MARKET" and item.get("market_impact") == "Stable":
        return True
    return echoes_title(item.get("ai_summary", ""), item.get("title", ""))


def load_news():
    if not os.path.exists(NEWS_FILE):
        return []
    try:
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Could not read {NEWS_FILE}: {e}")
        return []


def collect_candidates(seen_links):
    candidates = []
    for name, url in FEEDS:
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception as e:
            print(f"{name}: feed error: {e}")
            continue
        taken = 0
        for entry in feed.entries[:15]:
            link = getattr(entry, "link", "")
            title = clean(getattr(entry, "title", ""))
            snippet = clean(getattr(entry, "summary", getattr(entry, "description", "")))
            if not link or not title or link in seen_links:
                continue
            if len(snippet) < MIN_SNIPPET:
                continue
            candidates.append({"source": name, "link": link, "title": title, "snippet": snippet})
            taken += 1
            if taken >= PER_SOURCE:
                break
        print(f"{name}: {len(feed.entries)} entries in feed, {taken} new and usable")
    return candidates


def analyze(client, candidates):
    """One batched request for all stories. Returns {index: result}, or {} on failure."""
    stories = "\n\n".join(
        f"[{i}] ({c['source']}) {c['title']}\n{c['snippet'][:600]}"
        for i, c in enumerate(candidates)
    )
    prompt = INSTRUCTIONS + "\nSTORIES:\n\n" + stories

    for model in MODELS:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=SCHEMA,
                        temperature=0.3,
                    ),
                )
                data = json.loads(response.text)
                print(f"AI OK with {model}")
                return {int(x["id"]): x for x in data}
            except Exception as e:
                msg = str(e)
                print(f"{model} error (attempt {attempt + 1}): {msg[:300]}")
                if any(k in msg for k in ("429", "404", "NOT_FOUND", "RESOURCE_EXHAUSTED")):
                    break  # quota or model problem: go to the next model
                time.sleep(10)  # temporary error such as 503: wait and retry once
    return {}


def write_sitemap():
    # Only the home page until each story gets its own page.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url>\n    <loc>{SITE_URL}</loc>\n    <lastmod>{today}</lastmod>\n"
        "    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>\n"
        "</urlset>\n"
    )
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(xml)


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is missing")
        sys.exit(1)
    client = genai.Client(api_key=api_key)

    existing = load_news()
    kept = [item for item in existing if not is_bad(item)]
    removed = len(existing) - len(kept)
    if removed:
        print(f"Removed {removed} low-quality old entries")
    seen_links = {item.get("original_link") for item in kept}

    candidates = collect_candidates(seen_links)
    new_items = []

    if candidates:
        print(f"Sending {len(candidates)} stories to the AI in one request...")
        results = analyze(client, candidates)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        for i, c in enumerate(candidates):
            r = results.get(i)
            if not r:
                continue  # AI failed for this story: do not publish, retry next run
            summary = clean(r.get("summary", ""))
            analysis = clean(r.get("analysis", ""))
            if echoes_title(summary, c["title"]) or len(analysis) < 40:
                print(f"Skipped (summary too weak): {c['title'][:70]}")
                continue

            tag = str(r.get("tag", "")).upper()
            sentiment = str(r.get("sentiment", "")).upper()
            new_items.append({
                "original_link": c["link"],
                "source": c["source"],
                "published": now,
                "title": clean(r.get("title", "")) or c["title"],
                "tag": tag if tag in ALLOWED_TAGS else "MARKET",
                "sentiment": sentiment if sentiment in ALLOWED_SENTIMENT else "NEUTRAL",
                "ai_summary": summary,
                "market_impact": clean(r.get("impact", "")) or "Unclear",
                # AI text is escaped, so it is safe to render as HTML.
                "content": f"<p>{html.escape(analysis)}</p>",
            })
    else:
        print("No new usable stories.")

    if new_items or removed:
        final = (new_items + kept)[:MAX_KEEP]
        os.makedirs("data", exist_ok=True)
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=4)
        if new_items:
            write_sitemap()

    print(f"Done: {len(new_items)} new stories added.")


if __name__ == "__main__":
    main()
