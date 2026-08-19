
# SAAS_WORDS_TWO — Claude Code 운영 규칙

## 1. 프로젝트 정의

**2026-08-11 프로젝트 정의 전환(사용자 지시, 1차).** 원래 설계(공개 데이터에서
수요·공급이 확인된 SaaS 기회를 먼저 발굴한 뒤 그 기회에 맞는 제목을 생성)는
실측으로 `DEMAND-001`(수요 관문 통과 군집 0건)에 일곱 차례 반복 부딪혔고, 사용자가
프로젝트 목적 자체를 다음과 같이 재정의했다:

> 이 프로젝트는 수요·공급을 계산하지 말고, SaaS 제품명으로 쓰일 수 있는 **전세계
> 다양한 업계의 영어 단어를 큐레이션하고 조합해 신규 영어 2단어 Title Case 제목을
> 생성하는 역할**만 한다.

**2026-08-17 Keyword Planner 필터 게이트 추가(사용자 지시, §2.3 개정 포함).**
단어뱅크 조합 승인만으로는 부족하고, 최종 후보가 **Google Ads Keyword Planner
기준 전세계 평균 월간 검색량이 높으면서 광고 경쟁지수가 정확히 0(=NULL이 아님,
즉 "죽은 단어"가 아니라 "경쟁 전무"인 살아있는 단어)인 경우만** 출력에 포함하도록
코드 기반 게이트를 추가했다. 기준값(`avg_monthly_searches_min`,
`competition_index_exact`)은 `config/keyword_metrics.yaml`에 있으며 그 값만 바꾸면
동작이 바뀐다. 이 게이트는 순수 수치 비교이므로 전담 코드가 처리하고, 현재 세션의
판정 대상이 아니다. 배경·결정 근거는 `memory/ACTIVE_ISSUES.md`의 `GKP-001` 참고.

**2026-08-18 프로젝트 정의 전환(사용자 지시, 2차, 현재 유효한 정의).** 대량 배치
(`--round-size 10000`)를 실제로 여러 번 실행한 결과, GKP-001 게이트의 실측 통과율
(1~3%)로는 "정확히 500개 승인·발행" 계약이 실제 운영 방식과 맞지 않는다는 게
드러났다. 사용자가 다시 정의를 바꿨다:

> 목표 개수(500개)를 채우는 게 산출물이 아니다. **원시 후보를 대량(round-size,
> 기본 QA=50/production=10000)으로 생성 → API로 OK/NG를 가른 로우 데이터를
> 계속 쌓고 → OK만 정리된 표와 단어 리스트가 최종 산출물이다.** "한 번의 CLI
> 실행 = 한 라운드"이고 목표 수량·완료 개념이 없다. 업계 30% 분산 상한도 폐기한다.
> 이 계약 변경으로 필요 없어진 수요/공급(demand/supply) 파이프라인 — 1차 전환
> 때는 "보류(코드 보존)"였던 것 — 을 이번엔 코드·테스트·문서·전용 에이전트·
> 스킬·설정·`data/local.db`까지 전부 삭제한다.

`production`과 `qa`의 유일한 차이는 **round-size 규모**뿐이다(qa=소규모 스모크
테스트, production=실제 대량 배치) — 둘 다 아래 4개 문서를 동일하게 공유
갱신한다(2026-08-17 `bcba8a5`에서 이미 캐시 공유를 "의도된 설계"로 확정한 것의
연장선).

**유지되는 것**: 원자적 쓰기·체크섬 무결성, Git·완료 규칙, 코드/AI 판정 역할
분리 원칙(§5), 제목 명확성·의미 중복·유명 상표 유사 검토를 현재 세션이 직접
수행하는 것, Keyword Planner 게이트(§2.3, §4).
**폐기된 것(삭제, 보류 아님)**: "정확히 500/20개" 목표·완료 개념, 업계 30% 분산
상한, `words.txt`/`generated/` 출력물, 다중 라운드(`MAX_ROUNDS`/shortfall*2) 재생성
루프, 수요/공급 파이프라인 전체(`src/saas_words_two/pipeline.py`와 그 전용
의존성·스크립트·테스트·문서·에이전트·스킬·`data/local.db`) — 삭제된 코드는
`git log`(커밋 `d1ca668` 이후)로 복원 가능하고, 실측 교훈(`DEMAND-001`)은
`memory/ACTIVE_ISSUES.md`에 역사적 기록으로 남아있다.

**2026-08-18 자가확장 단어뱅크 도입(사용자 지시, 같은 날 2차 개정).** 2차 전환
직후 단어뱅크(42업계, 도달가능 25,589 조합)가 실제로 완전 소진됐다. 사용자가
"지구상 영어 단어가 얼마나 많은데 소진이 말이 되냐"고 지적 — 맞는 지적이었다.
소진은 알고리즘 한계가 아니라 `word_bank.py`가 손으로 고른 작은 목록이었기
때문이다. 해결책으로 두 방식(AI가 매 실행마다 그 자리에서 새 단어를 직접
제안 vs. 정적 목록을 수백~수천 배로 미리 확장) 중 **"매 실행마다 AI가 직접
생성"**을 사용자가 선택했다. 구현: `word_generation.generate_combinations`가
병합된 단어 풀(`domain_words`/`function_words` 오버라이드)을 받도록 확장,
조합공간이 소진되면 `word_pipeline`이 즉시 포기하지 않고 `expand_word_bank`
판정 라운드를 한 번 열어 현재 세션이 직접 새 도메인어/기능어를 제안 →
`config/word_bank_expansions.csv`(누적, git 추적, `word_bank.py` 원본은 안 건드림)에
append → 병합 풀로 재시도. 그래도 0개면 그제서야 진짜 `CAPABILITY_STAGNATION`.
실제 자격증명으로 라이브 검증 완료(run `QA-20260818-210404-KST`): 소진 상태에서
자가확장 트리거 → 새 업계 3개(hvac_services/locksmith_security_services/
interpreter_translation_services) + 새 기능어 12개 제안 → 신규 조합 30개 생성 →
AI 판정 20승인 → Keyword Planner 통과 1개(`Furnace Tracker`, 3,600/월·경쟁지수0).

**2026-08-19 단어 생성 노하우 누적 문서 도입(사용자 지시).** 라운드가 반복될
때마다 `expand_word_bank` 판정(새 도메인어/기능어 제안)의 품질이 세션마다
"감"에 좌우되는 문제(실측: 근거 없이 발명한 기능어 10개 중 4개가 즉시 은퇴
확정되며 통과율이 2.59%→0.51%로 급락한 사례)를 구조적으로 줄이기 위해
`memory/WORD_GENERATION_LEARNINGS.md`를 도입했다. "핵심 원칙" 섹션(지금 유효한
원칙 요약)과 "라운드별 로그" 섹션(append-only 시행착오 기록)으로 나뉘며,
**"핵심 원칙" 섹션은 `word_pipeline._write_expand_word_bank_request`가 매번
코드로 강제 추출해 판정 요청의 `accumulated_learnings` 필드에 주입한다** —
`function_word_performance`와 동일하게 세션이 "읽으려는 의지"에 기대지 않는
구조적 전달이다(§5 역할분리 표 참고). `expand_word_bank`로 새 단어를 제안한
라운드가 끝나면(그 라운드의 Keyword Planner 결과가 나온 뒤) 현재 세션이 이
문서에 로그를 append하고 일반화 가능한 교훈이면 핵심 원칙도 갱신해야 한다 —
이건 의미 해석이라 코드가 대신하지 않는다. **(2026-08-19 개정)** 핵심 원칙
각 항목은 `PROJECT_PLAYBOOK.md`와 동일한 `candidate`/`validated` 승격 규칙을
따른다(§8) — 서로 다른 라운드에서 같은 방향 관측 2회 이상 + 반례 없음이면
`validated`. 한 라운드에서 여러 변수를 동시에 바꾸면 그 라운드는 각 변수를
독립적으로 확인해준 게 아니므로(교란) 단독으로 승격 근거가 되지 않는다 —
`expand_word_bank` 판정 시 이 점이 프롬프트에 명시적으로 포함된다.

원본 설계서(`docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md`)는
여전히 역사적 기준이지만, 위 전환들이 실행 규칙의 우선순위를 가진다. 새 규칙과
원본이 충돌하면 전환 결정을 따르고, 충돌 사실을 `memory/ACTIVE_ISSUES.md`에
기록한 뒤 QA를 수행한다.

## 2. 절대 규칙
1. **AI 판정은 현재 실행 중인 Claude Code 세션 또는 그 세션이 호출한 서브에이전트가 직접 수행한다.** 별도의 `anthropic` 패키지, Anthropic API 호출, API 키 설정을 추가하지 않는다.
2. 단어뱅크 조합·형식 검증·정확/역순 중복 제거·원자적 저장은 코드로 처리한다. 업계 커버리지 판단, 단어 적합성 판단, 제목 명확성·의미 중복·유명 상표 유사 검토만 현재 세션/서브에이전트가 수행한다.
3. Google 검색 결과 페이지 스크래핑, CAPTCHA 우회, 브라우저 자동화를 구현하지 않는다.
   **(2026-08-17 개정, 사용자 지시)** 공식 Google Ads API
   (`KeywordPlanIdeaService.generateKeywordIdeas`, OAuth 정식 인증, 공개 REST
   엔드포인트)를 통한 Keyword Planner 연동은 예외적으로 허용한다 — 검색 결과
   페이지를 긁거나 CAPTCHA를 우회하거나 브라우저를 자동화하는 것이 아니라 공식
   API 호출이기 때문이다. 결정 근거는 `memory/ACTIVE_ISSUES.md`의 `GKP-001` 참고.
4. `production`·`qa` 모두 매 실행(라운드)마다 생성한 원시 후보와 그 AI 판정을
   `output/deliverables/history/generated_candidates.csv`(ledger)에 verdict와 무관하게
   전량 기록한다 — 재생성/재판정 낭비를 막고, AI 승인됐지만 Keyword Planner
   미확인인 후보(backlog)가 다음 실행에서 유실되지 않게 하기 위함이다(§4).
5. `qa`는 사용자와 동일한 `run.py` 진입점과 동일한 단계·검증·저장 함수를 사용한다. QA 전용 축약 소프트웨어나 별도 제목 생성 로직을 만들지 않는다. `qa`/`production`의 유일한 차이는 round-size 규모다.
6. **(2026-08-18 명확화)** `output/deliverables/history/`의 4개 문서(ledger/Keyword
   Planner 캐시/통과표/단어리스트, §4)는 QA·production이 공유하는 누적 산출물이다 —
   QA가 이 문서들에 기록을 남기는 것은 위반이 아니라 설계다(같은 조합을 두 번
   조회하지 않기 위해 2026-08-17 배치에서 의도적으로 도입, `GKP-001` 참고).
7. 사람 Google 관측은 append-only 원장에 추가한다. 기존 행을 수정·덮어쓰기 하지 않는다.
8. 코드·설정·문서 수정 뒤에는 반드시 `final-qa-runner`가 동일 파이프라인 QA를 실행하고 결과물을 검사해야 한다.
9. 강제 푸시, 무검증 이력 재작성, 민감정보·대용량 원문 데이터 커밋을 금지한다.
10. 기존 입출력 계약, 점수 기준, 상태 이름, 파일명 규칙을 임의로 변경하지 않는다. 변경이 필요하면 문서·회귀 QA·인수 기준을 함께 수정한다. *(2026-08-11/2026-08-18 두 차례 프로젝트 정의 전환 모두 이 절차를 따라 문서·회귀·인수 기준을 함께 갱신했다.)*

세부 범위·성공/실패 기준은 `docs/project/01-project-charter.md`를 따른다(전환 반영됨).

## 3. 우선순위
1. 근거 추적 가능성과 데이터 무결성
2. 원자적 쓰기와 ledger/캐시 병합 정확성(재생성·재조회 낭비 방지, backlog 유실 방지)
3. 입출력 형식 정확성(제목 형식, 문서 스키마)
4. 단어뱅크·조합 전략의 재현성과 업계 다양성
5. 기존 정상 동작 유지와 회귀 방지
6. 토큰·네트워크·디스크 절약
7. 성능과 코드 미관

## 4. 입력·출력 계약

**입력**: `input/blocklist.txt`, `src/saas_words_two/word_bank.py`(업계별
단어뱅크), `config/keyword_metrics.yaml`(검색량·경쟁지수 기준값), `.env.local`
(Google Ads API 자격증명, git 제외), 메모리 파일.

**출력 — 정확히 4개 문서, 각각 마스터(고정 경로, 항상 최신) + 날짜시간 스냅샷**:

| 카테고리 | 마스터 | 날짜시간 스냅샷 |
|---|---|---|
| ① 원시 생성 전체(제목+업계+AI판정+사유) | `output/deliverables/history/generated_candidates.csv` | `.../snapshots/generated_candidates_<KST타임스탬프>.csv` |
| ② Keyword Planner 조회 OK+NG 전체 | `output/deliverables/history/keyword_metrics_cache.csv` | `.../snapshots/keyword_metrics_cache_<타임스탬프>.csv` |
| ③ OK만 정리된 표 | `output/deliverables/history/keyword_metrics_passed.csv` | `.../snapshots/keyword_metrics_passed_<타임스탬프>.csv` |
| ④ OK 영어단어 리스트 | `output/deliverables/final_words/passed_words_latest.txt` | `output/deliverables/final_words/passed_words_<타임스탬프>.txt` |

목표 개수·완료 개념은 없다 — 매 실행(한 번의 CLI 실행 = 한 라운드)마다 위 4개
문서가 누적 갱신된다. `words.txt`/`output/deliverables/generated/`는 더 이상
존재하지 않는다(2026-08-18 폐기). 4개 문서 전부 UTF-8/LF다(마스터 CSV
①②③은 `csv.DictWriter(..., lineterminator="\n")`로 강제 — final-qa-runner가
실측으로 발견한 CRLF 혼입 버그를 이 배치에서 수정, 기존 데이터도 재정규화함).

**제목 형식**: UTF-8/LF, 한 줄 하나, 영문자 2단어, 단일 공백, Title Case, 숫자·
기호·하이픈 금지. 한 번 생성+판정된 조합(승인/거절 무관, ①에 기록됨)은 재생성
되지 않는다 — 정확·대소문자·역순 중복은 `word_generation.generate_combinations`가
생성 단계에서부터 차단한다.

**Keyword Planner 필터 게이트**: 후보가 `config/keyword_metrics.yaml`의
`avg_monthly_searches_min` 이상의 전세계 평균 월간 검색량과, `competition_index_exact`
(기본 0)와 **정확히 같은** 광고 경쟁지수를 가져야 문서②③④에 OK로 반영된다.
`competition_index`가 `NULL`(메트릭 자체가 없는 "죽은 단어")인 경우는 항상 탈락한다.
판정 근거는 `output/_pipeline/intermediate/<run_id>_keyword_metrics_evidence.jsonl`에
매 라운드 기록된다.

**backlog**: AI 승인됐지만 아직 Keyword Planner 미확인인 후보는 다음 실행(같은
run 재개든 새 run이든) 시작 시 `_stage_load_state`가 자동으로 쓸어담아 재판정 없이
게이트에 먼저 태운다 — 예산 소진/네트워크 크래시로 중단돼도 유실되지 않는다.

**자가확장 단어뱅크(2026-08-18)**: `config/word_bank_expansions.csv`는 위 4개
산출물 문서와 다른 카테고리다 — 판정 결과가 아니라 `word_bank.py`(정적 원본)를
보완하는 원재료 어휘 소스다. 조합공간이 소진되면 `word_pipeline`이
`expand_word_bank` 판정을 한 번 열어 현재 세션이 새 도메인어/기능어를 제안하고,
그 결과가 이 파일에 append된다(`word_bank.py` 자체는 손대지 않음). 매 실행은
`word_bank.py` + 이 파일을 병합한 풀로 후보를 생성한다.

**학습 루프(2026-08-18, 같은 날 3차 개정 — 사용자 지시)**: 통과율을 실측으로
끌어올리기 위한 피드백 구조(`src/saas_words_two/word_performance.py`,
`docs/design/15-continuous-word-quality-improvement.md`). 실측 근거(누적 30,263건):
기능어가 승부를 결정한다 — Portal 5.85%/Map 5.68% vs. Suite/Sync/Dashboard 등
28개 기능어는 각 300회+ 시도에 통과 0건이었고 여기에 API 조회의 32%가 낭비됐다.
세 가지 장치: ① 매 라운드 종료 시 성과 리포트
(`output/_pipeline/analysis/word_performance_latest.md`) 자동 갱신, ②
`config/retired_function_words.csv`(통과 0/시도 300+ 기능어 은퇴 목록, git 추적)
— 병합 풀에서 자동 제외되고 `expand_word_bank`에서 재제안돼도 버려진다, 갱신은
`python tools/analyze_word_performance.py --apply-retirement`, ③ `expand_word_bank`
판정 요청에 기능어 실측 성과 요약이 직접 포함되며, 새 기능어 제안은 승자
패턴(실제 검색되는 구체적 장소·사물 명사)을 따라야 하고 은퇴 패턴(SaaS
전문용어풍 합성어)은 금지다. **Keyword Planner 게이트 임계값은 학습 루프의 조정
대상이 아니다** — 게이트는 시장 신호이며 약화는 가짜 데이터만 늘린다.

**라운드별 정체 점검(2026-08-19, 사용자 지시)**: "라운드가 반복될 때마다 단어 생성
능력이 정말 향상됐는지, 정체되고 있는 건 아닌지"를 사람이 매번 수동으로 판단하지
않아도 되도록, `_stage_update_memory_and_git_checkpoint`(라운드 완료가 확정되는
유일한 지점)가 매 라운드 정확히 한 번 `output/_pipeline/analysis/round_history.csv`
(누적, git 추적, run_id당 1행, 중복 방지 내장)에 이번 라운드의 신규생성·통과 수를
append하고, 최근 구간(누적 생성 500개 이상 모일 때까지 최신 라운드부터 역순 합산)과
그 직전 구간의 통과율을 비교해 `improving`/`stagnant`(상대변화 ±10% 이내)/
`declining`을 판정한다(`word_performance.detect_stagnation`). 판정 결과는 콘솔에
즉시 출력되고 `memory/HANDOFF.md`에도 한 줄로 남아 다음 세션 시작 시 바로 보인다.
backlog만 처리한 라운드(신규 생성 0건)는 구간 계산에서 제외한다(이력에는 보존).
이 절은 데이터를 만들 뿐 판단을 대신하지 않는다 — `stagnant`/`declining` 신호가
나오면 현재 세션이 원인(단어뱅크 확장 방향, 은퇴 목록 적용 누락 등)을 해석해야
한다.

상세 계약은 `docs/contracts/02-input-output-contracts.md`를 따른다(전환 반영됨).

## 5. 판단과 코드 역할 분리 — 반드시 유지
| 영역 | 코드/스크립트 | 현재 Claude Code 세션·서브에이전트 |
|---|---|---|
| 업계 단어뱅크 구성 | 저장·형식 검증 | 업계 커버리지·단어 적합성 큐레이션 |
| 2단어 조합 생성 | 전담(도메인어+기능어 조합, exclude 기반 중복 방지) | — |
| 정확·역순 중복 제거 | 전담 | — |
| 제목 검토 | 형식 검사 | 명확성·의미 중복·유명 상표 유사 검토 |
| 단어뱅크 소진 시 새 도메인어/기능어 제안 | 병합·저장(`config/word_bank_expansions.csv`) | 신규 단어 제안(`expand_word_bank` 판정, 실측 성과 요약 준수) |
| 단어 성과 분석·은퇴 목록 | 전담(순수 통계, `word_performance.py`) | 리포트 해석·확장 제안에 반영 |
| 단어 생성 노하우 누적(`memory/WORD_GENERATION_LEARNINGS.md`) | "핵심 원칙" 섹션 추출·`expand_word_bank` 판정 요청에 강제 주입 | 라운드 결과 해석 후 로그 append·핵심 원칙 갱신 |
| 라운드별 정체 점검(개선/정체/저하 판정) | 전담(순수 수치 비교, `detect_stagnation`) | 정체·저하 신호의 원인 해석·대응 |
| Keyword Planner 게이트 | 전담(순수 수치 비교) | — |
| ledger/캐시 병합·문서 export | 전담(원자적 쓰기) | — |
| QA | 동일 파이프라인 실행 | `final-qa-runner`가 실행 결과 판정 |

전체 매트릭스는 `docs/architecture/06-agents-and-role-separation.md`를 따른다.

## 6. 고정 워크플로우

**현재(2026-08-18 두 번째 전환 이후) 유효한 워크플로우, "한 번의 CLI 실행 = 한 라운드":**
세션 시작 → Git/HANDOFF/PLAYBOOK 로드 → `_stage_load_state`(ledger에서 AI승인·
KP미확인 backlog 스윕) → `word_bank.py`+`word_bank_expansions.csv` 병합 풀에서
round-size만큼 신규 후보 생성(ledger·blocklist 제외) → **0개면** 조합공간이
소진된 것 — 즉시 포기하지 않고 `expand_word_bank` 판정(`memory/
WORD_GENERATION_LEARNINGS.md`의 "핵심 원칙"이 판정 요청에 코드로 강제
주입된 상태에서, 현재 세션이 그 원칙에 맞춰 새 도메인어/기능어 제안) →
확장분 반영 후 재시도, 그래도 0개면 진짜 `CAPABILITY_STAGNATION` → (신규
후보가 있으면) 코드 기반 형식·중복 검증 → 제목 명확성·의미 중복·상표 유사
검토(현재 세션) → ledger 기록(문서①) → (backlog + 이번 승인분)에 Keyword
Planner 게이트 적용(문서②③④ 갱신) → 메모리·Git 체크포인트 → **이번 라운드에
`expand_word_bank`가 있었다면** 그 결과(통과율 변화, 신규 은퇴 단어 유무)를
`memory/WORD_GENERATION_LEARNINGS.md`의 라운드별 로그에 append하고 일반화
가능한 교훈이면 핵심 원칙도 갱신. 더 하고 싶으면 다시 실행(새 run 또는
`--resume`) — 목표 수량을 쫓는 반복 루프는 없다.

제목 생성 세부 규칙은 `docs/pipeline/10-title-generation.md`(전환 반영됨)를 따른다.

## 7. 세션 시작 읽기 순서
1. `CLAUDE.md`
2. `memory/KNOWLEDGE_MANIFEST.yaml`
3. `memory/HANDOFF.md`
4. `memory/PROJECT_PLAYBOOK.md`
5. `memory/ACTIVE_ISSUES.md`
6. 현재 `output/_pipeline/runs/<run_id>/run_state.json`
7. `output/deliverables/history/generated_candidates.csv`/`keyword_metrics_passed.csv` 최근 상태
8. `config/word_bank_expansions.csv`(자가확장으로 누적된 어휘, 있다면)
9. `memory/WORD_GENERATION_LEARNINGS.md`(단어 생성 노하우 누적 — "핵심 원칙"은
   `expand_word_bank` 판정 요청에도 코드로 자동 주입되지만, "라운드별 로그"의
   맥락은 세션 시작 시 직접 읽어야만 파악된다)

전체 활동 로그를 매번 읽지 말고 필요한 범위만 검색한다. 세션/상태/메모리 규칙은 `docs/operations/11-workflow-state-memory.md`를 따른다.

## 8. 수정 원칙
- 기존 구조와 공개 계약을 유지하고 필요한 파일만 최소 범위로 수정한다.
- 핵심 ledger 병합·게이트 로직은 테스트 없이 교체하지 않는다.
- 실패를 숨기거나 부분 결과를 성공으로 표시하지 않는다.
- 새 라이브러리는 표준 라이브러리로 해결할 수 없는 이유와 라이선스·유지보수 위험을 기록한 뒤 추가한다.
- 출력·메모리 구조 변경 시 문서, 회귀 샘플, QA 인수 기준을 같은 배치에서 갱신한다.
- 한 번 성공한 방법은 `candidate`; 최소 반복 근거와 QA를 통과해야 `validated`로 승격한다.

## 9. 실행·검사 명령
```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python run.py --mode qa --round-size 50
python run.py --mode production --round-size 10000
python -m pytest -q
python tools/verify_design_coverage.py
```

## 10. Git·완료 규칙
원자 배치마다 작업 → 검증 → ACTIVITY_LOG/HANDOFF → 필요 시 이슈·노하우 → 민감정보 검사 → commit → `push origin main` → 원격 SHA 확인 순서를 지킨다. 푸시 실패 시 `COMMIT_PENDING`으로 저장하고 다음 배치를 시작하지 않는다. 세션 한계는 `DONE`이 아니며 검증·인수인계 후 `PAUSED`다.

**(2026-08-18 개정)** SSH를 통한 원격 GitHub 인증이 설정되어 있으므로, 휴대폰 Termius SSH 세션에서도 `git push`가 자동으로 작동한다. 새로운 세션에서 동일하게 SSH Push를 설정하려면 `docs/operations/14-remote-ssh-github-authentication.md`를 따른다.

Git과 실패 복구는 `docs/operations/12-git-and-recovery.md`, QA와 최종 완료 판정은 `docs/qa/13-qa-and-acceptance.md`, 원격 SSH 환경의 GitHub 인증은 `docs/operations/14-remote-ssh-github-authentication.md`를 따른다.

## 11. 완료 정의
다음이 모두 참일 때만 작업을 완료한다.
- 이번 실행(라운드)이 오류 없이 `DONE`/`CAPABILITY_STAGNATION`/`RETRYING` 중 하나로 정직하게 끝났다.
- 4개 문서(§4)가 스키마대로 갱신됐고, 마스터/스냅샷 내용이 일치한다.
- 제목(단어 조합) 결정이 근거(단어뱅크 출처·업계, 조합 규칙, AI 판정 사유)로 재현된다.
- QA가 동일 진입점과 전체 코드 경로로 PASS한다.
- 필수 회귀 사례(`qa/regression/REQUIRED_CASES.md`)가 통과한다.
- 문서·설정·코드·테스트가 서로 일치한다.
- `python tools/verify_design_coverage.py`가 PASS한다.
