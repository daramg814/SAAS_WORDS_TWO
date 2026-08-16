# HANDOFF

- 상태: `DONE`
- 요약 한 줄: **운영 이력에 두 번째 500개(`RUN-20260816-224846-KST`)를 기존
  500개(`RUN-20260811-204901-KST`)에 추가로 누적 게시했다.** 800개 후보 중
  782개 승인/18개 리젝트(전부 "X Terminal" 패턴, 기존 회귀 사례와 동일 이유로
  일관 리젝트) → 정확히 500개 선택·게시 → `output/history/words.txt` 이제
  정확히 1000줄. 이어서 동일 파이프라인 QA 20개(`QA-20260816-225030-KST`)도
  실행해 운영 체크섬 불변(QA 전후 `59f56ba3...` 동일) 확인. 커밋 `0d02d05`
  (production 체크포인트), `cbbd707`(QA 체크포인트) — 둘 다 파이프라인 자체
  git 체크포인트가 자동 커밋.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md` → `memory/ACTIVE_ISSUES.md` 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q
   ./.venv/Scripts/python tools/verify_design_coverage.py
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만.**
4. 운영 이력이 이제 1000개(500 + 500)로 채워졌으므로, **다음 production 실행도
   또 새 500개를 추가로 누적**하게 된다(기존 1000개와 정확·대소문자·역순
   중복 없이) — 사용자가 그걸 원하는지 먼저 확인할 것. 단순 재실행은 아직
   요청받지 않았다.

## 2. 이번 배치 (2026-08-16) — 두 번째 운영 500개 + QA 20개

### 2a. 진행 경과

- 사용자가 "단어 500개 생성해줘"라고 요청 → 이미 운영 이력이 500개로 채워진
  상태였으므로 AskUserQuestion으로 확인("기존 확인만" / "신규 500개 추가 누적"
  / "QA 20개만 재실행") → **"신규 500개 추가 누적"** 선택받음.
- `python run.py --mode production --target-count 500` 실행 → 1라운드 800개
  후보 생성 → 현재 세션이 직접 검토(782 승인/18 리젝트) → 정확히 500개 선택
  → 게시(`RUN-20260816-224846-KST`).
  - 리젝트 18건 전부 "X Terminal"(기능어 위치의 Terminal이 운송업 외 다른
    업계 도메인어와 결합해 불명확해지는 기존 회귀 패턴) — 예: Curriculum
    Terminal, Zoning Terminal, Audit Terminal, Refund Terminal 등.
  - "Terminal Lens"/"Terminal Sentry"/"Terminal Map"(운송업, Terminal이
    도메인어 위치)은 기존 판단 기준대로 승인.
- 완료 조건 확인 차 이어서 `python run.py --mode qa --target-count 20` 실행
  → 40개 후보 중 14개 동일 "X Terminal" 패턴 리젝트, 26개 승인 → 20개 선택
  → QA 산출물만 `output/qa/QA-20260816-225030-KST/`에 게시.
  - QA 전후 `output/history/words.txt` SHA-256 체크섬 동일
    (`59f56ba34027b1ab2d96614d316889f9fb5493eda43cc9cb10db2fd4c93f9323`) 확인 —
    운영 데이터 불변 검증 완료.
- 최종 검증: `output/history/words.txt` 정확히 1000줄, 전 구간 형식 통과,
  정확·대소문자·역순 중복 0건(코드 `validate_title_set`이 두 실행 모두에서
  PASS시킴 — 별도 수동 검사 불필요).

### 2b. 다음에 참고할 것

- **"X Terminal"(기능어 위치) 패턴이 이번이 세 번째 재현**(QA 20개 1차,
  운영 500개 1차, 이번 배치 production+QA 재확인) — 승인율은 이번에도
  97.75~97.5% 수준으로 안정적. 여전히 자동화(단어뱅크에서 완전 제거)보다
  판정 단계 개별 처리가 더 정확하다는 기존 결론(`PROJECT_PLAYBOOK.md`,
  `ACTIVE_ISSUES.md` 참고) 유지.
- 운영 이력이 1000줄이 됐으므로 다음 production 실행 시 word bank 소진 여부를
  주의할 것 — `word_generation.generate_combinations`는 전체 조합(도메인어 x
  기능어) 중 이력/블록리스트에 없는 것만 반환하며, 소진 시 `CAPABILITY_
  STAGNATION`으로 정직하게 멈춘다(가짜로 채우지 않음, `word_pipeline.py`
  참고). 조합 풀 규모(324 industry×domain_word 항목 × 59 기능어) 대비
  1000개 소비 정도라 아직 여유가 있으나, 계속 누적되면 언젠가 소진될 수
  있음을 인지할 것.
- `word_pipeline.py`의 `update_memory_and_git_checkpoint` 단계가 매 실행마다
  이 파일(HANDOFF.md)을 최소 템플릿(`상태/현재 단계/마지막 검증/다음 원자
  작업` 4줄)으로 **덮어쓴다** — 실행 직후 이 파일이 짧아져 있는 것은 버그가
  아니라 코드 설계다. 실행 세션이 그 위에 맥락을 다시 채워 넣는 것이 정상
  워크플로우(이번 파일이 그 예).

## 3. Git/원격 설정 — SSH(원격) 세션에서는 push가 원래 안 됨, 정상 동작

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git`.
- SSH(Termius 등) 접속은 Windows 세션 0에서 실행되어 Credential Manager(DPAPI)
  접근이 구조적으로 불가능하다(`query session`으로 확인). PAT가 사라진 게
  아니라 이 세션 종류의 한계.
- **운영 방식(사용자 확정)**: SSH/원격 세션에서는 커밋만 하고 push 실패는
  정상으로 취급한다. push는 PC 앞에서 사용자가 명시적으로 요청할 때만 수행.
- 로컬이 origin보다 몇 커밋 앞서 있는 게 정상 상태. PC에서 push 요청을 받으면
  `git push origin main` 후 `git log --oneline origin/main -1`로 확인할 것.

## 4. DEMAND-001 (프로젝트 정의 전환으로 범위 밖 — 재개 시 다시 유효)

수요/공급 파이프라인은 `pipeline.py`에 그대로 보존되어 있고, 일곱 번의 실측
실패 기록은 `ACTIVE_ISSUES.md`의 `DEMAND-001`에 전부 남아있다. 재개 시 그
문서부터 다시 읽을 것 — "같은 방법을 더 크게" 반복하지 말라는 결론이 유효하다.

## 5. 회귀 사례로 고정된 함정 (재발 방지, 누적)

- 시간/날짜 문자열 키는 절대 문자열로 비교하지 말 것.
- 외부 API가 UTC인데 파이프라인 `now`는 KST로 흐른다.
- 봇 필터링은 액터 로그인 명명 규칙만 믿지 말 것.
- 데이터 볼륨/소스 확대, 유사도 알고리즘 교체 둘 다 1차 유사도 군집화의
  재현율 한계를 해결하지 못한다(DEMAND-001, 재개 시 참고).
- 새 키 없는 공개 API는 클라이언트 코드 전에 curl/urllib로 먼저 찔러볼 것.
- 프로젝트 근본 정의를 바꾸는 지시는 AskUserQuestion으로 구조·발행기준부터
  확인할 것.
- **운영 이력이 이미 채워진 상태에서 "N개 생성해줘"처럼 모드가 불명확한
  요청을 받으면, 곧바로 신규 누적으로 진행하지 말고 AskUserQuestion으로
  "확인만/추가 누적/QA만" 중 무엇을 원하는지 먼저 확인할 것**(2026-08-16
  실제로 이렇게 확인 후 진행해서 헛작업 없이 끝남).
- `title_generation.max_titles_per_opportunity`(30% 상한)는 target_count가
  작으면(<10) cap이 0이 될 수 있다 — 테스트건 실행이건 QA 최소치(10) 미만으로
  이 로직을 쓰지 말 것.
- **"도메인어+기능어" 조합에서 특정 기능어(예: Terminal)가 일부 도메인어와
  결합할 때만 선택적으로 불명확해지는 패턴이 있다** — 기능어 자체를 제거하는
  대신, 판정 단계에서 매번 개별 맥락으로 판단하는 것이 더 정확했다(도메인어로
  쓰일 때는 legitimate한 경우가 있으므로). 세 차례(QA 20개, 운영 500개 1차,
  이번 500개+QA 2차) 모두 동일 판단으로 일관 처리됨.

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상.
- push 자체는 SSH 세션에서 실패하는 게 정상이지만, force-push·히스토리 재작성·
  브랜치 삭제 등 파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
- `pipeline.py`와 그 관련 모듈(수요/공급)을 "안 쓰니까"라는 이유로 삭제하지
  말 것 — 사용자가 명시적으로 "재개"라고 말할 때까지 보존이 원칙.
