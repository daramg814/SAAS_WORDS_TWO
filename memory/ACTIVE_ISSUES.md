# ACTIVE ISSUES

## GKP-001 — CLAUDE.md §2.3(Google Keyword Planner 의존 금지)과 검색량·경쟁지수 필터 통합 요청 충돌
- 상태: RESOLVED(사용자 확정 예외, §2.3 개정 완료)
- 날짜: 2026-08-17
- 충돌 내용: 사용자가 별도 프로젝트 `Word_check`(`C:\Share\Claude_project\Word_check`,
  Google Ads API `KeywordPlanIdeaService.generateKeywordIdeas`로 `avg_monthly_searches`/
  `competition_index`를 조회하는 로컬 배치 파이프라인, `docs/portable-build-spec.md`
  참고)를 참고해, SAAS_WORDS_TWO가 단어를 생성할 때마다 이 두 지표로 후보를
  필터링하도록 요청했다. 그런데 CLAUDE.md §2.3(개정 전)은 "Google Keyword
  Planner·Google Trends 의존을 구현하지 않는다"를 절대 규칙으로 명시하고 있었고,
  이는 §2.4/§2.8과 달리 "보류" 표시가 없는 현재 유효 규칙이었다 — 요청과 정면
  충돌.
- 사용자 확정 결정(AskUserQuestion): "§2.3 규칙을 개정하고 통합 진행" 선택.
  근거: Word_check는 스크래핑·CAPTCHA 우회·브라우저 자동화가 아니라 공식 Google
  Ads REST API(OAuth 정식 인증)만 사용하므로, §2.3이 실제로 막으려던 대상
  (검색 결과 페이지 긁기·자동화 우회)과는 다른 종류의 연동이다. §2.3을
  "스크래핑/CAPTCHA우회/브라우저자동화는 계속 금지, 공식 API를 통한 Keyword
  Planner 연동은 예외적으로 허용, Google Trends 의존은 계속 금지"로 개정했다
  (`CLAUDE.md` §2.3 참고).
- 구현 내용:
  - `config/keyword_metrics.yaml` — 필터 기준값(`avg_monthly_searches_min`,
    `competition_index_exact`) 및 API 런타임 설정. **이 파일의 두 숫자만 바꾸면
    필터 동작이 바뀐다** — 사용자 요청대로 기준값을 문서 하나에 모아 코드 수정
    없이 조정 가능하게 함.
  - `src/saas_words_two/keyword_metrics_client.py` — Word_check의
    `src/ads-api/local-client.ts`를 Python으로 이식(OAuth refresh token 인증,
    `generateKeywordIdeas` REST 호출, 배치당 20개 하드 제한, 429/401 재시도,
    일일 예산 가드). Word_check와 동일한 Google Ads 계정/자격증명을 재사용한다
    (`.env.local`, git 제외 — Word_check의 자격증명 발급 절차를 그대로 따름).
  - `src/saas_words_two/word_pipeline.py` — 제목 생성 라운드 루프 안에서, AI
    판정(명확성·의미중복·상표유사)을 통과한 후보에 대해서만 Keyword Planner
    조회를 실행하고, 두 조건을 모두 만족하는 것만 `approved`에 편입한다. 조회
    결과(통과/탈락 모두)는 `output/intermediate/<run_id>_keyword_metrics_evidence.jsonl`에
    기록해 추적 가능성을 확보한다.
- **`avg_monthly_searches_min` 기준값 결정(AI 리서치, 사용자가 위임)**: 1,000/월
  (전세계 기준)로 설정. 근거: (1) SEO/PPC 업계에 공식 고정 구간은 없지만, 일반적
  실무 관행에서 월 1,000회 이상은 "고검색량/헤드텀" 영역 진입점으로 통상
  간주되고, Semrush 등은 100회 이상을 "타겟팅할 가치가 있는" 최소선으로 제시한다
  — 1,000은 그보다 한 단계 위인 "높다"에 해당하는 값이다. (2) 이 프로젝트가
  필터링하는 대상은 사전에 없던 "도메인어+기능어" 신조어 조합이라, Keyword
  Planner가 애초에 메트릭 자체를 반환하지 않는(통계적으로 유의미하지 않음) 경우가
  대다수일 것으로 예상된다 — 값을 너무 높게(예: 10,000+) 잡으면 통과 후보가
  사실상 영구히 0개가 되어 게이트 자체가 무의미해진다. 1,000은 "일부는 통과할 수
  있는 현실적인 높은 기준"과 "고검색량이라는 취지 유지"의 균형점으로 AI가 판단해
  선택했다. **이 값이 실측(QA/production 실행)으로 통과율이 지나치게 낮거나
  높은 것으로 확인되면, `config/keyword_metrics.yaml` 값만 조정하면 된다** — 코드
  변경 불필요.
- `competition_index_exact = 0`은 사용자가 직접 지정(협상 대상 아님) — `NULL`
  (메트릭 없음, "죽은 단어")과 `0`(경쟁 없음, 살아있는 단어)을 명확히 구분해서
  `NULL`은 항상 탈락시킨다.
- 남은 리스크(다음 세션 참고): 신조어 2단어 조합 대부분이 메트릭 없음으로
  탈락할 가능성이 높아, 기존 `title_generation.MAX_ROUNDS=5`/부족분×2 라운드
  확장 전략만으로 목표 수량(500/20)에 도달하지 못하고 `RETRYING`/
  `CAPABILITY_STAGNATION`으로 끝나는 빈도가 높아질 수 있다. 이는 코드 결함이
  아니라 이 필터의 본질적 특성(사용자가 명시적으로 요청한 "매우 드문 조건")이다.
  실측 통과율을 확인한 뒤 필요하면 (a) 기준값 완화, (b) `MAX_ROUNDS`/후보
  생성량 확대, (c) 단어뱅크 확장 중 사용자와 협의해 조정할 것 — "5명 기준
  완화 금지"(DEMAND-001)처럼 기준을 몰래 낮추지 말고 반드시 근거와 함께
  사용자 확인을 받을 것.

### 실측 검증 결과 (2026-08-17, 실제 Google Ads API로 QA 20개 전체 실행)

- `python run.py --mode qa --target-count 20`을 실제 자격증명(Word_check와
  공유하는 테스트 계정)으로 5라운드(=`MAX_ROUNDS`) 전부 실행함
  (run_id `QA-20260817-190618-KST`). 174개 후보를 실제 조회한 결과 **4개만
  두 조건을 모두 통과**(`Audit Desk` 2,400/월·0, `Ticket Board` 40,500/월·0,
  `Terminal Map` 3,600/월·0, `Dispatch Center` 1,300/월·0) — 통과율 약 2.3%.
  20개 목표에 4개만 확보한 채 `RETRYING`으로 정직하게 종료(가짜로 채우지
  않음, 운영 데이터 미접촉 확인).
- 이 실행 도중 **진짜 결함 2개를 실측으로 발견해 즉시 수정**:
  1. `.env.local`의 실제 형식(`GOOGLE_ADS_CUSTOMER_ID=123  # 주석` 같은 줄
     끝 인라인 주석)을 최초 구현의 단순 파서가 값에 그대로 포함시켜 API가
     404를 반환함 - `keyword_metrics_client.load_env_file`이 인라인 주석을
     제거하도록 수정.
  2. Google Ads API가 `avgMonthlySearches`(proto int64)를 JSON에서 **문자열로
     직렬화**해서 반환하는데(proto3 JSON 매핑의 표준 동작, precision loss 방지
     목적), 최초 구현이 이를 그대로 비교에 사용해 `avg >= threshold`에서
     `TypeError`가 났다 - `_coerce_number`로 숫자 강제 변환 추가.
     `competitionIndex`(int32)도 방어적으로 동일 처리.
  둘 다 회귀 테스트로 고정함(`tests/test_keyword_metrics_client.py`의
  `test_load_env_file_strips_trailing_inline_comments`,
  `test_fetch_metrics_coerces_string_encoded_int64_avg_searches`).
- **핵심 발견(중요, 다음 production 실행 전 반드시 참고)**: 실측 데이터를 보면
  경쟁지수가 정확히 0인 단어는 검색량도 대체로 낮고(10~320대가 다수), 검색량이
  1,000을 크게 넘는 단어는 경쟁지수도 0이 아닌 경우가 대부분이었다(예: `Grid
  Station` 3,600/월·경쟁지수 1, `Brand Studio` 8,100/월·경쟁지수 5) - 시장
  논리상 자연스러운 상관관계(검색량이 높으면 광고주가 붙어 경쟁지수도 올라감).
  즉 "검색량 높음 AND 경쟁지수 정확히 0"은 사용자가 원한 대로 진짜 희귀한
  "차익거래"급 조건이며, 통과율 2.3%는 우연이 아니라 이 필터의 본질이다.
  **production(목표 500개)에 그대로 적용하면**: 현재 통과율(2.3%)과 라운드당
  후보 생성량(`first_round_size`/`next_round_size`, 부족분×2, 최대 5라운드)
  으로는 5라운드 누적 후보가 수천 개 수준에 그쳐 500개에 크게 못 미칠
  가능성이 높다(단순 산술로 대략 100개 안팎 예상) - `RETRYING`으로 끝날
  가능성이 실측상 높다. 이는 버그가 아니라 정직한 결과이지만, **다음
  production 실행 전 사용자에게 이 실측 통과율을 알리고 (a) 그대로 실행해
  `RETRYING`을 받아들일지, (b) `avg_monthly_searches_min`을 낮출지, (c)
  `MAX_ROUNDS`/라운드당 후보 수를 늘릴지 확인할 것** - 기준을 몰래 낮추지
  말 것.
- QA 산출물: `output/runs/QA-20260817-190618-KST/run_state.json`(승인 4건
  기록), `output/intermediate/QA-20260817-190618-KST_keyword_metrics_evidence.jsonl`
  (174건 전체 조회 근거, `.gitignore` 대상이라 로컬에만 있음). 운영
  `output/history/words.txt`는 이 실행으로 전혀 변경되지 않음(QA는 스냅샷만
  사용).

### 10,000개 대량 배치 실측 + 누적 캐시/`--round-size` 도입 (2026-08-17, 사용자 지시)

- 사용자가 "target_count=100, 통과율 1% 가정, 한 번에 10,000개씩 시도"를
  제안 → `RunOptions.round_size`/CLI `--round-size` 옵션을 신설해 라운드
  후보 수를 target 기반 공식 대신 고정값으로 지정 가능하게 함.
  (`title_generation.first_round_size`/`next_round_size` 자체는 원본
  demand/supply 경로용으로 그대로 보존, 이 옵션은 word_pipeline에서만
  우선 적용됨.)
- `python run.py --mode qa --target-count 100 --round-size 10000`을 실제
  자격증명으로 실행(run_id `QA-20260817-192736-KST`). **실측 3회 시도** 끝에
  완주:
  1차·2차 시도는 각각 진행률 49%(`RemoteDisconnected`), 91%(`503 Service
  Unavailable`) 지점에서 예외 미처리로 전체가 죽어 아무것도 안 남음(당시
  `KeywordMetricsClient`가 연결오류/5xx에 재시도 로직이 전혀 없었음 -
  python.md "네트워크 경계는 명시적 재시도" 위반, 실측으로 발견해 즉시 수정:
  연결오류/5xx는 최대 3회 재시도 후 그래도 실패하면 해당 배치만 "failed"로
  기록하고 전체 라운드는 계속 진행하도록 고침, 4xx는 재시도 없이 즉시 실패
  전파).
- 10,000개 1라운드 결과: **86개 통과**(0.89%) - 앞선 20개 QA 실측(2.30%)과
  같은 자릿수, 실행마다 표본이 달라 정확한 비율은 변동됨. 목표(100) 부족분
  14를 메우려 기존 공식(`shortfall*2`)이 27개짜리 2라운드를 생성했는데
  **0개 통과** - 통과율 ~1%에서 27개 배치가 0개를 뽑을 확률은 약 78%로,
  버그가 아니라 통계적으로 정상. 사용자가 "목표 개수를 쫓지 말고 10,000개
  고정 배치를 기준 단위로 삼으라"고 지시 → `round_size`가 라운드 1뿐 아니라
  **모든 라운드**에 균일 적용되도록 수정(`word_pipeline.py`,
  `tests/test_word_pipeline.py`의
  `test_round_size_override_also_controls_round2_candidate_count`로 회귀
  고정). 이 run(`QA-20260817-192736-KST`)은 round 3(28개) 판정 대기 상태로
  방치 - 소규모 라운드 추가 요청 자체가 새 방침과 안 맞아 더 진행하지 않음,
  86개 승인 실적은 유효한 실측 데이터로 보존.
- **누적 raw 데이터 캐시 신설**(사용자 지시): `output/history/
  keyword_metrics_cache.csv`(조회한 모든 단어, pass/fail 전부, 20개 배치
  단위로 즉시 append - 위 크래시 2건처럼 중간에 죽어도 그 지점까지는
  보존됨), `output/history/keyword_metrics_passed.csv`(그중 pass만 별도
  추출). `word_pipeline._excluded_normalized`가 캐시에 fail로 기록된 단어를
  제외 집합에 포함시켜 이후 어떤 실행에서도 재생성/재판정/재조회하지 않음
  - pass 기록은 제외하지 않고(아직 안 쓴 유효 후보), 대신
  `_apply_keyword_metrics_filter`가 캐시 적중 시 API 재호출 없이 재사용함.
  상세 계약은 `docs/contracts/02-input-output-contracts.md` 참고.
- **다음 세션 참고**: production(목표 500)을 이 게이트로 실제 달성하려면
  `--round-size 10000` 기준 약 5~6라운드(500/86≈5.8)가 필요할 것으로
  추정됨(실측 1회 표본 기준, 변동 가능) - 실행 전 사용자와 라운드 수/시간·
  API 예산 소요를 다시 확인할 것.

## PROCESS-001 — SSH/원격 세션 push 정책이 원본 설계 §15 Git 원칙과 충돌
- 상태: OPEN (사용자 확정 예외, 재논의 대상 아님 — 아래 참고)
- 충돌 내용: 원본 설계서 `# 15. Git 원칙`은 "푸시 실패 시 `COMMIT_PENDING`으로 저장하고
  **다음 작업을 금지한다**"라고 명시한다. CLAUDE.md 10항도 동일하게 "푸시 실패 시
  COMMIT_PENDING으로 저장하고 다음 배치를 시작하지 않는다"를 그대로 옮겨 적었다.
  그런데 2026-08-10~11 세션에서 사용자가 폰(Termius)으로 SSH 원격 접속해 작업하는
  동안 매 커밋마다 `post-commit` 훅의 자동 push가 실패했고, 사용자와 협의해
  **"SSH 세션에서는 push 실패를 다음 배치를 막는 사유로 보지 않고, 커밋만 정상적으로
  계속하며 push는 PC 앞에서 사용자가 명시적으로 요청할 때만 수행한다"**로 운영 방식을
  변경했다(`memory/HANDOFF.md` §3, `feedback_ssh_push_policy` 세션 메모리 참고).
  이는 원본/CLAUDE.md의 "다음 작업 금지" 문구를 문자 그대로 지키지 않는 명백한 예외다.
- 근본 원인: SSH(Termius 등) 접속은 Windows 세션 0(`services`, 비대화형)에서 실행되어
  Windows Credential Manager(DPAPI 보호)에 접근할 수 없고 `/dev/tty`도 없어 GCM 인증이
  구조적으로 불가능하다(`query session`으로 실제 확인). PC 앞 대화형 세션(세션 3)에서는
  이 문제가 없다 — 즉 PAT가 사라진 게 아니라 세션 종류의 구조적 한계다.
- 원본 의도 보존 여부: 원본 규칙의 진짜 목적은 "커밋된 작업이 유실되지 않게 하는 것"과
  "원격과 로컬이 오래 벌어지지 않게 하는 것"으로 판단된다. 이 예외는 (a) 커밋 자체는
  매 배치 정상적으로 수행되고(`git log`/`git reflog`로 전부 추적·복구 가능,
  reflog 기본 보존 90일), (b) push는 없어지는 게 아니라 "PC 세션까지 지연"되는 것이며,
  (c) force-push·히스토리 재작성 등 실제로 위험한 작업은 여전히 전부 사용자 확인을
  거친다는 점에서, 원본의 핵심 의도(작업 유실 방지)는 보존된다고 판단한다. 다만
  "다음 작업을 금지한다"는 문구 자체는 문자 그대로 지켜지지 않으므로 이 항목을 OPEN으로
  유지해 투명하게 기록한다.
- 조치: 재논의 대상 아님(사용자 명시 확정). git config·자격증명 저장 방식은 변경하지
  않았다. PC에서 push를 실제로 완료하면 이 항목에 결과를 추가 기록할 것.

## BOOTSTRAP-001 — 핵심 데이터 파이프라인 미구현
- 상태: RESOLVED (구현 완료, 아래 DEMAND-001로 이어짐)
- 영향: 1차 구현 전체(수집·필터·군집화·수요·공급·기회·제목·발행·구글보정·핸드오프/Git)를
  실제 동작 코드로 구현하고 240개 자동화 테스트로 검증함. 상세: git 로그
  (`chore: import ChatGPT-authored bootstrap scaffold` 이후 전체 커밋).
- 완료 조건 충족 여부: 코드 경로는 전체 PASS. 실제 QA 20개 달성은 DEMAND-001 참조.

## DEMAND-001 — HN 단독 1차 데이터원으로는 수요 관문(독립 사용자 5명) 통과 군집이 사실상 없음
- 상태: **보류(사용자 지시, 2026-08-11 프로젝트 정의 전환)** — 아래 실측 기록은
  전부 유효한 역사적 근거로 유지한다. 프로젝트는 당분간 수요/공급 계산을 하지
  않기로 재정의됐다(`CLAUDE.md` §1, `memory/HANDOFF.md` §2). 관련 파이프라인
  코드(`pipeline.py` 등)는 삭제하지 않고 보존됨 — 사용자가 "수요/공급 재개"를
  지시하면 이 이슈부터 다시 읽고 재개할 것. 아래는 보류 전 마지막 상태(OPEN,
  일곱 번 실측 시도 전부 실패)다.
- 증상: `python run.py --mode qa --target-count 20`을 실제 HN 데이터(검색 수집 포함
  4,585개 후보 군집)로 실행한 결과, 독립 사용자 수 상위 16개 군집을 모두 직접 검토했으나
  전부 (a) HN 관용구("feature requests welcome!", "way too complicated"가 서로 무관한
  수십 개 주제에 붙은 경우) 또는 (b) "How do you manage X/What do you use for X" 질문
  템플릿(X가 매번 다른 주제: dotfiles, 세금, 가족사, 탭 관리 등)이었다. 동일한 구체적
  SaaS 문제를 5명 이상이 독립적으로 언급한 군집은 하나도 발견하지 못했다.
- 영향: `extract_and_cluster_problems` 판정에서 전체 군집을 정직하게 REJECT하면
  `problems`/`opportunities`/`titles`가 모두 0건이 되어 `generate_and_review_titles`
  단계가 `RetryRequired`로 정지한다(run_id `QA-20260810-215254-KST`, 최종 상태
  `RETRYING`). 파이프라인 코드 자체는 소스 접근성→수집→필터→군집화→수요점수까지
  전 구간이 실제로 정상 동작했고, 운영 `output/history/words.txt`와
  `output/generated/`는 전혀 건드리지 않았다(설계된 "실패 시 미발행" 요건 충족 확인).
- 오류 시그니처: 없음(코드 예외 아님). 정상적인 `RETRYING` 종료 코드 4.
- 시도:
  1. `search_hits_per_pattern`을 40→300→1000(Algolia 최대)으로, 후보 문장을
     332→1,495→4,133개로 확대. 군집 품질은 개선되지 않음(볼륨이 늘수록 다양한
     무관 주제만 늘어남).
  2. 1차 군집화 알고리즘의 트리거 문구 제거 로직으로 명백한 오탐(공유 질문 템플릿)은
     줄였으나, 근본적으로 서로 다른 주제가 우연히 같은 관용구를 공유하는 경우까지
     걸러내지는 못함(이는 애초에 애매 군집으로 표시되어 AI 판정으로 넘어가도록 설계됨 — 설계대로 동작).
- 실패 이유(근본 원인): 문자열 유사도 1차 군집화는 "표현이 비슷한 문장"만 묶을 수 있고,
  서로 다른 표현으로 같은 문제를 말하는 진짜 반복 사례는 애초에 묶이지 않는다(재현율
  한계, 설계상 알려진 트레이드오프). 더 근본적으로는 Hacker News라는 단일 데이터원의
  특성상 폭넓고 기술적인 담론이 우세하며, 좁고 구체적인 업무 문제가 5명 이상에게서
  독립적으로 반복 언급될 확률이 낮다.
- 최종 해결: 미해결. 사용자와 협의해 "정직하게 진행 후 RETRYING 보고"로 결정(가짜
  판정으로 수량을 채우지 않음 — CLAUDE.md 데이터 무결성 원칙 우선).
- 검증: 코드 경로 자체는 240개 pytest + 실제 네트워크 실행으로 검증 완료. 수요
  데이터 부족은 코드 결함이 아니라 데이터 가용성 문제임을 확인.
- 다음 조치(2026-08-10, 사용자 확정): **A안부터 착수** — 2차 데이터원(Stack Exchange
  덤프 또는 GH Archive) 활성화. `sources.yaml`에 이미 게이트로 준비되어 있음. 좁고
  반복적인 기술 질문이 HN보다 많을 가능성이 높다는 판단. A안 시도 후에도 부족하면
  B안(의미 기반/임베딩 군집화, `docs/implementation/14-implementation-roadmap.md`
  3차 개선 항목)을 고려. "5명" 기준 완화는 검토 대상 아님(CLAUDE.md 12항 위반).
  상세 절차는 `memory/HANDOFF.md` §5 참고.
- 수정 파일: 해당 없음(코드 결함 아님). 관련 실행 기록:
  `output/runs/QA-20260810-215254-KST/`, `output/qa/QA-20260810-215254-KST/`.

### 진행 상황 업데이트 (2026-08-10, A안 구현 배치)

- 사용자가 GH Archive를 A안 데이터원으로 확정. 접근성 검사를 실제 네트워크로 실행해
  PASS 확인(hour=2026-08-10-7, total_events=163763, normalizable_events=29 —
  IssuesEvent(opened)/IssueCommentEvent(created) 중 봇 액터 제외). `sources.yaml`의
  `gh_archive.enabled: true`로 전환.
- 수집 코드(`gh_archive_client.py`, `collection.py::run_gh_archive_collection`),
  DB 스키마 확장(`hn_items.source` 컬럼), `collect_sources.py` 연결, 테스트 27개
  전부 구현·커밋 완료(pytest 240→258 통과, `verify_design_coverage.py` PASS 유지).
  상세는 `memory/HANDOFF.md` §2, §5 참고.

### A안 실데이터 검증 결과 (2026-08-10) — **A안으로는 DEMAND-001 해소되지 않음**

- `scripts/collect_sources.py`를 실제 네트워크로 4회 반복 실행해 GH Archive
  36시간치(2026-05-13-00 ~ 2026-05-14-02, `recent_days_max=90` 하한부터 시작)를
  수집. 수집 도중 봇 필터 결함을 하나 더 발견해 수정함 — 액터 로그인의 `[bot]`
  접미사만 봤더니 GitHub 자체 Copilot 리뷰 봇처럼 `user.type=="Bot"`이지만 액터
  로그인엔 접미사가 없는 계정을 놓쳤다(커밋 `09f9f29`). 수정 후 기존 필터-오탐
  데이터는 삭제하고 재수집.
- 최종 수집량: `hn_items` 총 44,842건(HN story 4,568 + comment 11,566, gh_archive
  story 8,908 + comment 19,800). 후보 문장 5,482~5,190개(필터/군집 재실행 시점에
  따라 약간 변동) — HN 단독 시점(4,133개)보다 훨씬 많음.
- **실제 파이프라인 QA를 끝까지 실행함**: `run.py --mode qa --target-count 20`
  (run_id `QA-20260810-233602-KST`). `extract_and_cluster_problems` 판정 단계에서
  전체 군집 5,190개(대부분 단일 멤버로 기계적으로 5명 미만) 중 `independent_user_count
  >= 5`인 19개 전부를 직접 읽고 정직하게 REJECT했다 — **19개 전부 다른 저장소·다른
  주제에 붙은 공용 보일러플레이트/템플릿 문구**였다:
  - GitHub 기본 이슈 템플릿 문구 그 자체: `"Is your feature request related to a
    problem?"`(6명), `"Current Workaround"`(6명) — 템플릿을 그대로 쓰는 모든 저장소가
    똑같이 공유하는 문구라, 서로 완전히 무관한 프로젝트들이 묶임.
  - README/저장소 보일러플레이트: `"Feedback and feature requests are welcome!"`류
    변형이 4개 군집(11/15/18/30명)에 걸쳐 나타남 — 실제로는 각기 다른 프로젝트의
    일반적인 "이슈 환영합니다" 문구.
  - HN에서 이미 확인된 것과 동일한 질문 템플릿: `"How do you manage X"`(X가 매번
    다름, 12명), `"What do you use and why?"`(6명).
  - 일반 불만 표현이 우연히 겹친 경우: `"way too complicated"`(22명),
    `"far too expensive/complicated"`(5명), `"I would pay for this service"`
    (5명, 매번 다른 서비스를 가리킴).
  - 나머지 5,171개 군집은 `independent_user_count < 5`라 기계적으로 탈락(판정으로
    구제 불가 — 판정은 군집을 쪼개거나 멤버를 제외할 수만 있지, 서로 다른 군집을
    합칠 수는 없음. 즉 5명 이상 군집 19개가 전부 탈락한 시점에 이 데이터셋에서는
    수학적으로 더 나올 수 없음).
  - `problems`/`opportunities` 0건 → `generate_and_review_titles`에서 `RetryRequired`
    → 최종 상태 `RETRYING`(정상 종료, 코드 예외 아님). 운영
    `output/history/words.txt` 체크섬 불변 확인(`git diff` 결과 없음).
- **결론(중요)**: A안의 가설 — "데이터원을 다양화하면 문제가 풀린다" — 은 **반증됨**.
  볼륨은 3배 이상(HN 단독 4,133개 → 5,190개 후보) 늘었지만 근본 원인은 그대로다:
  1차 문자열 유사도 군집화는 "비슷한 표현"만 묶고, 다른 표현으로 말한 같은 문제는
  애초에 못 묶는다(DEMAND-001 원래 진단 그대로). GH Archive는 오히려 HN보다 더
  강력한 새 오염원(모든 저장소가 공유하는 GitHub 기본 이슈 템플릿)을 추가했다.
  **결론: 데이터가 부족한 게 아니라 군집화 방법론(1차 문자열 유사도)의 재현율
  한계다.**
- **다음 조치(확정)**: B안(의미 기반/임베딩 군집화,
  `docs/implementation/14-implementation-roadmap.md` "3차 개선" 항목)을 다음
  세션에서 검토·착수. A안과 같은 방식(볼륨/소스만 늘리기)의 추가 반복은 결과가
  똑같을 것이 이미 두 번(HN 단독, HN+GH Archive) 확인됐으므로 더 시도하지 말 것.
  B안은 새 의존성(임베딩 모델/라이브러리)이 필요하므로 CLAUDE.md §8에 따라
  라이선스·유지보수 위험을 먼저 문서화한 뒤 추가할 것. "5명" 기준 완화는 여전히
  검토 대상 아님(CLAUDE.md 12항 위반).
- 관련 실행 기록: `output/runs/QA-20260810-233602-KST/`(judgment 요청/응답 원문
  포함, `.gitignore` 대상이라 로컬에만 있음), 커밋 `e07769c`(GH Archive 구현),
  `09f9f29`(봇 필터 수정).

### B안 실데이터 검증 결과 (2026-08-11) — **B안(TF-IDF)도 DEMAND-001을 해소하지 못함, 오히려 악화**

- 설계서 대비 코드 감사 배치에서 2차 데이터원 4개(Stack Exchange, npm Registry,
  Common Crawl, 공식 RSS)가 전부 활성화되어 데이터가 더 늘어난 상태(`hn_items`
  73,821건, 후보 문장 약 5,900~6,300개)에서 B안을 실제로 구현하고 재검증했다.
- **1차 시도 — TF-IDF 가중 코사인 유사도** (`clustering.compute_idf`,
  `tfidf_vector`, `cosine_similarity`, `cluster_candidates_tfidf`): 기존
  토큰중복+문자열유사도 혼합 방식을, 코퍼스 전체에서 흔한 단어(보일러플레이트)의
  가중치를 낮추는 TF-IDF로 교체하면 "여러 프로젝트가 공유하는 관용구"가 자동으로
  약해질 것이라는 가설로 구현. **실측 결과는 반대**: `independent_user_count>=5`
  군집이 기존 19개(HN+GH Archive+SE 시점, 더 작은 코퍼스)에서 **27개로 증가**했다.
  원인을 직접 디버깅함: `"I'd love to hear your feedback and feature requests!"`
  같은 문장은 불용어 제거 후 토큰이 3~7개뿐이고 **그 문장의 내용 자체가 거의 전부
  보일러플레이트 단어**라, TF-IDF가 그 단어들의 가중치를 낮춰도 비교 대상 두 문장
  모두 "낮아진 가중치의 단어들" 외에는 사실상 아무것도 안 남아 코사인 유사도가
  여전히 높게 나온다 — TF-IDF는 "다양한 내용 중 흔한 단어의 영향을 줄이는" 데는
  효과적이지만, **애초에 내용이 거의 없는 문장끼리는 어떤 가중치를 줘도 서로
  비슷해 보이는 것을 막지 못한다.**
- **2차 시도 — 일반 인사말/보일러플레이트 사전 필터 추가**
  (`text_filter.is_generic_courtesy_sentence`, `GENERIC_COURTESY_TOKENS`): 실제로
  반복 관찰된 "feedback/feature request/welcome/curious/workaround" 류 짧은
  인사말 문장을 후보 추출 단계에서 아예 제외하도록 추가. 이 필터를 적용한 뒤
  TF-IDF로 재군집하면 5명 이상 군집이 27개→21개로 줄었고, 가장 컸던 31명짜리
  "feedback 감사" 군집은 실제로 사라졌다 — **일부 개선은 확인됨.**
- **하지만 같은 필터링된 데이터에 기존(원래) `cluster_candidates`(문자열 유사도)를
  그대로 돌려 직접 비교하니 5명 이상 군집이 15개**로, TF-IDF(21개)보다 오히려
  적었다. 즉 **필터는 진짜 도움이 됐지만, TF-IDF 알고리즘 자체는 기존 방식보다
  나은 게 아니라 더 나빴다.**
- 남은 15개 군집(구 알고리즘 + 신규 필터 적용)의 내용을 직접 읽어봤는데
  **전부 여전히 같은 종류의 보일러플레이트**였다: `"way too complicated"`(22명,
  전혀 무관한 대상에 붙는 일반 불만), `"How do you manage X"`(12명, X가 매번 다름),
  `"Happy to answer questions... feature requests"`(8명, Show HN 마무리 인사말) 등
  — 필터 사전에 없는 새로운 보일러플레이트 종류일 뿐, 근본 패턴은 동일.
- **최종 결정**: `scripts/cluster_problems.py`는 **기존 `cluster_candidates`(문자열
  유사도)를 그대로 프로덕션에 사용**한다 — 실측상 TF-IDF보다 우수하기 때문(코드
  전체를 갈아엎지 않고 실측으로 검증 후 유지). `cluster_candidates_tfidf`는
  코드베이스에 남겨두되(테스트 통과, 문서화됨) 프로덕션에서 호출하지 않는다 —
  "한 번 짜본 코드를 버리기 아까워서"가 아니라 향후 다른 튜닝(예: n-gram, 다른
  IDF 평활화)의 출발점으로 남겨두는 의도적 선택이며, `cluster_problems.py` 주석에
  이 실측 비교 결과를 그대로 남겼다. `text_filter.is_generic_courtesy_sentence`
  필터는 실측으로 개선이 확인되었으므로 그대로 유지한다.
- **결론(세 번째 확인)**: A안(소스 다양화)에 이어 B안(TF-IDF 유사도)도 근본 원인을
  풀지 못했다. 오히려 "짧고 내용이 거의 없는 보일러플레이트 문장은 어떤 유사도
  지표로도 서로 비슷해 보인다"는 더 근본적인 한계를 확인했다 — 이는 유사도
  계산의 정교함 문제가 아니라 **애초에 그 문장이 "진짜 문제 설명"인지 "일반적인
  사교적 문구"인지 구분하는 것 자체가 의미 판정이라는 것**을 시사한다. 이 판정을
  코드가 완벽히 대신할 수 없다는 것은 설계상 이미 예정된 것이었고(`extract_and_
  cluster_problems`의 애매 군집 AI 판정 단계가 정확히 이 역할), 이번 세션 내내
  실제로 그 판정을 세션이 직접 수행해 19개 전부를 정직하게 REJECT한 것 자체가
  설계대로 정상 동작한 것이다. **남은 선택지는 판정 기준 완화(금지) 외에는:
  (a) 계속 더 많은 원시 데이터를 쌓아 우연히 5명 이상이 겹치는 진짜 문제가
  나타나길 기다리거나, (b) 완전히 다른 종류(더 구조화된/덜 정형화된)의 데이터원을
  찾는 것뿐이다.** 두 선택지 모두 이번 세션의 범위를 넘는 후속 작업으로 남긴다.

- **네 번째 확인(2026-08-11, 설계서 대비 구현 감사 배치 #26 최종 회귀 QA,
  `QA-20260811-020116-KST`)**: 감사 배치로 5개 선택 데이터원(GH Archive, Stack
  Exchange, npm Registry, Common Crawl, 공식 RSS/Atom)을 전부 활성화하고
  `text_filter.is_generic_courtesy_sentence` 필터와 데이터원별 신뢰도 보정까지
  붙인 뒤 `python run.py --mode qa --target-count 20`을 처음부터 다시 실제
  실행함(`data/local.db` 총 89,909건: HN 16,057 + GH Archive/Stack Exchange/기타
  4개 소스). 이 실행 도중 **별개의 진짜 버그를 실측으로 발견**: Stack Exchange
  덤프의 삭제/이전된 계정 게시물은 `OwnerUserId`가 원래 없는데(정상적인 덤프
  export 특성), `stack_exchange_client.normalize_row`가 이를 그대로
  `hn_items.by = NULL`로 넣어 `parse_sources.py`의 스키마 검증(`by` 필수)이
  270건에서 FAIL했다 — 합성 테스트 픽스처는 항상 `OwnerUserId`를 채워 넣었기
  때문에 그동안 안 걸렸던 것. `normalize_row`가 저자 없는 게시물을 아예
  스킵하도록 수정(커밋 `c5e254b`) 후 재실행.
  5,599개 군집 중 `independent_user_count>=5`인 16개(직전 확인의 19개보다 적음 —
  데이터셋이 달라졌기 때문, 우려할 변화 아님)를 전부 직접 읽고 REJECT — 여전히
  전부 같은 패턴(GitHub 이슈 템플릿 "## Workaround" 헤더, HN "Ask HN: How do
  you manage X" 질문 템플릿, "way too complicated/expensive" 고립 불만,
  "feedback/feature requests welcome" 인사말)이었다. `text_filter`의 일반
  인사말 필터가 이미 적용된 상태에서도 GitHub 이슈 템플릿류(`## Workaround`,
  `Is your feature request related to a problem?`)는 필터 사전에 없어 여전히
  통과했다 — 이는 필터 사전 확장으로 부분적으로 더 줄일 수 있는 항목이지만,
  근본 원인(짧고 내용이 거의 없는 문장은 유사도로 구분 불가)은 그대로다.
  결과: `problems`/`demand_scores` 0건, `CAPABILITY_STAGNATION`,
  `output/history/words.txt` 체크섬 실행 전후 동일(`e3b0c442...`, 변화 없음),
  `output/intermediate/QA-20260811-020116-KST_shortfall_titles.txt` 0줄로 정상
  기록. **결론(네 번째 확인)**: 소스 5개 전부 활성화 + 필터 추가라는, 이번
  세션이 시도할 수 있는 조합을 전부 적용한 뒤에도 동일한 근본 원인이 그대로
  재확인됨. 위 "결론(세 번째 확인)"의 판단이 그대로 유효하다 — 데이터/필터를
  더 다듬는 "같은 방법을 더 크게" 시도를 반복하지 말 것.

- **다섯 번째 확인(2026-08-11, "다른 종류의 데이터원 찾기" 탐색 결과)**:
  사용자가 "볼륨/필터를 더 다듬지 말고 근본적으로 다른 종류의 데이터원을
  찾으라"고 명시적으로 지시해, 지금까지의 모든 소스(HN/GH Archive/Stack
  Exchange/npm/Common Crawl/RSS)가 공유하는 "개발자·소프트웨어 커뮤니티 텍스트"
  범주를 완전히 벗어난 후보를 실측으로 탐색함. 키 없이(로그인·API 키·CAPTCHA
  우회 없이) 접근 가능한 후보를 하나씩 실제 HTTP 요청으로 검증:
  - **Reddit 공개 JSON**(`*.json` 엔드포인트, 검색 API 포함): 실측 403. 웹 검색으로
    교차 확인 — 2026-05-28 Reddit이 비인증 JSON 접근을 전면 차단(TLS 지문/IP
    평판 기반)했고 OAuth만 남음. OAuth는 앱 등록(사용자가 직접 자격증명을
    발급해 제공해야 함)이 필요해 이 세션이 자체적으로 해결 불가 — 기각.
  - **CFPB Consumer Complaint Database**: 공식 검색 UI API(`consumerfinance.gov/.../api/v1/`)는
    Akamai 봇 차단으로 403(헤더를 바꿔가며 우회 시도하지 않음 — CLAUDE.md 3항
    정신 위반). 과거 Socrata 오픈데이터 엔드포인트(`data.consumerfinance.gov`)는
    실측으로 플랫폼이 이전되어 폐기됨을 확인(404, Salesforce 기반 페이지로
    리다이렉트) — 기각.
  - **Product Hunt GraphQL**: 실측 401(`invalid_oauth_token`), 전부 OAuth 토큰
    필수 — 기각.
  - **Canny(공개 피드백 보드) API**: 실측 400(`invalid api key`) — 기각.
  - **GitHub Issue 전문 검색 API**(`api.github.com/search/issues`, GH Archive의
    시간창 firehose가 아니라 특정 문구를 전체 이력에서 직접 검색): 접근은
    가능(200 OK, 키 불필요)하지만 실측 검색("still use a spreadsheet" in:body)
    결과 22건이 전부 **서로 무관한 저장소의 서로 다른 기능 요청**이었다 — GH
    Archive와 동일한 구조적 문제(GitHub 이슈는 애초에 특정 저장소에 대한 기술
    요청이지, 여러 사람이 독립적으로 말하는 같은 시장 문제가 아님). 접근성은
    PASS했지만 내용 자체가 가설을 반증해 구현하지 않고 기각.
  - **Apple App Store 고객 리뷰**(iTunes Search API + `customerreviews` RSS,
    둘 다 공식·키 불필요, 실측 200 OK): **유일하게 실제로 구현·활성화한 후보.**
    `app_store_client.py` 신규(검색어로 앱 동적 발견 → 리뷰 수집,
    id는 `7`+12자리 zero-pad로 재매핑), `collection.py::run_app_store_reviews_collection`,
    `config/sources.yaml`의 `app_store_reviews.search_terms`에 인보이싱·CRM·
    일정관리 등 SMB SaaS 카테고리 12개 설정, `collect_sources.py` 연결, 테스트
    22개 신규(전체 pytest 403→419). 실제 접근성 검사 PASS
    (`app_id=584606479 review_count=50`) 후 `enabled: true` 전환, 실제 수집
    3회 반복 실행(총 hn_items 2,377건, 56개 앱). **실측 결과(핵심 발견)**:
    `filter_pain_sentences.py` 통과율이 다른 소스보다 훨씬 낮음(2,377건 중
    15건, 0.6% — HN/GH Archive는 보통 몇 % 수준). 남은 15건도 대부분
    "too expensive"(가격 불만) 또는 "workaround"/"feature request"(그 앱
    한정 기능 요청)였고, 서로 다른 앱에 대한 서로 무관한 불만이라 어떤
    군집에도 들어가지 못함 — **실제 파이프라인 재실행(`QA-20260811-031153-KST`)
    결과 `independent_user_count>=5`인 34개 군집 중 `app_store_reviews`가
    기여한 군집은 정확히 0개**(SQL로 직접 확인, 모든 34개 군집이 여전히
    `hacker_news`/`gh_archive`/`stack_exchange`뿐). 원인 추정: 앱 리뷰는
    "이 앱이 없다"가 아니라 "이미 쓰고 있는 이 앱이 별로다"(버그·가격 불만)에
    본질적으로 치우쳐 있어, 수요 파이프라인이 찾는 "미해결 시장 문제" 신호와
    구조적으로 다르다 — 오히려 기존 공급 후보의 `supply_gap_unresolved_complaints`
    판정 보조 증거로는 잠재적 가치가 있을 수 있다(이번 배치에서는 연결하지
    않음, 후속 과제로 남김). 34개 군집 전부 직접 읽고 정직하게 REJECT,
    `CAPABILITY_STAGNATION`, 체크섬 불변 확인.
  - **결론(다섯 번째 확인)**: 이번 세션이 실제로 접근 가능한 "다른 종류의
    데이터원" 후보(로그인·API 키·봇 차단 우회 없이) 6개를 전부 실측했다.
    5개는 접근 자체가 막혀 있었고(자격증명 필요 4개, 봇 차단 1개), 1개는
    접근은 가능했지만 실제 데이터 내용이 이 프로젝트가 찾는 "여러 사람이
    독립적으로 말하는 같은 시장 문제" 신호와 근본적으로 다른 종류의 콘텐츠였다.
    `app_store_reviews`는 실패로 되돌리지 않고 유지한다(B안 TF-IDF와 달리
    다른 소스에 해가 되지 않고, 데이터 다양성 자체는 정당한 목표이며, 후속
    supply-side 활용 가능성이 남아있음). **다음에 이 이슈를 다시 만나면**:
    (a) 사용자가 직접 자격증명(Reddit OAuth 앱, GitHub PAT, Canny API 키 등)을
    발급해 제공하면 그 경로들을 재시도할 수 있고, (b) 그렇지 않다면 남은
    선택지는 여전히 시간 경과에 따른 데이터 축적 또는 근본적으로 다른 판정
    방식(현재 세션/서브에이전트의 애매 군집 판정 확대)뿐이다.

- **여섯 번째 확인(2026-08-11, 알고리즘 정밀 튜닝 — "소량으로 다방면으로" 라운드)**:
  사용자가 이번엔 데이터원이 아니라 **군집화 알고리즘 자체**를 다시 연구하되,
  매번 대량 실측(전체 파이프라인 재실행+수백 개 군집 읽기)으로 토큰을 쓰지
  말고 **작은 합성 문장 몇 개로 가설을 싸고 빠르게 검증**하라고 지시함.
  방법: 실제 문제 군집(이미 여러 번 읽어서 알고 있는 실패 사례)의 정확한
  문장 몇 개만 파이썬으로 직접 `clustering.combined_similarity`에 넣어
  점수를 확인 → 원인 진단 → 최소 수정 → 같은 합성 문장으로 재확인 → (선택)
  이미 로컬에 있는 데이터로 저비용 재클러스터링 1회로 교차 검증. 새 네트워크
  수집은 전혀 하지 않음.
  - **버그 1(진짜 결함)**: `clustering.STOPWORDS`(약 40개 단어)에 "you"는
    있는데 **"your"가 빠져 있었다**. "Ask HN: How do you manage your
    prompts in ChatGPT?"와 "...your dotfiles?"가 실제로 12명 군집(C0031)으로
    잘못 묶인 원인을 직접 계산해 확인: 트리거 문구 제거 후 남는 "your"
    하나가 공유 토큰으로 잡히고, 게다가 "Ask HN:"/"?" 같은 공통 구조가
    문자열 유사도(SequenceMatcher)까지 끌어올려 0.40 문턱을 넘었다.
  - **버그 2**: "way too complicated/expensive"(PAIN_PATTERNS는 "too
    complicated"/"too expensive"만 포함)에서 트리거 문구를 떼어내면 "way"
    하나만 남는데, 이것도 불용어가 아니었다 — Discord·WASM·병원비·Twitter
    API처럼 전혀 무관한 22명짜리 군집(C0520)의 원인.
  - **수정**: `clustering.STOPWORDS`를 기존 임시방편 40개 목록에서 표준
    영어 기능어(의문사 how/what/where/there, 대명사 your/their 등, 조동사,
    전치사 등 약 150개) 목록으로 확장(`clustering.py`). 합성 문장으로
    회귀 확인 후 실제 로컬 재클러스터링 1회: 고득점(5명 이상) 군집이
    34개 → 25개로 감소, 최대 군집 크기가 22명 → 10명으로 완화. 기존
    `test_clustering.py` 18개 테스트 전부 그대로 통과(회귀 없음), 신규
    회귀 테스트 2개 추가.
  - **버그 3(별도 근본 원인, 다른 계층)**: GitHub 기본 이슈 템플릿의 섹션
    헤더("## Current Workaround", "Is your feature request related to a
    problem?", "- [x] I have searched for existing feature requests")가
    수천 개 무관한 저장소에 그대로 복사돼 붙어 있어, 스톱워드 확장으로는
    안 잡힘(헤더 단어 자체가 내용어라서). `text_filter.is_generic_courtesy_
    sentence`의 `GENERIC_COURTESY_TOKENS` 사전에 이 템플릿 어휘(current/
    workaround 주변 단어, checkbox 필드 어휘, "I would pay for this
    service" 같은 HN 마무리 인사 밈의 어휘)를 3라운드에 걸쳐 소량씩 추가
    (라운드마다 합성 문장으로 확인 → 실제 재클러스터링으로 교차 검증).
    "workaround"/"pay" 자체는 진짜 유용한 신호일 수 있으므로(구체적 내용이
    있으면), 짧고(≤8 토큰) 일반 어휘 비율이 높은(≥70%) 경우만 걸러지는
    기존 길이+비율 게이트에 얹었다 — 실제로 "Local workaround: we manually
    reconcile spreadsheets every Friday..." 같은 구체적 문장은 계속 통과함을
    테스트로 고정. 3라운드 누적 결과: 25개 → 20개.
  - **결론(누적, 세 시도 합산 34→20, 41% 감소)**: 이 방식(작은 합성 문장
    가설 검증 + 저비용 실측 교차확인)은 토큰을 거의 안 쓰고도 **진짜 결함
    2개**(빠진 불용어)와 **실질적 개선 1개**(템플릿 어휘 확장)를 찾아 실제로
    고득점 군집 수를 41% 줄였다 — 이전 라운드들(볼륨/소스/TF-IDF)과 달리
    이번엔 순수 손실이 아니라 실측 검증된 순이익이었다. 하지만 **남은 20개
    군집을 전부 다시 읽어봐도 여전히 100% 보일러플레이트**(새로운 "Happy to
    answer questions..." 마무리 인사 변형, "Local workaround verified/
    tested/result" 변형 등)였다 — 보일러플레이트의 종류가 사실상 무한해서,
    이 방식을 계속 반복해도 수렴은 하되(각 라운드 20~25% 감소) 0에 도달하지는
    않을 가능성이 높다. **다음에 이 방식을 다시 쓸 때**: 여전히 유효한
    전략이니 반복해도 좋지만(토큰 비용이 낮음), "몇 라운드째 남은 상위
    군집을 전부 정직하게 읽어도 여전히 100% 보일러플레이트"인 상태가
    계속되면 그 자체가 유의미한 신호 — 계속 어휘를 추가하는 것보다 어느
    시점에는 (a) 시간 경과에 따른 데이터 축적을 기다리거나 (b) 근본적으로
    다른 판정 계층(예: 후보 추출 단계에서 "이 문장이 마크다운 헤더/체크박스/
    템플릿 필드처럼 보이는가"를 구조적으로 판별하는 것 — 어휘가 아니라 형식
    기반)으로 전환할 시점일 수 있다.

- **일곱 번째 확인(2026-08-11, "대량의 업계 전문용어 확보" — 재현율 개선
  라운드)**: 지금까지 여섯 번의 시도는 전부 **정밀도**(오탐 제거) 쪽이었다.
  사용자가 이번엔 **재현율**(놓치고 있던 진짜 후보 더 찾기) 쪽 아이디어를
  제안함: 여러 업계의 전문용어를 조사해서 후보 문장 확장에 쓰자는 것.
  방법: 의료행정·법무·물류·재무회계·부동산관리·보험·인사급여·건설·소매운영·
  현장서비스·비영리 등 업계별 프로세스 전문용어를 AI 지식으로 큐레이션(웹
  조사 없이) → 실제 HN Algolia 검색(따옴표 정확 문구)으로 12개를 먼저
  실측: "prior authorization"/"chargeback dispute"/"lien waiver"/"bank
  reconciliation"/"tenant screening" 등은 실제로 관련성 높은 결과가
  나왔지만, "change order"/"rent roll"/"punch list"/"CAM reconciliation"
  같은 흔한 단어 조합은 따옴표를 써도 무관한 결과만 나오거나(Algolia
  퍼지 매칭) 0건이라 최종 목록에서 제외함.
  구현: `text_filter.INDUSTRY_TERMS`(47개, `PAIN_PATTERNS`와 별도 목록) —
  `matched_patterns()`가 이 목록도 함께 확인해 후보 채택 범위를 넓히되,
  `clustering.strip_trigger_phrases`는 여전히 `PAIN_PATTERNS`만 제거해
  업계 용어 자체는 군집화 유사도 계산에 그대로 남긴다(내용 신호로 활용).
  `collect_sources.py`에 정확 문구 HN 검색을 별도의 작은 예산으로 추가.
  실측 결과: 실제 수집 1회로 신규 421건(스토리 64+댓글 353) 확보, 후보
  문장 547건이 업계 용어로 채택됨(전체 8,495건 중). 표본 확인 결과 내용
  자체는 확실히 더 구체적/업계 특화적이었다(demurrage 경제학·통관·구독
  onboarding checklist 등). **하지만 실제 재클러스터링 결과 `independent_
  user_count>=5`인 20개 군집 중 업계 용어로 채택된 후보가 포함된 군집은
  0개**(SQL로 직접 확인) — 재현율은 늘었지만 아직 5명 이상이 우연히 거의
  같은 표현을 쓰는 경우까지는 안 이어짐(1차 문자열 유사도 군집화의 재현율
  한계는 여전히 유효 — "같은 의미를 다른 표현으로 말하면 애초에 못 묶임").
  **결론**: 순수 손실은 아니다(경계값을 넘는 노이즈 없이 후보 풀만
  확장됨, 코드/테스트/문서 전부 정상, pytest 430 passed) — 다만 이번
  한 번의 수집으로 바로 군집을 만들어내지는 못했다. 매 실행마다 업계
  용어 검색이 누적되므로(증분 수집), 시간이 지나며 우연히 5명이 겹치는
  경우가 나타날 가능성은 A안(소스 다양화)보다 구조적으로 조금 더
  높다(주제가 좁혀진 검색이라 노이즈 대비 신호 비율이 더 낫다) — 하지만
  이것도 검증된 사실이 아니라 가설이며, 다음 세션이 몇 차례 더 누적 수집
  후 재확인해볼 가치는 있다.
  - **가설 재확인(같은 날, `collect_sources.py` 4회 추가 실행)**: 위
    가설을 바로 실측함. 4회 반복 수집 후(`hn_items` 총 273,912건, `gh_
    archive`/`stack_exchange`/`app_store_reviews`는 계속 늘었지만
    `stack_exchange_dump`는 3회차부터 신규 0건 — 덤프 소진) 재클러스터링
    결과 고득점(5명 이상) 군집이 20→24개로 늘었지만(전체 후보 증가에
    비례) **업계 용어 후보가 포함된 군집은 여전히 0개**였다. 업계 용어
    HN 검색 자체도 1회차 이후 신규 0건으로 정체됨(정확 문구 검색이라
    HN에 실제 존재하는 매칭 게시물 수가 유한 — 47개 용어에 대해 이미
    거의 다 찾아낸 상태로 보임; 업계 용어 후보 총수는 547→570으로 소폭만
    증가, 전부 GH Archive/Stack Exchange/App Store 쪽에서 옴). **결론**:
    "시간 경과·누적 수집으로 우연히 5명이 겹칠 것"이라는 가설은 최소
    4회 반복으로는 확인되지 않았다 — HN 쪽 업계 용어 검색은 사실상
    포화 상태이므로, 더 늘리려면 (a) 업계 용어 목록 자체를 확장하거나
    (b) GH Archive/Stack Exchange처럼 자체 성장하는 소스에서 이 용어들이
    자연히 더 쌓이길 기다리는 수밖에 없다. "같은 방법을 계속 반복"하는
    것의 한계가 여기서도 확인됨 — 다음에 이 방향을 또 시도할 땐 업계
    용어 목록 확장이나 다른 소스 연결처럼 실제로 다른 조치를 취할 것.
