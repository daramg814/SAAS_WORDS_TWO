# ACTIVE ISSUES

## BOOTSTRAP-001 — 핵심 데이터 파이프라인 미구현
- 상태: RESOLVED (구현 완료, 아래 DEMAND-001로 이어짐)
- 영향: 1차 구현 전체(수집·필터·군집화·수요·공급·기회·제목·발행·구글보정·핸드오프/Git)를
  실제 동작 코드로 구현하고 240개 자동화 테스트로 검증함. 상세: git 로그
  (`chore: import ChatGPT-authored bootstrap scaffold` 이후 전체 커밋).
- 완료 조건 충족 여부: 코드 경로는 전체 PASS. 실제 QA 20개 달성은 DEMAND-001 참조.

## DEMAND-001 — HN 단독 1차 데이터원으로는 수요 관문(독립 사용자 5명) 통과 군집이 사실상 없음
- 상태: OPEN
- 증상: `python run.py --mode qa --target-count 20`을 실제 HN 데이터(검색 수집 포함
  4,585개 후보 군집)로 실행한 결과, 독립 사용자 수 상위 16개 군집을 모두 직접 검토했으나
  전부 (a) HN 관용구("feature requests welcome!", "way too complicated"가 서로 무관한
  수십 개 주제에 붙은 경우) 또는 (b) "How do you manage X/What do you use for X" 질문
  템플릿(X가 매번 다른 주제: dotfiles, 세금, 가족사, 탭 관리 등)이었다. 동일한 구체적
  SaaS 문제를 5명 이상이 독립적으로 언급한 군집은 하나도 발견하지 못했다.
- 영향: `extract_and_cluster_problems` 판정에서 전체 군집을 정직하게 REJECT하면
  `problems`/`opportunities`/`titles`가 모두 0건이 되어 `generate_and_review_titles`
  단계가 `RetryRequired`로 정지한다(run_id `QA-20260810-215254-KST`, 최종 상태
  `RETRYING`). 파이프라인 코드 자체는 소스 접근성→수집→필터→군집화→수요점수까지
  전 구간이 실제로 정상 동작했고, 운영 `output/history/words.txt`와
  `output/generated/`는 전혀 건드리지 않았다(설계된 "실패 시 미발행" 요건 충족 확인).
- 오류 시그니처: 없음(코드 예외 아님). 정상적인 `RETRYING` 종료 코드 4.
- 시도:
  1. `search_hits_per_pattern`을 40→300→1000(Algolia 최대)으로, 후보 문장을
     332→1,495→4,133개로 확대. 군집 품질은 개선되지 않음(볼륨이 늘수록 다양한
     무관 주제만 늘어남).
  2. 1차 군집화 알고리즘의 트리거 문구 제거 로직으로 명백한 오탐(공유 질문 템플릿)은
     줄였으나, 근본적으로 서로 다른 주제가 우연히 같은 관용구를 공유하는 경우까지
     걸러내지는 못함(이는 애초에 애매 군집으로 표시되어 AI 판정으로 넘어가도록 설계됨 — 설계대로 동작).
- 실패 이유(근본 원인): 문자열 유사도 1차 군집화는 "표현이 비슷한 문장"만 묶을 수 있고,
  서로 다른 표현으로 같은 문제를 말하는 진짜 반복 사례는 애초에 묶이지 않는다(재현율
  한계, 설계상 알려진 트레이드오프). 더 근본적으로는 Hacker News라는 단일 데이터원의
  특성상 폭넓고 기술적인 담론이 우세하며, 좁고 구체적인 업무 문제가 5명 이상에게서
  독립적으로 반복 언급될 확률이 낮다.
- 최종 해결: 미해결. 사용자와 협의해 "정직하게 진행 후 RETRYING 보고"로 결정(가짜
  판정으로 수량을 채우지 않음 — CLAUDE.md 데이터 무결성 원칙 우선).
- 검증: 코드 경로 자체는 240개 pytest + 실제 네트워크 실행으로 검증 완료. 수요
  데이터 부족은 코드 결함이 아니라 데이터 가용성 문제임을 확인.
- 다음 조치(2026-08-10, 사용자 확정): **A안부터 착수** — 2차 데이터원(Stack Exchange
  덤프 또는 GH Archive) 활성화. `sources.yaml`에 이미 게이트로 준비되어 있음. 좁고
  반복적인 기술 질문이 HN보다 많을 가능성이 높다는 판단. A안 시도 후에도 부족하면
  B안(의미 기반/임베딩 군집화, `docs/implementation/14-implementation-roadmap.md`
  3차 개선 항목)을 고려. "5명" 기준 완화는 검토 대상 아님(CLAUDE.md 12항 위반).
  상세 절차는 `memory/HANDOFF.md` §5 참고.
- 수정 파일: 해당 없음(코드 결함 아님). 관련 실행 기록:
  `output/runs/QA-20260810-215254-KST/`, `output/qa/QA-20260810-215254-KST/`.
