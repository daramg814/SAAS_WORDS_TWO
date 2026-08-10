# HANDOFF

- 상태: `PAUSED`
- 현재 단계: 1차 구현 전체(15개 파이프라인 단계) 코드 완성·240개 테스트 통과·실제
  QA(20개) 실행까지 완료. QA는 `RETRYING`으로 정상 종료(코드 결함 아님, DEMAND-001 참조).
- 마지막 검증: `python run.py --mode qa --target-count 20`을 실제 HN 데이터로 실행.
  source_access_test→collect_sources→filter_pain_sentences→extract_and_cluster_problems
  까지 전 구간 실제 네트워크·판정으로 통과. 4,585개 후보 군집을 정직하게 판정한 결과
  독립 사용자 5명 이상 요건을 통과하는 군집이 없어 `generate_and_review_titles`에서
  `RetryRequired`로 정지(run_id `QA-20260810-215254-KST`). 운영 `output/history/words.txt`
  와 `output/generated/`는 미변경 확인.
- 다음 원자 작업: `memory/ACTIVE_ISSUES.md`의 DEMAND-001 참고해 (1) 2차 데이터원
  (Stack Exchange, GH Archive) 접근성 검사·활성화, 또는 (2) 의미 기반 군집화 검토 후
  QA 재시도.
- 주의: 미구현 상태를 DONE 또는 QA PASS로 기록하지 말 것. 수요 데이터 부족을 감추기
  위해 판정을 완화하거나 가짜 문제를 생성하지 말 것(데이터 무결성 절대 규칙).
- 금지: 운영 `words.txt`/`output/generated/`에 검증되지 않은 부분 결과 기록 금지.
