# 사람 Google 검증·보정 정책

**목적:** 선택적 사람 관측을 append-only 학습 자산으로 누적하되 검색 결과 수를 실제 제품 수로 오인하지 않도록 한다.

## Claude Code 실행 지침
1. Google SERP 자동 스크래핑 대신 사용자가 입력한 관측만 가져온다.
2. MARKET_QUERY는 공급 희소성 보정에, TITLE_QUERY는 제목 충돌 위험에만 사용한다.
3. 결과 수는 log10 변환 후 조건별 백분위 또는 임시 구간으로 정규화한다.
4. 보정 가중치는 표본 수에 따라 증가하고 최대 25%, 관련 결과 수가 없으면 최대 12.5%다.
5. 단일 관측으로 플레이북·설정·에이전트 지침을 영구 변경하지 않는다. 최소 5건 반복과 QA가 필요하다.

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 4. 사용자 Google 검증 자산화

## 4.1 목적

자동 데이터만으로 계산한 공급량은 제품의 다른 명칭, 검색 누락, 오픈소스 대체재와 산업별 용어 차이 때문에 틀릴 수 있다. 사용자가 일부 항목을 직접 Google에서 확인한 결과를 입력하면 다음 두 가지를 교정한다.

1. `MARKET_QUERY`: 특정 SaaS 문제의 온라인 공급 노출 규모 보정
2. `TITLE_QUERY`: 생성된 영어 2단어 제목의 기존 사용·충돌 가능성 보정

두 검색은 의미가 다르므로 반드시 구분한다.

예:

```text
MARKET_QUERY:
"vendor insurance tracking software"

TITLE_QUERY:
"Vendor Guard"
```

`MARKET_QUERY` 결과는 공급 부족 예측을 보정한다. `TITLE_QUERY` 결과는 제목 신규성·혼잡도·브랜드 충돌 위험을 보정하며 시장 공급량 계산에는 직접 사용하지 않는다.

## 4.2 사용자가 입력하는 방식

프로젝트는 다음 파일을 자동 생성한다.

```text
/output/review/google_validation_queue.csv
```

권장 열:

| 열 | 설명 |
|---|---|
| `validation_id` | 검증 항목 고유 ID |
| `query_type` | `MARKET_QUERY` 또는 `TITLE_QUERY` |
| `problem_id` | 연관 SaaS 문제 ID |
| `title` | 연관 생성 제목, 없으면 공란 |
| `google_query` | 사용자가 그대로 복사해 검색할 문구 |
| `predicted_effective_supply` | AI가 추정한 유효 공급량 |
| `predicted_scarcity_score` | AI의 공급 부족 점수 |
| `predicted_result_band` | AI가 예상한 Google 결과 규모 구간 |
| `priority_reason` | 이 검증이 학습에 유용한 이유 |
| `user_result_count` | 사용자가 입력하는 Google 표시 결과 수 |
| `user_checked_at` | 검색한 현지 날짜·시간 |
| `country` | 검색 국가, 기본 `KR` |
| `language` | 검색 언어, 기본 `ko` 또는 검색 문구 언어 |
| `search_context` | 일반·시크릿·로그인 등 선택 기록 |
| `top_results_relevant` | 선택 항목. 첫 결과 일부에서 관련 SaaS로 보인 개수 |
| `user_notes` | 선택 메모 |

사용자는 전체 행을 처리할 필요가 없다. 검색한 행만 채워 `/input/human_google_checks.csv`로 저장한다. 프로젝트는 새 입력 행만 자동 감지한다.

최소 필수 입력:

```text
validation_id
user_result_count
user_checked_at
```

권장 입력:

```text
top_results_relevant
user_notes
```

Google 표시 결과 수는 대략적인 값이고 지역·언어·날짜·로그인 상태에 따라 달라질 수 있으므로 검색 문구와 관찰 조건을 함께 보존한다.

## 4.3 검증 대상 추천 방식

사람의 시간을 가장 가치 있게 사용하기 위해 모든 제목을 요청하지 않는다. `google_validation_queue.csv`에는 다음 항목을 우선 추천한다.

1. 공급 희소성 `S`등급인데 AI 신뢰도가 낮은 시장 검색어
2. 공급 부족 점수와 발견 제품 수가 서로 모순되는 문제
3. 최종 500개 중 높은 점수를 받았지만 제목 충돌 위험이 불확실한 제목
4. 이전 사람 검증에서 AI 오차가 컸던 산업·표현과 유사한 항목
5. 아직 사람 검증 데이터가 없는 산업군
6. 같은 의미의 검색어 중 AI 예측 차이가 큰 항목
7. 향후 점수 기준을 바꿀 가능성이 큰 경계값 항목

추천 목록은 산업·문제·제목 패턴이 한쪽으로 편중되지 않도록 다양성 제한을 적용한다.

기본 권장 목록:

```text
MARKET_QUERY 20개
TITLE_QUERY 30개
합계 최대 50개
```

이는 의무 작업량이 아니라 선택 가능한 추천 목록이다.

## 4.4 append-only 검증 원장

가져온 사람 검증 데이터는 다음 파일에 한 줄씩 추가한다.

```text
/memory/human_feedback/google_supply_observations.jsonl
```

예시:

```json
{
  "observation_id": "HGO-20260804-0001",
  "validation_id": "GVQ-20260804-0012",
  "query_type": "MARKET_QUERY",
  "problem_id": "P-0042",
  "title": null,
  "google_query": "\"vendor insurance tracking software\"",
  "user_result_count": 18400,
  "user_checked_at": "2026-08-04T20:15:00+09:00",
  "country": "KR",
  "language": "en",
  "search_context": "normal",
  "top_results_relevant": 7,
  "predicted_effective_supply_at_time": 1.8,
  "predicted_scarcity_score_at_time": 91,
  "predicted_result_band_at_time": "LOW",
  "source": "human_manual_google",
  "import_run_id": "RUN-20260804-003"
}
```

원칙:

- 기존 관측치를 수정하거나 덮어쓰지 않는다.
- 같은 검색어를 다른 날짜에 다시 검사하면 새 관측치로 추가한다.
- 완전히 동일한 `validation_id + result_count + checked_at`만 중복으로 거부한다.
- AI 예측값은 입력 시점의 값을 함께 동결 저장해 나중에 과거 예측 오차를 재현한다.
- 원문 CSV가 삭제되어도 JSONL 원장은 유지한다.
- Git에는 개인정보가 없는 검증 원장과 요약 지표만 저장한다.

## 4.5 Google 결과 수의 정규화

Google 결과 수는 실제 제품 개수가 아니며 매우 큰 범위를 가진다. 원시 숫자를 그대로 공급량에 더하지 않고 다음처럼 정규화한다.

```text
google_footprint = log10(user_result_count + 1)
```

그 후 `query_type`, 검색 문구 형태, 언어, 산업군별 누적 관측치 안에서 백분위로 변환한다.

```text
footprint_percentile = 같은 조건 관측치 중 상대적 위치
```

초기 데이터가 부족할 때는 고정 구간을 임시 사용한다.

| 표시 결과 수 | 임시 footprint 등급 |
|---:|---|
| 0~99 | 매우 낮음 |
| 100~999 | 낮음 |
| 1,000~9,999 | 중간 |
| 10,000~99,999 | 높음 |
| 100,000 이상 | 매우 높음 |

이 구간은 실제 관측 데이터가 30건 이상 쌓이면 프로젝트 자체 백분위 기준으로 교체한다.

`top_results_relevant`가 입력된 경우에는 표시 결과 수보다 더 높은 신뢰도를 부여한다. 표시 결과가 많더라도 상위 결과에서 관련 SaaS가 거의 없으면 검색 노이즈로 분류한다.

## 4.6 AI 예측과 사람 관측 비교

AI는 검증 큐를 생성할 때 다음을 미리 예측한다.

```text
predicted_result_band:
VERY_LOW
LOW
MEDIUM
HIGH
VERY_HIGH
```

사람 입력 후 실제 footprint 등급과 비교해 오차를 기록한다.

| 비교 결과 | 오차 유형 |
|---|---|
| 실제 등급이 예측보다 2단계 이상 높음 | `SUPPLY_UNDERESTIMATED` |
| 실제 등급이 예측보다 2단계 이상 낮음 | `SUPPLY_OVERESTIMATED` |
| 결과 수는 높지만 관련 SaaS 비율이 낮음 | `QUERY_NOISE_HIGH` |
| 결과 수는 낮지만 관련 SaaS 비율이 높음 | `NICHE_COMPETITION_DENSE` |
| 예측과 관측이 유사 | `CALIBRATED` |

`TITLE_QUERY`에는 별도 오차 유형을 사용한다.

| 비교 결과 | 제목 오차 유형 |
|---|---|
| 예상보다 결과가 매우 많음 | `TITLE_COLLISION_UNDERESTIMATED` |
| 예상보다 결과가 매우 적음 | `TITLE_COLLISION_OVERESTIMATED` |
| 상위 결과에 동일 제품·브랜드 존재 | `TITLE_BRAND_CONFLICT` |
| 일반 단어 조합만 많고 제품 충돌 없음 | `TITLE_GENERIC_PHRASE` |
| 결과가 적고 직접 충돌 없음 | `TITLE_CLEAR` |

## 4.7 공급 점수 보정

사람 입력 하나로 자동 공급 점수를 크게 뒤집지 않는다. 보정은 누적 표본 수와 일관성에 따라 제한적으로 적용한다.

문제별 사람 검증 신뢰도:

```text
human_weight =
min(0.25, valid_market_observations / 20 × 0.25)
```

- 관측 1건: 최대 1.25% 반영
- 관측 5건: 최대 6.25% 반영
- 관측 10건: 최대 12.5% 반영
- 관측 20건 이상: 최대 25% 반영

보정 개념:

```text
adjusted_supply_scarcity =
base_supply_scarcity × (1 - human_weight)
+ human_google_scarcity × human_weight
```

단, `top_results_relevant`가 없고 표시 결과 수만 입력된 관측은 최대 반영 비중을 절반으로 제한한다.

```text
표시 결과 수만 있음: 최대 12.5%
관련 결과 수까지 있음: 최대 25%
```

사람 검증이 공급 과소추정을 반복적으로 보여주면 다음을 자동 수행한다.

- 해당 산업의 공급 동의어 확장
- 공급 검색어 템플릿 추가
- Common Crawl·HN·GitHub 공급 후보 재조사
- `S`등급을 일시 보류하고 재검증
- 공급 누락 이슈 생성

사람 검증이 공급 과대추정을 반복적으로 보여주면 다음을 수행한다.

- 검색 노이즈를 만드는 일반 단어를 검색식에서 제외
- 직접·부분·범용 제품 분류 기준 재검토
- 범용 도구 가중치 축소 실험
- 희소성 점수 복원 가능성 검토

## 4.8 제목 충돌 점수 보정

`TITLE_QUERY` 결과는 공급 부족 점수와 분리해 제목 품질 점수에 반영한다.

제목별 추가 필드:

```text
google_title_footprint
google_title_collision_class
human_title_validation_count
title_collision_adjustment
```

기본 처리:

- 정확한 따옴표 검색 결과가 매우 적고 동일 제품이 없으면 신규성 가점
- 결과가 많아도 일반 문장·인명·비제품 사용만 있으면 중립
- 동일 SaaS·앱·회사명이 상위 결과에 있으면 강한 감점 또는 탈락
- 사용자가 메모로 직접 충돌을 표시하면 `TITLE_BRAND_CONFLICT`로 즉시 재검토

Google 결과 수만으로 상표권 사용 가능성을 확정하지 않는다. 이 데이터는 이름 혼잡도와 추가 조사 우선순위를 정하는 용도로만 사용한다.

## 4.9 누적 자기개선

매 실행 후 다음 지표를 갱신한다.

```text
전체 사람 검증 수
MARKET_QUERY 검증 수
TITLE_QUERY 검증 수
산업별 검증 수
공급 과소추정률
공급 과대추정률
제목 충돌 과소추정률
검색식별 노이즈율
사람 검증 전후 공급 등급 변경 수
사람 검증으로 탈락한 제목 수
```

저장 위치:

```text
/memory/human_feedback/google_calibration_metrics.json
```

검증 데이터가 충분히 쌓이면 다음 항목을 학습 자산으로 승격한다.

- 산업별 공급 검색 동의어
- 검색 노이즈가 낮은 검색식
- 공급 과소추정이 자주 발생하는 시장 유형
- 제목 충돌이 잦은 단어 조합
- Google footprint와 실제 발견 제품 수의 경험적 관계
- 사람 검증이 필요한 우선순위 규칙

검증된 규칙은 다음에 반영한다.

```text
/memory/human_feedback/google_query_playbook.md
/memory/PROJECT_PLAYBOOK.md
/config/project.yaml
/scripts/collect_supply_candidates.py
/scripts/score_opportunities.py
/scripts/dedupe_titles.py
```

## 4.10 편향 방지

사용자는 임의로 일부 항목만 검사하므로 사람이 선택한 표본이 전체 시장을 대표한다고 가정하지 않는다.

반드시 다음을 지킨다.

- 사람 검증 데이터가 없는 산업에 기존 보정값을 무리하게 전파하지 않는다.
- 검증한 항목과 비슷한 산업·검색식에만 보정을 우선 적용한다.
- 사람 검증 여부를 신뢰도 필드에 명시한다.
- 검증 표본 수가 적으면 `PROVISIONAL` 상태로 유지한다.
- 공급 점수 보정 상한은 25%로 제한한다.
- 단일 관측치로 점수 기준, 에이전트 지침 또는 플레이북을 영구 변경하지 않는다.
- 동일 규칙이 최소 5건 이상에서 반복되고 QA를 통과해야 검증 노하우로 승격한다.

## 4.11 처리 상태

| 상태 | 의미 |
|---|---|
| `QUEUED` | 사용자 검증 추천 목록에 포함 |
| `PARTIALLY_FILLED` | 일부 필드만 입력됨 |
| `IMPORTED` | 원장에 정상 반영됨 |
| `DUPLICATE_REJECTED` | 동일 관측 중복 |
| `INVALID` | 숫자·날짜·ID 형식 오류 |
| `PROVISIONAL` | 표본이 적어 임시 보정만 적용 |
| `CALIBRATED` | 충분한 검증으로 보정 규칙 확립 |
| `RESEARCH_REQUIRED` | AI 예측과 사람 관측 차이가 커서 공급 재조사 필요 |

---
