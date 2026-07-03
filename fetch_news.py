#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이미징 레이더 / 60GHz 헬스케어 레이더 뉴스 자동 수집 + HTML 생성 스크립트
【완전 무료 버전 - API 키 불필요】

동작 방식:
1. Google News RSS 피드에서 주제별 키워드로 최근 기사를 수집
2. 중복 기사 제거 (URL 해시 기반)
3. RSS의 description 필드를 요약으로 그대로 사용 (API 비용 없음)
4. docs/index.html 정적 페이지 생성 (GitHub Pages가 이 폴더를 호스팅)
5. data/seen_articles.json 에 기록 누적 저장 (중복 방지용)

필요한 것: GitHub 계정만 있으면 됨 (API 키, 비용 없음)
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

DATA_DIR  = Path("data")
DOCS_DIR  = Path("docs")
HISTORY_FILE = DATA_DIR / "seen_articles.json"
MAX_ARTICLES_PER_TOPIC = 15

# -------------------------------------------------------
# Google News RSS URL 생성 헬퍼
# 한글 키워드도 자동으로 URL 인코딩 처리
# -------------------------------------------------------
def gnews(query, lang="en", country="US"):
    q = urllib.parse.quote(query)
    ceid = f"{country}:{lang}"
    return (
        f"https://news.google.com/rss/search"
        f"?q={q}&hl={lang}&gl={country}&ceid={ceid}"
    )

# -------------------------------------------------------
# 주제별 RSS 피드 목록
# -------------------------------------------------------
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
}

# Google News는 브라우저 User-Agent가 없으면 403 반환
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# -------------------------------------------------------
# 유틸리티
# -------------------------------------------------------

def load_seen_ids():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids):
    DATA_DIR.mkdir(exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def make_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def clean_html(text):
    """RSS description에 섞인 HTML 태그 및 엔티티 제거"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_pubdate(pubdate_str):
    """RFC 2822 날짜 → YYYY-MM-DD"""
    try:
        from email.utils import parsedate
        t = parsedate(pubdate_str)
        if t:
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
    except Exception:
        pass
    return pubdate_str[:10] if pubdate_str else ""


def fetch_rss(url):
    """RSS URL을 가져와서 기사 목록으로 파싱"""
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

        articles.append({
            "title":     title,
            "url":       link,
            "source":    source,
            "published": parse_pubdate(pubdate),
            "summary":   desc if desc else "(요약 없음 — 원문을 확인하세요)",
        })

    return articles


# -------------------------------------------------------
# HTML 생성
# -------------------------------------------------------

def build_html(topic_results, generated_at):
    sections_html = ""
    for topic_key, info in TOPICS.items():
        articles = topic_results.get(topic_key, [])
        sections_html += f'<h2 class="topic-title">{info["label"]}</h2>\n'
        if not articles:
            sections_html += '<p class="empty">오늘은 새로운 기사가 없습니다.</p>\n'
            continue
        for art in articles:
            title   = art["title"].replace("<","&lt;").replace(">","&gt;")
            source  = art.get("source", "")
            pub     = art.get("published", "")
            summary = art["summary"].replace("\n","<br>")
            url     = art["url"]
            meta    = f"{source}&nbsp;·&nbsp;{pub}" if source and pub else source or pub
            sections_html += f"""
<div class="card">
  <div class="card-meta">{meta}</div>
  <h3 class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
  <p class="card-summary">{summary}</p>
  <a class="card-link" href="{url}" target="_blank" rel="noopener">원문 보기 →</a>
</div>
"""

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>레이더 기술 뉴스 트래커</title>
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
  .empty {{ color: #999; font-size: 14px; }}
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


# -------------------------------------------------------
# 메인
# -------------------------------------------------------

def main():
    seen_ids     = load_seen_ids()
    new_seen_ids = set(seen_ids)
    topic_results = {}

    for topic_key, info in TOPICS.items():
        print(f"\n=== {info['label']} ===")
        collected = []
        seen_urls_this_run = set()

        for feed_url in info["feeds"]:
            print(f"  피드: {feed_url[:90]}...")
            items = fetch_rss(feed_url)
            print(f"  → {len(items)}건 수신")
            time.sleep(1)   # Google News 요청 간격

            for art in items:
                uid = make_id(art["url"])
                if uid in seen_ids:
                    continue
                if art["url"] in seen_urls_this_run:
                    continue
                if not art["title"] or art["title"] == "[Removed]":
                    continue

                seen_urls_this_run.add(art["url"])
                new_seen_ids.add(uid)
                collected.append(art)

        collected.sort(key=lambda a: a["published"], reverse=True)
        topic_results[topic_key] = collected[:MAX_ARTICLES_PER_TOPIC]
        print(f"  → 신규 기사 {len(topic_results[topic_key])}건 채택")

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    build_html(topic_results, generated_at)
    save_seen_ids(new_seen_ids)
    print("\n완료: docs/index.html 생성됨")


if __name__ == "__main__":
    main()
