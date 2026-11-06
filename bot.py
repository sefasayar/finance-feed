import feedparser
import json
import os
import time
from datetime import datetime
from google import genai
from google.genai import types

# Sırayla denenir. Birinin kotası biterse veya yoğunsa sonrakine geçer.
MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
MAX_YENI = 10  # her çalışmada en fazla bu kadar yeni haber

API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

rss_kaynaklari = [
    "https://www.trthaber.com/ekonomi_articles.rss",
    "https://www.ntv.com.tr/ekonomi.rss"
]

SEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER", "description": "Haberin köşeli parantezdeki numarası"},
            "ozet": {"type": "STRING", "description": "Haberin 2 cümlelik özeti"},
            "piyasa_etkisi": {"type": "STRING", "description": "Piyasaya olası etkisi, yatırım tavsiyesi vermeden"},
            "kategori": {"type": "STRING", "description": "Makro, Borsa veya Kripto"}
        },
        "required": ["id", "ozet", "piyasa_etkisi", "kategori"]
    }
}

def toplu_yorumla(adaylar):
    """Tüm haberleri tek istekte yorumlar. {numara: sonuç} döner, olmazsa {}."""
    if not client:
        print("HATA: GEMINI_API_KEY bulunamadı")
        return {}

    metin = "\n\n".join(
        f"[{i}] {a['baslik']}\n{a['ham'][:400]}" for i, a in enumerate(adaylar)
    )
    prompt = (
        "Aşağıdaki finans haberlerini analiz et. Her haber için özet, piyasa etkisi ve "
        "kategori üret. Asla yatırım tavsiyesi verme (al/sat deme). "
        "id alanına haberin köşeli parantezdeki numarasını yaz.\n\n" + metin
    )

    for model in MODELS:
        for deneme in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=SEMA,
                    ),
                )
                sonuc = json.loads(response.text)
                print(f"   -> {model} başarılı")
                return {int(x["id"]): x for x in sonuc}
            except Exception as e:
                msg = str(e)
                print(f"   -> {model} hatası: {msg[:200]}")
                if "429" in msg or "404" in msg or "NOT_FOUND" in msg:
                    break  # kota doldu veya model yok: tekrar deneme, sıradaki modele geç
                time.sleep(10)  # 503 gibi geçici hata: kısa bekle, bir kez daha dene
    return {}

# Mevcut haberleri yükle, hatalı eskileri temizle
HATALI = {"Hata", "Sistem", "Sistem Yoğun", "Kısa Haber"}
mevcut = []
try:
    with open("haberler.json", "r", encoding="utf-8") as f:
        mevcut = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass
mevcut = [h for h in mevcut if h.get("kategori") not in HATALI]
bilinen = {h["baslik"] for h in mevcut}

# Yeni adayları topla
adaylar = []
for url in rss_kaynaklari:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            if entry.title in bilinen or any(a["baslik"] == entry.title for a in adaylar):
                continue
            ham = getattr(entry, "summary", getattr(entry, "description", entry.title))
            adaylar.append({"baslik": entry.title, "ham": ham})
    except Exception as e:
        print(f"RSS Kaynak Hatası ({url}): {e}")
adaylar = adaylar[:MAX_YENI]

yeni = []
if adaylar:
    print(f"{len(adaylar)} yeni haber tek istekte yorumlanıyor...")
    sonuclar = toplu_yorumla(adaylar)
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, a in enumerate(adaylar):
        r = sonuclar.get(i)
        if not r:
            continue  # başarısızsa kaydetme, sonraki çalışmada tekrar denenir
        yeni.append({
            "baslik": a["baslik"],
            "ozet": r["ozet"],
            "piyasa_etkisi": r["piyasa_etkisi"],
            "kategori": r["kategori"],
            "zaman": zaman
        })
else:
    print("Yeni haber yok.")

final_liste = (yeni + mevcut)[:50]
with open("haberler.json", "w", encoding="utf-8") as f:
    json.dump(final_liste, f, ensure_ascii=False, indent=4)

print(f"Tamam: {len(yeni)} yeni haber eklendi.")
