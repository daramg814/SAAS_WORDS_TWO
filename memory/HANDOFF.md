# HANDOFF

- 상태: `PAUSED`(코드/문서 변경은 검증 완료, production 실행은 사용자 확인 대기)
- 요약 한 줄: **`Word_check` 프로젝트의 Google Ads Keyword Planner 연동을 통합해,
  단어 생성 시 `avg_monthly_searches`(전세계 평균 월간 검색량) ≥ 1,000 AND
  `competition_index`(광고 경쟁지수) == 0(NULL 아님)인 후보만 통과시키는
  코드 게이트를 추가했다.** CLAUDE.md §2.3(Google Keyword Planner 의존 금지)과
  충돌해 사용자 확인 후 §2.3을 개정(공식 API는 예외 허용, 스크래핑/CAPTCHA
  우회/브라우저자동화/Trends 의존은 계속 금지). 실제 자격증명으로 QA 20개를
  끝까지(5라운드) 실행해 통합이 진짜로 동작함을 확인했고, 그 과정에서 진짜
  버그 2개(env 인라인 주석 파싱, Google Ads int64 문자열 응답)를 발견해
  즉시 수정·회귀테스트로 고정했다. 전체 테스트 474개 PASS,
  `verify_design_coverage.py` PASS. 상세 근거는 `memory/ACTIVE_ISSUES.md`의
  `GKP-001` 참고.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md`(특히 개정된 §1/§2.3/§4/§6) → `memory/KNOWLEDGE_MANIFEST.yaml` →
   이 파일 → `memory/PROJECT_PLAYBOOK.md` → `memory/ACTIVE_ISSUES.md`의
   `GKP-001` 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q
   ./.venv/Scripts/python tools/verify_design_coverage.py
   ```
3. **`.env.local`(Google Ads 자격증명, git 제외)이 이 프로젝트 루트에 있는지
   확인** - 없으면 `C:\Share\Claude_project\Word_check\.env.local`을 복사한다
   (두 프로젝트가 같은 Google Ads 테스트 계정을 공유한다).
4. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만.**

## 2. 이번 배치 (2026-08-17) — Keyword Planner 필터 게이트 통합

### 2a. 사용자 요청과 처리 경과

- 사용자가 `Word_check`(별도 프로젝트, Google Ads API로 `avg_monthly_searches`/
  `competition_index`를 조회하는 로컬 파이프라인) 문서를 읽고, 매 단어 생성마다
  이 두 지표로 필터링해 조건에 맞는 단어만 출력하도록 요청.
- `avg_monthly_searches`는 "높다"의 기준을 AI가 리서치로 정하고,
  `competition_index`는 정확히 0(NULL 아님)만 통과시키라는 요구.
- CLAUDE.md §2.3과 정면 충돌 확인 → AskUserQuestion으로 확인 → **"§2.3 규칙을
  개정하고 통합 진행"** 선택받음.
- 구현 완료 항목:
  - `CLAUDE.md` §1/§2.3/§4/§6 개정 (2026-08-17 기준 최신).
  - `config/keyword_metrics.yaml` - 필터 기준값(`avg_monthly_searches_min: 1000`,
    `competition_index_exact: 0`)과 API 런타임 설정. **이 파일의 두 숫자만
    바꾸면 필터 동작이 바뀐다** (사용자 요청 그대로).
  - `src/saas_words_two/keyword_metrics_client.py` - Google Ads API REST
    클라이언트(Word_check `local-client.ts` 이식).
  - `src/saas_words_two/word_pipeline.py` - 라운드 루프 안에서 AI 판정 통과
    후보에 대해서만 API 조회, 두 조건 모두 만족해야 `approved`에 편입.
    조회 근거는 `output/intermediate/<run_id>_keyword_metrics_evidence.jsonl`에
    전부 기록(pass/fail 모두).
  - 테스트: `tests/test_keyword_metrics_client.py`(신규, 15개),
    `tests/test_word_pipeline.py`(게이트 통합 테스트 6개 추가 + 기존 테스트
    스텁 클라이언트로 호환 유지).
  - `.env.local`/`.env.example` 추가(Word_check와 동일 계정 재사용).
- **실제 자격증명으로 QA 20개 전체(5라운드) 실행 완료**(`QA-20260817-190618-KST`):
  174개 후보 조회, 4개 통과(약 2.3%), `RETRYING`으로 정직 종료. 이 과정에서
  발견·수정한 실제 버그 2건과 핵심 발견(검색량-경쟁지수 역상관, production
  500개 목표 도달 가능성 낮음)은 `ACTIVE_ISSUES.md`의 `GKP-001` "실측 검증
  결과" 참고.

### 2b. 다음에 반드시 확인할 것 (production 실행 전)

- **실측 통과율(~2.3%)로는 현재 라운드 확장 전략(최대 5라운드, 부족분×2)으로
  production 목표 500개에 도달하지 못하고 `RETRYING`으로 끝날 가능성이 높다**
  - 버그가 아니라 필터의 본질(사용자가 원한 "고검색량+경쟁전무"는 시장
    논리상 희귀한 조합). **다음 production 실행 전 사용자에게 이 실측치를
    알리고 (a) 그대로 실행해 부분 결과/RETRYING을 받아들일지, (b)
    `config/keyword_metrics.yaml`의 `avg_monthly_searches_min`을 낮출지,
    (c) `title_generation.MAX_ROUNDS`/라운드당 후보 수를 늘릴지 확인할 것.**
    기준을 몰래 낮추지 말 것(DEMAND-001 "5명 기준 완화 금지"와 동일 원칙).
- 운영 이력은 이번 배치로 전혀 변경되지 않았다(1000줄 그대로, QA는 스냅샷만
  사용) - 다음 production 실행 시에도 기존 1000개와 중복 없이 신규만 누적된다.
- `output/runs/QA-20260817-190618-KST/run_state.json`은 `RETRYING` 상태로
  저장되어 있다 - 이 run_id로 `--resume`하면 이어서 시도할 수 있지만, 이미
  5라운드(MAX_ROUNDS) 소진 상태라 재시도해도 즉시 같은 `RetryRequired`를
  반환한다(라운드 확장 없이는 무의미) - 새 run_id로 다시 시작하거나 위 (b)/(c)
  조정 후 실행할 것.

## 3. Git/원격 설정 — SSH(원격) 세션에서는 push가 원래 안 됨, 정상 동작

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git`.
- SSH(Termius 등) 접속은 Windows 세션 0에서 실행되어 Credential Manager(DPAPI)
  접근이 구조적으로 불가능하다(`query session`으로 확인). PAT가 사라진 게
  아니라 이 세션 종류의 한계.
- **운영 방식(사용자 확정)**: SSH/원격 세션에서는 커밋만 하고 push 실패는
  정상으로 취급한다. push는 PC 앞에서 사용자가 명시적으로 요청할 때만 수행.

## 4. DEMAND-001 (프로젝트 정의 전환으로 범위 밖 - 재개 시 다시 유효)

수요/공급 파이프라인은 `pipeline.py`에 그대로 보존되어 있고, 일곱 번의 실측
실패 기록은 `ACTIVE_ISSUES.md`의 `DEMAND-001`에 전부 남아있다. 재개 시 그
문서부터 다시 읽을 것.

## 5. 회귀 사례로 고정된 함정 (재발 방지, 누적)

- 시간/날짜 문자열 키는 절대 문자열로 비교하지 말 것.
- 외부 API가 UTC인데 파이프라인 `now`는 KST로 흐른다.
- 봇 필터링은 액터 로그인 명명 규칙만 믿지 말 것.
- 데이터 볼륨/소스 확대, 유사도 알고리즘 교체 둘 다 1차 유사도 군집화의
  재현율 한계를 해결하지 못한다(DEMAND-001, 재개 시 참고).
- 새 키 없는 공개 API는 클라이언트 코드 전에 curl/urllib로 먼저 찔러볼 것.
- 프로젝트 근본 정의를 바꾸는 지시는 AskUserQuestion으로 구조·발행기준부터
  확인할 것. **CLAUDE.md의 절대 규칙과 새 요청이 충돌할 때도 동일하게
  AskUserQuestion으로 개정 여부를 먼저 확인할 것**(2026-08-17 GKP-001에서
  실제로 이렇게 처리함).
- 운영 이력이 이미 채워진 상태에서 "N개 생성해줘"처럼 모드가 불명확한
  요청을 받으면, 곧바로 신규 누적으로 진행하지 말고 AskUserQuestion으로
  확인할 것.
- **"도메인어+기능어" 조합에서 특정 기능어(예: Terminal, Ring)가 일부
  도메인어와 결합할 때만 선택적으로 불명확해지는 패턴이 있다** - 기능어
  자체를 제거하는 대신 판정 단계에서 매번 개별 맥락으로 판단하는 것이 더
  정확하다. 2026-08-17 배치에서도 "X Terminal"(비운송업)과 "X Ring"(추상적)
  패턴을 동일 기준으로 일관 리젝트함.
- **외부 REST API(특히 Google 계열)의 실제 JSON 응답 형식은 문서만 보고
  가정하지 말고 실제 호출로 검증할 것** - 이번 배치에서 두 가지를 실측으로만
  발견함: (1) `.env` 파일의 줄 끝 인라인 주석은 naive 파서가 값에 그대로
  포함시킨다, (2) Google Ads API의 int64 필드(`avgMonthlySearches`)는 JSON에서
  **문자열**로 온다(proto3 JSON 매핑 표준 동작) - `int(json_value)` 같은 타입
  가정을 코드에 하드코딩하지 말 것.
