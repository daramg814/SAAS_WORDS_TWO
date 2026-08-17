# 원본 설계서 누락 검증 매트릭스

- 기준 원본: `docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md`
- 검증 방식: 원본의 모든 Markdown 제목을 `DESIGN_COVERAGE.csv`에 1:1 매핑하고, 각 대분류의 원문을 대응 문서에 그대로 보존한다.
- 자동 검증: `python tools/verify_design_coverage.py`
- 매핑된 제목 수: **92개**
- 미매핑 제목 수: **0개**
- 원본 전체 파일도 별도로 보존하므로 세부 예시·표·공식·상태·변경 이력의 추적이 가능하다.

## 2026-08-18 두 번째 프로젝트 정의 전환에 따른 의도적 범위 축소(삭제)

`CLAUDE.md` §1(현재 유효한 프로젝트 정의)에 따라 원본 설계서의 `# 3. 데이터원
정책`·`# 4. 사용자 Google 검증 자산화`(일부)·`# 5. 최소 에이전트 구조`(일부)·
`# 7. 수요 예측 파이프라인`·`# 8. 공급 예측 파이프라인`·`# 9. 공급 희소성 우선
기회 판정`이 설명하는 실행 경로가 **완전히 삭제**됐다(2026-08-11에는 "보류/코드
보존"이었으나 번복 — 코드·테스트·문서·전용 에이전트·스킬까지 전부 삭제, `git log`
커밋 `d1ca668` 이후로 복원 가능). 대응 문서(`docs/pipeline/07-09-*.md`,
`docs/policies/04-05-*.md`)도 삭제됐다. 원본 소스 문서의 heading은 checksum-lock
되어 있어 `DESIGN_COVERAGE.csv`에서 지울 수 없으므로, 해당 행들은 아카이브
자리표시자 `docs/design/DEPRECATED_DEMAND_SUPPLY.md`로 repoint됐다 — 이것은
원본 대비 발견하지 못해 누락된 항목이 아니라 CLAUDE.md §1에 명시적으로 문서화된
의도적 결정이다.

동시에 "정확히 500/20개 확보" 목표·업계 30% 분산 상한(`# 10` 일부)도 폐기됐다 —
`docs/pipeline/10-title-generation.md`가 현재 유효한 4개 문서 모델을 설명한다.

## 대분류 매핑

| 원본 절 | 실행 문서 |
|---|---|
| `# 1. 작업 컨텍스트` | `docs/project/01-project-charter.md` |
| `# 2. 입력과 출력` | `docs/contracts/02-input-output-contracts.md` |
| `# 3. 데이터원 정책` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 4. 사용자 Google 검증 자산화` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 5. 최소 에이전트 구조` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 6. 판단과 코드 역할 분리` | `CLAUDE.md + docs/architecture/06-agents-and-role-separation.md` |
| `# 7. 수요 예측 파이프라인` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 8. 공급 예측 파이프라인` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 9. 공급 희소성 우선 기회 판정` | `docs/design/DEPRECATED_DEMAND_SUPPLY.md`(삭제됨) |
| `# 10. 영어 2단어 제목 생성` | `docs/pipeline/10-title-generation.md` |
| `# 11. 워크플로우와 상태 전이` | `docs/operations/11-workflow-state-memory.md` |
| `# 12. 폴더 구조` | `docs/implementation/14-implementation-roadmap.md` |
| `# 13. 영속 메모리와 토큰 절약` | `docs/operations/11-workflow-state-memory.md` |
| `# 14. 이슈와 노하우` | `docs/operations/11-workflow-state-memory.md` |
| `# 15. Git 원칙` | `docs/operations/12-git-and-recovery.md` |
| `# 16. QA` | `CLAUDE.md + docs/qa/13-qa-and-acceptance.md` |
| `# 17. 구현 우선순위` | `docs/implementation/14-implementation-roadmap.md` |
| `# 18. 최종 인수 기준` | `docs/qa/13-qa-and-acceptance.md` |
| `# 19. 핵심 요약` | `docs/project/01-project-charter.md` |
| `# 20. 버전 변경 이력` | `docs/design/15-version-history.md` |
