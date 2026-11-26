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
import urllib.error
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
    r"기술\s?개발\s?(?:과제|사업)|(?<![A-Za-z])R&D|연구\s?개발|과제\s?(?:참여|수행|착수|공고)|"
    r"컨소시엄|참여\s?기업|사업\s?참여|테스트베드|"
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
# ── 관심 프로필 (data/interest_profile.txt 를 GitHub에서 직접 수정하면 코드 변경 없이 반영) ──
PROFILE_FILE = DATA_DIR / "interest_profile.txt"
DEFAULT_PRODUCT_DESC = (
    "AFI920: 자동차·로봇·산업용 4D 이미징 레이더 제품. 자율주행/ADAS, 로보택시, 로봇·AMR, "
    "산업 센서, 레이더 시뮬레이션·검증(RIDE) 사업과 연계되는 공고가 관심 대상."
)

# ── AI 연계도 판정 (Google Gemini 무료 한도 사용. 키가 없거나 실패하면 키워드 방식으로 자동 대체) ──
AI_KEY_ENV   = "GEMINI_API_KEY"
AI_MODEL     = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")   # 단종되면 아래에서 자동으로 최신 flash 모델을 찾음
AI_ENDPOINT  = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
AI_MIN_SCORE = 5      # 0~10점 중 이 점수 이상만 표시
AI_CHUNK     = 20     # 한 번에 판정할 공고 수
AI_TIMEOUT   = 90     # 한 번 호출 최대 대기(초)
G2B_DAYS = 6   # 참고문서 v1.3: 조회기간 최대 7일 → 여유 있게 6일 전 0시 ~ 현재


# 과제·사업 소식을 찾는 뉴스 검색어 (data/interest_profile.txt 의 [과제검색어] 에 줄을 추가하면 함께 사용됨)
GOV_EXTRA_QUERIES = [
    "스마트항만 자율주행 기술개발 과제",
    "자율주행 기술개발 과제 선정 컨소시엄",
    "산업통상부 자율주행 R&D 과제 공고",
    "레이더 센서 기술개발 과제 선정",
    "자율주행 로봇 R&D 과제 참여",
    "국토교통부 자율주행 실증 사업 참여기업 모집",
    "해양수산부 스마트항만 R&D 과제",
]


# '해당 공고 확인' 버튼이 검색할 R&D·조달 공고 사이트 (NTIS, 부처·전문기관, 나라장터, 기업마당 등)
GOV_SEARCH_SITES = [
    "ntis.go.kr", "keit.re.kr", "iitp.kr", "kaia.re.kr", "kimst.re.kr", "kiat.or.kr",
    "smtech.go.kr", "motir.go.kr", "molit.go.kr", "mof.go.kr", "msit.go.kr", "g2b.go.kr", "bizinfo.go.kr",
]


def find_notice_urls(art):
    """과제 기사에서 '지난 공고'를 찾는 구글 검색 링크 2개 (공고 사이트 한정 / 전체 웹).
    본문에서 과제명·부처가 추출됐으면 정확 일치(따옴표) 검색, 아니면 AI 검색어/제목 사용."""
    proj = (art.get("ai_project") or "").strip()
    agency = (art.get("ai_agency") or "").strip()
    if proj:
        q = f'"{proj}" 공고'
        q_web = f'"{proj}" {agency} 공고 OR 공모 OR 과제'.strip()
    else:
        q = (art.get("ai_query") or "").strip()
        if not q:
            q = re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’\[\]「」『』…·,]", " ", art.get("title", ""))).strip()[:60] + " 공고"
        q_web = q
    sites = " OR ".join(f"site:{d}" for d in GOV_SEARCH_SITES)
    base = "https://www.google.com/search?q="
    return (base + urllib.parse.quote(f"{q} ({sites})"), base + urllib.parse.quote(q_web))


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
    "robotaxi_companies": {
        "label": "로보택시 업체 동향 (Robotaxi Companies)",
        "feeds": [
            gnews('Waymo OR Zoox OR "May Mobility" OR Motional OR Nuro robotaxi'),
            gnews('"Pony.ai" OR WeRide OR "Apollo Go" OR Baidu robotaxi'),
            gnews('Tesla Cybercab OR "Tesla robotaxi" OR Wayve OR Mobileye robotaxi'),
            gnews('Uber OR Lyft autonomous partnership robotaxi'),
            gnews('"로보택시" 웨이모 OR 포니AI OR 위라이드 OR 바이두 OR 테슬라', lang="ko", country="KR"),
            gnews('"자율주행 택시" 서울 OR 카카오모빌리티 OR 42dot OR 오토노머스에이투지 OR 라이드플럭스', lang="ko", country="KR"),
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
    """RSS 발행 시각을 한국시간(KST) 기준 날짜(YYYY-MM-DD)로 변환"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
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


def load_profile():
    """data/interest_profile.txt 읽기. [섹션명] 아래에 한 줄씩 적고, # 로 시작하는 줄은 주석."""
    sections = {"제품설명": [], "검색키워드": [], "제외키워드": [], "과제검색어": []}
    if PROFILE_FILE.exists():
        cur = None
        for line in PROFILE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1].strip()
                sections.setdefault(cur, [])
                continue
            if cur:
                sections[cur].append(line)
    return sections


def keyword_score(bid, keywords):
    """AI를 못 쓸 때의 대체 판정: 관심 키워드가 제목에 있으면 통과"""
    hit = [k for k in keywords if k.lower() in bid["title"].lower()]
    return (6, f"키워드 일치: {', '.join(hit[:3])}") if hit else (0, "관심 키워드 없음")


def list_gemini_models(key):
    """사용 가능한 flash 계열 모델을 후보 순서대로 반환 (가볍고 한가한 lite 먼저, 최신 버전 우선)"""
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
            headers={"x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("models", [])
    except Exception as e:
        print(f"  [AI판정] 모델 목록 조회 실패: {str(e)[:80]}")
        return []
    cands = []
    for m in models:
        name = m.get("name", "").replace("models/", "")
        mm = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?", name)
        if mm and "generateContent" in m.get("supportedGenerationMethods", []):
            cands.append((0 if mm.group(2) else 1, -float(mm.group(1)), name))
    cands.sort()
    return [c[2] for c in cands]


def resolve_gnews_url(url, timeout=12):
    """구글뉴스 RSS 링크 → 실제 기사 URL. 실패하면 None (구글 쪽 방식 변경 가능성 있음)."""
    if "news.google.com" not in url:
        return url
    try:
        m = re.search(r"/articles/([^?/]+)", url)
        if not m:
            return None
        aid = m.group(1)
        # 구형 링크: base64 안에 URL이 그대로 들어 있음
        try:
            import base64
            raw = base64.urlsafe_b64decode(aid + "=" * (-len(aid) % 4))
            mm = re.search(rb"https?://[\x21-\x7e]+", raw)
            if mm and b"news.google" not in mm.group(0):
                return mm.group(0).decode()
        except Exception:
            pass
        req = urllib.request.Request(f"https://news.google.com/articles/{aid}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html_ = r.read().decode("utf-8", "replace")
        sg = re.search(r'data-n-a-sg="([^"]+)"', html_)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html_)
        if not (sg and ts):
            return None
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                 f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{aid}",{ts.group(1)},"{sg.group(1)}"]')
        freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        data = urllib.parse.urlencode({"f.req": freq}).encode()
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=data, method="POST",
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        part = body.split("\n\n", 1)[1]
        return json.loads(json.loads(part)[0][2])[1]
    except Exception:
        return None


def fetch_article_text(url, limit=2500, timeout=12):
    """기사 URL의 본문 텍스트(앞부분)를 가져옴. 실패하면 ''."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1_500_000)
            enc = r.headers.get_content_charset() or "utf-8"
        html_ = raw.decode(enc, "replace")
        html_ = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html_)
        paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html_)
        text = " ".join(re.sub(r"(?s)<[^>]+>", " ", p) for p in paras)
        text = re.sub(r"\s+", " ", html_mod.unescape(text)).strip()
        return text[:limit]
    except Exception:
        return ""


def enrich_gov_news(items, key, max_items=25):
    """과제 뉴스의 본문을 읽고 AI가 과제명·주관부처·전담기관을 추출 → 공고 검색 정확도 향상.
    어느 단계든 실패하면 해당 기사는 기존 방식(제목 기반 검색어)을 그대로 씀."""
    if not key:
        return
    targets = [a for a in items if not a.get("official")][:max_items]
    docs = []
    for a in targets:
        real = resolve_gnews_url(a["url"])
        body = fetch_article_text(real) if real else ""
        if len(body) >= 200:
            docs.append((a, body))
    print(f"  [본문읽기] {len(docs)}/{len(targets)}건 본문 확보")
    if not docs:
        return
    system = (
        "아래 각 기사 본문에서 언급된 정부 R&D 과제·실증사업·지원사업의 정보를 추출한다. "
        "project는 기사에 나온 과제/사업의 정식 명칭(따옴표 안의 명칭 우선, 없으면 빈 문자열), "
        "agency는 주관 부처·기관, 없으면 빈 문자열. 기사에 없는 내용은 절대 추측하지 말 것. "
        "반드시 JSON {\"results\":[{\"id\":번호,\"project\":\"\",\"agency\":\"\"}]} 만 출력한다."
    )
    models = [AI_MODEL]
    tried_list = False
    for i in range(0, len(docs), 8):
        chunk = docs[i:i + 8]
        payload_items = [{"id": n, "title": a["title"], "body": b} for n, (a, b) in enumerate(chunk)]
        while models:
            model = models[0]
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(payload_items, ensure_ascii=False)}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            }
            req = urllib.request.Request(
                AI_ENDPOINT.format(model=model), data=json.dumps(payload).encode("utf-8"), method="POST",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"\{.*\}", content, re.DOTALL)
                for r in json.loads(m.group(0) if m else content)["results"]:
                    a = chunk[int(r["id"])][0]
                    a["ai_project"] = str(r.get("project", "")).strip()[:80]
                    a["ai_agency"] = str(r.get("agency", "")).strip()[:40]
                break
            except Exception as e:
                print(f"  [본문읽기 경고] {model}: {str(e)[:80]}")
                models.pop(0)
                if not models and not tried_list:
                    tried_list = True
                    models = [m for m in list_gemini_models(key) if m != model][:3]
    n = sum(1 for a, _ in docs if a.get("ai_project"))
    print(f"  [본문읽기] 과제명 추출 {n}건")


def ai_score_bids(bids, profile, kind="bid"):
    """공고 제목·기관을 AI가 읽고 연계도(0~10)와 이유를 붙임. 한 건이라도 성공하면 True.
    모델이 단종(404)·과부하(503/429)·지연(timeout)이면 다른 flash 계열 모델로 자동 전환."""
    key = os.environ.get(AI_KEY_ENV, "").strip()
    if not bids:
        return False
    if not key:
        print(f"  [AI판정] {AI_KEY_ENV} 없음 → 키워드 방식 사용")
        return False
    desc = " ".join(profile["제품설명"]) or DEFAULT_PRODUCT_DESC
    interests = ", ".join(profile["검색키워드"] or G2B_KEYWORDS)
    if kind == "news":
        system = (
            "너는 레이더 센서 회사의 사업개발 담당을 돕는 뉴스 선별기다. "
            "각 항목은 뉴스 제목(org는 언론사)이다. 정부 R&D 과제·실증사업·지원사업의 공모·선정·참여·착수 소식이면서 "
            "아래 제품·사업과 연계(파트너·경쟁사 동향, 후속 과제 단서 포함)될 가능성을 0~10점으로 평가한다. "
            "과제·사업과 무관한 일반 기사, 교육·행사·홍보성 기사, "
            "조선소·항만·물류·로봇 등 현장 자율주행·센서 과제와 그 참여 기업 소식은 가산(6점 이상). "
            "type은 '공모중', '선정·참여', '정책·계획', '기타' 중 하나. "
            "query는 해당 과제·사업의 원래 공고를 검색할 한국어 검색어(회사명·언론 표현 제외, 과제/사업의 핵심어 2~4개 + '공고'). "
            "반드시 JSON {\"results\":[{\"id\":번호,\"score\":정수,\"type\":\"유형\",\"reason\":\"20자 내외 한국어 이유\",\"query\":\"검색어\"}]} 만 출력한다.\n"
            f"제품·사업: {desc}\n관심 키워드: {interests}"
        )
    else:
        system = (
            "너는 레이더 센서 회사의 사업개발 담당을 돕는 공공조달·정부과제 공고 선별기다. "
            "공고 제목과 기관을 보고, 아래 제품·관심사와 사업화·납품·연구협력으로 연계될 가능성을 0~10점으로 평가한다. "
            "경비·청소·시설관리 같은 일반 용역, 제품과 무관한 구매는 0~2점. "
            "반드시 JSON {\"results\":[{\"id\":번호,\"score\":정수,\"reason\":\"20자 내외 한국어 이유\"}]} 만 출력한다.\n"
            f"제품·사업: {desc}\n관심 키워드: {interests}"
        )
    model = AI_MODEL
    fallbacks = None            # 처음 문제가 생겼을 때 한 번만 목록 조회
    failed = set()
    use_thinking_cfg = True
    ok = 0
    for i in range(0, len(bids), AI_CHUNK):
        chunk = bids[i:i + AI_CHUNK]
        items = [{"id": n, "title": b["title"], "org": b.get("org") or b.get("source", "")} for n, b in enumerate(chunk)]
        done = False
        for attempt in range(5):
            cfg = {"temperature": 0, "responseMimeType": "application/json"}
            if use_thinking_cfg:
                cfg["thinkingConfig"] = {"thinkingBudget": 0}   # 긴 '생각' 단계를 꺼서 응답 속도 향상
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(items, ensure_ascii=False)}]}],
                "generationConfig": cfg,
            }
            req = urllib.request.Request(
                AI_ENDPOINT.format(model=model), data=json.dumps(payload).encode("utf-8"), method="POST",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            )
            raw = ""
            try:
                with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                data = json.loads(raw)
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"\{.*\}", content, re.DOTALL)
                results = json.loads(m.group(0) if m else content)["results"]
                for r in results:
                    b = chunk[int(r["id"])]
                    b["ai_score"] = max(0, min(10, int(r["score"])))
                    b["ai_reason"] = str(r.get("reason", ""))[:60]
                    if kind == "news":
                        b["ai_type"] = str(r.get("type", ""))[:10]
                        b["ai_query"] = str(r.get("query", ""))[:80]
                    ok += 1
                done = True
                break
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read().decode("utf-8", "replace")[:150].replace("\n", " ")
                except Exception:
                    pass
                if he.code == 400 and use_thinking_cfg:
                    use_thinking_cfg = False                      # 이 모델이 옵션을 거부 → 빼고 재시도
                    print("  [AI판정] thinkingConfig 거부됨 → 옵션 없이 재시도")
                    continue
                reason = f"HTTP {he.code} {body}"
                switch = he.code in (404, 429, 500, 502, 503, 504)
            except (TimeoutError, urllib.error.URLError, OSError) as e:
                reason, switch = f"{str(e)[:60]} (응답 지연)", True
            except Exception as e:
                print(f"  [AI판정 경고] 응답 해석 실패: {str(e)[:80]}")
                if raw:
                    print(f"    [AI 원본 응답] {raw[:300]!r}")
                break
            print(f"  [AI판정 경고] {model}: {reason}")
            if not switch:
                break
            failed.add(model)
            if fallbacks is None:
                fallbacks = list_gemini_models(key)
            nxt = next((m for m in fallbacks if m not in failed), None)
            if not nxt:
                break
            print(f"  [AI판정] 모델 변경: {model} → {nxt}")
            model = nxt
            time.sleep(3)
        if not done and not model:
            break
        time.sleep(2)
    print(f"  [AI판정] {ok}/{len(bids)}건 판정 (모델: {model})")
    return ok > 0


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
    profile = load_profile()
    keywords = profile["검색키워드"] or G2B_KEYWORDS
    excludes = G2B_EXCLUDE + profile["제외키워드"]
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
    for kw in keywords:
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
                    if any(x in name for x in excludes):
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
                        "summary": summary, "gov": True, "official": True, "deadline": close, "org": inst,
                    })
                break  # 이 base가 응답했으면 다음 base는 시도 안 함
            time.sleep(0.5)
    print(f"  [나라장터] {len(out)}건")
    return out


def gov_sort_key(art):
    """공식 공고(마감 임박순) → 마감일 미표기 공고 → 뉴스(최신순)"""
    if art.get("official"):
        dl = art.get("deadline", "")
        hi = 0 if art.get("ai_score", 0) >= 8 else 1
        if dl:
            return (0, hi, dl, "")
        return (1, hi, "", "")
    # 뉴스: 날짜 최신순이 되도록 날짜 문자열을 뒤집어 정렬
    pub = art.get("published", "")
    return (2, 0, "", "".join(chr(255 - ord(c)) for c in pub))


def is_expired(art, now_str):
    return bool(art.get("official") and art.get("deadline") and art["deadline"] < now_str)


KST_TZ = datetime.timezone(datetime.timedelta(hours=9))
# 탭·섹션 표시 순서 (왼쪽 → 오른쪽 / 위 → 아래)
DISPLAY_ORDER = ["robotaxi", "robotaxi_companies", "autonomous_driving", "amr_logistics", "imaging_radar", GOV_KEY]
ARCHIVE_FIND_MIN = 6   # 지난 기사 목록에서 '공고 확인' 링크를 붙일 최소 AI 점수
MAX_ARCHIVE = 150    # '전체 기사 보기'에 담을 섹션별 최대 기사 수 (최근 30일, 최신순)
BID_VISIBLE = 8     # 공식 공고 목록에서 처음부터 보여줄 개수


def esc(text):
    return html_mod.escape(text or "", quote=True)


def dday_days(deadline, now):
    """마감까지 남은 일수 (오늘 마감=0). 마감일이 없거나 해석 불가면 None"""
    if not deadline:
        return None
    try:
        dt = datetime.datetime.strptime(deadline[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return (dt.date() - now.date()).days


def _title_tokens(title):
    t = re.sub(r"(\d+(?:\.\d+)?억)원", r"\1", title)
    t = re.sub(r"[^0-9A-Za-z가-힣]+", " ", t)
    return [w for w in t.split() if len(w) >= 2]


GENERIC_TOKENS = {
    "자율주행", "자율주행차", "자율주행차량", "로보택시", "로봇택시", "자율주행택시", "정부", "국책", "국가", "과제", "사업", "실증",
    "기술", "개발", "참여", "선정", "추진", "확대", "도입", "구축", "공모", "지원", "연구", "플랫폼", "스타트업", "투자",
    "레이더", "라이다", "센서", "로봇", "물류", "AMR", "AI", "국토교통부", "산업통상부", "과학기술정보통신부", "해양수산부",
    "한국", "서울", "부산", "대전", "대구", "인천", "경기", "제주", "전남", "경남", "경북", "충남", "충북", "전북", "강원",
}


def _same_story(a, b):
    """다른 언론사가 같은 사건을 쓴 기사인지 추정. 흔한 단어를 뺀 고유 단어(기업·기관·사업명·금액 등)를
    2개 이상 공유(그중 3글자 이상 1개 포함)하거나 전체 단어 유사도가 높으면 같은 소식. 발행일 3일 이내만 비교."""
    ta, tb = _title_tokens(a["title"]), _title_tokens(b["title"])
    if not ta or not tb:
        return False
    try:
        da = datetime.date.fromisoformat(a.get("published") or "")
        db = datetime.date.fromisoformat(b.get("published") or "")
        if abs((da - db).days) > 3:
            return False
    except ValueError:
        pass
    sa, sb = set(ta), set(tb)
    if len(sa & sb) / len(sa | sb) >= 0.5:
        return True
    shared = {w for w in sa & sb if w not in GENERIC_TOKENS}
    return len(shared) >= 2 and any(len(w) >= 3 for w in shared)


def group_same_story(arts):
    """같은 소식 기사는 대표 1건만 남기고 나머지는 대표의 dups에 링크로 보관. 대표 = AI 점수 높은 순 → 최신 순."""
    order = sorted(arts, key=lambda a: (a.get("ai_score") or 0, a.get("published") or ""), reverse=True)
    reps = []
    for a in order:
        a["dups"] = []
        for r in reps:
            if _same_story(r, a):
                r["dups"].append({"title": a["title"], "url": a["url"], "source": a.get("source", ""),
                                  "published": a.get("published", "")})
                break
        else:
            reps.append(a)
    keep = {id(r) for r in reps}
    return [a for a in arts if id(a) in keep]


def card_html(art, is_new=False):
    """일반 뉴스 카드 (제목 자체가 링크, 요약은 2줄까지만)"""
    title   = esc(art["title"])
    source  = esc(art.get("source", ""))
    pub     = esc(art.get("published", ""))
    summary = esc(art.get("summary", ""))
    url     = esc(art["url"])
    new_badge = '<span class="badge new">NEW</span>' if is_new else ""
    gov_badge = '<span class="badge">🏛 과제·입찰</span>' if art.get("gov") else ""
    meta = " · ".join(filter(None, [source, pub]))
    summary_html = f'<p class="card-summary">{summary}</p>' if summary else ""
    if art.get("dups"):
        links = "".join(
            f'<li><a href="{esc(d["url"])}" target="_blank" rel="noopener">{esc(d["title"])}</a>'
            f'<span> · {esc(d.get("source", ""))}</span></li>' for d in art["dups"])
        summary_html += (f'<details class="dups"><summary>같은 소식 {len(art["dups"])}건 더 보기</summary>'
                         f'<ul>{links}</ul></details>')
    if art.get("ai_type") is not None and art.get("ai_score") is not None:
        lvl = "high" if art["ai_score"] >= 8 else "mid"
        summary_html += (f'<div class="bid-ai {lvl}">🎯 {esc(art.get("ai_type", ""))} · '
                         f'{art["ai_score"]}/10 · {esc(art.get("ai_reason", ""))}</div>')
    if art.get("gov") and not art.get("official"):
        u_sites, u_web = find_notice_urls(art)
        summary_html += (f'<div class="find-row"><a class="find-btn" href="{esc(u_sites)}" target="_blank" rel="noopener">🔎 해당 공고 확인</a>'
                         f'<a class="find-alt" href="{esc(u_web)}" target="_blank" rel="noopener">웹 전체 검색</a></div>')
    return f"""
<article class="card">
  <h3 class="card-title"><a href="{url}" target="_blank" rel="noopener">{new_badge}{title}</a></h3>
  <div class="card-meta">{gov_badge}{meta}</div>
  {summary_html}
</article>"""


def bid_row_html(art, now, is_new=False):
    """나라장터 공식 공고 한 줄 (제목 · 기관 · 마감 D-n · 연계도 · 바로가기)"""
    title = esc(art["title"])
    url   = esc(art["url"])
    org   = esc(art.get("org", ""))
    dl    = art.get("deadline", "")
    days  = dday_days(dl, now)
    if days is None:
        dd = '<span class="dd none">마감 미표기</span>'
    elif days <= 3:
        dd = f'<span class="dd urgent">D-{days}</span>' if days > 0 else '<span class="dd urgent">오늘 마감</span>'
    else:
        dd = f'<span class="dd">D-{days}</span>'
    meta = " · ".join(filter(None, [org, f"마감 {esc(dl)}" if dl else ""]))
    score = art.get("ai_score")
    ai = ""
    if score is not None:
        lvl = "high" if score >= 8 else "mid"
        ai = f'<div class="bid-ai {lvl}">🎯 {score}/10 · {esc(art.get("ai_reason", ""))}</div>'
    new_badge = '<span class="badge new">NEW</span>' if is_new else ""
    return f"""
<li class="bid">
  <div class="bid-main">
    <a class="bid-title" href="{url}" target="_blank" rel="noopener">{new_badge}{title}</a>
    <div class="bid-meta">{meta}</div>
    {ai}
  </div>
  <div class="bid-side">{dd}<a class="bid-btn" href="{url}" target="_blank" rel="noopener">공고 ↗</a></div>
</li>"""


def archive_html(arts, label="전체 기사 더 보기"):
    """이미 위에 보여준 기사를 뺀 나머지를 가벼운 목록(제목·출처·날짜)으로 펼쳐 보기"""
    arts = arts[:MAX_ARCHIVE]
    if not arts:
        return ""
    def find_link(a):
        # 과제 뉴스 중 AI 연계 점수가 높은 지난 기사에도 '공고 확인' 링크를 붙임
        if a.get("gov") and not a.get("official") and (a.get("ai_score") or 0) >= ARCHIVE_FIND_MIN:
            u_sites, _ = find_notice_urls(a)
            return (f'<a class="arch-find" href="{esc(u_sites)}" target="_blank" rel="noopener" '
                    f'title="AI {a["ai_score"]}/10">🔎 공고 확인</a>')
        return ""
    rows = "".join(
        f'<li class="arch"><a href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["title"])}</a>'
        f'{("<span class=arch-meta>+" + str(len(a["dups"])) + "건 같은 소식</span>") if a.get("dups") else ""}'
        f'{find_link(a)}'
        f'<span class="arch-meta">{esc(" · ".join(filter(None, [a.get("source", ""), a.get("published", "")])))}</span></li>'
        for a in arts
    )
    return f"""
<details class="more archive">
  <summary>{label} ({len(arts)}건) ▼</summary>
  <ul class="archlist">{rows}</ul>
  {collapse_btn()}
</details>"""


def collapse_btn():
    return ("<button type=\"button\" class=\"more-collapse\" "
            "onclick=\"var d=this.closest('details');d.open=false;d.scrollIntoView({block:'center'});\">접기 ▲</button>")


def cards_with_more(arts, new_urls):
    """처음 VISIBLE_COUNT개는 바로, 나머지는 '더보기' (펼치면 맨 아래에 접기 버튼)"""
    first = "".join(card_html(a, a["url"] in new_urls) for a in arts[:VISIBLE_COUNT])
    html = f'<div class="grid">{first}</div>'
    rest = arts[VISIBLE_COUNT:]
    if rest:
        body = "".join(card_html(a, a["url"] in new_urls) for a in rest)
        html += f"""
<details class="more">
  <summary>더보기 ({len(rest)}건) ▼</summary>
  <div class="grid">{body}</div>
  {collapse_btn()}
</details>"""
    return html


def bids_with_more(bids, new_urls, now):
    first = "".join(bid_row_html(a, now, a["url"] in new_urls) for a in bids[:BID_VISIBLE])
    html = f'<ul class="bids">{first}</ul>'
    rest = bids[BID_VISIBLE:]
    if rest:
        body = "".join(bid_row_html(a, now, a["url"] in new_urls) for a in rest)
        html += f"""
<details class="more">
  <summary>공식 공고 더보기 ({len(rest)}건) ▼</summary>
  <ul class="bids">{body}</ul>
  {collapse_btn()}
</details>"""
    return html


SEARCH_SYNONYMS = [
    ["웨이모", "Waymo"], ["테슬라", "Tesla"], ["쏘카", "SOCAR"], ["카카오모빌리티", "Kakao Mobility"],
    ["포니AI", "Pony.ai", "Pony AI"], ["위라이드", "WeRide"], ["바이두", "Baidu"], ["아폴로고", "Apollo Go"],
    ["죽스", "Zoox"], ["누로", "Nuro"], ["모셔널", "Motional"], ["우버", "Uber"], ["리프트", "Lyft"],
    ["메이모빌리티", "May Mobility"], ["모빌아이", "Mobileye"], ["현대차", "현대자동차", "Hyundai"],
    ["로보택시", "로봇택시", "자율주행택시", "자율주행 택시", "robotaxi"],
    ["이미징 레이더", "4D 레이더", "imaging radar", "4D radar"],
    ["자율주행", "autonomous driving", "self-driving"],
    ["에이스웍스", "Aceworks"], ["비트센싱", "Bitsensing"],
]


def search_synonym_groups():
    """검색창용 동의어 묶음: 코드 기본값 + 프로필 [검색동의어] (한 줄에 쉼표로 구분)"""
    groups = [list(g) for g in SEARCH_SYNONYMS]
    for line in load_profile().get("검색동의어", []):
        g = [w.strip() for w in line.split(",") if w.strip()]
        if len(g) >= 2:
            groups.append(g)
    return groups


def build_html(new_results, all_results, generated_at):
    syn_json = json.dumps(search_synonym_groups(), ensure_ascii=False).replace("</", "<\\/")
    now = datetime.datetime.now(KST_TZ).replace(tzinfo=None)

    # ── 상단 요약 수치 ──
    today = now.strftime("%Y-%m-%d")
    today_urls = {a["url"] for k, v in all_results.items() if k != GOV_KEY
                  for a in v if a.get("published") == today}
    total_new = len(today_urls)
    gov_all = all_results.get(GOV_KEY, [])
    officials = [a for a in gov_all if a.get("official")]
    urgent = sum(1 for a in officials if (dday_days(a.get("deadline", ""), now) is not None
                                          and dday_days(a.get("deadline", ""), now) <= 3))
    high = sum(1 for a in officials if a.get("ai_score", 0) >= 8)
    summary_bar = f"""
<div class="summary-bar">
  <div class="sum"><b>{total_new}</b><span>오늘 기사</span></div>
  <a class="sum" href="#sec-{GOV_KEY}"><b>{len(officials)}</b><span>공식 공고</span></a>
  <a class="sum {'hot' if urgent else ''}" href="#sec-{GOV_KEY}"><b>{urgent}</b><span>마감 임박</span></a>
  <a class="sum {'hot' if high else ''}" href="#sec-{GOV_KEY}"><b>{high}</b><span>연계 높음</span></a>
</div>"""

    # ── 상단 탭 ──
    order = [k for k in DISPLAY_ORDER if k in TOPICS] + [k for k in TOPICS if k not in DISPLAY_ORDER]
    tabs = "".join(
        f'<a href="#sec-{k}">{esc(TOPICS[k]["label"].split(" (")[0])}</a>' for k in order
    )

    # ── 섹션 ──
    sections_html = ""
    for topic_key in order:
        info = TOPICS[topic_key]
        new_arts    = new_results.get(topic_key, [])
        all_arts    = all_results.get(topic_key, [])
        new_urls    = {a["url"] for a in new_arts}
        label       = esc(info["label"])
        inner = ""

        if topic_key == GOV_KEY:
            bids = [a for a in all_arts if a.get("official")]
            news = [a for a in all_arts if not a.get("official")]
            today_bids = sum(1 for a in bids if a.get("published") == today)
            if bids:
                extra = f" · 오늘 게시 {today_bids}건" if today_bids else ""
                inner += f'<p class="sub-label">📄 나라장터 공식 공고 <small>(연계도 높은 순 · 마감 임박 순{extra})</small></p>\n'
                inner += bids_with_more(bids, new_urls, now)
            else:
                inner += '<p class="empty">연계 가능한 공식 공고가 아직 없습니다.</p>\n'
            items, label_news, today_n = news, "📰 관련 뉴스", 0
        else:
            items, label_news, today_n = all_arts, None, 0

        by_date = sorted(items, key=lambda a: a.get("published", ""), reverse=True)
        today_items = [a for a in by_date if a.get("published") == today]
        today_n = len(today_items)
        if label_news:
            inner += f'<p class="sub-label">{label_news}</p>\n'
        if today_items:
            inner += f'<p class="sub-label today">📅 오늘 기사 <small>({today_n}건)</small></p>\n'
            inner += cards_with_more(today_items, new_urls)
            shown = today_items
        else:
            inner += '<p class="empty">오늘 기사가 아직 없습니다.</p>\n'
            shown = by_date[:MAX_RECENT_ARTICLES]
            if shown:
                inner += '<p class="sub-label">📋 최근 기사</p>\n'
                inner += cards_with_more(shown, new_urls)
        shown_urls = {a["url"] for a in shown}
        inner += archive_html([a for a in by_date if a["url"] not in shown_urls],
                              "지난 관련 뉴스 전체 보기" if label_news else "지난 기사 전체 보기")
        count = len(items) + (len([a for a in all_arts if a.get("official")]) if label_news else 0)

        sections_html += f"""
<details class="sec" id="sec-{topic_key}"{"" if topic_key == GOV_KEY else " open"}>
  <summary class="topic-title"><span>{label}</span><span class="cnt">오늘 {today_n} · 전체 {count}건</span></summary>
  {inner}
</details>"""

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
  :root {{
    --blue:#2f5fa6; --line:#e6dfcc; --muted:#8a8272;
    --fs-title:14px; --fs-meta:12px; --fs-body:13px;
    --lh-title:1.4; --lh-body:1.5; --gap:8px; --pad:10px 14px;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    max-width: 1100px; margin: 0 auto; padding: 16px 16px 80px;
    background: #f6f1e4; color: #2f2b24; line-height: 1.5;
  }}
  header {{ margin-bottom: 12px; }}
  h1 {{ font-size: 22px; margin: 0 0 2px; }}
  .updated {{ color: #6b6455; font-size: 13px; }}

  .summary-bar {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 12px 0 8px; }}
  .sum {{ background:#fffdf8; border:1px solid var(--line); border-radius:10px; padding:8px 6px; text-align:center; }}
  .sum b {{ display:block; font-size:20px; line-height:1.2; }}
  .sum span {{ font-size:11px; color:#6b6455; }}
  .sum.hot b {{ color:#dc2626; }}
  a.sum {{ color: inherit; text-decoration: none; }}
  a.sum:hover {{ background: #fbf7ea; }}

  nav.tabs {{
    position: sticky; top: 0; z-index: 10; display: flex; gap: 6px; overflow-x: auto;
    padding: 8px 0; margin: 0 0 8px; background: #f6f1e4d9; backdrop-filter: blur(6px);
    scrollbar-width: none;
  }}
  nav.tabs::-webkit-scrollbar {{ display: none; }}
  nav.tabs a {{
    flex: 0 0 auto; font-size: 13px; font-weight: 600; color: var(--blue); text-decoration: none;
    background:#fffdf8; border: 1px solid #d8cfb8; border-radius: 999px; padding: 6px 12px; white-space: nowrap;
  }}
  nav.tabs a:hover {{ background: #f3ecd6; }}


  /* 기사 검색: 돋보기 버튼이 눌리면 가로로 늘어나 입력창이 됨 */
  .searchbar.open {{ position:sticky; top:46px; z-index:9; background:#f6f1e4e6; padding:4px 0; backdrop-filter: blur(6px); }}
  .searchbar {{ display:flex; align-items:center; gap:8px; margin: 0 0 10px; }}
  .sbox {{
    display:flex; align-items:center; height:36px; width:112px; max-width:100%; overflow:hidden;
    background:#fffdf8; border:2px solid #1e4a99; border-radius:999px; cursor:pointer;
    transition: width .3s ease, border-color .2s, box-shadow .2s;
  }}
  .sbox:hover {{ background:#f3ecd6; }}
  .sbox.open {{ width:min(520px, 100%); cursor:text; background:#fffdf8; border-color:#1e4a99; box-shadow:0 0 0 3px #1e4a9933; }}
  .sbtn {{ flex:0 0 auto; display:flex; align-items:center; gap:6px; padding:0 8px 0 12px; border:0; background:none;
    color:var(--blue); font:inherit; font-size:13px; font-weight:600; cursor:inherit; white-space:nowrap; }}
  .sbtn svg {{ width:16px; height:16px; }}
  .sbox.open .sbtn span {{ display:none; }}
  .sinput {{ flex:1 1 auto; min-width:0; width:0; border:0; outline:0; background:none; font:inherit; font-size:14px; color:#2f2b24; padding:0; }}
  .sinput {{ display:none; }}
  .sinput::-webkit-search-cancel-button {{ -webkit-appearance:none; display:none; }}
  .sbox.open .sinput {{ display:block; width:auto; padding-right:6px; }}
  .scount {{ flex:0 0 auto; font-size:12px; color:var(--muted); white-space:nowrap; padding-right:4px; display:none; }}
  .sbox.open .scount {{ display:block; }}
  .snav, .sclose {{ flex:0 0 auto; display:none; border:0; background:none; color:var(--muted); font-size:15px; width:28px; height:28px; border-radius:50%; cursor:pointer; }}
  .sbox.open .snav, .sbox.open .sclose {{ display:block; }}
  .snav:hover, .sclose:hover {{ background:#f3ecd6; color:var(--blue); }}
  .snomatch {{ color:#b45309; }}
  @keyframes flashhit {{ 0% {{ box-shadow:0 0 0 0 #f2c14e00; background:#fff3c4; }} 30% {{ box-shadow:0 0 0 6px #f2c14e99; background:#ffe9a0; }} 100% {{ box-shadow:0 0 0 0 #f2c14e00; }} }}
  .hit-flash {{ animation: flashhit 1.4s ease-out 1; }}
  mark.shl {{ background:#ffe08a; color:inherit; padding:0 1px; border-radius:3px; }}
  article.card, li.arch, li.bid {{ scroll-margin-top: 130px; }}

  /* 오른쪽 고정 이동 버튼 */
  .jump {{ position:fixed; right:16px; bottom:24px; z-index:20; display:flex; flex-direction:column; gap:8px; }}
  .jump button {{
    width:46px; height:46px; border-radius:50%; border:2px solid #1e4a99; background:#fffdf8; color:#1e4a99;
    font:inherit; font-size:11px; font-weight:800; letter-spacing:.02em; cursor:pointer;
    box-shadow:0 2px 8px #0000001f; transition: background .15s, color .15s, transform .15s;
  }}
  .jump button:hover {{ background:#1e4a99; color:#fff; transform:translateY(-1px); }}
  @media (max-width: 600px) {{ .jump {{ right:10px; bottom:16px; }} .jump button {{ width:42px; height:42px; }} }}

  details.sec {{ scroll-margin-top: 56px; margin-top: 14px; }}
  .topic-title {{
    list-style: none; cursor: pointer; display: flex; justify-content: space-between; align-items: center;
    font-size: 17px; font-weight: 700; padding: 8px 2px; border-bottom: 2px solid var(--blue); margin-bottom: 12px;
  }}
  .topic-title::-webkit-details-marker {{ display: none; }}
  .topic-title::after {{ content: "▾"; color: var(--blue); margin-left: 8px; }}
  details.sec:not([open]) > .topic-title::after {{ content: "▸"; }}
  .topic-title span:first-child {{ flex: 1; }}
  .cnt {{ font-size: 12px; font-weight: 600; color: var(--muted); }}
  .sub-label {{ font-size: 13px; color: #5c5546; font-weight: 700; margin: 12px 0 8px 2px; }}
  .sub-label.today {{ color: var(--blue); font-size: 14px; }}
  .sub-label small {{ font-weight: 400; color: var(--muted); }}
  .empty {{ color: #9a927f; font-size: 14px; margin: 4px 2px 8px; }}

  .grid {{ display: grid; grid-template-columns: 1fr; gap: var(--gap); }}
  @media (min-width: 760px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
  .card {{ background:#fffdf8; border:1px solid var(--line); border-radius:10px; padding: var(--pad); }}
  .card-meta {{ font-size: var(--fs-meta); color: var(--muted); margin-top: 2px; }}
  .card-title {{ font-size: var(--fs-title); font-weight: 700; margin: 0; line-height: var(--lh-title); }}
  .card-title a {{ color:#2f2b24; text-decoration:none; }}
  .card-title a:hover {{ text-decoration: underline; color: var(--blue); }}
  .card-summary {{
    font-size: var(--fs-body); line-height: var(--lh-body); color:#4a453a; margin: 6px 0 0;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }}

  .find-row {{ display:flex; align-items:center; gap:10px; margin-top:8px; }}
  .find-btn {{
    font-size: 12px; font-weight: 700; color: var(--blue); text-decoration: none;
    border: 1px solid #d8cfb8; background: #fbf7ea; border-radius: 8px; padding: 4px 10px;
  }}
  .find-btn:hover {{ background: #f3ecd6; }}
  .find-alt {{ font-size: 12px; color: var(--muted); text-decoration: underline; }}
  .badge {{
    display:inline-block; font-size:11px; font-weight:600; background:#f5e7c0; color:#7a4b12;
    border-radius:6px; padding:0 6px; margin-right:4px;
  }}
  .badge.new {{ background:#e0e6f3; color:#2f5fa6; }}

  ul.bids {{ list-style: none; margin: 0 0 10px; padding: 0; display: grid; gap: var(--gap); }}
  li.bid {{
    display: flex; gap: 10px; align-items: center; justify-content: space-between;
    background:#fffdf8; border:1px solid var(--line); border-radius:10px; padding: var(--pad);
  }}
  .bid-main {{ min-width: 0; flex: 1; }}
  .bid-title {{ font-size: var(--fs-title); font-weight: 700; color:#2f2b24; text-decoration:none; line-height: var(--lh-title); }}
  .bid-title:hover {{ text-decoration: underline; color: var(--blue); }}
  .bid-meta {{ font-size: var(--fs-meta); color: var(--muted); margin-top: 2px; }}
  .bid-ai {{ font-size: 12px; margin-top: 4px; padding: 2px 8px; border-radius: 6px; display: inline-block; }}
  .bid-ai.high {{ background:#e1ecd2; color:#3d5a1f; }}
  .bid-ai.mid  {{ background:#efe9d6; color:#5c5546; }}
  .bid-side {{ display:flex; flex-direction:column; align-items:flex-end; gap:6px; flex: 0 0 auto; }}
  .dd {{ font-size: 12px; font-weight: 700; color:#5c5546; }}
  .dd.urgent {{ color:#dc2626; }}
  .dd.none {{ color:#999; font-weight:500; }}
  .bid-btn {{
    background:#5a8a3c; color:#fff !important; font-size:12px; font-weight:700;
    text-decoration:none; padding:5px 12px; border-radius:8px; white-space: nowrap;
  }}
  .bid-btn:hover {{ background:#4a7330; }}
  @media (min-width: 760px) {{ ul.bids {{ grid-template-columns: 1fr 1fr; }} }}

  ul.archlist {{ list-style: none; margin: 0; padding: 0; background:#fffdf8; border:1px solid var(--line); border-radius:10px; }}
  li.arch {{ display:flex; gap:10px; justify-content:space-between; align-items:baseline; padding:7px 14px; border-top:1px solid var(--line); }}
  li.arch:first-child {{ border-top: 0; }}
  li.arch a {{ font-size: var(--fs-body); color:#2f2b24; text-decoration:none; line-height: var(--lh-title); min-width:0; }}
  li.arch a:hover {{ text-decoration: underline; color: var(--blue); }}
  li.arch a:first-child {{ flex: 1 1 auto; }}
  li.arch a.arch-find {{ flex: 0 0 auto; font-size: var(--fs-meta); font-weight: 700; color: var(--blue); border:1px solid var(--line); border-radius:8px; padding:1px 8px; background:#fbf6e8; white-space:nowrap; }}
  li.arch a.arch-find:hover {{ background:#f3ecd6; text-decoration:none; }}
  details.dups {{ margin-top:6px; font-size: var(--fs-meta); color: var(--muted); }}
  details.dups summary {{ cursor:pointer; color: var(--blue); }}
  details.dups ul {{ margin:4px 0 0; padding-left:18px; }}
  details.dups a {{ color:#2f2b24; text-decoration:none; }}
  details.dups a:hover {{ text-decoration:underline; }}
  .arch-meta {{ flex: 0 0 auto; font-size: var(--fs-meta); color: var(--muted); white-space: nowrap; }}
  @media (max-width: 600px) {{ li.arch {{ flex-direction: column; gap: 0; }} }}
  details.more > summary, .more-collapse {{
    list-style: none; cursor: pointer; text-align: center; display:block; width:100%;
    background:#fffdf8; border:1px solid #d8cfb8; border-radius:10px; padding:10px;
    margin: 10px 0 4px; font-family: inherit; font-size:13px; font-weight:600; color: var(--blue);
  }}
  details.more > summary::-webkit-details-marker {{ display:none; }}
  details.more > summary:hover, .more-collapse:hover {{ background:#f3ecd6; }}
  details.more[open] > summary {{ display: none; }}
  details.more[open] {{ margin-top: 10px; }}
</style>
</head>
<body>
<header>
  <h1>📡 레이더 기술 뉴스 트래커</h1>
  <div class="updated">마지막 업데이트: {generated_at} (매일 자동 갱신)</div>
</header>
{summary_bar}
<nav class="tabs">{tabs}</nav>
<div class="searchbar" id="sbar">
  <div class="sbox" id="sbox" role="search">
    <button type="button" class="sbtn" id="sopen" aria-label="기사 검색">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><span>기사 검색</span>
    </button>
    <input class="sinput" id="sinput" type="search" placeholder="제목·요약에서 검색 (Enter: 다음 결과)" autocomplete="off" aria-label="기사 검색어">
    <span class="scount" id="scount"></span>
    <button type="button" class="snav" id="sprev" aria-label="이전 결과">▲</button>
    <button type="button" class="snav" id="snext" aria-label="다음 결과">▼</button>
    <button type="button" class="sclose" id="sclose" aria-label="검색 닫기">✕</button>
  </div>
</div>
{sections_html}
<div class="jump" aria-label="페이지 이동">
  <button type="button" id="jup" aria-label="맨 위로">UP</button>
  <button type="button" id="jdown" aria-label="맨 아래로">DOWN</button>
</div>
<script>
(function () {{
  function openFor(h) {{
    if (!h) return;
    try {{ var el = document.querySelector(h); if (el && el.tagName === 'DETAILS') el.open = true; }} catch (e) {{}}
  }}
  document.querySelectorAll('nav.tabs a, a.sum').forEach(function (a) {{
    a.addEventListener('click', function () {{ openFor(a.getAttribute('href')); }});
  }});
  window.addEventListener('hashchange', function () {{ openFor(location.hash); }});
  openFor(location.hash);
}})();

(function () {{
  var box = document.getElementById('sbox'), inp = document.getElementById('sinput'), cnt = document.getElementById('scount');
  var hits = [], cur = -1, timer = null;
  var GROUPS = {syn_json};
  var SEL = 'article.card, li.arch, li.bid';
  function norm(t) {{ return (t || '').toLowerCase().replace(/\\s+/g, ' '); }}
  function variants(q) {{
    // 검색어가 동의어 묶음의 단어와 겹치면(같거나 포함) 그 묶음의 다른 표기도 함께 검색
    var out = [q];
    GROUPS.forEach(function (g) {{
      var low = g.map(norm);
      low.forEach(function (t, i) {{
        if (t === q || (q.length >= 2 && t.indexOf(q) === 0)) {{
          low.forEach(function (o) {{ if (out.indexOf(o) < 0) out.push(o); }});
        }} else if (t.length >= 2 && q.indexOf(t) >= 0 && q !== t) {{
          low.forEach(function (o) {{ var v = q.replace(t, o); if (out.indexOf(v) < 0) out.push(v); }});
        }}
      }});
    }});
    return out;
  }}
  function clearMarks() {{
    document.querySelectorAll('mark.shl').forEach(function (m) {{
      var p = m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize();
    }});
  }}
  function markIn(el, q) {{
    var w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null), nodes = [], n;
    while ((n = w.nextNode())) nodes.push(n);
    nodes.forEach(function (t) {{
      if (t.parentNode.closest('mark.shl, script, style')) return;
      var i = t.nodeValue.toLowerCase().indexOf(q);
      if (i < 0) return;
      var mk = document.createElement('mark'); mk.className = 'shl';
      var rest = t.splitText(i); rest.splitText(q.length); mk.appendChild(rest.cloneNode(true));
      rest.parentNode.replaceChild(mk, rest);
    }});
  }}
  function openAncestors(el) {{
    var d = el.closest('details');
    while (d) {{ d.open = true; d = d.parentElement && d.parentElement.closest('details'); }}
  }}
  function show(i) {{
    if (!hits.length) return;
    cur = (i + hits.length) % hits.length;
    var el = hits[cur];
    openAncestors(el);
    el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    el.classList.remove('hit-flash'); void el.offsetWidth; el.classList.add('hit-flash');
    cnt.textContent = (cur + 1) + ' / ' + hits.length; cnt.classList.remove('snomatch');
  }}
  function run(jump) {{
    clearMarks();
    var q = norm(inp.value).trim(); hits = []; cur = -1;
    if (!q) {{ cnt.textContent = ''; return; }}
    var vars = variants(q);
    document.querySelectorAll(SEL).forEach(function (el) {{
      var t = norm(el.textContent);
      if (vars.some(function (v) {{ return t.indexOf(v) >= 0; }})) hits.push(el);
    }});
    if (!hits.length) {{ cnt.textContent = '결과 없음'; cnt.classList.add('snomatch'); return; }}
    hits.forEach(function (el) {{ vars.forEach(function (v) {{ markIn(el, v); }}); }});
    if (jump) show(0); else cnt.textContent = hits.length + '건';
  }}
  function openBox() {{ box.classList.add('open'); document.getElementById('sbar').classList.add('open'); setTimeout(function () {{ inp.focus(); }}, 120); }}
  function closeBox() {{ box.classList.remove('open'); document.getElementById('sbar').classList.remove('open'); inp.value = ''; clearMarks(); hits = []; cnt.textContent = ''; }}
  document.getElementById('sopen').addEventListener('click', function () {{ if (!box.classList.contains('open')) openBox(); }});
  box.addEventListener('click', function () {{ if (!box.classList.contains('open')) openBox(); }});
  document.getElementById('sclose').addEventListener('click', function (e) {{ e.stopPropagation(); closeBox(); }});
  document.getElementById('snext').addEventListener('click', function () {{ show(cur + 1); }});
  document.getElementById('sprev').addEventListener('click', function () {{ show(cur - 1); }});
  inp.addEventListener('input', function () {{ clearTimeout(timer); timer = setTimeout(function () {{ run(true); }}, 350); }});
  inp.addEventListener('keydown', function (e) {{
    if (e.key === 'Enter') {{ e.preventDefault(); clearTimeout(timer); if (hits.length && cur >= 0) show(e.shiftKey ? cur - 1 : cur + 1); else run(true); }}
    else if (e.key === 'Escape') {{ closeBox(); }}
  }});
}})();

document.getElementById('jup').addEventListener('click', function () {{ window.scrollTo({{ top: 0, behavior: 'smooth' }}); }});
document.getElementById('jdown').addEventListener('click', function () {{
  window.scrollTo({{ top: document.documentElement.scrollHeight, behavior: 'smooth' }});
}});
</script>
</body>
</html>
"""
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")


STORE_FILE = Path("data/articles_store.json")


def merge_store(all_results, ex_words, keep_days=30):
    """지난 실행에서 보여준 기사를 data/articles_store.json에 보관해, 구글뉴스 검색 결과에서 빠지거나
    AI 판정이 흔들려도 30일간은 목록에 남긴다. 공식 입찰(official)은 매번 새로 조회하므로 저장하지 않는다."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    try:
        store = json.loads(STORE_FILE.read_text(encoding="utf-8")) if STORE_FILE.exists() else {}
    except Exception:
        store = {}
    added = 0
    for key, arts in all_results.items():
        have = {a["url"] for a in arts}
        for a in store.get(key, []):
            if a.get("url") in have or (a.get("published") or "") < cutoff:
                continue
            if key == GOV_KEY and any(w in a.get("title", "") for w in ex_words):
                continue
            arts.append(a)
            added += 1
        if key != GOV_KEY:
            arts.sort(key=lambda a: a.get("published") or "", reverse=True)
    if added:
        print(f"  [보관기사] 이전 실행 기사 {added}건 복원")
    out = {k: [a for a in v if not a.get("official") and (a.get("published") or "") >= cutoff]
           for k, v in all_results.items()}
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  [보관기사 경고] 저장 실패: {str(e)[:60]}")


def main():
    seen        = load_seen()
    new_seen    = dict(seen)
    today       = datetime.date.today().isoformat()
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

    new_results = {}
    all_results = {}

    extra_q = GOV_EXTRA_QUERIES + [q for q in load_profile()["과제검색어"] if q not in GOV_EXTRA_QUERIES]
    gov_feeds = TOPICS[GOV_KEY]["feeds"]
    for q in extra_q:
        f = gnews(q, lang="ko", country="KR")
        if f not in gov_feeds:
            gov_feeds.append(f)

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
    g2b = fetch_g2b()
    prof = load_profile()
    if ai_score_bids(g2b, prof):
        kept = []
        for a in g2b:
            sc = a.get("ai_score")
            if sc is None:                       # 판정 누락분은 키워드 방식으로 보완
                sc, why = keyword_score(a, prof["검색키워드"] or G2B_KEYWORDS)
                a["ai_score"], a["ai_reason"] = sc, why
            if sc >= AI_MIN_SCORE:
                kept.append(a)
            else:
                print(f"    [연계도 낮음 제외] {a['title'][:40]} ({sc}점, {a.get('ai_reason','')})")
        g2b = kept
    else:
        for a in g2b:
            a["ai_score"], a["ai_reason"] = keyword_score(a, prof["검색키워드"] or G2B_KEYWORDS)
        g2b = [a for a in g2b if a["ai_score"] >= AI_MIN_SCORE]
    for a in g2b:
        if a["url"] in gov_urls:
            continue
        gov_urls.add(a["url"])
        gov_all.append(a)
        uid = make_id(a["url"])
        if uid not in seen:
            new_seen[uid] = today
            gov_new.append(a)
    # 과제 관련 뉴스도 제목을 AI가 읽고 연계도·유형(공모중/선정·참여/…)을 붙여 관련 없는 기사는 제외
    # 프로필 [제외키워드]가 제목에 있는 과제 뉴스는 AI에 보내기 전에 제외
    ex_words = [w for w in prof["제외키워드"] if w]
    if ex_words:
        def _hit(a):
            return (not a.get("official")) and any(w in a["title"] for w in ex_words)
        for a in gov_all:
            if _hit(a):
                print(f"    [과제뉴스 제외어] {a['title'][:40]}")
        gov_all = [a for a in gov_all if not _hit(a)]
        gov_new = [a for a in gov_new if not _hit(a)]
    news_items = [a for a in gov_all if not a.get("official")]
    if news_items and ai_score_bids(news_items, prof, kind="news"):
        drop = {a["url"] for a in news_items
                if a.get("ai_score") is not None and a["ai_score"] < AI_MIN_SCORE}
        for a in news_items:
            if a["url"] in drop:
                print(f"    [과제뉴스 제외] {a['title'][:40]} ({a['ai_score']}점, {a.get('ai_reason','')})")
        gov_all = [a for a in gov_all if a["url"] not in drop]
        gov_new = [a for a in gov_new if a["url"] not in drop]
    enrich_gov_news(gov_all, os.environ.get(AI_KEY_ENV, "").strip())
    now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    gov_all = [a for a in gov_all if not is_expired(a, now_str)]   # 마감 지난 공고 제외
    gov_new = [a for a in gov_new if not is_expired(a, now_str)]
    gov_all.sort(key=gov_sort_key)
    gov_new.sort(key=gov_sort_key)
    all_results[GOV_KEY] = gov_all
    new_results[GOV_KEY] = gov_new[:MAX_NEW_ARTICLES * 2]
    print(f"  → 신규 {len(new_results[GOV_KEY])}건 / 전체 {len(gov_all)}건")

    merge_store(all_results, [w for w in prof["제외키워드"] if w])
    for k in list(all_results):
        new_u = {a["url"] for a in new_results.get(k, [])}
        grouped = group_same_story([a for a in all_results[k] if not a.get("official")])
        grouped_urls = {a["url"] for a in grouped}
        all_results[k] = [a for a in all_results[k] if a.get("official") or a["url"] in grouped_urls]
        new_results[k] = [a for a in all_results[k]
                          if a["url"] in new_u or any(d["url"] in new_u for d in a.get("dups", []))]
    gov_all = all_results[GOV_KEY]
    gov_all.sort(key=gov_sort_key)
    new_results[GOV_KEY].sort(key=gov_sort_key)
    KST = datetime.timezone(datetime.timedelta(hours=9))
    generated_at = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    build_html(new_results, all_results, generated_at)
    save_seen(new_seen)
    print("\n완료: docs/index.html 생성됨")


if __name__ == "__main__":
    main()
