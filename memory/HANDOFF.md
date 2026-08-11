# HANDOFF

- 상태: `DONE`
- 요약 한 줄: **프로젝트 정의를 전환했다(사용자 지시, 2026-08-11).** 수요/공급
  파이프라인은 `DEMAND-001`(일곱 차례 실측 실패)로 보류하고, 프로젝트를 "업계
  단어뱅크 조합 기반 2단어 SaaS 제목 생성기"로 재정의했다. 새 파이프라인
  (`word_pipeline.py`)을 실제로 구현하고 실제 QA 실행(`QA-20260811-202954-KST`)
  으로 **20/20 제목을 정상 생성·검토·게시까지 끝까지 검증**했다. 운영 이력
  체크섬 불변 확인. pytest 456 passed, `verify_design_coverage.py` PASS. 커밋
  `47897ef`(파이프라인 자체 git 체크포인트 단계가 자동 커밋, 기존 확립된 동작).

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md`(전면 개정됨 — §1 프로젝트 정의부터 다시 읽을 것) →
   `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md` →
   `memory/ACTIVE_ISSUES.md` 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 456 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만**
   (아래 §3).
4. `production --target-count 500` 실행은 아직 안 함 — 다음 세션이 시작하기 좋은
   지점(§4 참고). 실행 전 §2의 "품질 관찰"을 먼저 읽을 것(20개 표본에서 발견한
   약점).

## 2. 이번 전환의 전체 내용

### 2a. 결정 배경

`DEMAND-001`(수요 관문 통과 군집 0건)을 이번 세션에서 일곱 가지 다른 방식으로
실측 시도했으나(볼륨 증가, A안 소스 다양화, B안 알고리즘 교체, 앱 리뷰 소스,
알고리즘 정밀도 튜닝, 업계 전문용어 재현율 확장, 4회 추가 누적 수집) 전부
실패했다(`ACTIVE_ISSUES.md` `DEMAND-001` 참고). 사용자가 프로젝트 목적 자체를
바꾸기로 결정: 수요/공급 계산 없이 업계 단어를 조합해 제목만 생성하고, 수요/공급
고민은 나중에 재개한다.

### 2b. 바뀐 것 / 유지된 것

**유지(불변)**: 출력 형식 계약(2단어 Title Case, 500/20개, 4종 중복 규칙),
QA/운영 분리, 원자적 게시+체크섬 재검증, `run.py` 진입점, Git·완료 규칙,
`RunOptions`/판정 예외 타입/`run_state.py`/`judgment.py`/`contracts.py`.

**중단(삭제 아님, 보류)**: `src/saas_words_two/pipeline.py`(수요/공급/기회
기반 15단계)는 **파일 그대로 보존**, `cli.py`가 더 이상 이걸 가리키지 않을 뿐.
관련 데이터 수집/군집화/점수 모듈(`collection.py`, `clustering.py`,
`demand_scoring.py`, `supply.py`, `opportunity_scoring.py` 등)도 전부 보존.

**신규**:
- `src/saas_words_two/word_bank.py`: 27개 업계 × 도메인어(267개, 예: Vendor,
  Claim, Payroll, Freight) + 기능어(59개, 예: Guard, Tracker, Sync, Flow) 풀.
- `src/saas_words_two/word_generation.py`: 결정론적 라운드로빈 조합 생성 —
  `title_generation.py`의 순수 수학 함수(1차 후보량, 라운드 확대, 30% 상한)를
  "기회" 대신 "업계"에 그대로 재사용(중복 구현 없음).
- `src/saas_words_two/word_pipeline.py`: 새 진입점 파이프라인. 5단계
  (`load_state → generate_and_review_titles → validate_outputs →
  publish_mode_outputs → update_memory_and_git_checkpoint`), **DB를 전혀
  쓰지 않음**(단어 조합은 결정론적이라 관계형 스키마 불필요). `cli.py`가
  이제 이 모듈의 `run_pipeline`을 호출한다(`pipeline.py`는 import되지 않음,
  보존만 됨).
- 테스트 44개 신규(`test_word_bank.py` 6, `test_word_generation.py` 7,
  `test_word_pipeline.py` 13 + 기존 스위트 재검증). 전체 pytest 401(전 배치
  종료 시점 근사치) → **456**.
- 문서: `CLAUDE.md` 1~11장 전면 개정(보류 항목은 "*(보류)*"로 명시, 삭제하지
  않음), `docs/project/01-project-charter.md`·`docs/pipeline/10-title-
  generation.md`·`docs/qa/13-qa-and-acceptance.md`의 "Claude Code 실행 지침"
  갱신("원본 설계 세부 규칙"은 그대로 보존).

### 2c. 실제 QA 실행 결과 — 품질 관찰 (500개 운영 실행 전 참고할 것)

`QA-20260811-202954-KST`: 1라운드에서 40개 후보 생성, 현재 세션이 직접
명확성·의미중복·상표유사 검토 → 39개 승인(1개 리젝트: "Curriculum Terminal" —
terminal이 커리큘럼과 결합했을 때 기능을 추측하기 어려움) → 30% 업계 상한 적용
후 20개 정확히 선택 → `validate_title_set` 통과 → 게시 → 운영 체크섬 불변 확인.

관찰:
- 승인율이 매우 높았다(39/40, 97.5%) — "도메인어+기능어" 조합 전략이 실제로
  대부분 그럴듯한 이름을 만들어낸다는 증거. 다만 이건 **20개 표본, 세션 1회
  판정**이라 500개 규모에서도 이 비율이 유지될지는 미확인.
- 리젝트된 유일한 사례("Curriculum Terminal")는 기능어(`FUNCTION_WORDS`)가
  일부 도메인과 부자연스럽게 결합할 수 있음을 보여준다 — 500개 생성 시 이런
  약한 조합이 더 많이 나올 수 있으니, 만약 승인율이 크게 떨어지면 기능어
  풀에서 애매한 단어(Terminal, Cascade, Anchor 등 이번에 "보더라인"으로
  느꼈던 것들)를 재검토할 것.
- 27개 업계 × 다양한 기능어 조합만으로 30% 상한을 넉넉히 만족했다 — 500개
  운영 실행에서도 업계 분산 자체는 문제 없을 가능성이 높다(각 업계 도메인어
  ~10개 × 기능어 59개 = 업계당 수백 개 조합 가능, 27개 업계 합 15,753개
  전체 조합 중 500개는 3.2%에 불과).

### 2d. 다음 세션이 할 일

1. **`production --target-count 500` 아직 실행 안 함** — 다음 세션이 직접
   실행하고 500개 전체를 성실하게 검토할 것(위 §2c의 관찰을 참고해 판정
   기준을 20개 때보다 느슨하게 하지 말 것 — 표본이 커질수록 애매한 조합도
   늘어날 수 있음을 예상하고 접근).
2. 실행 전 `final-qa-runner` 서브에이전트로 이번 전환 자체(CLAUDE.md 재작성,
   새 파이프라인 코드, 실제 QA 결과)를 독립 검증할 것 — 아직 안 함(이
   HANDOFF 작성 직후 디스패치 예정, 결과가 있으면 여기 추가로 기록될 것).
3. 사용자가 "이제 공급과 수요에 대해 고민을 시작하고"라고 말하면 `pipeline.py`
   (보존됨)를 다시 `cli.py`에 연결하는 방식으로 재개할 것 — 코드는 그대로
   있으니 새로 짤 필요 없음. 다만 재개 시점의 구체적 방식(완전 복귀 vs
   `word_pipeline`과 병행 등)은 그때 다시 사용자에게 확인할 것.

## 3. Git/원격 설정 — SSH(원격) 세션에서는 push가 원래 안 됨, 정상 동작

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git`.
- **근본 원인**: SSH(Termius 등 폰 원격) 접속은 Windows 세션 0(`services`, 비대화형)에서
  실행되는데, Windows Credential Manager(`wincredman`)는 DPAPI로 보호되어 있어
  대화형 로그인(세션 3, `console`)의 키가 있어야 접근 가능하다. PAT가 사라진 게
  아니라 이 세션 종류에서 원래 접근이 안 되는 것.
- **운영 방식(사용자 확정)**: SSH/원격 세션에서는 배치마다 평소대로 커밋만 하고,
  `post-commit` 훅의 push 실패는 정상으로 취급해 다음 배치를 막지 않는다. push는
  사용자가 PC 앞에서 명시적으로 요청할 때만 수행한다. git config은 바꾸지 않는다.
- 로컬이 origin보다 몇 커밋 앞서 있는 게 정상 상태다. PC에서 push 요청을 받으면
  `git push origin main` 실행 후 `git log --oneline origin/main -1`로 확인할 것.

## 4. DEMAND-001 (프로젝트 정의 전환으로 범위 밖 — 재개 시 다시 유효)

수요/공급 파이프라인은 `pipeline.py`에 그대로 보존되어 있고, 관련 실측
기록(일곱 번의 실패 시도)은 `ACTIVE_ISSUES.md`의 `DEMAND-001`에 전부 남아있다.
재개 시 그 문서부터 다시 읽을 것 — 특히 "같은 방법을 더 크게" 반복하지 말라는
누적 결론이 여전히 유효하다.

## 5. 회귀 사례로 고정된 함정 (재발 방지, 누적)

- 시간/날짜 문자열을 키로 쓰는 증분 수집기에서 선행 0 없는 키는 절대 문자열로
  비교하지 말 것 — 반드시 실제 날짜/시간 타입으로 변환해서 비교.
- 외부 API가 UTC 기준 리소스명을 쓰는데 파이프라인 내부 `now`는 KST로 흐른다.
- 봇/자동화 계정 필터링은 이벤트 액터 로그인 명명 규칙만 믿지 말 것.
- 데이터 볼륨/소스를 늘리는 것, 군집 유사도 알고리즘을 바꾸는 것 둘 다 1차
  유사도 군집화의 재현율 한계를 해결하지 못한다(DEMAND-001, 재개 시 참고).
- 새 키 없는 공개 API 후보는 클라이언트 코드를 먼저 짜지 말고 curl/urllib로
  실제 요청 한두 번을 먼저 날려볼 것 — 시간을 크게 아낀다.
- **프로젝트의 근본 정의(CLAUDE.md 1장)를 바꾸는 지시를 받으면, 바로 구현에
  들어가지 말고 먼저 AskUserQuestion으로 구조(완전 전환/순서 역전/병행)와
  발행 기준(최소 검토 필요 여부)을 확인할 것** — 이번엔 확인 후 진행해서
  큰 낭비 없이 끝났지만, 이런 결정은 되돌리기 비용이 크다.
- **`title_generation.max_titles_per_opportunity`(30% 상한)는 target_count가
  작으면(예: 3) `floor(3*0.3)=0`이 되어 어떤 항목도 통과 못 시킨다** — 테스트건
  실제 실행이건 QA 최소 목표(10개) 미만으로 이 로직을 테스트하지 말 것.

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상.
- push 자체는 SSH 세션에서 실패하는 게 정상이지만, force-push·히스토리 재작성·
  브랜치 삭제 등 파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
- `pipeline.py`와 그 관련 모듈(수요/공급)을 "안 쓰니까"라는 이유로 삭제하지
  말 것 — 사용자가 명시적으로 "재개"라고 말할 때까지 보존이 원칙.
