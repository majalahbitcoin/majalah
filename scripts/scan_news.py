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
import google.generativeai as genai

DATA_FILE = Path(__file__).parent.parent / "data" / "news.json"
MAX_ARTICLES = 200

# ── LAYER 1: RSS FEED SELECTION ───────────────────────────────────────────────
# Bitcoin Magazine and Bitcoin-specific feeds first.
# CoinDesk/Cointelegraph included but will be filtered heavily in Layer 2.
RSS_FEEDS = [
    # Pure Bitcoin publications — almost everything here is relevant
    ("Bitcoin Magazine",  "https://bitcoinmagazine.com/.rss/full/"),
    ("Bitcoin.com News",  "https://news.bitcoin.com/feed/"),

    # Mixed crypto — needs filtering, but carries important Bitcoin news
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block",         "https://www.theblock.co/rss.xml"),
    ("Decrypt",           "https://decrypt.co/feed"),

    # Mainstream financial — only Bitcoin stories pass filter
    ("Cointelegraph",     "https://cointelegraph.com/rss"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MajalahBitcoin/1.0; +https://majalahbitcoin.com)"
}

# ── LAYER 2: KEYWORD FILTER ───────────────────────────────────────────────────
# An article MUST contain at least one BITCOIN keyword
BITCOIN_KEYWORDS = {
    "bitcoin", "btc", "satoshi", "sats", "lightning network",
    "lightning payment", "taproot", "ordinals", "runes protocol",
    "bitcoin etf", "spot bitcoin", "bitcoin halving", "bitcoin mining",
    "bitcoin miner", "bitcoin wallet", "bitcoin adoption", "bitcoin price",
    "bitcoin treasury", "bitcoin reserve", "michael saylor", "strategy inc",
    "blockstream", "river financial", "swan bitcoin", "strike app",
}

# If an article contains ANY of these, it's NOT about Bitcoin — reject it
# even if it also mentions Bitcoin in passing
ALTCOIN_REJECTION_KEYWORDS = {
    "ethereum", " eth ", "solana", " sol ", "ripple", " xrp ",
    "cardano", " ada ", "dogecoin", "shiba", "avalanche", " avax",
    "polkadot", " dot ", "chainlink", " link ", "uniswap", " uni ",
    "defi protocol", "nft collection", "web3 game", "metaverse token",
    "meme coin", "altcoin", "alt coin", "ether ", "vitalik",
    "binance coin", " bnb ", "tron network", " trx ", "polygon matic",
}


def is_bitcoin_article(title: str, description: str) -> bool:
    """
    Returns True only if the article is genuinely about Bitcoin.
    Logic:
      - Combined text must contain at least one Bitcoin keyword
      - Must NOT be primarily about an altcoin/DeFi/NFT topic
    """
    combined = (title + " " + description).lower()

    # Must have at least one Bitcoin keyword
    has_bitcoin = any(kw in combined for kw in BITCOIN_KEYWORDS)
    if not has_bitcoin:
        return False

    # Reject if altcoin keywords appear in the TITLE (title = main topic)
    title_lower = title.lower()
    is_altcoin_story = any(kw in title_lower for kw in ALTCOIN_REJECTION_KEYWORDS)
    if is_altcoin_story:
        return False

    return True


def fetch_rss(name: str, url: str, since: datetime) -> list[dict]:
    """Fetch RSS feed and return only Bitcoin-relevant items newer than `since`."""
    items = []
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")
        entries = channel.findall("item") if channel else root.findall("atom:entry", ns)

        total_seen = 0
        total_passed = 0

        for entry in entries[:20]:
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
                link = link_el.text or link_el.get("href", "")

            pub_el = entry.find("pubDate") or entry.find("atom:published", ns)
            pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
            pub_dt = parse_date(pub_str)

            if not pub_dt or pub_dt <= since:
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
                "link": link.strip(),
                "source": name,
                "published": pub_dt.isoformat(),
            })

        print(f"  {name}: {total_passed}/{total_seen} passed Bitcoin filter")

    except (URLError, ET.ParseError, Exception) as e:
        print(f"  ⚠ Failed to fetch {name}: {e}")

    return items


def parse_date(date_str: str) -> datetime | None:
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


def write_digest(bitcoin_articles: list[dict], period_start: datetime, period_end: datetime) -> dict | None:
    """Send Bitcoin-only headlines to Gemini to write one original Malay article."""
    if not bitcoin_articles:
        return None

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.0-flash")

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
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        parsed = json.loads(text)

        # Gemini told us to skip — no relevant Bitcoin news this window
        if parsed.get("titleMs", "").upper().startswith("SKIP"):
            print("  Gemini: no relevant Bitcoin news this window, skipping.")
            return None

        if not parsed.get("titleMs") or not parsed.get("bodyMs"):
            raise ValueError("Missing required fields")

        return parsed

    except Exception as e:
        print(f"  ⚠ Gemini error: {e}")
        return None


def main():
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=4, minutes=30)

    print(f"[{now.isoformat()}] Scanning for BITCOIN-ONLY news since {since.isoformat()}")
    print(f"Layer 2 filter: {len(BITCOIN_KEYWORDS)} Bitcoin keywords, {len(ALTCOIN_REJECTION_KEYWORDS)} rejection keywords\n")

    # 1. Fetch + filter
    bitcoin_articles = []
    for name, url in RSS_FEEDS:
        items = fetch_rss(name, url, since)
        bitcoin_articles.extend(items)

    print(f"\nBitcoin-relevant articles: {len(bitcoin_articles)}")

    if not bitcoin_articles:
        print("No Bitcoin news found this window. Nothing to publish.")
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
        "periodStart": since.isoformat(),
        "periodEnd": now.isoformat(),
        "datetime": now.isoformat(),
        "scannedAt": now.isoformat(),
    }

    print(f"\n✓ Published: {item['titleMs']}")

    existing = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else []
    updated = [item] + existing
    updated = updated[:MAX_ARTICLES]
    DATA_FILE.write_text(json.dumps(updated, ensure_ascii=False, indent=2))
    print(f"Saved. Total digests in library: {len(updated)}")


if __name__ == "__main__":
    main()
