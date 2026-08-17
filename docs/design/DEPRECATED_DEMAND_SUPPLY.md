# 폐기된 절 — 수요/공급(demand/supply) 파이프라인

이 문서는 원본 설계서(`docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md`)의
데이터원 정책(§3), 사용자 Google 검증 자산화(§4 일부), 수요 예측 파이프라인(§7),
공급 예측 파이프라인(§8), 공급 희소성 우선 기회 판정(§9) 절을 대신 가리키는
아카이브 문서다.

**2026-08-18, 사용자 지시로 이 절들이 대응하던 실제 구현(`src/saas_words_two/pipeline.py`
및 `db.py`/`google_calibration.py`/`opportunity_scoring.py`/`clustering.py`/`text_filter.py`/
`collection.py`와 각 데이터원 클라이언트, `title_generation.py`의 배분 로직, 관련
스크립트·테스트·`data/local.db`)가 코드베이스에서 완전히 삭제됐다.** 2026-08-11
전환 때는 "보류(코드 보존)"였으나, 이번엔 "완전 삭제"로 결정이 번복됐다.

- 결정 근거와 실측 기록: `memory/ACTIVE_ISSUES.md`의 `DEMAND-001`(일곱 차례 실측
  실패 기록, 그대로 보존됨).
- 삭제 전 코드 전체 이력: `git log`(커밋 `d1ca668` 이후 전체) — 필요하면 그 시점의
  코드를 그대로 복원할 수 있다.
- 새 프로젝트 정의: `CLAUDE.md` §1.

이 문서는 `docs/design/DESIGN_COVERAGE.csv`가 원본 설계서의 heading
존재를 계속 검증할 수 있도록 삭제된 대상 문서들의 자리표시자로만 존재한다 —
내용 자체가 그 절들을 다시 설명하지는 않는다.
