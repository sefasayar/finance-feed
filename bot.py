import feedparser
import html
import json
import os
import re
import sys
import time
from calendar import timegm
from datetime import datetime, timezone
from difflib import SequenceMatcher

from google import genai
from google.genai import types

print("Finance Feed bot starting...")

NEWS_FILE = "data/news.json"
ARCHIVE_FILE = "data/archive.json"      # written by build_site.py, read here to avoid re-adding old stories
REJECTED_FILE = "data/rejected.json"    # links the AI judged off-topic, so they are not sent again

# Tried in order. If one is out of quota (429) or missing (404), the next one is used.
MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]

# Sources that include a real description in the RSS entry (Google News does not).
FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
]

PER_SOURCE = 3        # candidate stories taken per source per run (9 total, still 1 AI request)
MAX_KEEP = 25         # stories kept in news.json (older ones live on in data/archive.json)
MAX_REJECTED = 1000   # rejected links remembered
MAX_AGE_HOURS = 36    # ignore stories older than this
MIN_SNIPPET = 80      # ignore entries whose description is too short to summarize
MIN_INDEX_SNIPPET_CHARS = 150  # enough room for multiple source details, not a Google word-count rule
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ALLOWED_TAGS = ["STOCKS", "FED", "CRYPTO", "TECH", "ECONOMY", "COMMODITIES", "FOREX", "EARNINGS"]
ALLOWED_SENTIMENT = {"BULLISH", "BEARISH", "NEUTRAL"}

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER"},
            "relevant": {"type": "BOOLEAN"},
            "title": {"type": "STRING"},
            "tag": {"type": "STRING"},
            "sentiment": {"type": "STRING"},
            "summary": {"type": "STRING"},
            "impact": {"type": "STRING"},
            "analysis": {"type": "STRING"},
            "watch": {"type": "STRING"},
            "key_facts": {"type": "ARRAY", "items": {"type": "STRING"}},
            "tickers": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["id", "relevant", "title", "tag", "sentiment", "summary",
                     "impact", "analysis", "watch", "key_facts", "tickers"],
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
- relevant: true only if the story is mainly about financial markets, the economy, central banks, a company's business or earnings, commodities, currencies, crypto, or policy with a clear economic effect. false for politics without economic substance, personal-finance advice columns or reader questions, lifestyle, sports, entertainment and human-interest stories
- title: a clear headline under 90 characters, rewritten in your own words
- Keep the named company/person, action and central figure or date from the source when relevant. Do not add a keyword that is not supported by the headline or snippet. Avoid clickbait and vague headlines.
- tag: exactly one of {", ".join(ALLOWED_TAGS)}
- sentiment: BULLISH, BEARISH or NEUTRAL (the likely tone for markets)
- summary: 2 concise sentences explaining what happened. It must NOT repeat or paraphrase the title. Use specific facts and figures only when they appear in the supplied headline or snippet.
- impact: 1 to 3 words on the likely market effect
- analysis: 2 concise sentences. In the first, point to the most decision-relevant fact in the supplied text. In the second, explain a limited implication for the named company, asset or sector, and state what the snippet does not establish. Avoid generic market commentary, unsupported causes, predictions, and claims about broader trends. If no meaningful implication is supported, say so plainly.
- watch: one concise sentence naming a specific follow-up event only if it is mentioned or clearly established by the supplied text. Otherwise return an empty string. Do not invent dates, events, filings, or data releases.
- key_facts: 2 or 3 short, paraphrased details from the supplied snippet that are not already stated in the title or summary. Use only details explicitly present in the snippet. Return an empty list if the snippet does not support at least two distinct details. Never add background knowledge.
- tickers: stock tickers (for example NVDA) ONLY for companies explicitly named in the story and only when you are certain of the US ticker. Otherwise an empty list. Maximum 4.
For stories with relevant=false, keep the other fields short.
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


def load_json_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Could not read {path}: {e}")
        return []


def entry_time(entry, now):
    """Real publish time of the RSS entry (UTC), capped at now. None if the feed has no date."""
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not t:
        return None
    try:
        when = datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    except Exception:
        return None
    return min(when, now)


def collect_candidates(seen_links, now):
    candidates = []
    for name, url in FEEDS:
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception as e:
            print(f"{name}: feed error: {e}")
            continue
        taken = 0
        for entry in feed.entries[:20]:
            link = getattr(entry, "link", "")
            title = clean(getattr(entry, "title", ""))
            snippet = clean(getattr(entry, "summary", getattr(entry, "description", "")))
            if not link or not title or link in seen_links:
                continue
            if len(snippet) < MIN_SNIPPET:
                continue
            when = entry_time(entry, now)
            if when and (now - when).total_seconds() > MAX_AGE_HOURS * 3600:
                continue
            candidates.append({
                "source": name, "link": link, "title": title, "snippet": snippet,
                "published": (when or now).strftime("%Y-%m-%d %H:%M"),
            })
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


def clean_tickers(raw):
    out = []
    for t in raw if isinstance(raw, list) else []:
        t = str(t).strip().upper().lstrip("$")
        if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", t) and t not in out:
            out.append(t)
    return out[:4]


FACT_STOPWORDS = {
    "a", "about", "after", "also", "an", "and", "are", "as", "at", "be", "been",
    "by", "for", "from", "has", "have", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "their", "there", "this", "to", "was", "were", "which", "with",
    "market", "markets", "investor", "investors", "company", "companies", "business",
    "financial", "sector", "sectors", "impact", "likely", "could", "may", "might",
}


def fact_tokens(text):
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(t) > 1 and t not in FACT_STOPWORDS}


def supported_key_facts(raw, title, summary, evidence):
    """Keep only distinct fact bullets with visible lexical support in the RSS input."""
    kept = []
    evidence_tokens = fact_tokens(evidence)
    comparison_texts = [title.lower(), summary.lower()]
    for value in raw if isinstance(raw, list) else []:
        fact = clean(str(value))
        tokens = fact_tokens(fact)
        if len(tokens) < 3:
            continue
        overlap = len(tokens & evidence_tokens) / len(tokens)
        if overlap < 0.4:
            continue
        if any(SequenceMatcher(None, fact.lower(), text).ratio() >= 0.82
               for text in comparison_texts):
            continue
        if any(SequenceMatcher(None, fact.lower(), previous.lower()).ratio() >= 0.78
               for previous in kept):
            continue
        kept.append(fact)
        if len(kept) == 3:
            break
    return kept


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is missing")
        sys.exit(1)
    client = genai.Client(api_key=api_key)
    now = datetime.now(timezone.utc)

    existing = load_json_list(NEWS_FILE)
    kept = [item for item in existing if not is_bad(item)]
    removed = len(existing) - len(kept)
    if removed:
        print(f"Removed {removed} low-quality old entries")

    rejected = [str(x) for x in load_json_list(REJECTED_FILE)]
    archived = {item.get("original_link") for item in load_json_list(ARCHIVE_FILE) if isinstance(item, dict)}
    seen_links = {item.get("original_link") for item in kept} | archived | set(rejected)

    candidates = collect_candidates(seen_links, now)
    new_items = []
    new_rejected = []

    if candidates:
        print(f"Sending {len(candidates)} stories to the AI in one request...")
        results = analyze(client, candidates)
        if not results:
            # Fail loudly so GitHub emails you instead of the feed silently going stale.
            print("ERROR: AI analysis failed on every model. Nothing published this run.")
            sys.exit(1)

        for i, c in enumerate(candidates):
            r = results.get(i)
            if not r:
                continue  # AI skipped this story: do not publish, retry next run
            if r.get("relevant") is False:
                print(f"Skipped (off-topic): {c['title'][:70]}")
                new_rejected.append(c["link"])
                continue
            summary = clean(r.get("summary", ""))
            analysis = clean(r.get("analysis", ""))
            if echoes_title(summary, c["title"]) or len(analysis) < 40:
                print(f"Skipped (summary too weak): {c['title'][:70]}")
                new_rejected.append(c["link"])
                continue

            ai_title = clean(r.get("title", ""))
            if not ai_title or len(ai_title) > 90:
                ai_title = c["title"]
            key_facts = supported_key_facts(
                r.get("key_facts"), ai_title, summary, f"{c['title']} {c['snippet']}"
            )
            analysis_tokens = fact_tokens(analysis)
            evidence_tokens = fact_tokens(f"{c['title']} {c['snippet']}")
            analysis_specific = len(analysis_tokens & evidence_tokens) >= 2
            seo_indexability_reasons = []
            if len(c["snippet"]) < MIN_INDEX_SNIPPET_CHARS:
                seo_indexability_reasons.append("source_description_too_short")
            if len(key_facts) < 2:
                seo_indexability_reasons.append("fewer_than_two_supported_facts")
            if not analysis_specific:
                seo_indexability_reasons.append("analysis_not_specific_enough_to_source")
            if not c.get("published"):
                seo_indexability_reasons.append("missing_publication_date")
            if not c.get("link"):
                seo_indexability_reasons.append("missing_source_link")
            # This is a conservative eligibility screen, not a Google ranking rule.
            # Short/weak items still publish in the feed, but their story pages stay noindex.
            seo_indexable = not seo_indexability_reasons
            print(
                f"SEO gate {'PASS' if seo_indexable else 'NOINDEX'} "
                f"({', '.join(seo_indexability_reasons) or 'source detail and context passed'}): "
                f"{c['title'][:70]}"
            )

            tag = str(r.get("tag", "")).upper()
            sentiment = str(r.get("sentiment", "")).upper()
            watch = clean(r.get("watch", ""))
            content = f"<p>{html.escape(analysis)}</p>"
            if len(watch) >= 20:
                content += f"<p><strong>What to watch:</strong> {html.escape(watch)}</p>"

            item = {
                "original_link": c["link"],
                "source": c["source"],
                "published": c["published"],
                "title": ai_title,
                "tag": tag if tag in ALLOWED_TAGS else "MARKET",
                "sentiment": sentiment if sentiment in ALLOWED_SENTIMENT else "NEUTRAL",
                "ai_summary": summary,
                "market_impact": clean(r.get("impact", "")) or "Unclear",
                "key_facts": key_facts,
                "seo_indexable": seo_indexable,
                "seo_indexability_reasons": seo_indexability_reasons,
                "source_description_chars": len(c["snippet"]),
                "analysis": analysis,
                "what_to_watch": watch,
                # AI text is escaped, so it is safe to render as HTML.
                "content": content,
            }
            tickers = clean_tickers(r.get("tickers"))
            if tickers:
                item["tickers"] = tickers
            new_items.append(item)
    else:
        print("No new usable stories.")

    if new_rejected:
        os.makedirs("data", exist_ok=True)
        with open(REJECTED_FILE, "w", encoding="utf-8") as f:
            json.dump((rejected + new_rejected)[-MAX_REJECTED:], f, ensure_ascii=False, indent=1)

    if new_items or removed:
        combined = sorted(new_items + kept, key=lambda x: str(x.get("published", "")), reverse=True)
        final = combined[:MAX_KEEP]
        os.makedirs("data", exist_ok=True)
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=4)

    print(f"Done: {len(new_items)} new stories added, {len(new_rejected)} rejected.")


if __name__ == "__main__":
    main()
