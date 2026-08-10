# HANDOFF

- 상태: `COMMIT_PENDING` (커밋 `e07769c`는 로컬에 있으나 push 실패, 아래 §3 참고)
- 요약 한 줄: `DEMAND-001` A안(GH Archive 2차 데이터원 활성화) **구현·테스트·문서화 완료, 커밋 완료**.
  아직 안 한 것: 실제로 GH Archive 데이터를 충분히 모아 QA(20개)를 재실행해서
  DEMAND-001이 실제로 해소되는지 확인하는 것. **다음 세션은 여기(§4 "다음 원자 작업")부터
  바로 시작할 것** — 재논의 불필요.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md`
   → `memory/ACTIVE_ISSUES.md`(`DEMAND-001`) 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 258 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
3. `git log --oneline`으로 커밋 이력 확인. 원격 push는 자동(post-commit 훅, 아래 §3).
4. §4부터 바로 시작.

## 2. 완료된 것 (이번 세션, 전부 커밋됨)

- **GH Archive 접근성 검사 실제 PASS**: `gh_archive_client.access_test()`를 실제
  네트워크로 실행해 확인(hour=2026-08-10-7, total_events=163763,
  normalizable_events=29, compressed_bytes=20326143). 디스크에 아무것도 남기지 않음
  (gzip을 메모리에서 바로 해제·파싱). `config/sources.yaml`의 `gh_archive.enabled`를
  `true`로 전환함.
- **신규 `src/saas_words_two/gh_archive_client.py`**: `IssuesEvent`(action=opened)와
  `IssueCommentEvent`(action=created)만 정규화(PR 이벤트는 이번 배치 범위 밖 — 공급
  파이프라인의 향후 과제, 8절). 봇 액터(`login`이 `[bot]`로 끝남)는 독립 사용자 신호가
  아니므로 제외.
- **`db.py`**: 기존 `hn_items` 테이블에 `source` 컬럼 추가(마이그레이션 포함). GH Archive
  정규화 결과도 같은 테이블에 `source='gh_archive'`로 저장 — 필터·군집·수요 점수 등
  나머지 파이프라인 코드를 전혀 건드리지 않고 그대로 재사용하기 위한 설계적 선택.
  HN item id(현재 수천만대)와 GH 이슈/댓글 entity id(이미 수십억대)는 값 범위가 겹치지
  않아 충돌 가능성을 무시할 수 있다고 판단 — 근거는 `db.py`의 `COLUMN_MIGRATIONS` 주석에
  기록.
- **`collection.py`**: `run_access_test`가 `gh_archive`도 실제로 검사하도록 확장.
  신규 `run_gh_archive_collection()` — 시간 단위(`YYYY-MM-DD-H`) 커서 기반 점진 수집,
  `sources.yaml`의 `recent_days_max`(90일)를 backfill 하한으로 사용,
  `max_hours_per_run`(`project.yaml`, 기본 12) 예산만큼만 매 실행에서 처리.
  **구현 중 직접 발견해 고친 버그 2개** (회귀 테스트로 고정, §5 참고):
  1. 파이프라인의 `now`는 KST로 넘어오는데 GH Archive 파일명은 UTC 기준이라 변환 누락 시
     엉뚱한 시간대 파일을 요청하게 됨 → `now.astimezone(timezone.utc)` 추가.
  2. 시간 키에 선행 0이 없어(`"...-9"` vs `"...-10"`) 문자열 비교 시 9시가 10시보다
     "뒤"로 정렬되는 사전식 비교 오류 → `datetime`으로 변환해 비교하도록 수정.
- **`scripts/collect_sources.py`**: 접근성 PASS + `enabled`일 때만 GH Archive 수집 실행.
- 테스트 27개 신규(`tests/test_gh_archive_client.py`, `tests/test_collection.py` 확장).
  pytest 240 → **258개 전부 통과**. `tools/verify_design_coverage.py` PASS 유지.
- `docs/policies/04-data-source-policy.md` "Claude Code 실행 지침"에 GH Archive 활성화
  사실·설계 근거 기록.

## 3. Git/원격 설정 — **2026-08-10 push 인증이 끊어짐, 재확인 필요**

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git`.
- `.git/hooks/post-commit`이 커밋마다 자동 `git push origin main`을 시도한다(로컬 전용
  훅, 새 clone에서는 재설치 필요).
- **이번 세션에서 커밋 `e07769c`의 자동 push가 실패함**: `cmdkey /list`로 확인한 결과
  Windows Credential Manager에 GitHub PAT 항목이 더 이상 없고(이전 세션 §3에서
  "저장 완료·검증됨"이라고 기록했던 것과 다름), `~/.gitconfig`(사용자 전역 git 설정)도
  파일 자체가 없는 상태였다. git이 `wincredman`에 자격증명을 저장하려다 실패하고,
  대화형 프롬프트(`/dev/tty`)도 이 실행 환경에서는 열 수 없어 완전히 실패했다.
  즉 PAT 자체가 이 머신/프로필에서 사라졌거나 애초에 다른 프로필에 저장됐던 것으로
  보인다(원인 불명 — 새 프로필/환경 초기화 가능성).
- **해야 할 일(사용자 확인 필요, AI가 임의로 자격증명이나 전역 git 설정을 만들지
  않음)**: 사용자가 터미널에서 `! git push origin main`을 직접 실행해 GitHub 인증을
  다시 통과시키거나, PAT를 다시 발급해 Credential Manager에 등록해야 한다. 그 전까지
  커밋은 로컬에만 존재하며 원격과 다르다.
- 재인증 완료 후: `git push origin main`이 성공하는지 확인하고, 이 섹션을 다시
  "완료" 상태로 갱신할 것.

## 4. 다음 원자 작업 — GH Archive 실데이터 수집 후 QA 재실행

이번 배치는 **코드만** 완성했고 **아직 GH Archive 데이터를 실제로 쌓지 않았다**
(local.db에 gh_archive 행 0건). 다음 세션은 여기부터:

```bash
cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
# 1) 여러 번 반복 실행해서 GH Archive 백필을 쌓는다 (1회 = 최대 12시간치,
#    sources.yaml의 recent_days_max=90일이 하한). 필요한 만큼 반복 — 처음엔
#    예컨대 10~20회 실행해 5~10일치를 모으고 아래 3)으로 진행 여부를 판단할 것.
./.venv/Scripts/python scripts/collect_sources.py
# (반복)

# 2) 확보량 확인
./.venv/Scripts/python -c "
from saas_words_two import db
conn = db.connect(__import__('pathlib').Path('.'))
print(conn.execute(\"SELECT source, type, COUNT(*) FROM hn_items GROUP BY source, type\").fetchall())
"

# 3) QA 재실행 (기존 RETRYING run과 별개로 새로 시작)
./.venv/Scripts/python run.py --mode qa --target-count 20
# -> AWAITING_JUDGMENT면 output/runs/<run_id>/judgment/*_request.json을 읽고 판정 후
#    같은 폴더에 *_response.json을 써서:
./.venv/Scripts/python run.py --mode qa --target-count 20 --resume --run-id <run_id>
```

- **판정 기준(독립 사용자 5명)을 낮추지 말 것**(CLAUDE.md 12항 위반, `DEMAND-001` 참고).
- 이번에도 여전히 관문을 통과하는 군집이 없으면: (a) `max_hours_per_run`을 늘려
  백필 속도를 높이거나, (b) B안(임베딩 기반 군집화)을 고려하되 — 두 경우 모두
  `ACTIVE_ISSUES.md`의 `DEMAND-001`에 사실대로 기록하고 가짜 판정으로 수량을 채우지
  말 것.
- **성공/실패 무관하게** 이 QA 실행 결과는 `ACTIVE_ISSUES.md`(`DEMAND-001`)와 이 파일에
  정직하게 기록할 것(성공했다고 거짓 보고 금지, 실패도 은폐 금지).

## 5. 회귀 사례로 고정된 함정 (재발 방지)

- 시간/날짜 문자열을 키로 쓰는 증분 수집기를 새로 만들 때, **자릿수가 고정되지 않은
  키(선행 0 없음)는 절대 문자열로 비교하지 말 것** — 반드시 실제 날짜/시간 타입으로
  변환해서 비교. (`tests/test_collection.py`의
  `test_run_gh_archive_collection_crosses_single_to_double_digit_hour_boundary` 참고)
- 외부 API가 UTC 기준 리소스명을 쓰는데 파이프라인 내부 `now`는 KST로 흐른다 —
  새 데이터원을 붙일 때마다 시간대 변환 필요 여부를 반드시 확인할 것.
  (`test_run_gh_archive_collection_converts_kst_now_to_utc_before_selecting_hours` 참고)

## 6. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 수요 데이터 부족을 감추기 위해 판정을 완화하거나 가짜 문제를 만들지 말 것
  (데이터 무결성 절대 규칙, 최우선순위).
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상 — 실수로 강제 추가
  (`git add -f`)하지 말 것.
- push 자체는 훅이 자동 처리하지만, force-push·히스토리 재작성·브랜치 삭제 등
  파괴적 작업은 여전히 사용자에게 사전 확인받을 것.
