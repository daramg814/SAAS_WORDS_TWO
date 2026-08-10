# HANDOFF

- 상태: `PAUSED`
- 요약 한 줄: 1차 구현(파이프라인 15단계) 코드·테스트 전부 완료. 실제 QA(20개)도 끝까지
  돌렸으나 수요 관문을 통과하는 문제가 없어 `RETRYING`으로 정상 종료(코드 결함 아님,
  `DEMAND-001`). 사용자와 협의해 **다음 조치는 A안(2차 데이터원 활성화)으로 확정**함
  — 재논의 없이 바로 착수할 것.

## 1. 지금 이 세션을 새로 열면 가장 먼저 할 일

1. `CLAUDE.md` → `memory/KNOWLEDGE_MANIFEST.yaml` → 이 파일 → `memory/PROJECT_PLAYBOOK.md`
   → `memory/ACTIVE_ISSUES.md`(`DEMAND-001`) 순서로 읽는다.
2. 환경 확인:
   ```bash
   cd "C:\Share\Claude_project\SAAS_WORDS_TWO_claude_code_project_v2.4"
   ./.venv/Scripts/python -m pytest -q          # 240 passed 나와야 정상
   ./.venv/Scripts/python tools/verify_design_coverage.py   # PASS 나와야 정상
   ```
   `.venv`가 없거나 깨졌으면 `python -m venv .venv` 후
   `./.venv/Scripts/python -m pip install -e ".[dev]"`.
3. `git log --oneline`으로 커밋 이력 확인. **원격 push는 이미 설정 완료**(아래 §3) —
   커밋만 하면 자동으로 push되므로 별도 push 명령 불필요.
4. §4(다음 원자 작업)의 A안부터 바로 시작한다. B안·재논의는 A안 시도 후 여전히
   부족할 때만 고려(§4 하단 참고).

## 2. 완료된 것 (전부 커밋되어 있음, `git log`로 각 배치 확인 가능)

- HN 공식 API 접근성 검사·증분 수집 (Firebase API + Algolia 검색 API 두 가지 모두)
- 후보 문제 문장 필터, 문자열 유사도 1차 군집화(성능 최적화 완료: 4,133개 후보
  기준 3초)
- 수요 점수(100점 배점), 공급 후보 수집·활성 검증, 공급 희소성 등급·희소성 우선
  점수, 제목 생성 라운드 로직(부족분×2, 최대 5라운드), Google 사람 검증 보정 체계
  5개 스크립트
- `run.py`/`pipeline.py`: 15단계 전체 연결. 의미 판정이 필요한 지점(문제 추출,
  공급 활성/유형 분류, 기회 검토, 제목 생성, 제목 의미중복 검토)마다
  `output/runs/<run_id>/judgment/<stage>_request.json`을 쓰고 멈춘 뒤, 현재
  세션이 직접 읽고 판정해서 `_response.json`을 쓰면 `--resume`으로 이어감.
  별도 API 키·anthropic 패키지 없음(CLAUDE.md 절대 규칙 준수).
- pytest 240개, `qa/regression/REQUIRED_CASES.md`의 필수 회귀 사례 16개 전부
  `tests/test_regression_required_cases.py`에 대응 테스트 있음.

## 3. Git/원격 설정 (2026-08-10 완료, 재작업 불필요)

- `origin` = `https://github.com/daramg814/SAAS_WORDS_TWO.git` 연결됨, `main` push
  완료·SHA 일치 확인됨.
- `.git/hooks/post-commit`이 `main` 커밋마다 자동으로 `git push origin main` 실행
  (사용자 명시 요청). 훅은 로컬 전용(`git` 미추적) — 새 clone/새 머신에서는 재설치
  필요.
- 인증은 만료 없는 Classic PAT(`repo` scope, Windows Credential Manager 저장)로
  전환 완료. 이 저장소 로컬 설정 `credential.https://github.com.gitHubAuthModes=pat`
  로 GCM 브라우저 로그인 대신 PAT를 쓰도록 강제해놓음. 완전 무인 push 실제 커밋으로
  검증됨(브라우저 재로그인 불필요).
- 실패 시 훅이 stderr에 `post-commit: auto-push ... FAILED`를 출력하고 커밋 자체는
  `COMMIT_PENDING` 취급 — 사용자에게 알리고 수동 push로 해결할 것.

## 4. 실제 QA 실행에서 확인된 것 (`memory/ACTIVE_ISSUES.md`의 DEMAND-001 참고)

`python run.py --mode qa --target-count 20`을 실제 HN 데이터로 끝까지 실행함.
- source_access_test → collect_sources → filter_pain_sentences →
  extract_and_cluster_problems까지는 실제 네트워크·판정으로 전부 정상 동작.
- 문제: HN에서 후보 문장을 아무리 늘려도(14,910개 원문 / 4,990개 후보 문장,
  `search_hits_per_pattern`을 40→1000까지 올림) "동일한 구체적 SaaS 문제를
  독립 사용자 5명 이상이 언급"하는 군집이 실제로는 없었다. 독립 사용자 수 상위
  16개 군집을 전부 직접 읽어봤는데 HN 관용구("feature requests welcome!")나
  질문 템플릿("How do you manage X?"에서 X가 매번 다른 주제)이었음.
- 정직하게 전부 반려 → `problems`/`opportunities`/`titles` 전부 0건 →
  `generate_and_review_titles`에서 `RetryRequired`로 정상 종료(exit code 4,
  status=`RETRYING`). `output/history/words.txt`와 `output/generated/`는
  전혀 건드리지 않음(확인 완료).
- 마지막 실행: run_id `QA-20260810-215254-KST`. `output/runs/.../run_state.json`은
  git에 있음. 판정 요청/응답 원문(수 MB, HN 원문 대량 포함)은 `.gitignore`로
  제외했음(로컬에는 남아있음).

## 5. 다음 원자 작업 — A안(확정): 2차 데이터원 활성화

- `config/sources.yaml`에서 `stack_exchange_dump` 또는 `gh_archive`를
  `activation_gate: access_test_pass` 절차대로 접근성 검사 후 `enabled: true`로.
- `.claude/skills/source-access/SKILL.md` 절차(샘플 다운로드→형식 검사→디스크
  검사→중복 방지 검사) 그대로 따를 것. 새 데이터원마다 `collection.py`에 상응하는
  수집 함수를 추가해야 함(현재는 HN 전용으로만 구현되어 있음).
- 근거: Stack Exchange/GH Archive는 Q&A 구조상 동일 문제를 여러 사용자가 각자
  질문하는 경우가 많아, HN보다 5명 기준을 통과할 원재료가 많을 가능성이 높음
  (설계서 3.2절 원래 의도).
- **A안 시도 후에도 여전히 부족하면**: B안(의미 기반/임베딩 군집화, 새 의존성 필요
  — CLAUDE.md §8에 따라 라이선스·유지보수 위험 문서화 후 추가,
  `docs/implementation/14-implementation-roadmap.md` "3차 개선" 참고)을 그때 고려.
  두 안 모두 하지 않고 그냥 재시도만 하면 결과는 똑같다(데이터가 안 바뀌면 판정도
  똑같이 나옴). **판정 기준(독립 사용자 5명)을 임의로 낮추는 것은 CLAUDE.md 12항
  위반이므로 하지 말 것.**

## 6. QA를 이어서 실행하는 방법 (A안 적용 후)

```bash
# 데이터를 더 모은 뒤 새 QA 실행 (기존 run은 RETRYING으로 끝났으므로 새로 시작)
./.venv/Scripts/python scripts/collect_sources.py     # 필요시 반복 실행(증분 수집)
./.venv/Scripts/python run.py --mode qa --target-count 20
# -> AWAITING_JUDGMENT 로 멈추면 output/runs/<run_id>/judgment/*_request.json 을
#    직접 읽고 판정한 뒤 같은 폴더에 *_response.json 을 써서
./.venv/Scripts/python run.py --mode qa --target-count 20 --resume --run-id <run_id>
# -> 반복. 20개 확정되면 output/qa/<run_id>/ 에 최종 산출물 저장됨.
```

judgment response를 직접 쓸 때는 `saas_words_two.judgment.write_response()`를
python -c로 호출하는 방식을 이번 세션 내내 사용했음(요청 파일의 `items` 구조를
그대로 읽어 `decisions` 배열을 만들면 됨). 각 단계별 요청/응답 스키마는
`src/saas_words_two/pipeline.py`의 각 `_stage_*` 함수 docstring과
`_write_*_request`/`_consume_*` 함수 쌍을 보면 정확히 알 수 있음.

## 7. 주의·금지

- 미구현/미완료 상태를 DONE 또는 QA PASS로 기록하지 말 것.
- 수요 데이터 부족을 감추기 위해 판정을 완화하거나 가짜 문제를 만들지 말 것
  (데이터 무결성 절대 규칙, 최우선순위).
- 운영 `output/history/words.txt` / `output/generated/`에 검증 안 된 부분 결과를
  쓰지 말 것.
- `data/local.db`, `output/runs/*/judgment/`는 `.gitignore` 대상(대용량 원문
  데이터) — 실수로 강제 추가(`git add -f`)하지 말 것.
- push 자체는 훅이 자동 처리하지만, force-push·히스토리 재작성·브랜치 삭제 등
  파괴적 작업은 여전히 사용자에게 사전 확인받을 것(§3의 자동화는 일반적인
  `commit → push`에만 적용되는 예외).
