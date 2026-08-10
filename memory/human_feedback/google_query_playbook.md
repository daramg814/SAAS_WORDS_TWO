# Google Query Playbook

## 상태
초기 `candidate` 규칙만 존재한다. 사용자 관측 최소 5건 반복과 QA를 통과하기 전 `validated`로 승격하지 않는다.

## 고정 규칙
- MARKET_QUERY와 TITLE_QUERY를 분리한다.
- 결과 수를 실제 제품 수로 치환하지 않는다.
- 관련 상위 결과 수가 있으면 더 높은 신뢰도를 부여한다.
- 사람이 검증하지 않은 산업에 보정값을 확장하지 않는다.
