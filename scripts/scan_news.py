#!/usr/bin/env python3
"""
MajalahBitcoin — Bitcoin-ONLY News Scanner
Every 4 hours:
  1. Fetches from Bitcoin-focused RSS feeds
  2. Filters to ONLY articles actually about Bitcoin (BTC)
  3. Gemini writes ONE original Malay digest — Bitcoin topics only
  4. Saves to data/news.json

Three layers of Bitcoin-only filtering:
  Layer 1 — RSS source selection: prefer Bitcoin-native publications
  Layer 2 — Keyword filter: drop articles that aren't about Bitcoin
  Layer 3 — Gemini prompt: explicitly told to ignore non-Bitcoin items
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from google import genai

DATA_FILE = Path(__file__).parent.parent / "data" / "news.json"
MAX_ARTICLES = 200

# ── LAYER 1: RSS FEED SELECTION ───────────────────────────────────────────────
# Fetch up to 30 recent items per feed (no time filter) — dedupe by URL later
RSS_FEEDS = [
    # Pure Bitcoin publications
    ("Bitcoin Magazine",  "https://bitcoinmagazine.com/.rss/full/"),
    ("Bitcoin.com News",  "https://news.bitcoin.com/feed/"),

    # Mixed crypto — filtered heavily by Layer 2
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",     "https://cointelegraph.com/rss"),
    ("Decrypt",           "https://decrypt.co/feed"),
    ("The Block",         "https://www.theblock.co/rss.xml"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MajalahBitcoin/1.0; +https://majalahbitcoin.com)"
}

# ── LAYER 2: KEYWORD FILTER ───────────────────────────────────────────────────
BITCOIN_KEYWORDS = {
    "bitcoin", "btc", "satoshi", "sats", "lightning network",
    "lightning payment", "taproot", "ordinals", "runes protocol",
    "bitcoin etf", "spot bitcoin", "bitcoin halving", "bitcoin mining",
    "bitcoin miner", "bitcoin wallet", "bitcoin adoption", "bitcoin price",
    "bitcoin treasury", "bitcoin reserve", "michael saylor", "strategy inc",
    "blockstream", "river financial", "swan bitcoin", "strike app",
}

# Titles that START WITH or ARE PRIMARILY ABOUT these → reject
# Only applied to the title, not description — so "Bitcoin vs Ethereum" still passes
ALTCOIN_TITLE_KEYWORDS = {
    "ethereum", "solana", "ripple", "xrp", "cardano",
    "dogecoin", "shiba inu", "avalanche", "polkadot",
    "uniswap", "vitalik", "binance coin", "tron network",
    "polygon matic", "nft collection", "defi protocol",
    "memecoin", "meme coin",
}


def is_bitcoin_article(title: str, description: str) -> bool:
    """
    Returns True if the article is relevant to Bitcoin.

    Logic:
    - The word 'bitcoin' or 'btc' or any Bitcoin keyword must appear
      somewhere in the title OR description
    - The TITLE must not be explicitly and solely about an altcoin
      (e.g. "Ethereum hits new high" → reject, but
       "Bitcoin and Ethereum diverge" → keep, Gemini will focus on Bitcoin)
    """
    title_lower = title.lower()
    combined = (title + " " + description).lower()

    # Must mention Bitcoin somewhere
    has_bitcoin = any(kw in combined for kw in BITCOIN_KEYWORDS)
    if not has_bitcoin:
        return False

    # Reject only if title is CLEARLY and SOLELY about an altcoin
    for kw in ALTCOIN_TITLE_KEYWORDS:
        if title_lower.startswith(kw):
            return False

    return True


def fetch_rss(name: str, url: str, already_seen_urls: set) -> list[dict]:
    """Fetch RSS feed — return Bitcoin articles not already in our database."""
    items = []
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            content = resp.read()
        root = ET.fromstring(content)

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")
        entries = channel.findall("item") if channel else root.findall("atom:entry", ns)

        total_seen = 0
        total_passed = 0

        for entry in entries[:30]:
            title_el = entry.find("title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            if not title:
                continue

            desc_el = entry.find("description") or entry.find("atom:summary", ns)
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = re.sub(r"<[^>]+>", "", desc_el.text).strip()[:500]

            link_el = entry.find("link")
            link = ""
            if link_el is not None:
                link = (link_el.text or link_el.get("href", "")).strip()

            pub_el = entry.find("pubDate") or entry.find("atom:published", ns)
            pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
            pub_dt = parse_date(pub_str) or datetime.now(timezone.utc)

            # Skip articles we already stored
            if link and link in already_seen_urls:
                continue

            total_seen += 1

            # ── LAYER 2 FILTER ──
            if not is_bitcoin_article(title, desc):
                print(f"    ✗ SKIP (not Bitcoin): {title[:70]}")
                continue

            total_passed += 1
            items.append({
                "title": title,
                "description": desc,
                "link": link,
                "source": name,
                "published": pub_dt.isoformat(),
            })

        print(f"  {name}: {total_passed}/{total_seen} new Bitcoin articles")

    except (URLError, ET.ParseError, Exception) as e:
        print(f"  WARNING: Failed to fetch {name}: {e}")

    return items


def parse_date(date_str: str):
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def write_digest(bitcoin_articles: list[dict], period_start: datetime, period_end: datetime):
    """Send Bitcoin-only headlines to Gemini to write one original Malay article."""
    if not bitcoin_articles:
        return None

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    headlines_block = "\n".join(
        f'- [{a["source"]}] {a["title"]} — {a["description"]}'
        for a in bitcoin_articles
    )

    period_label = f"{period_start.strftime('%d %b %Y, %H:%M')} – {period_end.strftime('%H:%M')} UTC"

    # ── LAYER 3: PROMPT ENFORCEMENT ──
    prompt = f"""Anda adalah editor berita senior di MajalahBitcoin.com — portal berita BITCOIN SAHAJA dalam Bahasa Melayu.

PENTING: Kami HANYA melapor tentang Bitcoin (BTC). Kami BUKAN portal kripto am.
- Jika ada berita tentang Ethereum, Solana, altcoin, DeFi, NFT, atau token lain — ABAIKAN sepenuhnya.
- Hanya tulis tentang Bitcoin, Lightning Network, Bitcoin mining, Bitcoin ETF, Bitcoin adoption, dan topik berkaitan Bitcoin sahaja.

Berikut adalah berita-berita terkini dalam tempoh {period_label}:

{headlines_block}

Tugas anda: Tulis SATU artikel berita asal dalam Bahasa Melayu yang:
1. Meringkaskan perkembangan BITCOIN yang penting dalam tempoh ini
2. Ditulis seperti wartawan profesional — bukan terjemahan, tapi laporan asal
3. Gunakan bahasa Melayu yang natural dan mudah difahami pembaca Malaysia
4. Terangkan kepentingan setiap perkembangan kepada Bitcoiner Malaysia
5. Panjang: 4-6 perenggan
6. Jika tiada berita Bitcoin yang benar-benar relevan, nyatakan "SKIP" dalam titleMs

Balas HANYA dengan JSON ini (tiada markdown, tiada backticks):
{{
  "titleMs": "Tajuk artikel dalam Bahasa Melayu",
  "summaryMs": "Ringkasan 2 ayat dalam Bahasa Melayu",
  "bodyMs": "Teks penuh artikel dalam Bahasa Melayu, perenggan dipisahkan dengan \\n\\n",
  "sources": ["Bitcoin Magazine", "CoinDesk"]
}}"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        parsed = json.loads(text)

        if parsed.get("titleMs", "").upper().startswith("SKIP"):
            print("  Gemini: no relevant Bitcoin news this window, skipping.")
            return None

        if not parsed.get("titleMs") or not parsed.get("bodyMs"):
            raise ValueError("Missing required fields in Gemini response")

        return parsed

    except Exception as e:
        print(f"  ERROR in Gemini call: {e}")
        return None


def main():
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=4, minutes=30)

    # How many articles to send to Gemini — set MAX_FEED_ARTICLES in GitHub Actions env
    max_articles = int(os.environ.get("MAX_FEED_ARTICLES", "10"))

    print(f"[{now.isoformat()}] Scanning for BITCOIN-ONLY news")
    print(f"Layer 2: {len(BITCOIN_KEYWORDS)} Bitcoin keywords, {len(ALTCOIN_TITLE_KEYWORDS)} altcoin rejection keywords")
    print(f"Gemini cap: {max_articles} articles\n")

    # Load existing articles to avoid duplicates
    existing = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else []

    # Collect all URLs we already stored (from raw article links in past digests)
    already_seen = set()
    for item in existing:
        for link in item.get("articleLinks", []):
            already_seen.add(link)

    # 1. Fetch + filter
    bitcoin_articles = []
    for name, url in RSS_FEEDS:
        items = fetch_rss(name, url, already_seen)
        bitcoin_articles.extend(items)

    print(f"\nNew Bitcoin articles found: {len(bitcoin_articles)}")

    # Cap how many we send to Gemini to stay within free tier token limits
    if len(bitcoin_articles) > max_articles:
        print(f"Capping to {max_articles} articles before sending to Gemini")
        bitcoin_articles = bitcoin_articles[:max_articles]

    if not bitcoin_articles:
        print("No new Bitcoin news found. Nothing to publish.")
        return

    print("Sending to Gemini for Malay digest...")

    # 2. Write digest
    digest = write_digest(bitcoin_articles, since, now)
    if not digest:
        print("No digest produced.")
        return

    # 3. Save
    item = {
        "id": f"digest_{int(now.timestamp())}",
        "titleMs": digest["titleMs"],
        "summaryMs": digest["summaryMs"],
        "bodyMs": digest["bodyMs"].replace("\\n\\n", "\n\n"),
        "sources": digest.get("sources", []),
        "rawCount": len(bitcoin_articles),
        "articleLinks": [a["link"] for a in bitcoin_articles],
        "periodStart": since.isoformat(),
        "periodEnd": now.isoformat(),
        "datetime": now.isoformat(),
        "scannedAt": now.isoformat(),
    }

    print(f"\nPublished: {item['titleMs']}")

    updated = [item] + existing
    updated = updated[:MAX_ARTICLES]
    DATA_FILE.write_text(json.dumps(updated, ensure_ascii=False, indent=2))
    print(f"Saved. Total digests: {len(updated)}")


if __name__ == "__main__":
    main()
