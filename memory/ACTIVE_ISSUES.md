# ACTIVE ISSUES

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
- 상태: OPEN
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
