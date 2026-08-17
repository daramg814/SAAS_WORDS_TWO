# 필수 회귀 사례

- QA 19개/21개 실패
- 추가 라운드 후 정확히 20개
- 데이터원 하나 실패
- 중복 게시글·동일 작성자 반복 댓글
- 직접·부분·범용 제품 혼합
- 폐업 제품
- 수요 높음+공급 많음 제외
- 수요 중간+공급 거의 없음 우선
- 공급 없음+수요 없음 제외
- 기회 하나 30% 초과 방지
- 운영 이력 정확/대소문자/역순 중복
- 게시 실패 롤백
- 세션 중단·재개
- Git push 실패
- Google 입력 일부 행/중복/잘못된 형식/다른 날짜
- 검색 노이즈, 공급 과소·과대, TITLE_QUERY 분리, 보정 전파 제한
- Keyword Planner 게이트: competition_index NULL(죽은 단어)은 avg_monthly_searches가
  아무리 높아도 항상 탈락(GKP-001)
- Keyword Planner 게이트: avg_monthly_searches가 임계값 미만이면 탈락
- Keyword Planner 게이트: 자격증명 누락/일일 예산 초과 시 가짜 통과 없이 RetryRequired
- Keyword Planner 게이트: 이미 탈락으로 캐시된 단어는 재생성/재조회하지 않음(exclude 편입)
- Keyword Planner 게이트: 이미 통과로 캐시된 단어는 API 재호출 없이 캐시값 재사용
