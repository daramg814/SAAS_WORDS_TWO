# 단어 생성 능력의 지속적 향상 구조

**작성일: 2026-08-18**  
**배경: 10,000 원시 후보 중 12개 통과 (0.12%) → 통과율 극도로 낮음**

---

## ⚠️ 2026-08-18 더블체크 개정 (구현 반영 완료 — 이 절이 아래 초안보다 우선한다)

초안 작성 후 누적 캐시 30,263건을 실측 분석해 더블체크한 결과, 아래 초안의
가정 중 세 가지를 수정하고 그 수정안대로 **구현을 완료**했다:

1. **기준선 수정**: 통과율 기준선은 0.12%가 아니라 **누적 0.70%(212/30,263)**다.
   0.12%는 정적 단어뱅크 소진 직후 "찌꺼기 조합 + 신규 확장 단어"로만 돈
   라운드의 일회성 저점이다.
2. **핵심 레버 수정**: 초안의 "스코어 기반 생성 순서 변경"(§3.1, §4.1-3)은
   효과가 거의 없다 — 모든 조합은 정확히 한 번만 시도되므로 순서를 바꿔도 최종
   통과 수는 같다. 진짜 레버는 ① **확장 제안 조종**(소진 이후 신규 생성은
   사실상 전부 `expand_word_bank` 제안에서 나오므로, 제안 시점에 실측 승자
   패턴을 강제) ② **죽은 기능어 은퇴**(통과 0/시도 300+ 기능어 28개에 전체 API
   조회의 32%가 낭비됨 — 은퇴시키면 즉시 회수)다.
3. **목표 하향**: 초안의 "3~5% 안정화"는 낙관적이다. 최상위 5개 기능어(Portal/
   Map/Hub/Point/Station)만 모아도 3.72%이므로 **현실적 목표는 1.5~2.5%**다.

**실측 요지**: 기능어가 승부를 결정한다. 실제 검색되는 구체적 명사(Portal
5.85%, Map 5.68%, Hub 2.75%)는 통과하고, SaaS 전문용어풍 합성어(Suite/Sync/
Dashboard/Toolkit/Workbench 등 28개)는 각 300회+ 시도에 통과 0건으로 전멸했다.

**구현된 것(같은 날 배치)**:
- `src/saas_words_two/word_performance.py` — 통계·리포트·은퇴 목록(순수 코드)
- `config/retired_function_words.csv` — 은퇴 기능어 28개 seed(실측 근거 포함),
  `_merged_word_bank`가 병합 풀에서 자동 제외, `_consume_word_bank_expansion`이
  재제안을 차단
- `output/_pipeline/analysis/word_performance_latest.md` — 매 라운드 종료 시
  자동 갱신되는 성과 리포트
- `expand_word_bank` 판정 요청에 기능어 실측 성과 요약(`function_word_performance`)
  직접 포함 + 승자 패턴 준수/은퇴 패턴 금지 지침
- `tools/analyze_word_performance.py` — 수동 분석·`--apply-retirement`
- 게이트 불변 원칙은 초안 그대로 유지(§6.1)

아래 초안은 역사적 기록으로 보존한다. 초안과 이 개정이 충돌하면 이 개정을 따른다.

---

## ⚠️ 2026-08-19 추가 개정 — 라운드별 정체 점검 루틴

사용자가 "라운드가 반복 진행되는데 단어 생성 능력이 정체되고 있는 건 아닌지"를
매 라운드 끝날 때마다 자동으로 더블체크하고 싶다고 요청해 구현했다. 위의 학습
루프(은퇴 목록·확장 판정 강화)가 "다음 라운드를 어떻게 더 잘 만들지"를 다뤘다면,
이 절은 "그게 실제로 먹히고 있는지를 어떻게 매번 확인할지"를 다룬다.

**핵심 설계**: 기존 성과 리포트(§ 위)는 누적 스냅샷이라 추세를 알 수 없었다 -
"지금까지 총 0.70% 통과"만 알 수 있지 "최근 라운드가 예전보다 나아지고 있는지"는
알 수 없었다. `output/_pipeline/analysis/round_history.csv`가 라운드마다 한 줄씩
쌓이는 이력을 추가하고, `word_performance.detect_stagnation`이 최근 구간(누적
생성 500개 이상)과 그 직전 구간의 통과율을 비교해 `improving`/`stagnant`(상대변화
±10% 이내)/`declining`을 판정한다. 500개·±10% 임계값은 노이즈(작은 표본에서 통과
1건 차이가 통과율을 크게 흔드는 것)를 실제 추세와 혼동하지 않기 위한 것이다.

**실행 시점**: `_stage_update_memory_and_git_checkpoint`(라운드 완료가 확정되는
유일한 지점) — 여기서 이력에 append하고, 콘솔에 즉시 출력하고, HANDOFF.md에도
남긴다. run_id당 정확히 한 번만 기록되도록 중복 방지가 내장돼 있다(같은 run을
실수로 다시 `--resume`해도 이력이 중복되지 않음).

**이 루틴이 하지 않는 것**: `stagnant`/`declining` 판정이 나와도 원인을 스스로
진단하거나 대응책을 자동 실행하지 않는다 — 순수 수치 비교까지가 코드의 역할이고
(§5 역할 분리 표 참고), "왜 정체됐는지"(단어뱅크 확장 방향이 잘못됐는지, 은퇴
목록이 제대로 반영 안 됐는지 등)를 해석하는 것은 각 라운드 종료 후 현재 세션의
몫이다.

---

## ⚠️ 2026-08-19 세 번째 개정 — 단어 생성 노하우 누적 문서(구현 완료)

바로 위 절이 "정체됐는지 아는 방법"을 다뤘다면, 이 절은 **"그 해석 결과를 다음
세션이 다시 써먹을 수 있게 어떻게 남길지"**를 다룬다. 사용자가 실측으로 지적한
문제: 라운드별 정체 판정이 나와도 "왜 정체됐는지"에 대한 세션의 해석은 그
대화가 끝나면 사라진다 — `memory/PROJECT_PLAYBOOK.md`는 옛 수요/공급
파이프라인(`DEMAND-001`) 내용만 있고 단어 생성 관련 서술은 어디에도 없었다.
아래 §7 "메모리에 저장할 정보"의 초안(`memory/WORD_GENERATION_LEARNINGS.md`
제안)은 계획만 있고 실제로 만들어진 적이 없었다 — 이 개정에서 실제로 구현했다.

**구현된 것**:
- `memory/WORD_GENERATION_LEARNINGS.md` — "핵심 원칙"(지금 유효한 원칙 요약)
  + "라운드별 로그"(append-only 시행착오 기록) 두 섹션.
- `word_pipeline._load_word_generation_learnings_principles` — "핵심 원칙"
  섹션만 정규식으로 추출(다음 `## ` 헤딩 전까지). 본문 설명 중 헤딩과 같은
  문자열이 먼저 등장해도 오매칭되지 않도록 줄 시작(`^`) 앵커를 씀(실측으로
  발견된 버그를 고친 것).
- `word_pipeline._write_expand_word_bank_request`가 이 함수를 호출해
  `accumulated_learnings` 필드로 판정 요청에 **강제 주입** — `function_word_
  performance`와 동일한 구조적 전달 패턴. 세션이 memory 파일을 "읽으려는
  의지"에 기대지 않는다.
- 갱신은 여전히 세션의 몫이다(의미 해석이라 코드가 대신할 수 없음, §5 역할
  분리 표) — `expand_word_bank`가 있었던 라운드가 끝나면 그 결과를 로그에
  append하고 일반화되면 핵심 원칙도 갱신하도록 `_EXPAND_WORD_BANK_INSTRUCTIONS`
  에 명시적으로 지시문을 넣어뒀다.

**실측 검증**: 같은 세션 안에서 "니치 전문용어 + 근거 없는 신조어" 확장(통과율
2.59%→0.51% 급락) 후 원인을 이 문서에 기록하고, 다음 확장부터 "핵심 원칙"을
따라 확장했더니 통과율이 1.42%로 회복(9/10 신규 기능어 생존, `Code`가 통과율
7.78%로 전체 1위)됐다 — 상세 근거는 `WORD_GENERATION_LEARNINGS.md`의
라운드별 로그 참고.

---

## 1. 현재 상황 분석

### 1.1 병목 지점

```
단어뱅크 조합 (25,589개)
    ↓
신규 생성 (10,000개 원시)
    ↓
AI 판정 (의미 중복, 명확성, 상표 유사도) → ~95% 승인
    ↓
Keyword Planner 필터 (검색량 ≥1000, 경쟁지수=0 정확히) 
    ↓
최종 통과 (12개, 0.12%)  ← 여기서 극도로 필터됨
```

### 1.2 문제 정의

| 단계 | 통과율 | 문제 |
|------|--------|------|
| 신규 생성 → AI 판정 | ~95% | AI 판정이 너무 느슨함 |
| AI 판정 → Keyword Planner | 0.12% | **실제 시장 수요와 괴리** |
| 원인 | | AI가 본지 못하는 요소 있음 |

**핵심 문제:**
- AI는 "명확성"과 "중복"만 검사
- AI는 "검색 수요"를 모름
- AI는 "경쟁 상태"를 모름

---

## 2. 개선 전략: 학습 루프 구축

### 2.1 매 라운드 Feedback 수집

**단계 1: 분석 데이터 수집**

각 라운드 후:
```
├─ 통과 단어들 (12개)
│  ├─ 검색량 범위
│  ├─ 도메인어 특성
│  ├─ 기능어 특성
│  └─ 조합 패턴
├─ 거절 단어들 (9,988개)
│  ├─ 거절 이유별 분류
│  ├─ 검색량 분포
│  └─ 경쟁지수 분포
└─ 메타데이터
   ├─ 라운드 번호
   ├─ 실행 시각
   └─ 누적 통과율 추이
```

### 2.2 분석 차원

**2.2.1 단어 수준 분석**

```bash
# 통과 단어 분석
SELECT title, avg_monthly_searches, competition_index
FROM keyword_metrics_passed 
WHERE checked_at >= '2026-08-18'
ORDER BY avg_monthly_searches DESC
```

**패턴:**
- 통과한 단어들의 검색량 범위?
- 통과한 단어들의 도메인어/기능어 유형?
- 통과한 단어들의 음절 수, 발음?

**2.2.2 업계 수준 분석**

```bash
# 업계별 통과율
SELECT industry, COUNT(*) as total, 
       SUM(CASE WHEN gate_passed THEN 1 ELSE 0 END) as passed,
       ROUND(100.0 * SUM(CASE WHEN gate_passed THEN 1 ELSE 0 END) / COUNT(*), 2) as pass_rate
FROM generated_candidates gc
JOIN keyword_metrics_cache kmc ON gc.title = kmc.title
GROUP BY industry
ORDER BY pass_rate DESC
```

**질문:**
- 어느 업계가 잘 통과하는가?
- 어느 업계가 실패하는가?
- 왜 그런 차이가 나는가?

**2.2.3 도메인어-기능어 상호작용**

```bash
# 조합 수준 분석
SELECT domain_word, function_word, COUNT(*) as attempts,
       SUM(CASE WHEN gate_passed THEN 1 ELSE 0 END) as passed
FROM generated_candidates gc
JOIN keyword_metrics_cache kmc ON gc.title = kmc.title
GROUP BY domain_word, function_word
HAVING COUNT(*) >= 3
ORDER BY passed DESC
```

**발견:**
- 어떤 도메인어가 높은 검색량을 가지는가?
- 어떤 기능어가 수요를 끌어내는가?
- 특정 조합이 시너지를 내는가?

---

## 3. 구체적 개선 메커니즘

### 3.1 Word Bank 점수화 (Scoring)

**현재:** 정적 word_bank.py (고정)

**개선:** 동적 스코어 추가

```python
# config/word_scores.yaml (신규)
domain_words:
  furnace:
    base_score: 1.0
    pass_rate: 1.0  # 1/1 통과
    searches_avg: 3600
    frequency: 1
  
  heating:
    base_score: 0.7
    pass_rate: 0.0  # 0/5 통과
    searches_avg: 0
    frequency: 5

function_words:
  tracker:
    base_score: 1.0
    pass_rate: 0.15  # 3/20 통과
    avg_searches: 5000
    frequency: 20
  
  guide:
    base_score: 0.05
    pass_rate: 0.0  # 0/50 통과
    searches_avg: 100
    frequency: 50
```

**활용:**
- 생성 단계에서 높은 스코어 조합 우선 시도
- 낮은 스코어 단어 더 적게 사용

### 3.2 AI 판정 기준 진화 (Self-Refinement)

**현재 AI 판정:**
```
✓ 명확성 (어떤 SaaS인지 알 수 있나?)
✓ 의미 중복 (비슷한 단어가 있나?)
✓ 상표 유사 (유명 브랜드는 아닌가?)
✗ 검색 수요 (실제로 검색되는가?)
✗ 경쟁성 (경쟁이 0인가?)
```

**개선된 AI 판정:**
```
✓ 명확성
✓ 의미 중복
✓ 상표 유사
+ 예상 검색 수요 (Keyword Planner 기반 학습)
  - "Furnace Tracker" 형태는 높음
  - "Guide" 단어 조합은 낮음
+ 경쟁성 가능성
  - 검색량 높은 단어는 경쟁 가능성 높음
  - 검색량 낮은 단어는 경쟁이 없을 가능성 높음
```

### 3.3 라운드별 Feedback Loop

```
라운드 1: 10,000개 생성 → 12개 통과
   ↓ 분석
통과 단어 패턴 학습:
   - 도메인어: furnace(1/1), registration(2/10), burial(1/1)...
   - 기능어: tracker(3/20), journal(5/15), playbook(3/12)...
   - 업계: hvac_services, funeral_services, media_publishing
   - 검색량: 1,000 ~ 246,000

라운드 2: 개선된 조합 우선 시도
   - "고 스코어" 도메인어 + "고 스코어" 기능어 집중
   - 기존 통과 업계의 유사 단어 추가
   - 결과: 통과율 개선 기대

라운드 3: 더 나은 패턴 발견 및 적용
   (반복)
```

---

## 4. 구현 가능한 개선 안

### 4.1 즉시 가능 (코드 수정 없음)

1. **분석 리포트 생성**
   ```bash
   python tools/analyze_word_performance.py \
     --input output/deliverables/history/keyword_metrics_passed.csv \
     --output analysis/word_patterns.yaml
   ```
   
   출력: 도메인어/기능어별 통과율, 검색량 분포, 업계별 성과

2. **단어뱅크 수동 조정**
   - 통과율 0%인 단어 제거
   - 통과한 단어와 유사한 단어 추가
   - 거절된 단어의 이유 파악

3. **후보 생성 우선순위 변경**
   - 현재: 라운드-로빈 (균등)
   - 개선: 스코어 기반 (고점수 우선)

### 4.2 단기 가능 (1-2주)

1. **Word Scoring 시스템**
   ```yaml
   # config/word_scores.yaml
   domain_words:
     furnace: {score: 1.0, pass_count: 1, total_attempts: 1}
     heating: {score: 0.0, pass_count: 0, total_attempts: 5}
   ```

2. **선택적 생성 모드**
   ```bash
   # 높은 스코어 단어만 우선 사용
   python word_generation.py --scoring-mode high
   ```

3. **Performance Dashboard**
   - 라운드별 통과율 추이
   - 도메인어/기능어별 성과
   - 업계별 분석

### 4.3 중기 계획 (1개월)

1. **AI 판정 진화**
   - Keyword Planner 히스토리 학습
   - "통과 가능성" 예측 점수 추가
   - 생성 단계에서 활용

2. **자동 Word Bank 확장**
   - 통과한 단어와 유사한 단어 자동 제안
   - 거절된 단어의 분류 및 원인 학습

3. **A/B 테스트 프레임워크**
   - 전략 A: 현재 방식
   - 전략 B: 스코어 기반
   - 통과율 비교

---

## 5. 예상 개선 경로

```
현재:      0.12% (12/10,000)
↓
개선 1:   0.3% (30/10,000)  ← 단어뱅크 정제 + 스코어링
↓
개선 2:   0.8% (80/10,000)  ← AI 판정 진화
↓
개선 3:   2% (200/10,000)   ← 자동 확장 + 피드백 루프
↓
안정화:   3-5% (300-500/10,000) ← 최적 수렴
```

---

## 6. 주의사항

### 6.1 피해야 할 것

❌ **"통과율을 높이기 위해 필터를 약하게"**
- Keyword Planner 게이트는 절대 변경 금지
- 게이트는 "실제 시장 신호"임
- 약화 = 가짜 데이터 증가

❌ **"AI가 Keyword Planner 결과를 추측"**
- AI는 검색 데이터 없음
- 추측은 hallucination 유발
- 학습 데이터만 사용

### 6.2 해야 할 것

✅ **"실제 통과 데이터에서만 학습"**
- 과거 통과 단어 분석
- 과거 거절 단어 분석
- 통계적 패턴만 추출

✅ **"라운드마다 메트릭 추적"**
- 통과율 추이
- 도메인어/기능어 성과
- 업계별 동향

✅ **"점진적 개선"**
- 한 번에 하나씩 변경
- 각 변경의 효과 측정
- 검증 후 다음 단계

---

## 7. 메모리에 저장할 정보

**`memory/WORD_GENERATION_LEARNINGS.md` (신규)**

각 라운드 후:
```markdown
## 라운드 1 (2026-08-18)
- 생성: 10,000개
- 통과: 12개 (0.12%)
- 통과 단어: Furnace Tracker (3,600), Registration Journal (12,100)...
- 통과 업계: hvac_services (1), funeral_services (1), media_publishing (2)...
- 통과 기능어: tracker, journal, playbook, ops...
- 미통과 이유: 대부분 검색량 < 1,000 또는 경쟁지수 ≠ 0

## 라운드 2 (미래)
- 개선 전략: tracker/journal/playbook/ops 우선 시도
- 예상 효과: 통과율 0.3% 목표
```

---

## 8. 행동 계획

### 이번 주
- [ ] 분석 스크립트 작성 (`tools/analyze_word_performance.py`)
- [ ] 라운드 1 분석 리포트 생성
- [ ] 통과/거절 단어 패턴 식별

### 다음 주
- [ ] Word scoring 시스템 구현
- [ ] 라운드 2 생성 (스코어 기반)
- [ ] 통과율 개선 검증

### 4주 후
- [ ] AI 판정 진화 첫 버전
- [ ] Dashboard 구현
- [ ] 예상 0.3-0.5% 통과율 달성

---

## 9. 성공 메트릭

| 메트릭 | 목표 |
|--------|------|
| 라운드 2 통과율 | 0.3% 이상 |
| 라운드 3 통과율 | 0.5% 이상 |
| 최종 안정화 | 3-5% |
| 월간 통과 단어 | 300+ (10,000 × 3%) |

---

## 결론

**0.12% → 3-5% 개선은 가능합니다.**

핵심:
1. **Feedback Loop** (실제 통과 데이터에서만 학습)
2. **점진적 개선** (한 번에 하나씩)
3. **메트릭 추적** (진행 상황 확인)
4. **절대 금지** (게이트 약화, AI 추측)

다음 라운드부터 시작할 수 있습니다.
