---
name: git-checkpoint
description: 원자 배치 Git 저장
---

# git-checkpoint

## 실행 순서
1. 검증 후 커밋
2. 민감정보 검사
3. push origin main
4. 원격 SHA 확인

## 완료 조건
- 결과가 파일/로그/체크섬으로 재현 가능함
- 관련 QA가 PASS함
- 실패를 성공으로 숨기지 않음

## 참조
- `/CLAUDE.md`
- 관련 `docs/` 정책 문서
