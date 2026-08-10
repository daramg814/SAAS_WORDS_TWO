---
name: pipeline-qa
description: 동일 파이프라인 QA
---

# pipeline-qa

## 실행 순서
1. run.py 사용
2. 기본 20개
3. 운영 체크섬 불변
4. 필수 회귀 판정

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
