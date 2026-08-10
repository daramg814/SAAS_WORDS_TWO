# HANDOFF

- 상태: `PAUSED`
- 요약 한 줄: **"설계서 대비 전체 구현 감사" 배치(#8~#26) 완료에 이어, 사용자가
  추가로 지시한 "DEMAND-001을 다른 종류의 데이터원으로 풀어보라"는 탐색까지
  마쳤다.** App Store 리뷰(Apple 공식 API)를 새 수요 데이터원으로 실제
  구현·활성화했지만, 실측 결과 `DEMAND-001`(수요 관문 통과 군집 0건)은 여전히
  미해결이다 — 상세는 `ACTIVE_ISSUES.md` `DEMAND-001` "다섯 번째 확인". 이
  세션은 사용자가 "자리를 비운다"며 확인 없이 계속 진행하라고 명시적으로
  승인한 상태에서 자율적으로 여기까지 진행했다.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

감사 배치와 이번 데이터원 탐색 라운드 둘 다 끝났다. 새로 열면 사용자에게
다음 작업을 물어볼 것 — 단, `DEMAND-001`을 다시 다룰 경우 아래 §4를 먼저 읽고
이미 다섯 번 확인된 실패 패턴("같은 방법을 더 크게" 반복, 또는 자격증명이
필요한 API를 시도)을 반복하지 말 것.

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md`
   → `memory/ACTIVE_ISSUES.md`(`DEMAND-001` 전체) 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 419 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만**
   (아래 §3 — SSH/원격 세션에서는 자동 push가 원래 실패하며 이는 정상임, 차단 아님).

## 2. 이번 감사 배치("모든 것을 전부 고쳐줘")의 전체 진행 상황

`e27bce5` 이후 설계서 대비 전체 코드 구현 감사(서브에이전트 6개 병렬)를 실행해
발견한 격차를 사용자가 권장 순서 그대로 전부 수정하라고 지시했다. 완료 순서와
핵심 내용(전부 로컬 커밋됨, `4175252`부터 이 문서 갱신 시점 커밋까지 연속):

1. **#8** C등급 기회가 SCARCITY_PRIORITY로 새는 안전장치 누락 수정
2. **#9** 목표 수량 미달 시 `output/intermediate/`에 부분 결과 저장
3. **#10** 접근성 테스트에 디스크 사용량 확인 단계 추가
4. **#11** `input/brief.md`을 실제로 읽어 판정에 반영
5. **#12** 사람 보정 공급 희소성 점수를 실제 순위/등급에 반영
6. **#13** SSH push 정책을 `ACTIVE_ISSUES.md`에 공식 충돌(`PROCESS-001`)로 등재
7. **#14** 설계 4.8 제목 충돌 Google 보정 필드/로직 구현
8. **#15** 설계 4.11 Google 검증 처리 상태 enum 전체 구현
9. **#16** 설계 4.9 누적 자기개선 지표 + `minimum_repetitions_for_rule_promotion` 연결
10. **#17** `CAPABILITY_STAGNATION`/`RECOVERY_REQUIRED` 상태 전이 트리거 구현
11. **#18** 공급 후보 수집을 GH Archive까지 확장
12. **#19** 제품 중복 제거에 의미 기반 병합(`merge_group`) 판정 단계 추가
13. **#20~#23** Stack Exchange dump·npm Registry·Common Crawl·공식 RSS/Atom —
    2차 구현 선택 데이터원 5개를 전부 접근성 검사 PASS 후 활성화 완료
    (`config/sources.yaml` 전 소스 `enabled: true`). 상세 근거는
    `docs/policies/04-data-source-policy.md` 5~9번.
14. **#24** B안(TF-IDF 가중 코사인 유사도 군집화) 구현 + 실데이터 검증 →
    **기존 방식보다 나쁨으로 확인, 프로덕션은 원래 알고리즘 유지**(정직한
    부정적 결과 — 상세: `ACTIVE_ISSUES.md` `DEMAND-001` "B안 실데이터 검증 결과").
15. **#25 (방금 완료)** 데이터원별 신뢰도 보정(`source_reliability.py` +
    `scripts/calibrate_source_reliability.py`) — 매 실행 종료 시 그때까지의
    `problem_evidence`/`demand_scores`·`supply_candidates`/`supply_verification`
    누적 결과만으로 소스별 통과율을 집계해 `source_reliability` 테이블에 upsert.
    표본 5건 미만은 `NO_DATA` 유지(사람 보정과 동일 패턴). 점수 공식은 건드리지
    않고 `collect_and_verify_supply`/`review_opportunities` 판정 항목에 참고
    정보로만 흘려보냄(CLAUDE.md 12항 준수). 상세: `docs/pipeline/09-opportunity-scoring.md`
    6번, `PROJECT_PLAYBOOK.md`. 실측: 현재 `local.db`는 통과 사례가 0건이라
    (`DEMAND-001`) 모든 소스가 정직하게 `NO_DATA` — 이는 버그가 아니라 예상된
    현재 상태.

16. **#26 (완료)** 전체 회귀 QA 및 최종 인수 기준 재검증:
    1. `pytest -q` → **403 passed**(#26 도중 SE 버그 수정으로 2개 증가).
       `tools/verify_design_coverage.py` → **PASS, 92 headings, 0 missing**.
    2. `python run.py --mode qa --target-count 20`을 실제로 처음부터 재실행
       (`QA-20260811-020116-KST`). 도중 `collect_sources` 단계에서 실제
       스키마 검증 FAIL 발견 → 진짜 버그였음(아래 별도 항목). 수정 후
       재실행해 `extract_and_cluster_problems` 판정까지 도달, 5,599개 군집 중
       `independent_user_count>=5`인 16개를 전부 직접 읽고 정직하게 REJECT.
       결과: `CAPABILITY_STAGNATION`(0 problems) — `DEMAND-001` 4번째 확인
       (상세: `ACTIVE_ISSUES.md`). `output/history/words.txt` 체크섬
       (`e3b0c442...`, 빈 파일) 실행 전후 동일 확인.
    3. **커밋 `c5e254b`(#26 도중 실측으로 발견한 진짜 버그 수정)**:
       `stack_exchange_client.normalize_row`가 `OwnerUserId`가 없는 게시물
       (실제 SE 덤프에서 삭제/이전 계정 게시물은 흔히 이 필드가 없음 — 정상
       데이터 특성, 파싱 오류 아님)을 `hn_items.by = NULL`로 그대로 넣어
       `parse_sources.py` 스키마 검증이 270건에서 FAIL했다. 합성 테스트
       픽스처는 항상 `OwnerUserId`를 채웠기 때문에 그동안 발견되지 않았음.
       저자 없는 게시물은 애초에 "독립 사용자" 집계에 기여할 수 없으므로
       정규화 단계에서 스킵하도록 수정(가짜 저자를 채우지 않음). 이미
       수집된 로컬 DB의 오염 데이터 270건 + 참조하던 `candidate_sentences`
       3건도 정리함(로컬 전용, git 대상 아님).
    4. `final-qa-runner` 서브에이전트로 독립 검증 디스패치 — **PASS**
       (테스트/설계 커버리지/점수 공식 불변/CLAUDE.md 1항 준수/체크섬 불변
       전부 직접 재확인함). 단, **메모리 문서 마감 누락**을 지적함
       (`HANDOFF.md`가 `c5e254b` 이전 상태로 정체, `ACTIVE_ISSUES.md`의
       "네 번째 확인" 서술이 아직 커밋 안 됨) — 이 문서를 포함한 최종 커밋으로
       바로잡음(현재 커밋이 그 커밋).
    5. 결론: 이번 감사 배치(#8~#26) 자체는 **완료**. CLAUDE.md §11의 8개 완료
       정의 중 "500개 정확히 게시"류는 프로젝트 전체(제목 500개 생산)의 기준이지
       이 감사 배치의 기준이 아니다 — 이 배치의 기준은 "발견된 모든 설계-코드
       격차가 실제로 고쳐지고 테스트·문서·실행으로 검증됨"이며 이는 충족됐다.
       남은 유일한 이슈는 `DEMAND-001`(별도, 사전에 추적되던, 이 배치 범위 밖).

## 2b. 데이터원 탐색 라운드(감사 배치 이후, 2026-08-11) — "다른 종류의 데이터원 찾기"

사용자 지시: 볼륨/필터를 더 다듬지 말고, 지금까지의 모든 소스(HN/GH Archive/
Stack Exchange/npm/Common Crawl/RSS)가 공유하는 "개발자·소프트웨어 커뮤니티
텍스트" 범주를 완전히 벗어난 새 데이터원을 찾아 반복 시도하고, 찾으면 계획·
문서를 역수정하라.

키 없이(로그인·API 키·CAPTCHA 우회 없이) 접근 가능한 후보 6개를 실측(curl/
urllib로 직접 요청 먼저, 클라이언트 코드는 나중):
- Reddit 공개 JSON, CFPB Consumer Complaint Database, Product Hunt GraphQL,
  Canny 피드백 보드 API — **전부 자격증명 필요 또는 봇 차단으로 기각**(상세
  근거는 `ACTIVE_ISSUES.md` `DEMAND-001` "다섯 번째 확인" 및
  `docs/policies/04-data-source-policy.md` 10번).
- GitHub Issue 전문 검색 API — 접근은 PASS했지만 실제 검색 결과 표본이
  GH Archive와 같은 구조적 문제(서로 무관한 저장소의 기능 요청)를 보여 구현
  자체를 안 함.
- **Apple App Store 고객 리뷰 — 유일하게 구현·활성화함.** 신규
  `src/saas_words_two/app_store_client.py`, `collection.py::run_app_store_reviews_collection`,
  `config/sources.yaml`의 `app_store_reviews`(검색어 12개, 카테고리별 앱 동적
  발견), `collect_sources.py` 연결. 테스트 22개 신규(pytest 403→419). 실제
  접근성 PASS 후 활성화, 실제 수집 3회(2,377건, 56개 앱).

**실측 결과**: 실제 파이프라인 재실행(`QA-20260811-031153-KST`)에서
`independent_user_count>=5` 군집 34개 전부를 직접 읽고 REJECT — 이 중
`app_store_reviews`가 기여한 군집은 **정확히 0개**(SQL로 직접 확인). 앱
리뷰는 "미해결 시장 문제"보다 "기존 앱의 버그/가격 불만"에 본질적으로
치우쳐 있어 구조적으로 다른 종류의 콘텐츠였다. `CAPABILITY_STAGNATION`,
체크섬 불변 확인. 커밋 `f554e6f`.

**결정**: `app_store_reviews`는 되돌리지 않고 유지(B안 TF-IDF와 달리 다른
소스에 해가 되지 않고, 향후 공급 후보 `supply_gap_unresolved_complaints`
판정 보조 증거로 쓰일 잠재력이 남아있음). `DEMAND-001`은 여전히 미해결.
**다음에 다시 만나면**: 사용자가 직접 자격증명(Reddit OAuth 앱, GitHub PAT,
Canny API 키 등)을 발급해 제공하면 그 경로들을 재시도할 수 있다 — 그렇지
않다면 이 세션이 자체적으로 시도할 수 있는 "다른 종류의 데이터원" 후보는
사실상 소진되었다.

## 3. Git/원격 설정 — SSH(원격) 세션에서는 push가 원래 안 됨, 정상 동작

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git`.
- **근본 원인**: SSH(Termius 등 폰 원격) 접속은 Windows 세션 0(`services`, 비대화형)에서
  실행되는데, Windows Credential Manager(`wincredman`)는 DPAPI로 보호되어 있어
  대화형 로그인(세션 3, `console`)의 키가 있어야 접근 가능하다. `query session`으로
  실제 확인함. PAT가 사라진 게 아니라 이 세션 종류에서 원래 접근이 안 되는 것.
- **운영 방식(사용자 확정)**: SSH/원격 세션에서는 배치마다 평소대로 커밋만 하고,
  `post-commit` 훅의 push 실패는 정상으로 취급해 다음 배치를 막지 않는다. push는
  사용자가 PC 앞에서 명시적으로 요청할 때만 수행한다. git config은 바꾸지 않는다.
- **로컬 전용 커밋의 안전성**: 매 배치가 독립 커밋(never amend)이라 `git log`/
  `git reflog`가 그 자체로 복귀 지점(reflog 기본 보존 90일/도달 불가능 30일). 단,
  push 전까지는 이 디스크가 유일한 사본 — 백업 문제이지 되돌리기 문제는 아님.
- 로컬이 origin보다 몇 커밋 앞서 있는 게 정상 상태다. PC에서 push 요청을 받으면
  `git push origin main` 실행 후 `git log --oneline origin/main -1`로 확인할 것.

## 4. DEMAND-001 (별도 미해결 이슈 — 이번 감사 배치의 범위 밖)

수요 관문(`독립 사용자 5명 이상`)을 통과하는 군집이 아직 0건이다. 다섯 가지
실측 실험 전부 근본 원인을 못 풀었다:
1. **볼륨 증가**(HN `search_hits_per_pattern` 40→1000): 실패.
2. **A안(소스 다양화, GH Archive 추가)**: 후보 5,200개로 증가했지만 실패
   (오히려 새로운 보일러플레이트 오염원 추가).
3. **B안(TF-IDF 가중 코사인 유사도)**: 기존 문자열 유사도보다 오히려 나쁨.
4. **#26 최종 QA(5개 소스 전부 활성화 + 일반 인사말 필터 + SE 버그 수정 후
   재실행)**: 여전히 동일 패턴(GitHub 이슈 템플릿, HN 질문 템플릿, 고립
   불만/인사말 문구) — `ACTIVE_ISSUES.md` `DEMAND-001` "네 번째 확인" 참고.
5. **"다른 종류의 데이터원 찾기" 라운드(App Store 리뷰 실장)**: 접근 가능한
   6개 후보 중 5개는 자격증명/봇 차단으로 기각, 유일하게 구현한 App Store
   리뷰는 실제 34개 고득점 군집 중 기여 0건 — `ACTIVE_ISSUES.md` `DEMAND-001`
   "다섯 번째 확인" 참고 (§2b에 요약).

**결론(`PROJECT_PLAYBOOK.md` "확인된 한계" 누적 기록)**: 짧은 보일러플레이트
문장은 내용어가 거의 없어 어떤 1차 유사도 지표로도 서로 구분이 안 된다 — 이건
`extract_and_cluster_problems`의 애매 군집 AI 판정이 원래 하도록 설계된 일이며,
매번 고득점 군집을 전부 정직하게 REJECT한 것 자체가 설계대로 정상 동작한
결과다. 남은 방법은 (a) 판정 기준 완화(금지, CLAUDE.md 12항) 외에 (b) 더 오래
데이터를 쌓거나 (c) 사용자가 직접 자격증명을 제공해야 하는 데이터원(Reddit
OAuth, GitHub PAT, Canny API 키 등)을 시도하는 것뿐. **다음에 이 이슈를
다시 만나면 "같은 방법을 더 크게" 실험(볼륨 증가·소스 다양화·유사도 알고리즘
교체·키 없는 새 소스 탐색)을 반복하지 말 것** — 다섯 번 다 같은 실패 패턴으로
이미 확인됨.

## 5. 회귀 사례로 고정된 함정 (재발 방지)

- 시간/날짜 문자열을 키로 쓰는 증분 수집기에서 선행 0 없는 키는 절대 문자열로
  비교하지 말 것 — 반드시 실제 날짜/시간 타입으로 변환해서 비교.
- 외부 API가 UTC 기준 리소스명을 쓰는데 파이프라인 내부 `now`는 KST로 흐른다 —
  새 데이터원을 붙일 때마다 시간대 변환 필요 여부를 반드시 확인할 것.
- **봇/자동화 계정 필터링은 이벤트 액터(`actor`) 로그인의 명명 규칙(`[bot]` 접미사
  등)만 믿지 말 것** — GitHub 자체 Copilot 리뷰봇처럼 액터 로그인엔 표시가 없고
  내용 작성자(`user.type`)에만 "Bot"이 찍히는 경우가 있다. 그래도 100% 걸러지진
  않는다 — 잔여 케이스는 필터로 완전히 잡으려 하지 말고 애매 군집 판정 단계에서
  처리할 것.
- **데이터 볼륨/소스를 늘리는 것, 군집 유사도 알고리즘을 바꾸는 것 둘 다 1차
  유사도 군집화의 재현율 한계를 해결하지 못한다** — §4 참고. 다음에 이 문제를
  다시 만나면 같은 종류의 실험을 반복하지 말 것.
- **설계 로드맵에 계산 방법이 안 적힌 "3차 개선" 항목을 구현할 때는 기존 점수
  공식 입력을 바꾸지 말고 판정 단계의 참고 정보로만 추가할 것**(CLAUDE.md 12항
  — `source_reliability.py`가 실제 적용 사례, `PROJECT_PLAYBOOK.md` 참고).
- **새 테이블/스크립트를 파이프라인 단계에 연결할 때 `_run_or_raise`는 이미
  열려 있는 `conn`과 같은 `data/local.db` 파일에 subprocess로 쓴다** — 이 코드베이스
  전반에서 이미 검증된 패턴(예: `collect_supply_candidates.py` 다음에 바로
  `conn.execute`로 결과를 읽음)이므로 새로 추가할 때 트랜잭션 안전성을 재검토할
  필요 없이 그대로 따르면 된다.

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 수요 데이터 부족을 감추기 위해 판정을 완화하거나 가짜 문제를 만들지 말 것
  (데이터 무결성 절대 규칙, 최우선순위).
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상 — 실수로 강제 추가
  (`git add -f`)하지 말 것.
- push 자체는 SSH 세션에서 실패하는 게 정상이지만, force-push·히스토리 재작성·
  브랜치 삭제 등 파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
