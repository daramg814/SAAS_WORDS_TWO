---
paths:
  - "output/**"
  - "src/saas_words_two/word_pipeline.py"
---
# 출력 규칙
- UTF-8 LF, 빈 줄 없음, 한 줄 한 제목을 유지한다.
- 게시 전 형식·중복·blocklist 검사를 수행한다.
- **(2026-08-18 개정)** QA/production은 `output/deliverables/history/`의 4개 문서
  (ledger/Keyword Planner 캐시/통과표/단어리스트)를 공유 갱신한다 — 이건 위반이
  아니라 설계다(같은 조합을 두 번 조회/판정하지 않기 위해, CLAUDE.md §2 규칙6).
  QA run 디렉토리(`output/_pipeline/runs/<run_id>/`) 격리는 판정 요청/응답 등
  실행별 내부 상태에만 적용된다.
