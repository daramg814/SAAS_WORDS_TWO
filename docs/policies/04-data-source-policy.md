# 데이터원·접근성 정책

**목적:** 공개 데이터원을 단계적으로 활성화하고 실패를 전체 실행 실패로 과장하지 않으면서 근거 신뢰도를 보존한다.

## Claude Code 실행 지침
1. HN 공식 API만 기본 ENABLED로 시작한다.
2. 선택 데이터원은 샘플 다운로드·파싱·디스크·중복 방지 검사를 모두 통과한 뒤 활성화한다.
3. 실패 데이터원은 3회 지수 백오프 후 DISABLED 처리하고 보고서에 기록한다.
4. Common Crawl은 이미 확보한 후보 도메인의 기능·가격·활성 상태 보강에만 사용한다.
5. **GH Archive는 접근성 검사(PASS, `output/logs/access_test_report.md`)를 거쳐
   `config/sources.yaml`에서 `enabled: true`로 전환됨(2026-08-10, `DEMAND-001` A안).**
   IssuesEvent(action=opened)·IssueCommentEvent(action=created)만 정규화하며(PR 이벤트는
   미포함 — 8절 공급 파이프라인의 향후 과제), 봇 액터(`login`이 `[bot]`로 끝나는 계정)는
   독립 사용자 신호가 아니므로 제외한다. 정규화 결과는 기존 `hn_items` 테이블에
   `source='gh_archive'` 컬럼으로 구분되어 저장되며(HN 항목 id는 수천만대, GH 이슈/댓글
   entity id는 이미 수십억대라 충돌 가능성은 무시할 수 있는 수준 — `src/saas_words_two/db.py`
   COLUMN_MIGRATIONS 주석 참고), 이후 필터·군집·수요 점수 단계는 기존 로직을 그대로
   재사용한다. 수집 창은 `sources.yaml`의 `recent_days_max`(90일)를 하드 하한으로 삼아
   시간 단위 커서(`data/cache/gh_archive_last_hour.txt`)로 점진 수집한다
   (`src/saas_words_two/collection.py::run_gh_archive_collection`).

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 3. 데이터원 정책

## 3.1 기본 데이터원

### Hacker News 공식 API

용도:

- Ask HN의 문제·도구 추천 질문
- 일반 게시글과 댓글의 반복 업무 불만
- Show HN의 제품 공급 후보

특징:

- JSON
- API 키·로그인 불필요
- 마지막 수집 ID 이후만 증분 수집
- 원문은 로컬 DB에 저장하고 AI에는 후보 문장만 전달

기본 상태: `ENABLED`

## 3.2 선택 데이터원

다음 데이터원은 실제 Claude Code PC에서 접근성 시험을 통과한 경우에만 활성화한다.

| 데이터원 | 용도 | 활성 조건 |
|---|---|---|
| Stack Exchange 선택 사이트 덤프 | 장기간 반복 문제와 질문 | 파일 다운로드·7z 해제·XML 파싱 PASS |
| GH Archive 최근 30~90일 | 기능 요청·수작업·내부 스크립트 문제 | `.json.gz` 다운로드·해제·필터 PASS |
| Common Crawl | 이미 확보한 제품 도메인의 기능·가격·활성 상태 확인 | 인덱스 조회·부분 레코드 다운로드 PASS |
| npm Registry | 개발자 도구·오픈소스 대체재 공급 보조 | JSON 메타데이터·검색 PASS |
| 공식 RSS·Atom | 특정 산업의 공개 문제·공지 | 고정 피드 URL과 증분 수집 PASS |

## 3.3 접근성 테스트

프로젝트 최초 실행과 데이터원 설정 변경 시 다음을 수행한다.

```text
1. 최소 샘플 다운로드
2. 응답 형식 확인
3. 압축 해제 또는 JSON 파싱
4. 필요한 필드 추출
5. 디스크 사용량 확인
6. 재실행 시 중복 다운로드 방지 확인
7. 결과를 access_test_report.md에 기록
```

실패한 데이터원은 자동으로 `DISABLED` 처리하며 전체 파이프라인은 가능한 데이터원만으로 계속한다. 단, 독립 출처가 부족하면 결과 신뢰도를 낮춘다.

---
