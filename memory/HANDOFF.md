# HANDOFF

- 상태: `PAUSED`
- 요약 한 줄: **A안(GH Archive 2차 데이터원) 실데이터로 끝까지 검증 완료 — DEMAND-001은
  해소되지 않음.** 근본 원인이 데이터 부족이 아니라 1차 문자열 유사도 군집화의
  재현율 한계임이 실제 파이프라인 실행으로 재확인됨. **다음 조치는 B안(의미 기반/
  임베딩 군집화)으로 확정** — 재논의 없이 바로 착수할 것. 상세 근거는
  `memory/ACTIVE_ISSUES.md`의 `DEMAND-001` "A안 실데이터 검증 결과" 참고.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md`
   → `memory/ACTIVE_ISSUES.md`(`DEMAND-001` 전체, 특히 "A안 실데이터 검증 결과") 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 260 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 로컬 커밋 확인. **push는 PC에서 사용자가 요청할 때만**
   (아래 §3 — SSH/원격 세션에서는 자동 push가 원래 실패하며 이는 정상임, 차단 아님).
4. §4(B안)부터 바로 시작.

## 2. 완료된 것 (이번 세션, 전부 로컬 커밋됨: `e07769c`, `9ff5827`, `2ac267f`, `09f9f29`)

- GH Archive 접근성 검사 실제 PASS, `sources.yaml`의 `gh_archive.enabled: true` 전환.
- `gh_archive_client.py` 신규(`IssuesEvent`(opened)/`IssueCommentEvent`(created)만
  정규화, 봇 필터링), `collection.py::run_gh_archive_collection`(시간 커서 기반 점진
  수집), `hn_items.source` 컬럼으로 기존 파이프라인 코드 재사용, `collect_sources.py`
  연결. 구현 중 버그 3개 발견·수정(전부 회귀 테스트로 고정):
  1. KST→UTC 변환 누락, 2) 시간키 문자열 비교 오류, 3) 봇 액터를 이벤트 `actor`
     로그인 접미사(`[bot]`)만으로 판정해 GitHub 자체 Copilot 리뷰봇 등을 놓침 →
     이슈/댓글에 내장된 실제 작성자(`user.type`)까지 확인하도록 수정.
- 테스트 27개 신규. pytest 240 → **260개 전부 통과**. `verify_design_coverage.py` PASS.
- **실제 데이터로 A안을 끝까지 검증함** (아래 §4 "이번 세션에서 실제로 한 것" 참고).
  결과는 부정적(RETRYING) — 코드는 정상 동작했고, 이것 자체가 유효한 QA 결과.

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

## 4. 다음 원자 작업 — B안(확정): 의미 기반/임베딩 군집화

### 이번 세션에서 실제로 한 것 (요약 — 전체 근거는 `ACTIVE_ISSUES.md` DEMAND-001)

1. `scripts/collect_sources.py`를 4회 반복 실행해 GH Archive 36시간치 실수집
   (총 `hn_items` 44,842건: HN 16,134 + GH Archive 28,708).
2. `filter_pain_sentences.py` → 후보 문장 ~5,200개(HN 단독 4,133개보다 훨씬 많음).
3. `run.py --mode qa --target-count 20` 실행(run_id `QA-20260810-233602-KST`).
   `extract_and_cluster_problems` 판정에서 `independent_user_count>=5`인 군집
   19개**전부**를 직접 읽고 REJECT — 전부 GitHub 기본 이슈 템플릿·README
   보일러플레이트·HN 질문 템플릿이었음(구체 근거는 ACTIVE_ISSUES.md 참고).
   나머지 5,171개 군집은 애초에 5명 미만이라 기계적으로 탈락.
4. **결과**: `problems`/`opportunities` 0건, `RETRYING`. 운영 데이터 불변 확인.
5. **결론**: 데이터 볼륨/소스 다양성 문제가 아니라 1차 문자열 유사도 군집화 자체의
   재현율 한계. A안(소스 다양화)으로는 원리적으로 풀리지 않는다.

### 다음 세션이 할 일

1. `docs/implementation/14-implementation-roadmap.md`의 "3차 개선 > 문제 군집 정확도
   향상" 항목과 `docs/pipeline/07-demand-pipeline.md` 원본 설계의 군집화 관련 절을
   먼저 읽고, 의미 기반 군집화(예: 문장 임베딩 + 코사인 유사도, 또는 현재 세션이
   직접 의미 판정하는 범위를 확대하는 방식)의 구체적 설계를 잡는다.
2. **CLAUDE.md 절대 규칙 1번**: 별도 `anthropic` API 호출을 추가하면 안 된다 —
   임베딩이 필요하다면 로컬에서 돌릴 수 있는 표준 라이브러리 또는 소규모 오픈
   임베딩 모델(라이선스·유지보수 위험을 문서화한 뒤 §8 절차대로 추가)이어야 하고,
   "의미 판정"의 최종 결정은 여전히 현재 세션/서브에이전트가 해야 한다 — 임베딩은
   1차 후보 축소(코드 영역)에만 쓸 것.
3. 새 의존성 추가 전 CLAUDE.md §8에 따라 문서화(라이선스·유지보수 위험) 먼저.
4. 구현 후 반드시 동일 파이프라인 QA로 재검증(이번 세션처럼 판정을 얼버무리지
   말고, 실제 상위 군집 내용을 직접 읽고 정직하게 판정할 것).
5. **"5명" 기준을 낮추는 것은 여전히 검토 대상이 아니다**(CLAUDE.md 12항 위반).

## 5. 회귀 사례로 고정된 함정 (재발 방지)

- 시간/날짜 문자열을 키로 쓰는 증분 수집기에서 선행 0 없는 키는 절대 문자열로
  비교하지 말 것 — 반드시 실제 날짜/시간 타입으로 변환해서 비교.
- 외부 API가 UTC 기준 리소스명을 쓰는데 파이프라인 내부 `now`는 KST로 흐른다 —
  새 데이터원을 붙일 때마다 시간대 변환 필요 여부를 반드시 확인할 것.
- **봇/자동화 계정 필터링은 이벤트 액터(`actor`) 로그인의 명명 규칙(`[bot]` 접미사
  등)만 믿지 말 것** — GitHub 자체 Copilot 리뷰봇처럼 액터 로그인엔 표시가 없고
  내용 작성자(`user.type`)에만 "Bot"이 찍히는 경우가 있다. 그래도 100% 걸러지진
  않는다(`wingetbot`, `codecov-commenter` 등은 `user.type`도 "User") — 이런 잔여
  케이스는 필터로 완전히 잡으려 하지 말고 애매 군집 판정 단계에서 처리할 것.
- **데이터 볼륨/소스를 늘리는 것으로는 1차 문자열 유사도 군집화의 재현율 한계를
  해결할 수 없다** — HN 단독, HN+GH Archive 두 번 다 같은 결과(보일러플레이트만
  더 많이 묶임)로 확인됨. 다음에 이 문제를 다시 만나면 볼륨을 늘리는 실험을
  반복하지 말고 군집화 방법론 자체를 바꿀 것.

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 수요 데이터 부족을 감추기 위해 판정을 완화하거나 가짜 문제를 만들지 말 것
  (데이터 무결성 절대 규칙, 최우선순위) — 이번 세션은 19개 군집을 전부 정직하게
  REJECT하고 RETRYING을 그대로 기록했다. 이 원칙을 계속 지킬 것.
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상 — 실수로 강제 추가
  (`git add -f`)하지 말 것.
- push 자체는 SSH 세션에서 실패하는 게 정상이지만, force-push·히스토리 재작성·
  브랜치 삭제 등 파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
