
# 구현 시작 지침

## 현재 상태
이 압축 파일은 **Claude Code가 실제 구현을 시작할 수 있도록 계약·문서·설정·에이전트·스킬·코드 골격을 배치한 부트스트랩 프로젝트**다. 데이터 수집과 전체 파이프라인은 아직 완성 구현이 아니며, 미구현 스크립트는 성공한 척하지 않고 명시적으로 종료한다.

## 첫 작업
1. `CLAUDE.md`와 `memory/HANDOFF.md`를 읽는다.
2. `python tools/verify_design_coverage.py`와 `python -m pytest -q`를 실행한다.
3. 1차 구현의 첫 원자 배치인 HN 접근성 검사·증분 수집을 구현한다.
4. 샘플과 회귀 테스트를 추가한다.
5. 동일 진입점 QA를 실행한다.
6. HANDOFF/ACTIVITY_LOG/Git 체크포인트를 갱신한다.

## 구현 순서
`docs/implementation/14-implementation-roadmap.md`를 따른다. 한 번에 전체를 재작성하지 말고 원자 배치별로 검증한다.
