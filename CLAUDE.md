
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
존재하지 않는다(2026-08-18 폐기).

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

상세 계약은 `docs/contracts/02-input-output-contracts.md`를 따른다(전환 반영됨).

## 5. 판단과 코드 역할 분리 — 반드시 유지
| 영역 | 코드/스크립트 | 현재 Claude Code 세션·서브에이전트 |
|---|---|---|
| 업계 단어뱅크 구성 | 저장·형식 검증 | 업계 커버리지·단어 적합성 큐레이션 |
| 2단어 조합 생성 | 전담(도메인어+기능어 조합, exclude 기반 중복 방지) | — |
| 정확·역순 중복 제거 | 전담 | — |
| 제목 검토 | 형식 검사 | 명확성·의미 중복·유명 상표 유사 검토 |
| Keyword Planner 게이트 | 전담(순수 수치 비교) | — |
| ledger/캐시 병합·문서 export | 전담(원자적 쓰기) | — |
| QA | 동일 파이프라인 실행 | `final-qa-runner`가 실행 결과 판정 |

전체 매트릭스는 `docs/architecture/06-agents-and-role-separation.md`를 따른다.

## 6. 고정 워크플로우

**현재(2026-08-18 두 번째 전환 이후) 유효한 워크플로우, "한 번의 CLI 실행 = 한 라운드":**
세션 시작 → Git/HANDOFF/PLAYBOOK 로드 → `_stage_load_state`(ledger에서 AI승인·
KP미확인 backlog 스윕) → 단어뱅크에서 round-size만큼 신규 후보 생성(ledger·
blocklist 제외) → 코드 기반 형식·중복 검증 → 제목 명확성·의미 중복·상표 유사
검토(현재 세션) → ledger 기록(문서①) → (backlog + 이번 승인분)에 Keyword Planner
게이트 적용(문서②③④ 갱신) → 메모리·Git 체크포인트. 더 하고 싶으면 다시 실행
(새 run 또는 `--resume`) — 목표 수량을 쫓는 반복 루프는 없다.

제목 생성 세부 규칙은 `docs/pipeline/10-title-generation.md`(전환 반영됨)를 따른다.

## 7. 세션 시작 읽기 순서
1. `CLAUDE.md`
2. `memory/KNOWLEDGE_MANIFEST.yaml`
3. `memory/HANDOFF.md`
4. `memory/PROJECT_PLAYBOOK.md`
5. `memory/ACTIVE_ISSUES.md`
6. 현재 `output/_pipeline/runs/<run_id>/run_state.json`
7. `output/deliverables/history/generated_candidates.csv`/`keyword_metrics_passed.csv` 최근 상태

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

Git과 실패 복구는 `docs/operations/12-git-and-recovery.md`, QA와 최종 완료 판정은 `docs/qa/13-qa-and-acceptance.md`를 따른다.

## 11. 완료 정의
다음이 모두 참일 때만 작업을 완료한다.
- 이번 실행(라운드)이 오류 없이 `DONE`/`CAPABILITY_STAGNATION`/`RETRYING` 중 하나로 정직하게 끝났다.
- 4개 문서(§4)가 스키마대로 갱신됐고, 마스터/스냅샷 내용이 일치한다.
- 제목(단어 조합) 결정이 근거(단어뱅크 출처·업계, 조합 규칙, AI 판정 사유)로 재현된다.
- QA가 동일 진입점과 전체 코드 경로로 PASS한다.
- 필수 회귀 사례(`qa/regression/REQUIRED_CASES.md`)가 통과한다.
- 문서·설정·코드·테스트가 서로 일치한다.
- `python tools/verify_design_coverage.py`가 PASS한다.
