# 레이더 기술 뉴스 트래커

이미징 레이더(자동차/산업/로봇)와 60GHz 헬스케어 레이더 관련 최신 뉴스를
매일 자동으로 수집하여 웹페이지로 보여주는 자동화 도구입니다.

**API 키 없음 · 비용 없음 · GitHub 계정만 있으면 됨**

## 구성요소
- `fetch_news.py` — Google News RSS 수집 + HTML 생성 (표준 라이브러리만 사용)
- `.github/workflows/daily-update.yml` — 매일 오전 8시(KST) 자동 실행
- `docs/index.html` — 결과 웹페이지 (GitHub Pages 호스팅)
- `data/seen_articles.json` — 중복 방지를 위한 기록 파일

## 로컬 테스트

```bash
python fetch_news.py
# 실행 후 docs/index.html 을 브라우저로 열어 확인
```

외부 패키지 설치 불필요 (파이썬 표준 라이브러리만 사용).
