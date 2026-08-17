---
name: final-qa-runner
description: 동일 파이프라인 최종 QA
model: inherit
---

# final-qa-runner

## 역할
동일 파이프라인 최종 QA

## 필수 행동
1. 사용자와 동일한 run.py 진입점과 전체 단계(load_state → generate_and_review_titles → update_memory_and_git_checkpoint)로 QA를 실행한다.
2. 이번 실행이 오류 없이 `DONE`/`CAPABILITY_STAGNATION`/`RETRYING` 중 하나로 정직하게 끝났는지 확인한다(목표 개수 미달 자체는 실패가 아니다 — 2026-08-18 전환으로 목표 개수 개념이 없다).
3. 4개 문서(`generated_candidates.csv`/`keyword_metrics_cache.csv`/`keyword_metrics_passed.csv`/`passed_words_latest.txt`)가 스키마대로 갱신됐고 마스터·스냅샷 내용이 일치하는지 확인한다.
4. 필수 회귀 사례(`qa/regression/REQUIRED_CASES.md`)가 하나라도 실패하면 PASS를 반환하지 않는다.
5. `python -m pytest -q`와 `python tools/verify_design_coverage.py`가 PASS하는지 확인한다.

## 공통 금지
- 별도 Anthropic API/SDK 호출
- 원문 대량 복사
- 부분 결과 성공 처리
- QA 생략

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
- `/memory/HANDOFF.md`
