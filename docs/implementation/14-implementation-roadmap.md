# 폴더 구조·구현 우선순위

**목적:** 설계서가 요구한 파일 구조를 유지하며 1차 핵심 파이프라인부터 단계적으로 구현한다.

## Claude Code 실행 지침
1. 1차 구현은 HN→로컬 DB→문제→수요→공급→기회→제목 500→QA 20→Git 순서다.
2. 선택 데이터원은 접근성 QA를 통과한 순서대로 2차에 추가한다.
3. 3차 개선은 군집 정확도, 공급 누락, 신뢰도 보정, 제목 승인율, 검증된 플레이북에 한정한다.
4. 설계서에 명시된 경로를 임의로 이름 변경하지 않는다.

## 원본 설계 세부 규칙

> 아래 내용은 정보 손실 방지를 위해 원본 설계서의 해당 절을 그대로 보존한다.

# 12. 폴더 구조

```text
/project-root
├── CLAUDE.md
├── .claude
│   ├── settings.json
│   ├── skills
│   │   ├── source-access/SKILL.md
│   │   ├── demand-analysis/SKILL.md
│   │   ├── supply-analysis/SKILL.md
│   │   ├── title-generation/SKILL.md
│   │   ├── project-memory/SKILL.md
│   │   ├── git-checkpoint/SKILL.md
│   │   └── pipeline-qa/SKILL.md
│   └── agents
│       ├── main-orchestrator/AGENT.md
│       ├── opportunity-reviewer/AGENT.md
│       ├── human-feedback-calibrator/AGENT.md
│       ├── session-handoff-manager/AGENT.md
│       └── final-qa-runner/AGENT.md
├── config
│   ├── project.yaml
│   └── sources.yaml
├── input
│   ├── brief.md
│   ├── blocklist.txt
│   └── human_google_checks.csv
├── data
│   ├── raw
│   ├── cache
│   └── local.db
├── output
│   ├── generated
│   ├── final
│   ├── intermediate
│   ├── runs
│   ├── logs
│   ├── qa
│   ├── review
│   │   ├── google_validation_queue.csv
│   │   └── google_feedback_import_report.md
│   └── history
│       ├── words.txt
│       └── words.normalized.txt
├── memory
│   ├── KNOWLEDGE_MANIFEST.yaml
│   ├── HANDOFF.md
│   ├── ACTIVITY_LOG.jsonl
│   ├── ACTIVE_ISSUES.md
│   ├── PROJECT_PLAYBOOK.md
│   ├── QUALITY_TRENDS.jsonl
│   ├── GIT_CHECKPOINT.json
│   ├── human_feedback
│   │   ├── google_supply_observations.jsonl
│   │   ├── google_calibration_metrics.json
│   │   └── google_query_playbook.md
│   ├── issues
│   └── lessons
├── qa
│   ├── samples
│   └── regression
└── docs
    ├── data-source-policy.md
    ├── scoring-policy.md
    └── output-contract.md
```

---

# 17. 구현 우선순위

## 1차 구현

1. Hacker News 접근성 검사와 증분 수집
2. 로컬 SQLite 또는 DuckDB 적재
3. 후보 문제 문장 필터
4. 문제 구조 추출과 군집화
5. 수요 점수
6. HN Show와 댓글 기반 공급 후보
7. 활성 제품·공급 분류
8. 공급 희소성 등급과 희소성 우선 점수
9. 2단어 후보 반복 생성과 정확히 500개 승인
10. 운영 500개 생성 및 QA 20개 축소 실행·Git

## 2차 구현

접근성 QA를 통과한 순서대로 추가한다.

1. Stack Exchange 선택 사이트
2. GH Archive 최근 30~90일
3. npm Registry
4. Common Crawl 후보 도메인 검증
5. 산업별 공식 RSS

## 3차 개선

- 문제 군집 정확도 향상
- 공급 누락 감소
- 데이터원별 신뢰도 보정
- 제목 승인율 추세 분석
- 검증된 노하우만 플레이북 반영

---
