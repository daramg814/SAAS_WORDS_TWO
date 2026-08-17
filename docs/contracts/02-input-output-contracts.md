# 입력·출력 계약

**목적:** 모드별 입력, 최종 산출물, 부분 결과, 이력 반영, 파일명과 저장 격리를 고정한다.

**(2026-08-17 신규) `output/` 최상위 구조**: 사용자가 실제로 가져가는 결과물과 순수
내부 기계장치가 같은 레벨(`generated`/`history`/`qa`/`runs`/`intermediate`/`logs`/
`review`/`final` 8개 폴더)에 나란히 있어 구분이 안 되던 문제를 정리했다.
```text
output/
├── deliverables/    # 사용자가 가져가는 최종 산출물
│   ├── generated/   # production 확정 배치
│   ├── history/     # words.txt(누적 승인 제목), keyword_metrics_cache.csv, keyword_metrics_passed.csv
│   └── review/       # google_validation_queue.csv 등 사람이 직접 처리하는 큐
└── _pipeline/        # 순수 내부 기계장치 (사용자가 볼 필요 없음, `_`로 시작해 파일탐색기에서도 맨 위/아래로 정렬)
    ├── runs/          # run_state.json, 판정 요청/응답 원문(라운드당 최대 수 MB)
    ├── intermediate/  # 라운드 미달 시 임시 저장, keyword_metrics evidence jsonl
    ├── qa/             # QA 모드 산출물(운영과 격리 목적, 최종 채택본 아님)
    └── final/          # 레거시(수요/공급 opportunities.jsonl, 현재 미사용)
```
아래 모든 경로 표기는 이 새 구조를 기준으로 한다. 예전 `output/history/words.txt`
같은 표기를 다른 문서·기억에서 보게 되면 `output/deliverables/history/words.txt`로
읽을 것 — 단, `memory/ACTIVE_ISSUES.md`의 과거 사건 기록과
`docs/design/source/`의 원본 설계서는 **당시 실제 경로를 그대로 보존**하므로
수정하지 않는다(역사적 사실 왜곡 금지).

## Claude Code 실행 지침
1. production과 qa는 동일 코드 경로를 사용하고 설정값만 다르게 전달한다.
2. 500개 또는 QA 목표 수량 미만의 결과는 최종 위치에 게시하지 않는다.
3. 운영 이력은 임시 파일 작성 후 원자적 교체하고 증가분을 검증한다.
4. QA는 운영 이력의 읽기 전용 스냅샷만 사용한다.
5. **(2026-08-17 신규)** AI 판정을 통과한 후보는 게시 전에 추가로 Google Ads Keyword Planner 필터(`config/keyword_metrics.yaml`의 `avg_monthly_searches_min`/`competition_index_exact`)를 통과해야 한다 — `memory/ACTIVE_ISSUES.md`의 `GKP-001` 참고. 이 필터 통과율이 낮으면(2026-08-17 QA 실측 약 2.3%) 목표 수량 미달로 `RETRYING`/`CAPABILITY_STAGNATION`이 될 수 있으며, 이는 정직한 결과이지 결함이 아니다.

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
| `/output/deliverables/review/google_validation_queue.csv` | UTF-8 CSV | 사람이 확인하면 학습 가치가 높은 검색어 추천 목록 |
| `/output/deliverables/history/words.txt` | UTF-8 TXT | 과거 전체 승인 제목 |
| `/memory/PROJECT_PLAYBOOK.md` | Markdown | 검증된 간단한 운영 노하우 |
| `/memory/HANDOFF.md` | Markdown | 현재 Run과 다음 작업 |

입력이 없으면 광범위한 B2B·B2C SaaS 문제를 대상으로 한다.

## 2.2 실행 모드

| 모드 | 목표 승인 수 | 출력 위치 | 운영 누적 파일 반영 |
|---|---:|---|---|
| `production` | 500개 | `/output/deliverables/generated/` | 반영 |
| `qa` | 기본 20개 | `/output/_pipeline/qa/` | 반영하지 않음 |

두 모드는 동일한 진입점과 동일한 코드 경로를 사용한다. 차이는 설정으로 전달되는 `target_title_count`, 출력 루트와 운영 파일 반영 여부뿐이다.

예시 설정 개념:

```yaml
execution_mode: production
target_title_count: 500

qa:
  target_title_count: 20
  output_root: output/_pipeline/qa
  update_production_history: false
```

QA 전용 축약 구현이나 별도 제목 생성 코드는 만들지 않는다.

## 2.3 핵심 출력

### 실행별 신규 제목

```text
/output/deliverables/generated/saas_words_YYYYMMDD_HHMMSS_KST.txt
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
- 500개 미만의 결과는 `/output/_pipeline/intermediate/`에만 저장하고 최종 파일로 게시하지 않음

### 전체 누적 제목

```text
/output/deliverables/history/words.txt
```

- 모든 과거 승인 제목을 한 줄에 하나씩 저장
- 임시 파일 작성 후 원자적 교체
- 현재 실행 결과와 정확히 일치하는 증가분 검증

### QA 출력

```text
/output/_pipeline/qa/<qa_run_id>/
├── generated/saas_words_qa.txt
├── opportunities.jsonl
├── qa_report.md
├── qa_history_snapshot.txt
└── logs/
```

QA 결과는 운영용 `/output/deliverables/generated/`와 `/output/deliverables/history/words.txt`에 반영하지 않는다. QA 시작 시 운영 `words.txt`의 읽기 전용 스냅샷을 사용해 중복 검사는 동일하게 수행한다.

### 사용자 Google 검증 출력

```text
/output/deliverables/review/google_validation_queue.csv
/output/deliverables/review/google_feedback_import_report.md
/memory/human_feedback/google_supply_observations.jsonl
/memory/human_feedback/google_calibration_metrics.json
/memory/human_feedback/google_query_playbook.md
```

`google_validation_queue.csv`는 사용자가 반드시 전부 처리해야 하는 작업 목록이 아니다. 사용자는 시간 날 때 원하는 행만 검색하고 결과를 `/input/human_google_checks.csv`에 입력한다. 입력된 행은 다음 실행에서 자동 반영되며, 미입력 행은 계속 대기하거나 새 우선순위에 따라 교체될 수 있다.

### 기회 데이터

```text
/output/_pipeline/final/opportunities.jsonl
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

## 2026-08-17 신규 — Keyword Planner 검색량·경쟁지수 필터 계약 (GKP-001)

> 아래는 원본 설계서에 없는 신규 계약이다(CLAUDE.md §2.3/§4, `memory/ACTIVE_ISSUES.md`
> GKP-001 참고). 위 2.1~2.3의 원본 보존 내용과 별개로, 현재(전환 이후) 유효한
> `word_pipeline.py` 경로에 추가된 게이트를 기술한다.

### 신규 입력

| 경로 | 형식 | 역할 |
|---|---|---|
| `.env.local` | KEY=VALUE (git 제외) | Google Ads API OAuth 자격증명. `.env.example`이 키 이름 스키마. 없으면 `KeywordMetricsCredentialsError`로 명시적 실패(가짜 통과 없음) |
| `config/keyword_metrics.yaml` | YAML | `avg_monthly_searches_min`/`competition_index_exact` 필터 기준값과 API 런타임 설정(batch_size, budget, rate limit). **이 파일의 두 기준값만 바꾸면 필터 동작이 바뀐다** — 코드 수정 불필요 |

### 신규 중간 산출물

```text
/output/_pipeline/intermediate/<run_id>_keyword_metrics_evidence.jsonl
```

- 매 라운드 AI 판정 통과 후보 전원(통과/탈락 모두)의 `title`, `avg_monthly_searches`,
  `competition_index`, `api_status`, `passed`, `source`(`cache`|`api`), `checked_at`을
  한 줄씩 append.
- production/QA 공통 — QA도 동일 경로에 기록되며 `output/_pipeline/qa/<qa_run_id>/` 밖에
  쓰는 것이 아니라 실행 전반의 판정 근거 로그이므로 `output/_pipeline/intermediate/`가
  맞는 위치(CLAUDE.md §4 QA 출력 격리 규칙과 무관 — 격리 대상은 `output/deliverables/generated`
  /`output/deliverables/history`뿐).

### 신규 누적(cross-run) 출력 — 2026-08-17 사용자 요청

```text
/output/deliverables/history/keyword_metrics_cache.csv    # 지금까지 조회한 모든 단어, pass/fail 전부 (표 형태)
/output/deliverables/history/keyword_metrics_passed.csv   # 위에서 gate_passed=True만 뽑은 부분집합
```

컬럼(고정 순서, CLAUDE.md 12항 — 임의 변경 금지): `title,avg_monthly_searches,
competition_index,api_status,gate_passed,checked_at`.

- **raw 데이터 보존**: pass든 fail이든 조회된 모든 단어가 여기 남는다(run 단위로
  흩어지는 `output/_pipeline/intermediate/*_keyword_metrics_evidence.jsonl`과 달리, 여러 run에
  걸쳐 누적되는 단일 문서).
- **배치 단위 즉시 기록**: `KeywordMetricsClient.fetch_metrics`가 20개 배치를 받을
  때마다(`on_batch_fn`) 바로 이 파일에 append한다 — 라운드 전체가 끝나야 기록되는
  게 아니므로, 중간에 네트워크 오류로 죽어도 이미 확인한 단어는 남는다(실측 근거:
  GKP-001에서 9,645개 라운드가 49%·91% 지점에서 각각 다른 이유로 죽어 아무것도
  안 남았던 사고 2건, `memory/ACTIVE_ISSUES.md` GKP-001 참고).
- **재조회 생략**: `word_generation.generate_combinations`에 전달되는 exclude
  집합(`word_pipeline._excluded_normalized`)이 `gate_passed=False`로 기록된 단어를
  전부 포함한다 — 이미 탈락으로 확인된 조합은 이후 어떤 실행에서도 다시
  생성·판정·API 조회되지 않는다. `gate_passed=True`인 단어는 제외 대상이
  **아니다**(아직 안 쓴 좋은 후보이므로 계속 후보 풀에 남아야 함) — 대신 이미
  캐시에 있으므로 API만 다시 호출하지 않고 재사용한다(`_apply_keyword_metrics_filter`).

### 게이트 규칙

최종 `approved`에 편입되려면 AI 판정(명확성·의미중복·상표유사) 통과 **및** 아래
두 조건을 모두 만족해야 한다:

1. `avg_monthly_searches >= config/keyword_metrics.yaml.avg_monthly_searches_min`
2. `competition_index == config/keyword_metrics.yaml.competition_index_exact`(기본 0)

`competition_index`가 `NULL`(Keyword Planner가 해당 조합에 메트릭 자체를 반환하지
않음 — 통계적으로 유의미하지 않은 "죽은 단어")인 경우는 조건 2를 항상 실패한다.
`avg_monthly_searches`가 `NULL`인 경우도 마찬가지로 조건 1을 항상 실패한다. 코드가
전담하는 순수 수치 비교이며(CLAUDE.md §2 역할 분리), 현재 세션의 판정 대상이
아니다.

---
