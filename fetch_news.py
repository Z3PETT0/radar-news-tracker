#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이미징 레이더 / 자율주행 / 로봇택시 뉴스 자동 수집 + HTML 생성
【완전 무료 버전 - API 키 불필요】
"""

import json
import datetime
import hashlib
import html as html_mod
import os
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
MAX_RECENT_ARTICLES = 10   # 신규 기사가 없을 때 보여줄 최근 기사 수
VISIBLE_COUNT       = 5    # 처음부터 보여줄 기사 수 (나머지는 '더보기'로 펼침)
RECENT_DAYS_KEEP    = 7

# 어떤 주제든 공통으로 걸러낼 키워드 (제목에 포함되면 제외)
EXCLUDE_KEYWORDS = [
    "영화", "드라마", "배우", "예고편", "티저", "ost",
    "연예", "아이돌", "콘서트", "앨범", "뮤직비디오",
    "recipe", "cooking", "fashion", "celebrity", "trailer",
]


# ── 정부과제 · 입찰 관련 설정 ─────────────────────────────
GOV_KEY = "gov_bids"
GOV_PATTERN = re.compile(
    r"정부\s?과제|국책\s?과제|국가\s?과제|연구개발\s?과제|R&D\s?과제|과제\s?(?:공고|공모|선정)|"
    r"공모|입찰|발주|공고|사업자\s?선정|수행기관|주관기관|실증\s?사업|시범\s?사업|지원\s?사업|"
    r"나라장터|조달청|NTIS|IITP|KIAT|"
    r"\b(?:grant|grants|funding|tender|RFP|RFQ|solicitation|BAA|Horizon Europe|call for proposals)\b",
    re.IGNORECASE,
)

# 나라장터(공공데이터포털) 공식 공고 조회 — 키가 없으면 자동으로 건너뜀
G2B_KEY_ENV = "DATA_GO_KR_KEY"
G2B_KEYWORDS = ["레이더", "자율주행", "로봇", "AMR", "라이다"]
G2B_BASES = [
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService02",   # 포털 End Point (참고문서 v1.3)
]
G2B_OPERATIONS = [
    "getBidPblancListInfoServcPPSSrch02",   # 나라장터검색조건에 의한 입찰공고 용역조회
    "getBidPblancListInfoThngPPSSrch02",    # 나라장터검색조건에 의한 입찰공고 물품조회
]
# 공식 공고에서 제목에 이 단어가 있으면 제외 (사업과 무관한 일반 용역)
G2B_EXCLUDE = [
    "경비", "청소", "시설관리", "급식", "식자재", "폐기물", "방역", "소독", "세탁",
    "조경", "도색", "누수", "보안관제", "청사", "관리용역", "인력파견", "차량임차",
]
G2B_DAYS = 6   # 참고문서 v1.3: 조회기간 최대 7일 → 여유 있게 6일 전 0시 ~ 현재


def gnews(query, lang="en", country="US"):
    q = urllib.parse.quote(query)
    ceid = f"{country}:{lang}"
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={ceid}"


TOPICS = {
    GOV_KEY: {
        "label": "🏛 정부과제 · 입찰 (Gov Projects & Bids)",
        "gov": True,
        "feeds": [
            gnews('"정부과제" 자율주행 OR 레이더 OR 로봇', lang="ko", country="KR"),
            gnews('"실증사업" 자율주행 공모 OR 선정', lang="ko", country="KR"),
            gnews('"R&D 과제" 레이더 OR 센서 OR 자율주행 선정', lang="ko", country="KR"),
            gnews('자율주행 입찰 OR 발주 OR "사업자 선정"', lang="ko", country="KR"),
            gnews('로봇 실증 공모 OR "지원사업" 모집', lang="ko", country="KR"),
            gnews('NTIS 신규과제 공고 자율주행 OR 로봇 OR 센서', lang="ko", country="KR"),
            gnews('"autonomous vehicle" grant OR funding program', ),
            gnews('"request for proposals" autonomous OR radar OR robotics'),
        ],
    },
    "imaging_radar": {
        "label": "이미징 레이더 (자동차 · 산업 · 로봇)",
        "feeds": [
            gnews('"imaging radar" automotive'),
            gnews('"4D radar" autonomous driving'),
            gnews('"imaging radar" robotics'),
            gnews('"imaging radar" industrial'),
            gnews('"이미징 레이더"', lang="ko", country="KR"),
            gnews('"4D 레이더" 자율주행', lang="ko", country="KR"),
        ],
    },
    "autonomous_driving": {
        "label": "자율주행 (Autonomous Driving)",
        "feeds": [
            gnews('"autonomous driving" technology'),
            gnews('"self-driving" car safety'),
            gnews('"autonomous vehicle" sensor'),
            gnews('"자율주행차" -영화 -드라마 -배우', lang="ko", country="KR"),
            gnews('"자율주행" 기술 -영화 -드라마', lang="ko", country="KR"),
            gnews('"자율주행" ADAS 상용화', lang="ko", country="KR"),
        ],
    },
    "amr_logistics": {
        "label": "자율주행 로봇·물류 (AMR / Logistics)",
        "feeds": [
            gnews('AMR "자율주행" 물류 로봇', lang="ko", country="KR"),
            gnews('"자율주행 플랫폼" 로봇 -영화 -드라마', lang="ko", country="KR"),
            gnews('"자율주행" 항만 OR 물류 OR 스마트팩토리 -영화', lang="ko", country="KR"),
            gnews('"autonomous mobile robot" AMR warehouse'),
            gnews('"autonomous" port OR terminal automation logistics'),
        ],
    },
    "robotaxi": {
        "label": "로봇택시 (Robotaxi)",
        "feeds": [
            gnews('"robotaxi" launch OR deploy OR service'),
            gnews('Waymo robotaxi 2026'),
            gnews('Tesla robotaxi autonomous'),
            gnews('"robotaxi" regulation OR policy'),
            gnews('"로봇택시" -영화 -드라마', lang="ko", country="KR"),
            gnews('"자율주행 택시" 상용 -영화', lang="ko", country="KR"),
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


def is_irrelevant(title):
    """제목에 제외 키워드가 포함되면 True"""
    title_lower = title.lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw.isascii():
            # 영문 키워드는 단어 단위로만 매칭 (cost, Boston 등 오탐 방지)
            if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
                return True
        elif kw in title_lower:
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


def is_gov(art):
    return bool(GOV_PATTERN.search(art["title"] + " " + art.get("summary", "")))


def _g2b_items(data):
    try:
        items = data["response"]["body"]["items"]
    except (KeyError, TypeError):
        return []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def fetch_g2b():
    """나라장터 입찰공고(용역·물품)를 키워드별로 조회. 인증키(DATA_GO_KR_KEY)가 없으면 건너뜀."""
    key = os.environ.get(G2B_KEY_ENV, "").strip()
    if not key:
        print("  [나라장터] DATA_GO_KR_KEY 없음 → 건너뜀")
        return []
    key = urllib.parse.unquote(key)
    now = datetime.datetime.now()
    bgn = now - datetime.timedelta(days=G2B_DAYS)
    out, seen_no = [], set()
    working_base = None
    warned = set()
    for kw in G2B_KEYWORDS:
        for op in G2B_OPERATIONS:
            bases = [working_base] if working_base else G2B_BASES
            for base in bases:
                params = {
                    "serviceKey": key, "pageNo": 1, "numOfRows": 30, "type": "json",
                    "inqryDiv": 1,
                    "inqryBgnDt": bgn.strftime("%Y%m%d") + "0000",
                    "inqryEndDt": now.strftime("%Y%m%d%H%M"),
                    "bidNtceNm": kw,
                }
                url = f"{base}/{op}?{urllib.parse.urlencode(params)}"
                try:
                    req = urllib.request.Request(url, headers=HEADERS)
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                except Exception as e:
                    body = ""
                    if hasattr(e, "read"):
                        try:
                            body = e.read().decode("utf-8", "replace")[:300].replace("\n", " ")
                        except Exception:
                            pass
                    tag = (base.split("/")[-1], op)
                    if tag not in warned:      # 같은 주소·기능의 오류는 처음 한 번만 자세히 출력
                        warned.add(tag)
                        print(f"    [나라장터 경고] {base} / {op}: {str(e)[:80]}")
                        if body:
                            print(f"      응답내용: {body}")
                    continue
                working_base = base
                for it in _g2b_items(data):
                    no = str(it.get("bidNtceNo", "")) + str(it.get("bidNtceOrd", ""))
                    name = (it.get("bidNtceNm") or "").strip()
                    if not name or no in seen_no:
                        continue
                    if any(x in name for x in G2B_EXCLUDE):
                        continue
                    seen_no.add(no)
                    inst = it.get("ntceInsttNm") or it.get("dminsttNm") or ""
                    close = (it.get("bidClseDt") or "")[:16]
                    summary = " · ".join(filter(None, [
                        f"수요기관: {inst}" if inst else "",
                        f"마감: {close}" if close else "",
                    ]))
                    link = it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "https://www.g2b.go.kr"
                    out.append({
                        "title": name, "url": link, "source": "나라장터(공식)",
                        "published": (it.get("bidNtceDt") or "")[:10],
                        "summary": summary, "gov": True, "official": True, "deadline": close,
                    })
                break  # 이 base가 응답했으면 다음 base는 시도 안 함
            time.sleep(0.5)
    print(f"  [나라장터] {len(out)}건")
    return out


def gov_sort_key(art):
    """공식 공고(마감 임박순) → 마감일 미표기 공고 → 뉴스(최신순)"""
    if art.get("official"):
        dl = art.get("deadline", "")
        if dl:
            return (0, dl, "")
        return (1, "", "")
    # 뉴스: 날짜 최신순이 되도록 날짜 문자열을 뒤집어 정렬
    pub = art.get("published", "")
    return (2, "", "".join(chr(255 - ord(c)) for c in pub))


def is_expired(art, now_str):
    return bool(art.get("official") and art.get("deadline") and art["deadline"] < now_str)


def card_html(art):
    title   = art["title"].replace("<", "&lt;").replace(">", "&gt;")
    source  = art.get("source", "")
    pub     = art.get("published", "")
    summary = art.get("summary", "")
    url     = art["url"]
    meta    = "&nbsp;·&nbsp;".join(filter(None, [source, pub]))
    if art.get("official"):
        meta = '<span class="badge official">공식 공고</span> ' + meta
    elif art.get("gov"):
        meta = '<span class="badge">🏛 과제·입찰</span> ' + meta
    summary_html = f'<p class="card-summary">{summary}</p>' if summary else ""
    if art.get("official"):
        link_html = f'<a class="bid-btn" href="{url}" target="_blank" rel="noopener">📄 공고 바로가기 →</a>'
    else:
        link_html = f'<a class="card-link" href="{url}" target="_blank" rel="noopener">원문 보기 →</a>'
    return f"""
<div class="card">
  <div class="card-meta">{meta}</div>
  <h3 class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
  {summary_html}
  {link_html}
</div>"""


def cards_with_more(arts):
    """처음 VISIBLE_COUNT개는 바로 보여주고, 나머지는 '더보기' 버튼으로 펼침"""
    html = "".join(card_html(a) for a in arts[:VISIBLE_COUNT])
    rest = arts[VISIBLE_COUNT:]
    if rest:
        html += f"""
<details class="more">
  <summary>더보기 ({len(rest)}건) ▼</summary>
  {"".join(card_html(a) for a in rest)}
  <button type="button" class="more-collapse" onclick="var d=this.closest('details');d.open=false;d.scrollIntoView({{block:'center'}});">접기 ▲</button>
</details>"""
    return html


def build_html(new_results, all_results, generated_at):
    sections_html = ""
    for topic_key, info in TOPICS.items():
        new_arts    = new_results.get(topic_key, [])
        all_arts    = all_results.get(topic_key, [])
        recent_arts = [a for a in all_arts if a not in new_arts][:MAX_RECENT_ARTICLES]

        sections_html += f'<h2 class="topic-title">{info["label"]}</h2>\n'
        if new_arts:
            sections_html += cards_with_more(new_arts)
        else:
            sections_html += '<p class="empty">오늘은 새로운 기사가 없습니다.</p>\n'
            if recent_arts:
                sections_html += '<p class="recent-label">📋 최근 기사</p>\n'
                sections_html += cards_with_more(recent_arts)

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
  .badge {{
    display: inline-block; font-size: 11px; font-weight: 600;
    background: #fef3c7; color: #92400e; border-radius: 6px;
    padding: 1px 7px; margin-right: 4px;
  }}
  .bid-btn {{
    display: inline-block; background: #16a34a; color: #fff !important;
    font-size: 13px; font-weight: 600; text-decoration: none;
    padding: 8px 14px; border-radius: 8px;
  }}
  .bid-btn:hover {{ background: #15803d; }}
  .badge.official {{ background: #dcfce7; color: #166534; }}
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
  details.more > summary {{
    list-style: none; cursor: pointer; text-align: center;
    background: #fff; border: 1px solid #d4d4d8; border-radius: 10px;
    padding: 12px; margin-bottom: 14px;
    font-size: 14px; font-weight: 600; color: #2563eb;
  }}
  details.more > summary::-webkit-details-marker {{ display: none; }}
  details.more > summary:hover {{ background: #f0f5ff; }}
  details.more[open] > summary {{ display: none; }}
  .more-collapse {{
    display: block; width: 100%; cursor: pointer; text-align: center;
    background: #fff; border: 1px solid #d4d4d8; border-radius: 10px;
    padding: 12px; margin-bottom: 14px; font-family: inherit;
    font-size: 14px; font-weight: 600; color: #2563eb;
  }}
  .more-collapse:hover {{ background: #f0f5ff; }}
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
    seen        = load_seen()
    new_seen    = dict(seen)
    today       = datetime.date.today().isoformat()
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

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
                if is_irrelevant(art["title"]):
                    print(f"    [무관 기사 제거] {art['title'][:50]}")
                    continue
                if is_duplicate_title(art["title"], seen_titles):
                    print(f"    [중복제목 제거] {art['title'][:50]}")
                    continue
                if art["published"] and art["published"] < cutoff_date:
                    continue

                art["gov"] = bool(info.get("gov")) or is_gov(art)
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

    # 다른 주제에서 과제·입찰 키워드가 잡힌 기사 + 나라장터 공식 공고를 정부과제 섹션에 합치기
    print(f"\n=== 정부과제 · 입찰 통합 ===")
    gov_all = list(all_results.get(GOV_KEY, []))
    gov_new = list(new_results.get(GOV_KEY, []))
    gov_urls = {a["url"] for a in gov_all}
    for key in TOPICS:
        if key == GOV_KEY:
            continue
        for a in all_results.get(key, []):
            if a.get("gov") and a["url"] not in gov_urls:
                gov_urls.add(a["url"])
                gov_all.append(a)
                if a in new_results.get(key, []):
                    gov_new.append(a)
    for a in fetch_g2b():
        if a["url"] in gov_urls:
            continue
        gov_urls.add(a["url"])
        gov_all.append(a)
        uid = make_id(a["url"])
        if uid not in seen:
            new_seen[uid] = today
            gov_new.append(a)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    gov_all = [a for a in gov_all if not is_expired(a, now_str)]   # 마감 지난 공고 제외
    gov_new = [a for a in gov_new if not is_expired(a, now_str)]
    gov_all.sort(key=gov_sort_key)
    gov_new.sort(key=gov_sort_key)
    all_results[GOV_KEY] = gov_all
    new_results[GOV_KEY] = gov_new[:MAX_NEW_ARTICLES * 2]
    print(f"  → 신규 {len(new_results[GOV_KEY])}건 / 전체 {len(gov_all)}건")

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    build_html(new_results, all_results, generated_at)
    save_seen(new_seen)
    print("\n완료: docs/index.html 생성됨")


if __name__ == "__main__":
    main()
