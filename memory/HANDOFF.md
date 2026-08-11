# HANDOFF

- 상태: `DONE`
- 요약 한 줄: **프로젝트 정의 전환(업계 단어뱅크 기반 제목 생성) 후 실제 운영
  500개를 끝까지 완료했다.** `RUN-20260811-204901-KST`: 1라운드에서 후보 800개
  생성 → 현재 세션이 직접 검토(790 승인/10 리젝트, "Terminal" 기능어가 일부
  도메인과 결합할 때 불명확해지는 패턴을 QA 라운드에서 이미 확인한 대로 일관되게
  리젝트) → 30% 업계 상한 적용 → 정확히 500개 선택 → 게시. `output/history/
  words.txt` 500줄, 전부 형식 통과, 정확·대소문자 중복 0건. pytest 456 passed.
  커밋 `daaa178`(파이프라인 자체 git 체크포인트가 자동 커밋).

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md` → `memory/ACTIVE_ISSUES.md` 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 456 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만.**
4. 운영 이력이 이제 500개로 채워졌으므로, **다음 production 실행은 새 500개를
   추가로 누적**하게 된다(기존 500개와 중복 없이) — 사용자가 그걸 원하는지
   먼저 확인할 것. 단순 재실행은 아직 요청받지 않았다.

## 2. 프로젝트 정의 전환 + 실제 운영 500개 완료 — 전체 경과

### 2a. 배경과 결정

`DEMAND-001`(수요 관문 통과 군집 0건)을 일곱 가지 방식으로 실측 시도했으나
전부 실패(`ACTIVE_ISSUES.md` 참고). 사용자가 AskUserQuestion으로 확인 후
프로젝트 정의를 전환: 수요/공급 계산 없이 업계 단어뱅크를 조합해 제목만
생성하고, 최소한의 AI 품질 검토(명확성·의미중복·상표유사)는 유지.

### 2b. 구현

- `CLAUDE.md` 전면 개정(§1 프로젝트 정의부터) — 수요/공급 규칙은 삭제 대신
  `*(보류)*`로 표시해 보존.
- `src/saas_words_two/word_bank.py`: 27개 업계 × 도메인어 267개(고유) + 기능어
  59개.
- `src/saas_words_two/word_generation.py`: 결정론적 라운드로빈 조합, 기존
  `title_generation.py`의 순수 수학 함수 재사용.
- `src/saas_words_two/word_pipeline.py`: 새 진입점(DB 미사용). `cli.py`가 이제
  이 모듈을 가리킨다. **`pipeline.py`(수요/공급 기반)는 그대로 보존, 삭제 안 함.**
- 테스트 44개 신규, 전체 pytest 401 → 456.
- `final-qa-runner` 독립 검증 PASS(사소한 문서 미비점 3개 발견 → 즉시 수정).

### 2c. 실제 실행 결과 (QA 20개 → 운영 500개 순서로 검증)

1. **QA 20개**(`QA-20260811-202954-KST`): 40개 후보 중 39개 승인(1개 리젝트:
   "Curriculum Terminal" — terminal이 커리큘럼과 결합할 때 기능 불명확).
2. **운영 500개**(`RUN-20260811-204901-KST`): 800개 후보 중 790개 승인, 10개
   리젝트 — 전부 "X Terminal" 패턴(Zoning/Audit/Maintenance/Grid/Screening/
   Refund/Review/Assembly/Pipeline/Curriculum + Terminal)에서 QA 라운드와
   같은 이유로 일관되게 리젝트. Terminal이 도메인어로 쓰일 때(예: "Terminal
   Keeper", "Dispatch Terminal" — 운송업)는 명확해서 승인, 기능어로 다른
   업계 도메인어와 결합할 때만 불명확해지는 패턴을 확인. 승인율 98.75%
   (790/800) — QA 표본(97.5%)보다 오히려 소폭 높음(같은 기준을 일관되게
   적용한 결과로 판단).
3. 최종 검증: `output/history/words.txt` 정확히 500줄, 전부 `^[A-Z][a-z]* 
   [A-Z][a-z]*$` 형식 통과, 정확 중복 0건, 대소문자 정규화 중복 0건.

### 2d. 다음에 참고할 것

- **"Terminal"을 기능어로 쓸 때의 불명확성 패턴이 두 번(QA 20개, 운영 500개)
  모두 재현됨** — `word_bank.py`의 `FUNCTION_WORDS`에서 아예 빼는 것을 고려할
  수 있으나, "Terminal Keeper"/"Dispatch Terminal"처럼 **도메인어로 쓰일 때는
  legitimate**하므로 완전히 제거하면 그 조합들도 사라진다. 현재는 판정 단계
  (현재 세션)에서 매번 개별 판단하는 것으로 충분히 처리되고 있음 — 리젝트율이
  낮아(전체의 1.25~2.5%) 자동화가 시급하지 않다.
- 운영 이력이 이제 비어있지 않으므로, 다음 `production` 실행 시
  `validate_title_set`이 이번 500개와의 정확/대소문자/역순 중복도 함께
  검사한다(이미 구현·테스트됨, 별도 조치 불필요).
- `DEMAND-001`과 수요/공급 파이프라인은 여전히 보류 상태 — `pipeline.py`는
  그대로 있으니 재개 시 새로 짤 필요 없음.

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
- `title_generation.max_titles_per_opportunity`(30% 상한)는 target_count가
  작으면(<10) cap이 0이 될 수 있다 — 테스트건 실행이건 QA 최소치(10) 미만으로
  이 로직을 쓰지 말 것.
- **"도메인어+기능어" 조합에서 특정 기능어(예: Terminal)가 일부 도메인어와
  결합할 때만 선택적으로 불명확해지는 패턴이 있다** — 기능어 자체를 제거하는
  대신, 판정 단계에서 매번 개별 맥락으로 판단하는 것이 더 정확했다(도메인어로
  쓰일 때는 legitimate한 경우가 있으므로).

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상.
- push 자체는 SSH 세션에서 실패하는 게 정상이지만, force-push·히스토리 재작성·
  브랜치 삭제 등 파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
- `pipeline.py`와 그 관련 모듈(수요/공급)을 "안 쓰니까"라는 이유로 삭제하지
  말 것 — 사용자가 명시적으로 "재개"라고 말할 때까지 보존이 원칙.
