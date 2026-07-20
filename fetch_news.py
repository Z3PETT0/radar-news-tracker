#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이미징 레이더 / 60GHz 헬스케어 / 자율주행 / 로봇택시 뉴스 자동 수집 + HTML 생성
【완전 무료 버전 - API 키 불필요】
"""

import json
import datetime
import hashlib
import html as html_mod
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

DATA_DIR     = Path("data")
DOCS_DIR     = Path("docs")
HISTORY_FILE = DATA_DIR / "seen_articles.json"

MAX_NEW_ARTICLES    = 15
MAX_RECENT_ARTICLES = 5
RECENT_DAYS_KEEP    = 7


def gnews(query, lang="en", country="US"):
    q = urllib.parse.quote(query)
    ceid = f"{country}:{lang}"
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={ceid}"


TOPICS = {
    "imaging_radar": {
        "label": "이미징 레이더 (자동차 · 산업 · 로봇)",
        "feeds": [
            gnews('"imaging radar" automotive'),
            gnews('"4D radar" autonomous driving'),
            gnews('"imaging radar" robotics'),
            gnews('"imaging radar" industrial'),
            gnews("이미징 레이더", lang="ko", country="KR"),
            gnews("4D 레이더 자율주행", lang="ko", country="KR"),
        ],
    },
    "60ghz_healthcare": {
        "label": "60GHz 레이더 헬스케어",
        "feeds": [
            gnews('"60GHz radar" health'),
            gnews('"mmWave radar" patient monitoring'),
            gnews('"60GHz radar" vital sign'),
            gnews('"contactless radar" healthcare'),
            gnews("60GHz 레이더 헬스케어", lang="ko", country="KR"),
            gnews("밀리미터파 레이더 생체신호", lang="ko", country="KR"),
        ],
    },
    "autonomous_driving": {
        "label": "자율주행 (Autonomous Driving)",
        "feeds": [
            gnews('"autonomous driving" news'),
            gnews('"self-driving" car 2026'),
            gnews('"autonomous vehicle" ADAS'),
            gnews("자율주행 뉴스", lang="ko", country="KR"),
            gnews("자율주행차 ADAS", lang="ko", country="KR"),
            gnews("자율주행 상용화", lang="ko", country="KR"),
        ],
    },
    "robotaxi": {
        "label": "로봇택시 (Robotaxi)",
        "feeds": [
            gnews('"robotaxi" news 2026'),
            gnews('"robo-taxi" autonomous'),
            gnews('Waymo robotaxi'),
            gnews('Tesla robotaxi'),
            gnews('"robotaxi" service launch'),
            gnews("로봇택시", lang="ko", country="KR"),
            gnews("자율주행 택시", lang="ko", country="KR"),
        ],
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def load_seen():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {}
        return data
    return {}


def save_seen(seen):
    cutoff = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS_KEEP)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    DATA_DIR.mkdir(exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def make_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def normalize_title(title):
    t = title.lower()
    t = re.sub(r"[^\w가-힣]", "", t)
    return t


def is_duplicate_title(title, seen_titles, threshold=0.8):
    norm = normalize_title(title)[:40]
    if not norm:
        return False
    for existing in seen_titles:
        existing_cut = existing[:40]
        if not existing_cut:
            continue
        shorter = min(len(norm), len(existing_cut))
        if shorter == 0:
            continue
        matches = sum(1 for a, b in zip(norm, existing_cut) if a == b)
        if matches / shorter >= threshold:
            return True
    return False


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_description(desc, title, source):
    if not desc:
        return ""
    text = desc
    if title:
        title_prefix = re.escape(title[:30])
        text = re.sub(rf"^{title_prefix}.*", "", text, flags=re.DOTALL).strip()
    if source:
        src_escaped = re.escape(source.strip())
        text = re.sub(rf"\s*{src_escaped}\s*$", "", text, flags=re.IGNORECASE).strip()
    if len(text) < 20:
        return ""
    if len(text) > 200:
        text = text[:200].rsplit(" ", 1)[0] + "…"
    return text


def parse_pubdate(pubdate_str):
    try:
        from email.utils import parsedate
        t = parsedate(pubdate_str)
        if t:
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
    except Exception:
        pass
    return pubdate_str[:10] if pubdate_str else ""


def fetch_rss(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read()
    except Exception as e:
        print(f"    [경고] 가져오기 실패: {e}")
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"    [경고] XML 파싱 실패: {e}")
        return []

    articles = []
    for item in root.findall(".//item"):
        get = lambda tag: (item.find(tag).text or "") if item.find(tag) is not None else ""
        title   = clean_html(get("title"))
        link    = get("link").strip()
        desc    = clean_html(get("description"))
        pubdate = get("pubDate")
        source  = get("source")
        if not title or not link:
            continue
        if source:
            src_escaped = re.escape(source.strip())
            title = re.sub(rf"\s*[-–—]\s*{src_escaped}\s*$", "", title, flags=re.IGNORECASE).strip()
        articles.append({
            "title":     title,
            "url":       link,
            "source":    source,
            "published": parse_pubdate(pubdate),
            "summary":   clean_description(desc, title, source),
        })
    return articles


def card_html(art):
    title   = art["title"].replace("<", "&lt;").replace(">", "&gt;")
    source  = art.get("source", "")
    pub     = art.get("published", "")
    summary = art.get("summary", "")
    url     = art["url"]
    meta    = "&nbsp;·&nbsp;".join(filter(None, [source, pub]))
    summary_html = f'<p class="card-summary">{summary}</p>' if summary else ""
    return f"""
<div class="card">
  <div class="card-meta">{meta}</div>
  <h3 class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
  {summary_html}
  <a class="card-link" href="{url}" target="_blank" rel="noopener">원문 보기 →</a>
</div>"""


def build_html(new_results, all_results, generated_at):
    sections_html = ""
    for topic_key, info in TOPICS.items():
        new_arts    = new_results.get(topic_key, [])
        all_arts    = all_results.get(topic_key, [])
        recent_arts = [a for a in all_arts if a not in new_arts][:MAX_RECENT_ARTICLES]

        sections_html += f'<h2 class="topic-title">{info["label"]}</h2>\n'
        if new_arts:
            for art in new_arts:
                sections_html += card_html(art)
        else:
            sections_html += '<p class="empty">오늘은 새로운 기사가 없습니다.</p>\n'
            if recent_arts:
                sections_html += '<p class="recent-label">📋 최근 기사</p>\n'
                for art in recent_arts:
                    sections_html += card_html(art)

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>레이더 기술 뉴스 트래커</title>
<link rel="icon" type="image/png" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="레이더 뉴스">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    max-width: 800px; margin: 0 auto;
    padding: 24px 16px 80px;
    background: #f7f7f8; color: #1a1a1a; line-height: 1.6;
  }}
  header {{ margin-bottom: 32px; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  .updated {{ color: #666; font-size: 14px; }}
  .topic-title {{
    font-size: 19px; margin-top: 40px; margin-bottom: 16px;
    padding-bottom: 8px; border-bottom: 2px solid #2563eb;
  }}
  .card {{
    background: #fff; border: 1px solid #e5e5e5;
    border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;
  }}
  .card-meta  {{ font-size: 12px; color: #888; margin-bottom: 6px; }}
  .card-title {{ font-size: 16px; margin: 0 0 8px; }}
  .card-title a {{ color: #1a1a1a; text-decoration: none; }}
  .card-title a:hover {{ text-decoration: underline; }}
  .card-summary {{ font-size: 14px; color: #333; margin: 0 0 8px; }}
  .card-link {{ font-size: 13px; color: #2563eb; text-decoration: none; }}
  .empty {{ color: #999; font-size: 14px; margin-bottom: 8px; }}
  .recent-label {{
    font-size: 13px; color: #555; font-weight: 600;
    margin: 16px 0 10px; padding-left: 4px;
  }}
</style>
</head>
<body>
<header>
  <h1>📡 레이더 기술 뉴스 트래커</h1>
  <div class="updated">마지막 업데이트: {generated_at} (매일 자동 갱신)</div>
</header>
{sections_html}
</body>
</html>
"""
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")


def main():
    seen         = load_seen()
    new_seen     = dict(seen)
    today        = datetime.date.today().isoformat()
    cutoff_date  = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

    new_results = {}
    all_results = {}

    for topic_key, info in TOPICS.items():
        print(f"\n=== {info['label']} ===")
        new_arts    = []
        all_arts    = []
        seen_urls   = set()
        seen_titles = []

        for feed_url in info["feeds"]:
            print(f"  피드: {feed_url[:90]}...")
            items = fetch_rss(feed_url)
            print(f"  → {len(items)}건 수신")
            time.sleep(1)

            for art in items:
                uid = make_id(art["url"])
                if art["url"] in seen_urls:
                    continue
                if not art["title"] or art["title"] == "[Removed]":
                    continue
                if is_duplicate_title(art["title"], seen_titles):
                    print(f"    [중복제목 제거] {art['title'][:50]}")
                    continue
                if art["published"] and art["published"] < cutoff_date:
                    continue

                seen_urls.add(art["url"])
                seen_titles.append(normalize_title(art["title"]))
                all_arts.append(art)

                if uid not in seen:
                    new_seen[uid] = today
                    new_arts.append(art)

        all_arts.sort(key=lambda a: a["published"], reverse=True)
        new_arts.sort(key=lambda a: a["published"], reverse=True)

        new_results[topic_key] = new_arts[:MAX_NEW_ARTICLES]
        all_results[topic_key] = all_arts
        print(f"  → 신규 {len(new_results[topic_key])}건 / 전체 {len(all_arts)}건")

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    build_html(new_results, all_results, generated_at)
    save_seen(new_seen)
    print("\n완료: docs/index.html 생성됨")


if __name__ == "__main__":
    main()
