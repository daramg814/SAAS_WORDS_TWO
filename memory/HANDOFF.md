# HANDOFF

- 상태: `PAUSED`
- 요약 한 줄: **"설계서 대비 전체 구현 감사"에서 발견된 항목을 전부 수정하는
  배치를 진행 중(사용자 지시: "모든 것을 전부 고쳐줘").** #8~#24(17개) 완료,
  **#25(데이터원별 신뢰도 보정) 방금 완료**, 남은 것은 **#26(전체 회귀 QA +
  최종 인수 기준 재검증)뿐**. `DEMAND-001`(수요 관문 통과 군집 0건)은 여전히
  미해결 — A안(GH Archive 등 소스 다양화)과 B안(TF-IDF 군집화) 둘 다 실측으로
  검증했고 둘 다 근본 원인을 못 풀었다(상세: `ACTIVE_ISSUES.md` `DEMAND-001`).
  이건 이번 감사 배치의 범위 밖 별개 이슈이며, 감사 배치 자체는 #26만 남았다.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md`
   → `memory/ACTIVE_ISSUES.md`(`DEMAND-001` 전체) 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 401 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만**
   (아래 §3 — SSH/원격 세션에서는 자동 push가 원래 실패하며 이는 정상임, 차단 아님).
4. §2의 "남은 작업"(#26)부터 바로 시작 — 사용자 확인 불필요(진행 중인 표준 지시).

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

**남은 작업: #26 (전체 회귀 QA 및 최종 인수 기준 재검증)** — 다음 세션이 바로
시작할 것:
1. `pytest -q` 전체 재확인(401 이상), `tools/verify_design_coverage.py` PASS 재확인.
2. `python run.py --mode qa --target-count 20` 실행해 이번 배치의 모든 변경이
   동일 파이프라인에서 실제로 동작하는지 end-to-end 확인(judgment 체크포인트마다
   현재 세션이 직접 판정 — 결과가 RETRYING이어도 정직하게 기록할 것, `DEMAND-001`은
   여전히 미해결이므로 RETRYING이 나오는 게 오히려 정상).
3. 운영 `output/history/words.txt` 체크섬 QA 전후 불변 확인.
4. CLAUDE.md §11 완료 정의 8개 항목을 하나씩 재확인.
5. `final-qa-runner` 서브에이전트로 독립 검증 1회 디스패치.
6. 이 배치 전체를 요약하는 최종 커밋 + `memory/ACTIVE_ISSUES.md`/`PROJECT_PLAYBOOK.md`
   정리 + 이 HANDOFF.md를 "감사 배치 완료, DEMAND-001만 별도 미해결 이슈로 남음"
   상태로 최종 갱신.

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

수요 관문(`독립 사용자 5명 이상`)을 통과하는 군집이 아직 0건이다. 세 가지 실측
실험 전부 근본 원인을 못 풀었다:
1. **볼륨 증가**(HN `search_hits_per_pattern` 40→1000): 실패.
2. **A안(소스 다양화, GH Archive 추가)**: 후보 5,200개로 증가했지만 실패
   (오히려 새로운 보일러플레이트 오염원 추가).
3. **B안(TF-IDF 가중 코사인 유사도)**: 기존 문자열 유사도보다 오히려 나쁨.

**결론(`PROJECT_PLAYBOOK.md` "확인된 한계" 누적 기록)**: 짧은 보일러플레이트
문장은 내용어가 거의 없어 어떤 1차 유사도 지표로도 서로 구분이 안 된다 — 이건
`extract_and_cluster_problems`의 애매 군집 AI 판정이 원래 하도록 설계된 일이며,
19개 군집을 전부 정직하게 REJECT한 것 자체가 설계대로 정상 동작한 결과다. 남은
방법은 (a) 판정 기준 완화(금지, CLAUDE.md 12항) 외에 (b) 더 오래 데이터를
쌓거나 (c) 근본적으로 다른 종류의 데이터원을 찾는 것뿐. **다음에 이 이슈를
다시 만나면 "같은 방법을 더 크게" 실험(볼륨 증가·소스 다양화·유사도 알고리즘
교체)을 반복하지 말 것** — 세 번 다 같은 실패 패턴으로 이미 확인됨.

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
