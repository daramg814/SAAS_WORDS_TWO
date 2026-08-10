---
name: source-access
description: 데이터원 접근성 검사와 증분 수집
---

# source-access

## 실행 순서
1. 샘플 다운로드
2. 형식·압축·필드 검사
3. 중복 방지·디스크 검사
4. PASS만 활성화

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
