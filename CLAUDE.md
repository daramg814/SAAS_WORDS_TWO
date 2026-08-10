
# SAAS_WORDS_TWO — Claude Code 운영 규칙

## 1. 프로젝트 정의
공개 데이터에서 **실제 반복 수요가 확인되고 공급이 부족한 SaaS 문제**를 발굴한 뒤, 해당 기회에 맞는 **신규 영어 2단어 Title Case 제목**을 생성한다. `production`은 최종 승인 제목을 정확히 500개 게시하고 운영 누적 이력에 반영하며, `qa`는 동일한 진입점과 전체 코드 경로에서 기본 20개를 생성하되 운영 데이터를 절대 수정하지 않는다.

원본 설계서는 `docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md`가 기준이다. 실행 규칙과 원본이 충돌하면 원본의 의도를 보존하고, 충돌 사실을 `memory/ACTIVE_ISSUES.md`에 기록한 뒤 QA를 수행한다.

## 2. 절대 규칙
1. **AI 판정은 현재 실행 중인 Claude Code 세션 또는 그 세션이 호출한 서브에이전트가 직접 수행한다.** 별도의 `anthropic` 패키지, Anthropic API 호출, API 키 설정을 추가하지 않는다.
2. 수집·파싱·정규화·집계·점수 계산·정확 중복 제거·원자적 저장은 코드로 처리한다. 의미 해석, 애매한 군집 판정, 제품 유형 판정, 기회 독립 검토, 제목 명확성·의미 중복 검토만 현재 세션/서브에이전트가 수행한다.
3. Google 검색 결과 페이지 스크래핑, CAPTCHA 우회, 브라우저 자동화, Google Keyword Planner·Google Trends 의존을 구현하지 않는다.
4. 접근성 QA를 통과하지 못한 선택 데이터원은 `DISABLED` 처리하고 가능한 데이터원만으로 계속한다. 독립 출처 부족은 신뢰도를 낮춘다.
5. `production`은 승인 제목이 정확히 500개가 되기 전까지 완료하거나 최종 파일을 게시하지 않는다. 부족분은 중간 출력에만 저장한다.
6. `qa`는 사용자와 동일한 `run.py` 진입점과 동일한 단계·검증·저장 함수를 사용한다. QA 전용 축약 소프트웨어나 별도 제목 생성 로직을 만들지 않는다.
7. QA 전후 운영 `output/history/words.txt` 체크섬은 동일해야 한다. QA 출력은 `output/qa/<qa_run_id>/` 밖에 쓰지 않는다.
8. `MARKET_QUERY`와 `TITLE_QUERY`를 혼합하지 않는다. 시장 공급 보정과 제목 충돌 보정은 서로 다른 점수에만 반영한다.
9. 사람 Google 관측은 append-only 원장에 추가한다. 기존 행을 수정·덮어쓰기 하지 않는다.
10. 코드·설정·문서 수정 뒤에는 반드시 `final-qa-runner`가 동일 파이프라인 QA를 실행하고 결과물을 검사해야 한다.
11. 강제 푸시, 무검증 이력 재작성, 민감정보·대용량 원문 데이터 커밋을 금지한다.
12. 기존 입출력 계약, 점수 기준, 상태 이름, 파일명 규칙을 임의로 변경하지 않는다. 변경이 필요하면 문서·회귀 QA·인수 기준을 함께 수정한다.

세부 범위·성공/실패 기준은 `docs/project/01-project-charter.md`를 따른다.

## 3. 우선순위
1. 근거 추적 가능성과 데이터 무결성
2. 운영/QA 격리와 원자적 게시
3. 입출력 형식 및 정확한 목표 수량
4. 공급 희소성 우선 점수의 재현성
5. 기존 정상 동작 유지와 회귀 방지
6. 토큰·네트워크·디스크 절약
7. 성능과 코드 미관

## 4. 입력·출력 계약
- 입력: `config/project.yaml`, `config/sources.yaml`, 선택 `input/brief.md`, `input/blocklist.txt`, `input/human_google_checks.csv`, 운영 이력 `output/history/words.txt`, 메모리 파일.
- 운영 출력: `output/generated/saas_words_YYYYMMDD_HHMMSS_KST.txt` 정확히 500줄, `output/history/words.txt` 원자적 증가, `output/final/opportunities.jsonl`.
- QA 출력: `output/qa/<qa_run_id>/` 내부에만 생성하며 기본 제목 파일은 정확히 20줄이다.
- 제목 형식: UTF-8/LF, 한 줄 하나, 영문자 2단어, 단일 공백, Title Case, 숫자·기호·하이픈 금지, 정확·대소문자·역순·현재 실행·과거 이력 중복 0.
- 사람 검증: 입력 최소 필드는 `validation_id`, `user_result_count`, `user_checked_at`; 완전 동일한 `validation_id + result_count + checked_at`만 중복 거부한다.

상세 계약과 스키마는 `docs/contracts/02-input-output-contracts.md` 및 `docs/contracts/03-schema-reference.md`를 따른다.

## 5. 판단과 코드 역할 분리 — 반드시 유지
| 영역 | 코드/스크립트 | 현재 Claude Code 세션·서브에이전트 |
|---|---|---|
| 데이터 수집·다운로드·압축 해제·파싱 | 전담 | 결과 이상 여부만 해석 |
| 후보 문장 필터·중복 제거·집계 | 전담 | 필터 품질과 누락 위험 검토 |
| 문제 구조 추출·애매한 의미 군집 | 형식 검증·1차 유사도 | 의미 추출과 애매한 군집 판정 |
| 수요 점수 | 재현 가능한 계산 | 손실·구매 의도 등 의미 판정 |
| 공급 후보 수집·활성 신호 추출 | 전담 | 직접·부분·범용·비경쟁 판정 |
| 기회 점수·정렬·등급 | 전담 | 상위 기회 독립 검토 |
| 제목 생성 | 형식·정확/역순 중복 검사 | 후보 생성, 명확성·의미 중복 검토 |
| 사람 Google 입력 | 파싱·정규화·가중치 계산 | 오차 유형과 규칙 승격 후보 검토 |
| 출력 게시·체크섬·롤백 | 전담 | 게시 승인과 결과 해석 |
| QA | 동일 파이프라인 실행 | `final-qa-runner`가 사용자 결과물 판정 |

전체 매트릭스와 금지 경계는 `docs/architecture/06-agents-and-role-separation.md`를 따른다.

## 6. 고정 워크플로우
세션 시작 → Git/HANDOFF/PLAYBOOK/현재 Run/최근 품질/이력 로드 → 데이터원 접근성 검사 → 증분 수집 → 코드 기반 후보 축소 → 문제 구조 추출·군집 → 수요 점수 → 통과 문제만 공급 조사 → 활성 제품 분류 → 공급 부족·희소성 점수 → 상위 기회 독립 검토 → 제목 반복 생성·검증 → 목표 수량 도달 → 동일 파이프라인 QA → 모드별 원자적 게시 → Google 검증 큐/새 입력 처리 → 메모리·Git 체크포인트.

수요, 공급, 기회, 제목 세부 규칙은 각각 다음을 따른다.
- `docs/pipeline/07-demand-pipeline.md`
- `docs/pipeline/08-supply-pipeline.md`
- `docs/pipeline/09-opportunity-scoring.md`
- `docs/pipeline/10-title-generation.md`
- `docs/policies/05-human-google-calibration.md`

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
10. 현재 기회와 관련된 최근 사람 관측

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
- 수요·공급·기회·제목 결정이 근거 ID로 재현된다.
- 운영 게시가 원자적이며 증가분과 체크섬이 검증된다.
- QA가 동일 진입점과 전체 코드 경로로 PASS하고 운영 데이터가 불변이다.
- 필수 회귀 사례가 통과한다.
- 문서·설정·코드·테스트가 서로 일치한다.
- `python tools/verify_design_coverage.py`가 PASS한다.
- 원본 설계서 대비 누락 검토 결과가 `docs/design/DESIGN_COVERAGE_MATRIX.md`에 0건으로 기록된다.
