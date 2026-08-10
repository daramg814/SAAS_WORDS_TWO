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
6. **Stack Exchange dump는 접근성 검사(PASS, 실제 다운로드·7z 해제·XML 파싱)를 거쳐
   `enabled: true`로 전환됨(2026-08-11, 설계서 대비 구현 감사 배치).** 대상 사이트는
   `softwarerecs.stackexchange.com`("Software Recommendations") — "이 작업에 어떤
   도구를 쓰나요" 질문이 사이트 전체 주제라 이 프로젝트의 수요 신호 패턴
   (`text_filter.PAIN_PATTERNS`)과 가장 잘 맞는 사이트를 의도적으로 선택했다(전체 SE
   네트워크가 아닌 "선택 사이트" 하나라는 3.2절 원문 의도 그대로).
   7z 해제를 위해 표준 라이브러리로 해결할 수 없어 `py7zr`(순수 파이썬, LGPL-2.1+,
   활발히 유지보수됨, 월 1~200만 다운로드)을 신규 의존성으로 추가함
   (`pyproject.toml` 주석에 동일 근거 기록). `Posts.xml`만 스트리밍 파싱하며
   (`ET.iterparse` + `elem.clear()`, 사이트 전체를 메모리에 올리지 않음), Question/Answer
   두 PostTypeId만 `hn_items`(`source='stack_exchange'`)에 정규화해 저장한다. 원문 Post
   Id는 사이트별로 작고 겹칠 수 있어 `9` + 3자리 사이트 코드 + 8자리 zero-pad Post Id로
   구성한 12자리 id로 재매핑해 HN(수천만대)·GH Archive(수십억대) id 범위와 충돌하지
   않게 했다(`stack_exchange_client.make_item_id`). 덤프는 정적 스냅샷이라 매 실행 재
   다운로드하지 않고 `data/raw/stack_exchange/`에 캐시하며, 이미 처리한 Post Id까지는
   커서로 건너뛴다(`collection.py::run_stack_exchange_collection`).
7. **npm Registry는 접근성 검사(PASS, 실제 검색 API 호출)를 거쳐 `enabled: true`로
   전환됨(2026-08-11).** 공식 검색 API(`registry.npmjs.org/-/v1/search`, 키·로그인
   불필요, npmjs.com 자체 검색창과 동일 엔드포인트)를 사용한다. 수요가 아닌 공급
   보조 데이터원이라(3.2절 "개발자 도구·오픈소스 대체재 공급 보조") 데이터원 접근성
   검사(`collection.run_access_test`)에서는 검증만 하고, 실제 수집은
   `scripts/collect_supply_candidates.py`가 수요를 통과한 문제별로 npm 패키지를
   검색해 공급 후보로 추가하는 방식으로 이루어진다(HN Show/mention, GH Archive
   mention과 동일하게 넓게 모으고 관련성 판정은 기존 활성 신호 검증 판정 단계에
   맡긴다 — "이게 개발자 문제인가"를 코드가 미리 분류하지 않는다).
8. **Common Crawl은 접근성 검사(PASS, 실제 CDX 조회·WARC range 요청·HTML 추출)를
   거쳐 `enabled: true`로 전환됨(2026-08-11).** 공식 CDX 인덱스(`index.commoncrawl.org`)와
   WARC 데이터(`data.commoncrawl.org`)만 사용하며, 키·로그인 불필요. **CLAUDE.md 4항·
   3.1절 원문 그대로 "이미 확보한 후보 도메인의 기능·가격·활성 상태 보강에만" 사용하고
   Common Crawl 전체를 검색하지 않는다** — `collect_supply_candidates.py`의
   `enrich_with_common_crawl()`이 이미 `supply_candidates`에 있는 도메인만 대상으로
   최신 크롤(`collinfo.json`으로 매번 자동 확인, 특정 CC-MAIN을 하드코딩하지 않음)에서
   캡처를 조회하고, HTTP Range 요청으로 WARC 레코드 일부만 가져와(전체 WARC 파일을
   내려받지 않음) HTML 본문을 텍스트로 추출한다(최대 3,000자, `text_filter.strip_html`
   재사용). 캡처가 없거나 실패해도 빈 문자열로 기록해 재시도하지 않으며(`NULL`=미시도,
   `""`=시도했지만 못 찾음), 추출된 발췌문은 `collect_and_verify_supply` 판정 단계의
   `kind=product` 항목에 `common_crawl_excerpt`로 포함되어 HN 텍스트를 보강하는
   추가 증거로만 쓰인다.
9. **공식 RSS·Atom 피드는 접근성 검사(PASS, 실제 피드 요청·XML 파싱)를 거쳐
   `enabled: true`로 전환됨(2026-08-11).** 3.2절 "고정 피드 URL"대로
   `config/sources.yaml`의 `official_feeds.feed_urls`에 명시된 목록만 수집하며
   (임의 발견·크롤링 없음), 초기 목록은 GitHub 공식 블로그·체인지로그
   (`github.blog/feed/`, `github.blog/changelog/feed/`) — 이 프로젝트 자체가
   특정 산업을 아직 선택하지 않은 상태(`input/brief.md`: "포함 시장: 별도 제한 없음")라
   실제로 동작하며 안정적인 공식 피드의 예시로 선택했다. 산업이 정해지면
   `feed_urls`를 그에 맞게 교체·추가할 것. RSS 2.0과 Atom 둘 다 표준 라이브러리
   `xml.etree.ElementTree`만으로 파싱 가능해(둘 다 순수 XML) 새 의존성이 필요
   없었다. 피드는 보통 최근 항목만 나열하므로 커서 없이 매 실행 전체를 다시
   가져오고, guid/id가 정수가 아니라 해시 기반 12자리 id(`8` 접두 — Stack Exchange의
   `9` 접두와 겹치지 않게)로 재매핑해 중복 방지에 사용한다(`rss_client.make_item_id`).

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
