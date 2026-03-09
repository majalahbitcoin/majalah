#!/usr/bin/env python3
"""
MajalahBitcoin — Article Translator
Fetches a URL, extracts article content, translates faithfully to Bahasa Melayu.
Triggered manually via GitHub Actions workflow_dispatch.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from google import genai

DATA_FILE = Path(__file__).parent.parent / "data" / "articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MajalahBitcoin/1.0; +https://majalahbitcoin.com)"
}


def fetch_article(url: str) -> dict:
    """Fetch article HTML and extract key content."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("beautifulsoup4 not installed")
        return {"html": "", "text": "", "images": []}

    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript"]):
        tag.decompose()

    # Extract hero image
    hero_image = None
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        hero_image = og_img["content"]

    # Extract article body — try common selectors
    body = None
    for selector in ["article", "[class*='article-body']", "[class*='post-content']",
                     "[class*='entry-content']", "main", ".content"]:
        body = soup.select_one(selector)
        if body:
            break
    if not body:
        body = soup.find("body")

    # Collect images within article
    images = []
    if body:
        for img in body.find_all("img"):
            src = img.get("src") or img.get("data-src", "")
            alt = img.get("alt", "")
            if src and src.startswith("http"):
                images.append({"src": src, "alt": alt})

    # Get clean text
    text = body.get_text(separator="\n", strip=True) if body else ""
    # Trim to ~6000 chars to stay within Gemini free tier context
    text = text[:6000]

    # Get YouTube embeds
    youtube_ids = []
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        m = re.search(r"youtube\.com/embed/([a-zA-Z0-9_-]+)", src)
        if m:
            youtube_ids.append(m.group(1))

    return {
        "text": text,
        "hero_image": hero_image,
        "images": images[:8],  # max 8 images
        "youtube_ids": youtube_ids[:3],
        "title": (soup.find("meta", property="og:title") or {}).get("content", "")
                 or (soup.find("title") or soup.new_tag("x")).get_text(),
        "site_name": (soup.find("meta", property="og:site_name") or {}).get("content", ""),
    }


def translate_with_gemini(url: str, article: dict) -> dict:
    """Send article text to Gemini for faithful Malay translation."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    images_info = "\n".join(f'- {img["src"]} (alt: {img["alt"]})' for img in article["images"])
    youtube_info = "\n".join(f'- https://www.youtube.com/embed/{vid}' for vid in article["youtube_ids"])

    prompt = f"""Anda adalah penterjemah profesional. Terjemah artikel berikut ke Bahasa Melayu dengan setia dan lengkap.

URL asal: {url}
Tajuk asal: {article['title']}

KANDUNGAN ARTIKEL:
{article['text']}

IMEJ DALAM ARTIKEL:
{images_info if images_info else '(tiada)'}

VIDEO YOUTUBE:
{youtube_info if youtube_info else '(tiada)'}

Arahan:
1. Terjemah SEMUA teks dengan setia — jangan ringkas, jangan ubah maksud
2. Gunakan Bahasa Melayu yang natural dan mudah difahami
3. Untuk bodyMs: gunakan HTML dengan tag <p>, <h2>, <h3>, <strong>, <em>, <blockquote>
4. Sertakan imej dengan: <img src="URL_ASAL" alt="penerangan dalam BM">
5. Sertakan YouTube dengan: <iframe src="URL_EMBED" allowfullscreen></iframe>

Balas HANYA dengan JSON ini (tiada markdown, tiada backticks):
{{
  "titleMs": "Tajuk dalam Bahasa Melayu",
  "source": "Nama penerbitan",
  "heroImage": "URL imej utama atau null",
  "bodyMs": "Teks penuh HTML dalam Bahasa Melayu"
}}"""

    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    text = response.text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    parsed = json.loads(text)
    if not parsed.get("titleMs") or not parsed.get("bodyMs"):
        raise ValueError("Incomplete response from Gemini")

    return parsed


def main():
    url = os.environ.get("ARTICLE_URL", "").strip()
    if not url:
        print("ERROR: ARTICLE_URL not set")
        sys.exit(1)

    print(f"Fetching: {url}")
    article = fetch_article(url)
    print(f"Extracted {len(article['text'])} chars, {len(article['images'])} images")

    print("Translating with Gemini...")
    translated = translate_with_gemini(url, article)

    hostname = urlparse(url).hostname or url
    hostname = hostname.replace("www.", "")

    item = {
        "id": f"art_{int(datetime.now(timezone.utc).timestamp())}",
        "originalUrl": url,
        "titleMs": translated["titleMs"],
        "source": translated.get("source") or article.get("site_name") or hostname,
        "heroImage": translated.get("heroImage") or article.get("hero_image"),
        "bodyMs": translated["bodyMs"],
        "addedAt": datetime.now(timezone.utc).isoformat(),
    }

    print(f"✓ Translated: {item['titleMs']}")

    existing = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else []
    # Remove duplicate if same URL exists
    existing = [a for a in existing if a.get("originalUrl") != url]
    updated = [item] + existing

    DATA_FILE.write_text(json.dumps(updated, ensure_ascii=False, indent=2))
    print(f"Saved. Total articles: {len(updated)}")


if __name__ == "__main__":
    main()
