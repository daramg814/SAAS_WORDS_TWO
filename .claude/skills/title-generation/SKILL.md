---
name: title-generation
description: 2단어 후보 반복 생성과 검증
---

# title-generation

## 실행 순서
1. 기회별 할당
2. 형식/중복 하드 검사
3. 부족분×2 재생성
4. 목표 수량 원자 게시

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
