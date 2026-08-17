---
name: title-generation
description: 2단어 후보 반복 생성과 검증
---

# title-generation

## 실행 순서
1. load_state: ledger에서 AI승인·Keyword Planner 미확인 backlog 스윕
2. round-size만큼 신규 후보 생성(ledger·blocklist 제외) → 형식/중복 하드 검사
3. 제목 명확성·의미중복·상표유사 판정 → ledger 기록(승인/거절 무관)
4. (backlog + 이번 승인분) Keyword Planner 게이트 → 4개 문서 갱신(목표 수량 없음, 한 번의 CLI 실행 = 한 라운드)

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
