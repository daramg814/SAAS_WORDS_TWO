---
name: pipeline-qa
description: 동일 파이프라인 QA
---

# pipeline-qa

## 실행 순서
1. run.py 사용(round-size만 소규모로, 그 외 production과 동일 경로)
2. DONE/CAPABILITY_STAGNATION/RETRYING 중 하나로 정직하게 끝나는지 확인(목표 개수 없음)
3. 4개 문서(ledger/캐시/통과표/단어리스트)가 스키마대로 갱신되는지 확인
4. 필수 회귀 판정(`qa/regression/REQUIRED_CASES.md`)

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
