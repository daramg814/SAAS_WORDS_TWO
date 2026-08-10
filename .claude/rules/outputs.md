---
paths:
  - "output/**"
  - "scripts/publish_outputs.py"
  - "scripts/validate_outputs.py"
---
# 출력 규칙
- 부분 결과는 최종 경로와 운영 history에 쓰지 않는다.
- UTF-8 LF, 빈 줄 없음, 한 줄 한 제목을 유지한다.
- 게시 전 형식·중복·줄 수·blocklist·이력 중복을 모두 검사한다.
- QA 출력은 QA run 디렉토리 밖으로 나가지 않는다.
