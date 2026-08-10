# 입력·출력 계약

**목적:** 모드별 입력, 최종 산출물, 부분 결과, 이력 반영, 파일명과 저장 격리를 고정한다.

## Claude Code 실행 지침
1. production과 qa는 동일 코드 경로를 사용하고 설정값만 다르게 전달한다.
2. 500개 또는 QA 목표 수량 미만의 결과는 최종 위치에 게시하지 않는다.
3. 운영 이력은 임시 파일 작성 후 원자적 교체하고 증가분을 검증한다.
4. QA는 운영 이력의 읽기 전용 스냅샷만 사용한다.

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 2. 입력과 출력

## 2.1 입력

| 경로 | 형식 | 역할 |
|---|---|---|
| `/config/project.yaml` | YAML | 데이터원, 기간, 점수 기준, 운영 목표 500개, QA 목표 20개 등 실행 설정 |
| `/config/sources.yaml` | YAML | 데이터원 엔드포인트와 활성 상태 |
| `/input/brief.md` | Markdown | 목표 시장, 제외 시장, 언어 등 선택 설정 |
| `/input/blocklist.txt` | UTF-8 TXT | 금지 단어와 금지 제목 |
| `/input/human_google_checks.csv` | UTF-8 CSV | 사용자가 일부 검색어의 Google 표시 결과 수를 입력하는 선택 파일 |
| `/output/review/google_validation_queue.csv` | UTF-8 CSV | 사람이 확인하면 학습 가치가 높은 검색어 추천 목록 |
| `/output/history/words.txt` | UTF-8 TXT | 과거 전체 승인 제목 |
| `/memory/PROJECT_PLAYBOOK.md` | Markdown | 검증된 간단한 운영 노하우 |
| `/memory/HANDOFF.md` | Markdown | 현재 Run과 다음 작업 |

입력이 없으면 광범위한 B2B·B2C SaaS 문제를 대상으로 한다.

## 2.2 실행 모드

| 모드 | 목표 승인 수 | 출력 위치 | 운영 누적 파일 반영 |
|---|---:|---|---|
| `production` | 500개 | `/output/generated/` | 반영 |
| `qa` | 기본 20개 | `/output/qa/` | 반영하지 않음 |

두 모드는 동일한 진입점과 동일한 코드 경로를 사용한다. 차이는 설정으로 전달되는 `target_title_count`, 출력 루트와 운영 파일 반영 여부뿐이다.

예시 설정 개념:

```yaml
execution_mode: production
target_title_count: 500

qa:
  target_title_count: 20
  output_root: output/qa
  update_production_history: false
```

QA 전용 축약 구현이나 별도 제목 생성 코드는 만들지 않는다.

## 2.3 핵심 출력

### 실행별 신규 제목

```text
/output/generated/saas_words_YYYYMMDD_HHMMSS_KST.txt
```

규칙:

- UTF-8
- LF 줄바꿈
- 한 줄에 제목 하나
- 정확히 영어 단어 2개
- 단어 사이 공백 하나
- 숫자·기호·하이픈 금지
- 현재 실행에서 승인된 신규 제목만 포함
- 정상 완료 파일은 정확히 500줄이어야 함
- 500개 미만의 결과는 `/output/intermediate/`에만 저장하고 최종 파일로 게시하지 않음

### 전체 누적 제목

```text
/output/history/words.txt
```

- 모든 과거 승인 제목을 한 줄에 하나씩 저장
- 임시 파일 작성 후 원자적 교체
- 현재 실행 결과와 정확히 일치하는 증가분 검증

### QA 출력

```text
/output/qa/<qa_run_id>/
├── generated/saas_words_qa.txt
├── opportunities.jsonl
├── qa_report.md
├── qa_history_snapshot.txt
└── logs/
```

QA 결과는 운영용 `/output/generated/`와 `/output/history/words.txt`에 반영하지 않는다. QA 시작 시 운영 `words.txt`의 읽기 전용 스냅샷을 사용해 중복 검사는 동일하게 수행한다.

### 사용자 Google 검증 출력

```text
/output/review/google_validation_queue.csv
/output/review/google_feedback_import_report.md
/memory/human_feedback/google_supply_observations.jsonl
/memory/human_feedback/google_calibration_metrics.json
/memory/human_feedback/google_query_playbook.md
```

`google_validation_queue.csv`는 사용자가 반드시 전부 처리해야 하는 작업 목록이 아니다. 사용자는 시간 날 때 원하는 행만 검색하고 결과를 `/input/human_google_checks.csv`에 입력한다. 입력된 행은 다음 실행에서 자동 반영되며, 미입력 행은 계속 대기하거나 새 우선순위에 따라 교체될 수 있다.

### 기회 데이터

```text
/output/final/opportunities.jsonl
```

필수 필드:

```json
{
  "problem_id": "P-0001",
  "target_user": "small construction firms",
  "task": "track contractor insurance expiration",
  "workaround": "email and spreadsheets",
  "pain": "missed renewals",
  "demand_score": 78,
  "supply_scarcity_score": 72,
  "opportunity_score": 76,
  "confidence": "A",
  "decision": "GENERATE_TITLES",
  "evidence_ids": ["E-001", "E-002"],
  "product_ids": ["S-001", "S-002"]
}
```

---
