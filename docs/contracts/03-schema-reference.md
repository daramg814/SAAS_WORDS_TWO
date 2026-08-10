
# 데이터 스키마 참조

## 공통 식별자
- `run_id`: `RUN-YYYYMMDD-HHMMSS-KST` 계열, 실행 내 불변.
- `qa_run_id`: QA 전용 실행 ID, 운영 실행 ID와 구분.
- `problem_id`: `P-0001` 계열.
- `evidence_id`: `E-0001` 계열.
- `product_id`: `S-0001` 계열.
- `validation_id`: `GVQ-YYYYMMDD-NNNN` 계열.
- `observation_id`: `HGO-YYYYMMDD-NNNN` 계열.

## opportunities.jsonl 필수 필드
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

## google_validation_queue.csv 열 순서
`validation_id,query_type,problem_id,title,google_query,predicted_effective_supply,predicted_scarcity_score,predicted_result_band,priority_reason,user_result_count,user_checked_at,country,language,search_context,top_results_relevant,user_notes`

## human_google_checks.csv 최소 필수
- `validation_id`
- `user_result_count`
- `user_checked_at`

## 사람 관측 JSONL 필수 원칙
입력 시점의 예측값을 함께 동결하고, 기존 관측을 수정하지 않는다. 동일 검색어의 다른 날짜 관측은 새 행이다.

## 실행 상태
`RUNNING`, `RETRYING`, `CAPABILITY_STAGNATION`, `COMMIT_PENDING`, `RECOVERY_REQUIRED`, `PAUSED`, `FAILED`, `DONE`만 사용한다.
