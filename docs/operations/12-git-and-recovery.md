# Git 체크포인트·실패 복구

**목적:** 검증 가능한 원자 배치와 원격 상태 확인을 통해 세션 재개와 데이터 무결성을 보장한다.

## Claude Code 실행 지침
1. 각 원자 배치가 검증되기 전 커밋하지 않는다.
2. push 실패 시 COMMIT_PENDING으로 저장하고 다음 작업을 금지한다.
3. force push, 무검증 reset/history rewrite를 금지한다.
4. data/raw, 캐시, 덤프, 토큰, 쿠키, 개인정보는 커밋하지 않는다.
5. 원격 SHA를 확인한 후에만 다음 배치를 시작한다.

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 15. Git 원칙

모든 원자 작업은 다음 순서로 완료한다.

```text
배치 작업
→ 결과 검증
→ ACTIVITY_LOG·HANDOFF 갱신
→ 필요 시 이슈·노하우 갱신
→ 민감정보 검사
→ commit
→ push origin main
→ 원격 SHA 확인
→ 다음 배치
```

푸시 실패 시 `COMMIT_PENDING`으로 저장하고 다음 작업을 금지한다.

금지:

- force push
- 무검증 reset·history rewrite
- `.env`, 토큰, 쿠키, 개인정보 커밋
- 대용량 원문 데이터 커밋

Git에는 코드·설정·메모리·최종 결과·요약 지표만 저장한다. `/data/raw`, 다운로드 캐시와 대용량 덤프는 `.gitignore`로 제외한다.

---
