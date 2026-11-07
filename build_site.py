#!/usr/bin/env python3
"""Finance Feed static site builder (standard library only).

Reads data/news.json (written by bot.py) and generates:
  news/<slug>.html     one page per story
  daily/<date>.html    daily digest pages, plus daily/index.html
  tag/<tag>.html       category hubs
  feed.xml             RSS feed (also useful for social automation later)
  sitemap.xml          real URLs only
and fills the <!-- FEED:START --> ... <!-- FEED:END --> block in index.html.

Design rules:
- Output is deterministic (no build timestamps), so git only sees a change
  when the content really changed.
- Nothing is ever deleted. data/archive.json keeps every story ever seen, so
  old pages stay online after they drop out of news.json (which keeps 25).
- Thin pages are noindex until they have enough words (MIN_WORDS_TO_INDEX).
"""
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlparse

# ---------------------------------------------------------------- settings
SITE_URL = os.environ.get("SITE_URL", "https://sefasayar.github.io/finance-feed/").rstrip("/") + "/"
BASE = urlparse(SITE_URL).path or "/"        # "/finance-feed/" now, "/" on a custom domain
SITE_NAME = "Finance Feed"
TAGLINE = "Market-moving news, read by AI."

NEWS_FILE = "data/news.json"
ARCHIVE_FILE = "data/archive.json"
INDEX_FILE = "index.html"
STATIC_PAGES = ["about.html", "privacy.html", "disclaimer.html"]

MIN_WORDS_TO_INDEX = 120   # story pages below this stay noindex (set 0 to index all)
MIN_DAILY_ITEMS = 3        # a digest page needs at least this many stories
MIN_TAG_ITEMS = 5          # a category hub is indexable from this many stories
TAG_PAGE_LIMIT = 60
FEED_LIMIT = 30
HOME_LIMIT = 25
RELATED = 4

TAG_NAMES = {
    "STOCKS": "Stocks", "FED": "Federal Reserve", "CRYPTO": "Crypto", "TECH": "Tech",
    "ECONOMY": "Economy", "COMMODITIES": "Commodities", "FOREX": "Forex",
    "EARNINGS": "Earnings", "MARKET": "Markets",
}
DIRS = {
    "BULLISH": ("positive", "\u25B2 Bullish"),
    "BEARISH": ("negative", "\u25BC Bearish"),
    "NEUTRAL": ("neutral", "\u25CF Neutral"),
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
stats = Counter()


# ---------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s), quote=True)


def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def paragraphs(content_html):
    parts = re.split(r"</p\s*>|<br\s*/?>", str(content_html or ""), flags=re.I)
    return [t for t in (clean_text(p) for p in parts) if t]


def shorten(text, limit):
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "\u2026"


def slugify(text, limit=60):
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    if len(t) > limit:
        t = t[:limit].rsplit("-", 1)[0] or t[:limit]
    return t or "story"


def short_hash(s, n=6):
    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:n]


def slug_for(raw):
    key = raw.get("original_link") or raw.get("title") or ""
    return f"{slugify(raw.get('title'))}-{short_hash(key)}"


def parse_time(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fmt_dt(d):
    return f"{d.strftime('%b')} {d.day}, {d.year} {d.strftime('%H:%M')} UTC"


def fmt_day(day):
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def tag_slug(tag):
    return re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-") or "market"


def tag_name(tag):
    return TAG_NAMES.get(tag, tag.title())


def safe_url(u):
    u = str(u or "").strip()
    return u if re.match(r"^https?://", u, re.I) else None


def load_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        sys.exit(f"ERROR: cannot read {path}: {e}")
    if not isinstance(data, list):
        sys.exit(f"ERROR: {path} must contain a JSON list")
    return [x for x in data if isinstance(x, dict)]


def write_if_changed(path, text):
    old = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            old = f.read()
    if old == text:
        return False
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    stats["written"] += 1
    return True


# ---------------------------------------------------------------- data
def merge_archive(archive, news):
    """Archive first, current news last (fresh content wins, slug is kept)."""
    by_key = {}
    for raw in archive + news:
        if not clean_text(raw.get("title")):
            continue
        key = raw.get("original_link") or raw.get("title")
        prev = by_key.get(key)
        rec = dict(raw)
        valid = lambda s: isinstance(s, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{2,110}", s)
        keep = (prev or {}).get("slug")
        rec["slug"] = keep if valid(keep) else (raw.get("slug") if valid(raw.get("slug")) else slug_for(raw))
        by_key[key] = rec

    # make slugs unique (oldest first, so existing URLs never change)
    ordered = sorted(by_key.items(), key=lambda kv: (str(kv[1].get("published") or ""), kv[0]))
    seen = set()
    for key, rec in ordered:
        slug = rec["slug"]
        if slug in seen:
            slug = f"{slug}-{short_hash(key, 4)}"
            rec["slug"] = slug
        seen.add(slug)
    return [rec for _, rec in ordered]


def prepare(raw):
    sentiment = str(raw.get("sentiment", "")).upper()
    if sentiment not in DIRS:
        sentiment = "NEUTRAL"
    tag = clean_text(raw.get("tag") or "MARKET").upper() or "MARKET"
    pub = parse_time(raw.get("published"))
    paras = paragraphs(raw.get("content"))
    summary = clean_text(raw.get("ai_summary"))
    words = len((summary + " " + " ".join(paras)).split())
    title = clean_text(raw.get("title"))
    return {
        "slug": raw["slug"],
        "title": title,
        "tag": tag,
        "tag_slug": tag_slug(tag),
        "sentiment": sentiment,
        "summary": summary,
        "impact": clean_text(raw.get("market_impact")),
        "paras": paras,
        "source": clean_text(raw.get("source")),
        "link": safe_url(raw.get("original_link")),
        "pub": pub or EPOCH,
        "has_date": pub is not None,
        "words": words,
        "path": f"news/{raw['slug']}.html",
    }


def indexable(s):
    return s["words"] >= MIN_WORDS_TO_INDEX


# ---------------------------------------------------------------- layout
def layout(*, title, desc, path, body, robots="index, follow", og_type="website", jsonld=None, nav=""):
    canonical = SITE_URL + path
    ld = ""
    if jsonld:
        data = json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        ld = f'<script type="application/ld+json">{data}</script>\n'
    def current(name):
        return ' aria-current="page"' if nav == name else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{esc(canonical)}">
<meta name="color-scheme" content="dark">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="twitter:card" content="summary">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{BASE}feed.xml">
<link rel="stylesheet" href="{BASE}assets/site.css">
{ld}</head>
<body>
<header class="site-head">
  <div class="wrap bar">
    <a class="brand" href="{BASE}">{SITE_NAME}</a>
    <nav class="main-nav" aria-label="Main">
      <a href="{BASE}"{current("home")}>Live feed</a>
      <a href="{BASE}daily/"{current("daily")}>Daily digest</a>
      <a href="{BASE}about.html"{current("about")}>About</a>
    </nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-foot">
  <div class="wrap">
    <nav aria-label="Footer">
      <a href="{BASE}about.html">About</a>
      <a href="{BASE}privacy.html">Privacy</a>
      <a href="{BASE}disclaimer.html">Disclaimer</a>
      <a href="{BASE}feed.xml">RSS</a>
    </nav>
    <p>Summaries and market-impact notes are generated by AI from public news sources and can contain errors. This is not investment advice.</p>
  </div>
</footer>
</body>
</html>
"""


def card(s, show_tag=True):
    d, label = DIRS[s["sentiment"]]
    meta = [f'<span class="dir">{label}</span>']
    if show_tag:
        meta.append(f'<span class="cat">{esc(s["tag"])}</span>')
    right = s["source"]
    if s["has_date"]:
        right = (right + " \u00B7 " if right else "") + fmt_dt(s["pub"])
    if right:
        meta.append(f'<span class="time">{esc(right)}</span>')
    snippet = f'<span class="snippet">{esc(s["summary"])}</span>' if s["summary"] else ""
    impact = f'<span class="chips"><span class="chip">Impact: {esc(s["impact"])}</span></span>' if s["impact"] else ""
    return (f'<li><a class="card" data-dir="{d}" href="{BASE}{s["path"]}">'
            f'<span class="row">{"".join(meta)}</span>'
            f'<span class="headline">{esc(s["title"])}</span>{snippet}{impact}</a></li>')


def card_list(items, show_tag=True):
    return '<ul class="cards">\n' + "\n".join(card(s, show_tag) for s in items) + "\n</ul>"


# ---------------------------------------------------------------- pages
def news_page(s, related):
    d, label = DIRS[s["sentiment"]]
    url = SITE_URL + s["path"]
    desc = shorten(s["summary"] or s["title"], 155)
    meta = [f'<span class="dir">{label}</span>', f'<span class="cat">{esc(s["tag"])}</span>']
    if s["source"]:
        meta.append(f'<span>{esc(s["source"])}</span>')
    if s["has_date"]:
        meta.append(f'<time datetime="{iso(s["pub"])}">{fmt_dt(s["pub"])}</time>')

    parts = [
        f'<nav class="crumbs" aria-label="Breadcrumb"><a href="{BASE}">Home</a><span>/</span>'
        f'<a href="{BASE}tag/{s["tag_slug"]}.html">{esc(tag_name(s["tag"]))}</a></nav>',
        f'<article class="story" data-dir="{d}">',
        f'<div class="meta">{"".join(meta)}</div>',
        f'<h1>{esc(s["title"])}</h1>',
    ]
    if s["summary"]:
        parts.append(f'<p class="lead">{esc(s["summary"])}</p>')
    if s["paras"]:
        parts.append('<section class="block"><h2>AI commentary</h2>'
                     + "".join(f"<p>{esc(p)}</p>" for p in s["paras"]) + "</section>")
    if s["impact"]:
        parts.append('<section class="block"><h2>Market outlook</h2>'
                     f'<div class="outlook"><span class="dir">{label.split(" ", 1)[1]}</span>'
                     f'<span class="what">{esc(s["impact"])}</span></div></section>')
    if s["link"]:
        name = s["source"] or urlparse(s["link"]).hostname or "the source"
        parts.append(f'<p class="source"><a href="{esc(s["link"])}" target="_blank" rel="noopener noreferrer">'
                     f'Read the original story on {esc(name)} \u2192</a></p>')
    parts.append(f'<p class="note">Generated by AI from the headline and short description published by the source. '
                 f'Not investment advice. <a href="{BASE}about.html">How this works</a>.</p>')
    parts.append("</article>")
    if related:
        parts.append('<section class="related"><h2>Earlier stories</h2>' + card_list(related) + "</section>")

    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": s["title"][:110],
        "description": desc,
        "inLanguage": "en",
        "articleSection": tag_name(s["tag"]),
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
    }
    if s["has_date"]:
        ld["datePublished"] = iso(s["pub"])
        ld["dateModified"] = iso(s["pub"])
    if s["link"]:
        ld["isBasedOn"] = s["link"]

    return layout(
        title=f'{s["title"]} | {SITE_NAME}', desc=desc, path=s["path"], body="\n".join(parts),
        robots="index, follow" if indexable(s) else "noindex, follow",
        og_type="article", jsonld=ld,
    )


def day_page(day, items, prev_day, next_day):
    n = len(items)
    counts = Counter(s["sentiment"] for s in items)
    tags = Counter(s["tag"] for s in items)
    top = ", ".join(f"{tag_name(t)} ({c})" for t, c in tags.most_common(3))
    long_day = fmt_day(day)
    desc = (f"{n} market stories on {long_day}: {counts['BULLISH']} bullish, {counts['BEARISH']} bearish, "
            f"{counts['NEUTRAL']} neutral. AI summaries with links to the original sources.")
    intro = (f"Finance Feed tracked {n} market-related stories on {long_day} (UTC). "
             f"{counts['BULLISH']} carried a bullish tone, {counts['BEARISH']} bearish and {counts['NEUTRAL']} neutral. "
             f"The most covered categories were {top}.")
    chips = "".join(
        f'<span class="chip" data-dir="{DIRS[k][0]}">{DIRS[k][1]}: {counts[k]}</span>'
        for k in ("BULLISH", "BEARISH", "NEUTRAL"))

    groups = defaultdict(list)
    for s in items:
        groups[s["tag"]].append(s)
    sections = []
    for t, _ in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
        sections.append(f'<section class="block"><h2>{esc(tag_name(t))}</h2>'
                        + card_list(groups[t], show_tag=False) + "</section>")

    pager = []
    if prev_day:
        pager.append(f'<a href="{BASE}daily/{prev_day}.html">\u2039 {fmt_day(prev_day)}</a>')
    if next_day:
        pager.append(f'<a class="next" href="{BASE}daily/{next_day}.html">{fmt_day(next_day)} \u203A</a>')

    body = "\n".join([
        f'<nav class="crumbs" aria-label="Breadcrumb"><a href="{BASE}">Home</a><span>/</span>'
        f'<a href="{BASE}daily/">Daily digest</a></nav>',
        f"<h1>Market news digest: {long_day}</h1>",
        f'<p class="lead">{esc(intro)}</p>',
        f'<div class="chips tally">{chips}</div>',
        "\n".join(sections),
        f'<nav class="pager" aria-label="Other days">{"".join(pager)}</nav>' if pager else "",
    ])
    return layout(title=f"Market News Digest, {long_day} | {SITE_NAME}", desc=desc,
                  path=f"daily/{day}.html", body=body, nav="daily")


def daily_index(days):
    rows = "\n".join(
        f'<li><a class="card plain" href="{BASE}daily/{d}.html"><span class="headline">{fmt_day(d)}</span>'
        f'<span class="snippet">{c} stories</span></a></li>' for d, c in days)
    tags = "".join(f'<a class="pill" href="{BASE}tag/{slug}.html">{esc(name)}</a>' for slug, name in TAG_LINKS)
    body = "\n".join([
        f'<nav class="crumbs" aria-label="Breadcrumb"><a href="{BASE}">Home</a></nav>',
        "<h1>Daily market news digest</h1>",
        '<p class="lead">One page per day with every market story Finance Feed tracked, grouped by category, with links to the original sources.</p>',
        f'<section class="block"><h2>Browse by category</h2><div class="pills">{tags}</div></section>',
        f'<section class="block"><h2>All days</h2><ul class="cards">{rows}</ul></section>',
    ])
    return layout(title=f"Daily Market News Digest | {SITE_NAME}",
                  desc="Daily digests of market-moving news with AI summaries and links to the original sources.",
                  path="daily/index.html", body=body, nav="daily")


def tag_page(tag, items):
    name = tag_name(tag)
    shown = items[:TAG_PAGE_LIMIT]
    counts = Counter(s["sentiment"] for s in shown)
    desc = (f"Latest {name.lower()} news with AI summaries. In the last {len(shown)} stories: "
            f"{counts['BULLISH']} bullish, {counts['BEARISH']} bearish, {counts['NEUTRAL']} neutral.")
    body = "\n".join([
        f'<nav class="crumbs" aria-label="Breadcrumb"><a href="{BASE}">Home</a></nav>',
        f"<h1>{esc(name)} news</h1>",
        f'<p class="lead">{esc(desc)}</p>',
        card_list(shown, show_tag=False),
    ])
    return layout(title=f"{name} News and AI Analysis | {SITE_NAME}", desc=desc,
                  path=f"tag/{tag_slug(tag)}.html", body=body,
                  robots="index, follow" if len(items) >= MIN_TAG_ITEMS else "noindex, follow")


def home_item(s):
    d, label = DIRS[s["sentiment"]]
    return (f'<li><a class="item" data-dir="{d}" href="{BASE}{s["path"]}">'
            f'<span class="row"><span class="dir">{label}</span><span class="cat">{esc(s["tag"])}</span>'
            f'<span class="time">{esc(s["source"])}</span></span>'
            f'<span class="headline">{esc(s["title"])}</span>'
            f'<span class="snippet">{esc(s["summary"])}</span></a></li>')


def inject_home(stories):
    if not os.path.exists(INDEX_FILE):
        return
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        page = f.read()
    pat = re.compile(r"(<!-- FEED:START -->).*?(<!-- FEED:END -->)", re.S)
    if not pat.search(page):
        print("index.html has no FEED:START/FEED:END markers, home page left unchanged.")
        return
    block = "\n" + "\n".join(home_item(s) for s in stories[:HOME_LIMIT]) + "\n"
    new = pat.sub(lambda m: m.group(1) + block + m.group(2), page, count=1)
    write_if_changed(INDEX_FILE, new)


def build_feed(stories):
    items = []
    for s in stories[:FEED_LIMIT]:
        url = SITE_URL + s["path"]
        pub = f"<pubDate>{format_datetime(s['pub'], usegmt=True)}</pubDate>" if s["has_date"] else ""
        items.append(
            f"<item><title>{esc(s['title'])}</title><link>{esc(url)}</link>"
            f'<guid isPermaLink="true">{esc(url)}</guid>{pub}'
            f"<category>{esc(tag_name(s['tag']))}</category>"
            f"<description>{esc(s['summary'])}</description></item>")
    newest = format_datetime(stories[0]["pub"], usegmt=True) if stories and stories[0]["has_date"] else ""
    last = f"<lastBuildDate>{newest}</lastBuildDate>" if newest else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>\n'
        f"<title>{SITE_NAME}</title><link>{SITE_URL}</link><description>{esc(TAGLINE)}</description>"
        f"<language>en</language>{last}\n"
        f'<atom:link href="{SITE_URL}feed.xml" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items) + "\n</channel></rss>\n")


def build_sitemap(entries):
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, prio in entries:
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        out.append(f"  <url><loc>{esc(loc)}</loc>{mod}<changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    out.append("</urlset>\n")
    return "\n".join(out)


# ---------------------------------------------------------------- main
TAG_LINKS = []


def main():
    news = load_list(NEWS_FILE)
    archive = load_list(ARCHIVE_FILE)
    if not news and not archive:
        print("No stories found, nothing to build.")
        return

    records = merge_archive(archive, news)

    # archive: one record per line, keeps git diffs small
    archive_text = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n]\n"
    write_if_changed(ARCHIVE_FILE, archive_text)

    # give the live feed stable slugs so index.html can link to the story pages
    slug_by_key = {(r.get("original_link") or r.get("title")): r["slug"] for r in records}
    changed = False
    for n in news:
        slug = slug_by_key.get(n.get("original_link") or n.get("title"))
        if slug and n.get("slug") != slug:
            n["slug"] = slug
            changed = True
    if changed:
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(news, f, ensure_ascii=False, indent=4)
        stats["written"] += 1

    stories = sorted((prepare(r) for r in records), key=lambda s: (s["pub"], s["slug"]), reverse=True)

    # story pages
    for i, s in enumerate(stories):
        older = [o for o in stories[i + 1:] if o["slug"] != s["slug"]]
        same = [o for o in older if o["tag"] == s["tag"]][:RELATED]
        rest = [o for o in older if o not in same][: RELATED - len(same)]
        write_if_changed(s["path"], news_page(s, same + rest))
    stats["stories"] = len(stories)

    # category hubs
    by_tag = defaultdict(list)
    for s in stories:
        by_tag[s["tag"]].append(s)
    global TAG_LINKS
    TAG_LINKS = [(tag_slug(t), tag_name(t)) for t, _ in sorted(by_tag.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    for t, items in by_tag.items():
        write_if_changed(f"tag/{tag_slug(t)}.html", tag_page(t, items))

    # daily digests
    by_day = defaultdict(list)
    for s in stories:
        if s["has_date"]:
            by_day[s["pub"].strftime("%Y-%m-%d")].append(s)
    days = sorted((d for d, items in by_day.items() if len(items) >= MIN_DAILY_ITEMS))
    for i, d in enumerate(days):
        write_if_changed(f"daily/{d}.html",
                         day_page(d, by_day[d], days[i - 1] if i > 0 else None,
                                  days[i + 1] if i + 1 < len(days) else None))
    if days:
        write_if_changed("daily/index.html", daily_index([(d, len(by_day[d])) for d in reversed(days)]))

    # home page, feed, sitemap
    inject_home(stories)
    write_if_changed("feed.xml", build_feed(stories))

    newest_day = stories[0]["pub"].strftime("%Y-%m-%d") if stories[0]["has_date"] else None
    entries = [(SITE_URL, newest_day, "hourly", "1.0")]
    if days:
        entries.append((SITE_URL + "daily/", days[-1], "daily", "0.8"))
        for d in days:
            entries.append((f"{SITE_URL}daily/{d}.html", d, "daily", "0.8"))
    for t, items in by_tag.items():
        if len(items) >= MIN_TAG_ITEMS:
            last = items[0]["pub"].strftime("%Y-%m-%d") if items[0]["has_date"] else None
            entries.append((f"{SITE_URL}tag/{tag_slug(t)}.html", last, "daily", "0.6"))
    for s in stories:
        if indexable(s):
            last = s["pub"].strftime("%Y-%m-%d") if s["has_date"] else None
            entries.append((SITE_URL + s["path"], last, "monthly", "0.5"))
    for page in STATIC_PAGES:
        if os.path.exists(page):
            entries.append((SITE_URL + page, None, "yearly", "0.3"))
    write_if_changed("sitemap.xml", build_sitemap(entries))

    n_idx = sum(1 for s in stories if indexable(s))
    print(f"Site built: {len(stories)} stories ({n_idx} indexable), {len(days)} digest days, "
          f"{len(by_tag)} categories, {stats['written']} files written.")


if __name__ == "__main__":
    main()
