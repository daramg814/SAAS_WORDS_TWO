# 에이전트 구조·LLM/스크립트 역할 분리

**목적:** 토큰을 절약하는 최소 에이전트 구조와 각 판단 경계를 고정한다.

## Claude Code 실행 지침
1. 메인 오케스트레이터가 모든 서브에이전트 호출과 파일 경로 전달을 통제한다.
2. 서브에이전트끼리 직접 호출하지 않는다.
3. 큰 데이터는 프롬프트에 복사하지 말고 파일 경로와 필요한 범위만 전달한다.
4. 스크립트가 할 수 있는 결정론적 작업을 LLM에게 반복 위임하지 않는다.
5. 최종 기회와 제목만 독립 리뷰하고 점수 하위/탈락 항목을 반복 검토하지 않는다.

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 5. 최소 에이전트 구조

## 4.1 선택 근거

토큰 사용량을 줄이기 위해 상시 다중 에이전트 구조를 사용하지 않는다. 대부분의 작업은 메인 에이전트와 스크립트가 수행하고, 최종 기회와 제목만 독립 검토한다.

## 4.2 에이전트

| 에이전트 | 역할 | 호출 시점 |
|---|---|---|
| `main-orchestrator` | 문제 추출, 의미 군집, 수요·공급 해석, 제목 생성, 전체 상태 조율 | 전체 실행 |
| `opportunity-reviewer` | 점수 상위 기회의 수요·공급 근거와 최종 제목 독립 검토 | 기회 점수 계산 후 |
| `final-qa-runner` | 사용자와 동일한 진입점으로 전체 파이프라인 실행 | 게시 전, 코드·문서 변경 후 |
| `session-handoff-manager` | 현재 상태와 다음 작업을 짧게 정리 | 배치 완료·세션 종료 전 |
| `human-feedback-calibrator` | 사용자 Google 검증 입력의 의미 해석, 오차 유형 판정과 보정 규칙 후보 검토 | 새 사람 입력 반영 시 |

이슈 정리와 노하우 정리는 별도 상시 에이전트를 호출하지 않는다. 스크립트가 후보를 기록하고, 메인 에이전트가 실제 재발 가능성이나 측정 가능한 개선이 있는 경우에만 문서를 갱신한다.

서브에이전트 간 직접 호출은 금지한다. 모든 전달은 `main-orchestrator`를 통하며 큰 데이터는 파일 경로만 전달한다.

---

# 6. 판단과 코드 역할 분리

| 업무 | 처리 방식 | 담당 에이전트 | 담당 스크립트 |
|---|---|---|---|
| 사용자 검증 큐 생성 | 코드+LLM | main-orchestrator | `build_google_validation_queue.py` |
| 사용자 CSV 가져오기 | 코드 | 결과 검토: human-feedback-calibrator | `import_human_google_checks.py` |
| Google 관측 정규화 | 코드 | 해당 없음 | `normalize_google_feedback.py` |
| AI 예측 오차 유형 판정 | LLM+코드 | human-feedback-calibrator | `calibrate_supply_predictions.py` |
| 공급·제목 점수 보정 | 코드 | 결과 해석: human-feedback-calibrator | `apply_human_calibration.py` |
| 데이터 다운로드 | 코드 | 해당 없음 | `collect_sources.py` |
| 압축 해제·파싱 | 코드 | 해당 없음 | `parse_sources.py` |
| 후보 문장 필터 | 코드 | 결과 검토: main-orchestrator | `filter_pain_sentences.py` |
| 문제 의미 추출 | LLM | main-orchestrator | 형식 검증 |
| 동일 문제 의미 군집 | 코드+LLM | main-orchestrator | `cluster_problems.py` |
| 독립 사용자·기간 집계 | 코드 | 해당 없음 | `score_demand.py` |
| 손실·구매 의도 판단 | LLM | main-orchestrator | 점수 합산 |
| 제품 후보 수집 | 코드 | 해당 없음 | `collect_supply_candidates.py` |
| 활성 제품 검증 | 코드+LLM | main-orchestrator | `verify_products.py` |
| 직접·부분·범용 분류 | LLM | main-orchestrator | 점수 합산 |
| 희소성 우선 점수·등급 계산 | 코드 | 결과 해석: main-orchestrator | `score_opportunities.py` |
| 공급 희소성 순 독립 기회 검토 | LLM | opportunity-reviewer | 해당 없음 |
| 2단어 제목 생성 | LLM | main-orchestrator | 형식 검증 |
| 정확·역순 중복 | 코드 | 해당 없음 | `dedupe_titles.py` |
| 의미 중복·명확성 | LLM | opportunity-reviewer | 해당 없음 |
| 출력 저장 | 코드 | 해당 없음 | `publish_outputs.py` |
| 인수인계 | LLM+코드 | session-handoff-manager | `update_handoff.py` |
| Git 저장 | 코드 | 결과 확인: main-orchestrator | `git_checkpoint.py` |
| QA | 독립 LLM+코드 | final-qa-runner | `run_pipeline_qa.py --mode qa --target-count 20` |

---
