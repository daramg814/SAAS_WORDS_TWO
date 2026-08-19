# WORD_GENERATION_LEARNINGS

**목적**: `expand_word_bank` 판정(단어뱅크 소진 시 새 도메인어/기능어 제안)이 매
라운드 반복될 때, 이전 라운드에서 무엇이 통했고 무엇이 안 통했는지를 세션이
매번 처음부터 다시 알아내지 않도록 누적 기록한다.

**작동 방식(2026-08-19 도입, 사용자 지시)**: 이 문서는 아래 두 섹션으로 나뉜다.
- **"핵심 원칙" 섹션**(바로 아래, 마크다운 헤딩 레벨 2): 지금 시점에 유효하다고
  확인된 원칙만 간결하게 유지한다. 이 섹션은 `word_pipeline.
  _write_expand_word_bank_request`가 **매번 코드로 강제 추출해서
  `expand_word_bank` 판정 요청(`accumulated_learnings` 필드)에 자동으로
  끼워 넣는다** — 세션이 이 문서를 "읽으려는 의지"에 기대지 않는다
  (`function_word_performance` 필드와 동일한 구조적 전달 패턴). 추출 코드는
  "핵심 원칙" 다음에 오는 헤딩 레벨 2까지를 그대로 가져가므로, 이 섹션의
  제목 줄 형식(`## 핵심 원칙`)을 바꾸지 말 것.
- **"라운드별 로그" 섹션**: 실제 있었던 일을 append-only로 남긴다. 원칙이 왜
  지금 형태인지 재구성할 근거가 필요할 때 여기를 본다.

**갱신 의무**: `expand_word_bank`로 새 단어를 제안한 라운드가 끝나(그 라운드의
Keyword Planner 결과와 `word_performance_latest.md`가 갱신되고 나면) 현재
세션이 이 문서에 로그를 append하고, 일반화 가능한 교훈이면 핵심 원칙도 갱신한다
— 코드가 대신 써주지 않는다(이건 의미 해석이라 CLAUDE.md §5 역할분리상 세션의
몫이다).

---

## 핵심 원칙

1. **기능어는 "SaaS스러운 신조어"가 아니라 일상에서 실제로 검색되는 짧고 흔한
   명사여야 한다.** 승자 실측(Code 7.78%, Status 5.65~6.97%, Rate 5.47%, Map
   5.45~5.70%, Portal 4.94~5.62%, List 4.40%)은 전부 이런 단어다. 반대로
   "그럴듯해 보이지만 근거 없이 지어낸" 카테고리 명사(Catalog, Checklist,
   Hotline, Queue, Book)는 300회 이상 시도에 통과 0건으로 즉시 은퇴 확정됐다.
   새 기능어를 제안하기 전에 "이게 실제로 사람들이 구글에 검색하는 흔한
   단어인가, 아니면 내가 의미상 그럴듯해서 지어낸 카테고리명인가"를 반드시
   자문할 것.
2. **니치 B2B 전문용어 업계(HVAC 부품명, 잠금장치 하드웨어명, 수영장 관리
   화학용어 등)로 도메인어를 확장하는 건 위험도가 높다.** 실측: HVAC/잠금장치/
   수영장관리/통역 업계에 니치 전문용어 75개를 확장한 라운드는 통과율
   0.51%로 급락했다. 반대로 이미 통과 실적이 검증된 업계(보험·부동산관리처럼
   일반인도 아는 개념)에 도메인어를 추가한 라운드는 통과율이 1.42%로
   회복됐다. 새 업계를 통째로 추가하기보다 **이미 성과가 좋은 업계의
   도메인어를 늘리는 쪽을 우선**할 것.
3. **실제 상표와 겹치는 도메인어를 조심할 것.** Freon(듀폰/케무어스
   냉매 상표), Toast(요식업 POS 브랜드), Compass(부동산 브랜드), Filter
   Forge(소프트웨어 제품명) 패턴이 review_titles 판정에서 반복적으로
   거절됐다 — `expand_word_bank` 단계에서부터 실제 브랜드명일 가능성이 있는
   단어는 피하는 게 review_titles 낭비를 줄인다.
4. **한 라운드에 제안하는 기능어들끼리 뜻이 겹치지 않게 할 것(2026-08-18에
   이미 확인된 원칙, 계속 유효).** 동의어 여러 개를 한 번에 넣으면 같은
   도메인어와 조합될 때마다 사실상 같은 문구가 반복돼 review_titles
   승인률이 떨어진다.
5. **`retired_function_words.csv`에 오른 패턴(SaaS 전문용어풍 합성어)은
   재제안하지 말 것** — 코드(`_consume_word_bank_expansion`)가 정확히 같은
   단어 재제안은 막아주지만, "같은 계열의 다른 단어"(예: Dashboard 대신
   Cockpit)는 막아주지 않는다. 은퇴 목록의 *패턴*을 학습해서 피할 것.

## 라운드별 로그

### RUN-20260819-201533-KST (2026-08-19, 도메인어 22 + 기능어 재사용 10)
- **제안**: property_management_services 도메인어 22개(Violation, Amenity,
  Utility, Complaint, Eviction, Renewal, Vendor, Assessment, Resident,
  Turnover, Occupant, Deposit, Repair, Vacancy, Notice, Warranty,
  Inspection, Maintenance, Landscaping, Snow, Roof, Elevator) + 이미
  있던 기능어 10개(Status/View/History/File/Level/Rate/Update/Digest/
  Feed/Draft) 재확인.
- **결과**: 신규생성 5,411개, AI승인 4,863개, KP통과 140개 → **통과율
  2.59%(이 문서 작성 시점 기준 역대 최고)**.
- **교훈**: 이미 검증된 소수 기능어를 그대로 재사용하고 도메인어만
  확장한 게 안전했다. property_management_services는 이후 라운드에서도
  Complaint(6%대)/Vacancy(5%대)/Notice(4%대) 등 꾸준히 상위권 도메인어를
  배출 — "한 업계를 깊게 파는" 전략이 통했다.

### RUN-20260819-205109-KST (2026-08-19, 도메인어 75 + 기능어 10 신규 발명)
- **제안**: hvac_services/locksmith_security_services 도메인어 각 20개,
  신규 업계 pool_maintenance_services 도메인어 20개, interpreter_
  translation_services 도메인어 15개(전부 니치 B2B 전문용어) + 신규
  기능어 10개(Summary, Timeline, Reminder, Checklist, Index, Ticket,
  Queue, Estimate, Catalog, Hotline — "범용적으로 결합될 것 같다"는
  직관만으로 발명, 실측 근거 없음).
- **결과**: 신규생성 10,000개, AI승인 9,140개, KP통과 51개 → **통과율
  0.51%(전 라운드 2.59% 대비 급락, -80.3%)**. 신규 기능어 10개 중
  **Catalog/Checklist/Hotline/Queue 4개가 300회+ 시도에 통과 0건으로
  즉시 은퇴 확정**.
- **원인**: (a) 기능어를 실측 승자 패턴이 아니라 "그럴듯한 카테고리명"으로
  발명했다. (b) 니치 전문용어 도메인어가 실제 검색 수요가 낮았다.
- **대응**: 은퇴 목록에 4개 추가 반영, 다음 확장부터 기능어는 반드시
  "일상에서 실제로 검색되는 짧고 흔한 명사"만, 도메인어는 니치 신규
  업계 대신 이미 성과 검증된 업계 위주로 전환.

### RUN-20260819-213339-KST (2026-08-19, 도메인어 35 + 기능어 10 — 원칙 반영 후)
- **제안**: 이미 성과가 좋았던 insurance 도메인어 20개(Endorsement,
  Reinsurance, Loss, Peril, Exclusion, Liability, Indemnity, Salvage,
  Settlement, Arbitration, Fraud, Lapse, Cancellation, Quote, Broker,
  Carrier, Beneficiary, Payout, Adjustment, Litigation) +
  property_management_services 15개(Lease, Parking, Pet, Balcony,
  Hallway, Fence, Pool, Clubhouse, Playground, Curb, Sidewalk,
  Mailroom, Storage, Fitness, Rooftop) + 기능어 10개(Order, Bill,
  Receipt, Code, List, Table, Book, Slip, Sample, Slot — 전부 짧고
  일상적인 명사로 재선정).
- **결과**: 신규생성 9,036개, AI승인 8,251개, KP통과 128개 → **통과율
  1.42%(전 라운드 0.51% 대비 +152.5%)**. 신규 기능어 10개 중 **9개
  생존, Book 1개만 은퇴**. `Code`는 통과율 7.78%(42/540)로 **전체
  기능어 중 1위**(기존 1위 Status를 앞지름), `List`(4.40%)·`Sample`
  (2.26%)도 상위 20위 진입.
- **교훈**: "일상적으로 검색되는 짧은 명사" 원칙과 "이미 검증된 업계
  확장" 원칙을 동시에 지켰을 때 은퇴율이 40%(4/10)→10%(1/10)로
  줄고 통과율이 3배 가까이 회복됐다. 다만 아직 RUN-20260819-201533의
  2.59%(역대 최고)는 회복하지 못했다 — 다음 확장에서 이 원칙을 더
  일관되게 유지하면서 관찰할 것.
