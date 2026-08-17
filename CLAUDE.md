
# SAAS_WORDS_TWO — Claude Code 운영 규칙

## 1. 프로젝트 정의

**2026-08-11 프로젝트 정의 전환(사용자 지시, 현재 유효한 정의).** 원래 설계(공개
데이터에서 수요·공급이 확인된 SaaS 기회를 먼저 발굴한 뒤 그 기회에 맞는 제목을
생성)는 실측으로 `DEMAND-001`(수요 관문 통과 군집 0건)에 일곱 차례 반복 부딪혔고
(볼륨 증가·소스 다양화·군집 알고리즘 교체·전문용어 재현율 확장 등 모두 실측 시도,
`memory/ACTIVE_ISSUES.md` 참고), 사용자가 프로젝트 목적 자체를 다음과 같이
재정의했다:

> 이 프로젝트는 수요·공급을 계산하지 말고, SaaS 제품명으로 쓰일 수 있는 **전세계
> 다양한 업계의 영어 단어를 큐레이션하고 조합해 신규 영어 2단어 Title Case 제목을
> 생성하는 역할**만 한다. 수요·공급에 대한 고민은 이후 별도 단계에서 재개한다.

`production`은 최종 승인 제목을 정확히 500개 게시하고 운영 누적 이력에 반영하며,
`qa`는 동일한 진입점과 전체 코드 경로에서 기본 20개를 생성하되 운영 데이터를
절대 수정하지 않는다 — 이 출력 계약(형식·수량·중복 규칙)은 전환 이전과 **완전히
동일하며 바뀌지 않는다.**

**유지되는 것**: 출력 형식 계약(§4), QA/운영 분리, 원자적 게시·체크섬 검증,
Git·완료 규칙, 코드/AI 판정 역할 분리의 원칙 자체(§5), 제목 명확성·의미 중복·
유명 상표 유사 검토를 현재 세션이 직접 수행하는 것.
**중단되는 것(삭제 아님, 보류)**: 데이터원 수집·수요 군집화·수요 점수·공급 조사·
기회 점수 파이프라인(`src/saas_words_two/pipeline.py`와 관련 모듈). 코드는 그대로
보존하며, 재개 시점은 사용자 지시를 따른다. 이 코드가 만들어낸 실측 결과와
교훈(`memory/ACTIVE_ISSUES.md`의 `DEMAND-001`)은 계속 유효한 기록이다.

원본 설계서는 `docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md`가
여전히 역사적 기준이지만, 위 전환이 실행 규칙의 우선순위를 가진다. 새 규칙과
원본이 충돌하면 이 전환 결정을 따르고, 충돌 사실을 `memory/ACTIVE_ISSUES.md`에
기록한 뒤 QA를 수행한다.

**2026-08-17 Keyword Planner 필터 게이트 추가(사용자 지시, §2.3 개정 포함).**
단어뱅크 조합 승인만으로는 부족하고, 최종 후보가 **Google Ads Keyword Planner
기준 전세계 평균 월간 검색량이 높으면서 광고 경쟁지수가 정확히 0(=NULL이 아님,
즉 "죽은 단어"가 아니라 "경쟁 전무"인 살아있는 단어)인 경우만** 출력에 포함하도록
파이프라인에 코드 기반 게이트를 추가했다. 기준값(`avg_monthly_searches_min`,
`competition_index_exact`)은 `config/keyword_metrics.yaml`에 있으며 그 값만 바꾸면
동작이 바뀐다(§2.3, `memory/ACTIVE_ISSUES.md`의 `GKP-001` 참고). 이 게이트는 §2의
코드/AI 역할 분리 원칙을 따라 순수 수치 비교이므로 전담 코드가 처리하고, 현재
세션의 판정 대상이 아니다.

## 2. 절대 규칙
1. **AI 판정은 현재 실행 중인 Claude Code 세션 또는 그 세션이 호출한 서브에이전트가 직접 수행한다.** 별도의 `anthropic` 패키지, Anthropic API 호출, API 키 설정을 추가하지 않는다.
2. 단어뱅크 조합·형식 검증·정확/역순 중복 제거·원자적 저장은 코드로 처리한다. 업계 커버리지 판단, 단어 적합성 판단, 제목 명확성·의미 중복·유명 상표 유사 검토만 현재 세션/서브에이전트가 수행한다. *(수요/공급 재개 시 이전 역할 분리 표(§5 원표)가 함께 부활한다.)*
3. Google 검색 결과 페이지 스크래핑, CAPTCHA 우회, 브라우저 자동화를 구현하지 않는다.
   **(2026-08-17 개정, 사용자 지시)** 공식 Google Ads API
   (`KeywordPlanIdeaService.generateKeywordIdeas`, OAuth 정식 인증, 공개 REST
   엔드포인트)를 통한 Keyword Planner 연동은 예외적으로 허용한다 — 검색 결과
   페이지를 긁거나 CAPTCHA를 우회하거나 브라우저를 자동화하는 것이 아니라 공식
   API 호출이기 때문이다. Google Trends 의존은 여전히 금지한다. 결정 근거와
   충돌 처리 기록은 `memory/ACTIVE_ISSUES.md`의 `GKP-001` 참고.
4. *(보류 — 데이터원 접근성 QA 규칙. 수요/공급 재개 시 적용.)* 접근성 QA를 통과하지 못한 선택 데이터원은 `DISABLED` 처리하고 가능한 데이터원만으로 계속한다.
5. `production`은 승인 제목이 정확히 500개가 되기 전까지 완료하거나 최종 파일을 게시하지 않는다. 부족분은 중간 출력에만 저장한다.
6. `qa`는 사용자와 동일한 `run.py` 진입점과 동일한 단계·검증·저장 함수를 사용한다. QA 전용 축약 소프트웨어나 별도 제목 생성 로직을 만들지 않는다.
7. QA 전후 운영 `output/history/words.txt` 체크섬은 동일해야 한다. QA 출력은 `output/qa/<qa_run_id>/` 밖에 쓰지 않는다.
8. *(보류 — MARKET_QUERY는 수요/공급 재개 시 적용.)* `TITLE_QUERY`(제목 충돌 보정)는 계속 유효하며, 다른 어떤 점수와도 섞지 않는다.
9. 사람 Google 관측은 append-only 원장에 추가한다. 기존 행을 수정·덮어쓰기 하지 않는다. 제목 상표 충돌 확인용으로 계속 사용 가능하다.
10. 코드·설정·문서 수정 뒤에는 반드시 `final-qa-runner`가 동일 파이프라인 QA를 실행하고 결과물을 검사해야 한다.
11. 강제 푸시, 무검증 이력 재작성, 민감정보·대용량 원문 데이터 커밋을 금지한다.
12. 기존 입출력 계약, 점수 기준, 상태 이름, 파일명 규칙을 임의로 변경하지 않는다. 변경이 필요하면 문서·회귀 QA·인수 기준을 함께 수정한다. *(이번 프로젝트 정의 전환 자체가 이 절차를 따라 문서·회귀·인수 기준을 함께 갱신한 예다.)*

세부 범위·성공/실패 기준은 `docs/project/01-project-charter.md`를 따른다(전환 반영됨).

## 3. 우선순위
1. 근거 추적 가능성과 데이터 무결성
2. 운영/QA 격리와 원자적 게시
3. 입출력 형식 및 정확한 목표 수량
4. 단어뱅크·조합 전략의 재현성과 업계 다양성 *(전환 이전: 공급 희소성 우선 점수의 재현성)*
5. 기존 정상 동작 유지와 회귀 방지
6. 토큰·네트워크·디스크 절약
7. 성능과 코드 미관

## 4. 입력·출력 계약
- 입력: `config/project.yaml`, 선택 `input/brief.md`(업계 범위 지정용), `input/blocklist.txt`, 선택 `input/human_google_checks.csv`(제목 상표 충돌 확인용), 운영 이력 `output/history/words.txt`, 메모리 파일, `src/saas_words_two/word_bank.py`(업계별 단어뱅크), `config/keyword_metrics.yaml`(검색량·경쟁지수 기준값), `.env.local`(Google Ads API 자격증명, git 제외). *(`config/sources.yaml`은 수요/공급 재개 시 다시 쓰인다 — 보류.)*
- 운영 출력: `output/generated/saas_words_YYYYMMDD_HHMMSS_KST.txt` 정확히 500줄, `output/history/words.txt` 원자적 증가. *(`output/final/opportunities.jsonl`은 기회 개념이 없어 더 이상 생성하지 않는다 — 수요/공급 재개 시 부활.)*
- QA 출력: `output/qa/<qa_run_id>/` 내부에만 생성하며 기본 제목 파일은 정확히 20줄이다.
- 제목 형식: UTF-8/LF, 한 줄 하나, 영문자 2단어, 단일 공백, Title Case, 숫자·기호·하이픈 금지, 정확·대소문자·역순·현재 실행·과거 이력 중복 0. **(전환 이전과 완전히 동일, 불변.)**
- **(2026-08-17 신규) Keyword Planner 필터 게이트**: 최종 출력에 포함되려면 후보가
  `config/keyword_metrics.yaml`의 `avg_monthly_searches_min` 이상의 전세계 평균
  월간 검색량과, `competition_index_exact`(기본 0)와 **정확히 같은** 광고
  경쟁지수를 가져야 한다. `competition_index`가 `NULL`(Keyword Planner 응답에
  메트릭 자체가 없음, 통계적으로 유의미하지 않은 "죽은 단어")인 경우는 0과 다르므로
  항상 탈락한다 — 이 둘을 혼동하지 않는 것이 이 게이트의 핵심 요건이다. 이
  판정은 코드가 전담하며(§2 역할 분리), 매 라운드 판정 근거는
  `output/intermediate/<run_id>_keyword_metrics_evidence.jsonl`에 기록되어
  추적 가능하다(§3 우선순위 1).
- 사람 검증: 입력 최소 필드는 `validation_id`, `user_result_count`, `user_checked_at`; 완전 동일한 `validation_id + result_count + checked_at`만 중복 거부한다(제목 상표 충돌 확인용으로 계속 사용 가능).

상세 계약과 스키마는 `docs/contracts/02-input-output-contracts.md` 및 `docs/contracts/03-schema-reference.md`를 따른다(전환 반영됨).

## 5. 판단과 코드 역할 분리 — 반드시 유지
| 영역 | 코드/스크립트 | 현재 Claude Code 세션·서브에이전트 |
|---|---|---|
| 업계 단어뱅크 구성 | 저장·형식 검증 | 업계 커버리지·단어 적합성 큐레이션 |
| 2단어 조합 생성 | 전담(도메인어+기능어 조합) | — |
| 정확·역순·이력 중복 제거 | 전담 | — |
| 제목 검토 | 형식 검사 | 명확성·의미 중복·유명 상표 유사 검토 |
| 사람 Google 입력(제목 상표 확인용) | 파싱·정규화·가중치 계산 | 오차 유형과 규칙 승격 후보 검토 |
| 출력 게시·체크섬·롤백 | 전담 | 게시 승인과 결과 해석 |
| QA | 동일 파이프라인 실행 | `final-qa-runner`가 사용자 결과물 판정 |

전체 매트릭스와 금지 경계는 `docs/architecture/06-agents-and-role-separation.md`를 따른다.

## 6. 고정 워크플로우

**현재(2026-08-17 Keyword Planner 게이트 추가 이후) 유효한 워크플로우:**
세션 시작 → Git/HANDOFF/PLAYBOOK/이력 로드 → 단어뱅크에서 후보 조합 생성 →
코드 기반 형식·중복 검증 → 제목 명확성·의미 중복·상표 유사 검토(현재 세션) →
**코드 기반 Keyword Planner 검색량·경쟁지수 필터(§4 신규 게이트, 두 조건 모두
충족해야 통과)** → 목표 수량 미달 시 반복 생성 → 목표 수량 도달 → 동일 파이프라인
QA → 모드별 원자적 게시 → 메모리·Git 체크포인트.

제목 생성 세부 규칙은 `docs/pipeline/10-title-generation.md`(전환 반영됨)를 따른다.

**보류된 워크플로우(수요/공급 재개 시 부활):** 데이터원 접근성 검사 → 증분 수집 →
코드 기반 후보 축소 → 문제 구조 추출·군집 → 수요 점수 → 통과 문제만 공급 조사 →
활성 제품 분류 → 공급 부족·희소성 점수 → 상위 기회 독립 검토. 상세는 그대로
보존됨:
- `docs/pipeline/07-demand-pipeline.md`
- `docs/pipeline/08-supply-pipeline.md`
- `docs/pipeline/09-opportunity-scoring.md`
- `docs/policies/05-human-google-calibration.md`(제목 상표 확인 부분은 계속 유효)

## 7. 세션 시작 읽기 순서
1. `CLAUDE.md`
2. `memory/KNOWLEDGE_MANIFEST.yaml`
3. `memory/HANDOFF.md`
4. `memory/PROJECT_PLAYBOOK.md`
5. `memory/ACTIVE_ISSUES.md`
6. 현재 `output/runs/<run_id>/run_state.json`
7. 최근 `memory/QUALITY_TRENDS.jsonl`
8. `output/history/words.txt`
9. `memory/human_feedback/google_calibration_metrics.json`
10. 현재 생성 중인 제목과 관련된 최근 사람 Google 관측(상표 충돌 확인용)

전체 활동 로그를 매번 읽지 말고 필요한 Action ID 범위만 검색한다. 세션/상태/메모리 규칙은 `docs/operations/11-workflow-state-memory.md`를 따른다.

## 8. 수정 원칙
- 기존 구조와 공개 계약을 유지하고 필요한 파일만 최소 범위로 수정한다.
- 핵심 점수·중복·게시 로직은 테스트 없이 교체하지 않는다.
- 실패를 숨기거나 부분 결과를 성공으로 표시하지 않는다.
- 새 라이브러리는 표준 라이브러리로 해결할 수 없는 이유와 라이선스·유지보수 위험을 기록한 뒤 추가한다.
- 데이터원·점수·에이전트·출력·메모리 구조 변경 시 문서, 회귀 샘플, QA 인수 기준을 같은 배치에서 갱신한다.
- 한 번 성공한 방법은 `candidate`; 최소 반복 근거와 QA를 통과해야 `validated`로 승격한다.

## 9. 실행·검사 명령
```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python run.py --mode qa --target-count 20
python run.py --mode production --target-count 500
python -m pytest -q
python tools/verify_design_coverage.py
python scripts/validate_outputs.py --help
```
현재 스캐폴드에서 미구현 단계는 성공한 척하지 말고 명시적으로 실패해야 한다. 구현 순서는 `docs/implementation/14-implementation-roadmap.md`를 따른다.

## 10. Git·완료 규칙
원자 배치마다 작업 → 검증 → ACTIVITY_LOG/HANDOFF → 필요 시 이슈·노하우 → 민감정보 검사 → commit → `push origin main` → 원격 SHA 확인 순서를 지킨다. 푸시 실패 시 `COMMIT_PENDING`으로 저장하고 다음 배치를 시작하지 않는다. 세션 한계는 `DONE`이 아니며 검증·인수인계 후 `PAUSED`다.

Git과 실패 복구는 `docs/operations/12-git-and-recovery.md`, QA와 최종 완료 판정은 `docs/qa/13-qa-and-acceptance.md`를 따른다.

## 11. 완료 정의
다음이 모두 참일 때만 작업을 완료한다.
- 해당 모드 목표 수량과 출력 형식이 정확하다.
- 제목(단어 조합) 결정이 근거(단어뱅크 출처·업계, 조합 규칙)로 재현된다. *(전환 이전: 수요·공급·기회·제목 결정이 근거 ID로 재현된다 — 수요/공급 재개 시 부활.)*
- 운영 게시가 원자적이며 증가분과 체크섬이 검증된다.
- QA가 동일 진입점과 전체 코드 경로로 PASS하고 운영 데이터가 불변이다.
- 필수 회귀 사례가 통과한다.
- 문서·설정·코드·테스트가 서로 일치한다.
- `python tools/verify_design_coverage.py`가 PASS한다.
- 원본 설계서 대비 누락 검토는 이 전환으로 인한 의도적 범위 축소(수요/공급 보류)를 반영해 `docs/design/DESIGN_COVERAGE_MATRIX.md`에 기록한다 — 임의 누락이 아니라 §1에 문서화된 결정임을 명시한다.
