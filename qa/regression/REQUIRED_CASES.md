# 필수 회귀 사례

**2026-08-18 개정**: 수요/공급(demand/supply) 파이프라인 완전 삭제 + "정확히 500개
발행"/업계 30% 상한 폐기에 따라, 그 개념에 묶여있던 사례(구 목록의 데이터원 실패,
독립사용자수, 공급 혼합/폐업, 수요·공급 배제, 30% 상한, Google 입력·보정 관련 항목)를
제거했다. 원래 취지는 `git log`(커밋 `d1ca668` 이후)와 `memory/ACTIVE_ISSUES.md`에
보존되어 있다. 아래는 현재 유일한 진입점 `word_pipeline.py` 기준으로 유효한 목록이다.

- QA 19개/21개 실패
- 운영 이력(ledger) 정확/대소문자/역순 중복
- 원자적 쓰기는 부분 파일을 남기지 않음
- 세션 중단·재개(stage/context 보존)
- Git push 실패 시 COMMIT_PENDING(데이터 유실 아님)
- Keyword Planner 게이트: competition_index NULL(죽은 단어)은 avg_monthly_searches가
  아무리 높아도 항상 탈락(GKP-001)
- Keyword Planner 게이트: avg_monthly_searches가 임계값 미만이면 탈락
- Keyword Planner 게이트: 자격증명 누락/일일 예산 초과 시 가짜 통과 없이 예외 전파
- Keyword Planner 게이트: 이미 탈락으로 캐시된 단어는 재생성/재조회하지 않음
- Keyword Planner 게이트: 이미 통과로 캐시된 단어는 API 재호출 없이 캐시값 재사용
- 생성 ledger: AI 승인됐지만 Keyword Planner 미확인인 후보(backlog)는 다음 실행(같은
  run 재개든 새 run이든)에 자동으로 게이트에 반영되어 유실되지 않는다
- 생성 ledger: 한 번 생성+판정된 조합(승인/거절 무관)은 재생성되지 않는다
