---
title: 미해결 질문 · 모순 목록
type: question
sources: [README.md, docs/developer_guide.md, prototype/therapy_ui_v4.html]
updated: 2026-10-23
---

# 미해결 질문 · 모순 목록

Ingest / Lint 중 발견한 모순과 결정이 필요한 사항. 해결되면 ~~취소선~~ 처리하고 결론과 날짜를 적는다.

## 모순 (문서 ↔ 코드)

1. **앱 이름** — 문서는 "다시나 / 말벗 / 마음벗", 프로토타입 v4는 "이음 / 말이음 / 마음이음". 어느 쪽이 공식인가? → [[naming]]
2. **단어읽기 개수** — README·가이드는 "단어읽기 30개", 코드 `SEV_WORDS_RAW`는 **27개**. (출처: prototype/therapy_ui_v4.html:2655) → [[severity-assessment]]
3. **프로젝트 구조** — README의 `create_appflow.js`, `EW_AppFlow.pptx`, `package.json`이 저장소에 없다.
4. **레벨 수** — 컨트롤 바는 Lv.1~4, 지속발성(#3)은 Lv.5까지 정의. 일괄 변경 시 Lv.5는 어떻게? → [[level-system]]
5. **레벨 판정 예시** — 가이드 §10은 "70% 확률로 성공"(시뮬레이션), §3.1은 "80% 규칙". 실제 앱의 성공 기준(측정값 ≥ 목표)이 확정 필요.

## 미정 사항

6. **안내 영상 누락** — #9 하품-한숨, #13 탭핑, #14 천천히읽기, #15 크게읽기는 영상 매핑이 없다. (출처: prototype/therapy_ui_v4.html:3304) → [[exercises]]
7. **중증도 판정 기준** — 측정값 → 중도/중등도/경도로 나누는 임계값이 문서에 없다. → [[severity-assessment]]
8. **rPPG 우울 판정** — HRV 3점 매핑(18/38/58ms)만 있고 경계값·임상 근거 미정. → [[rppg]]
9. **영역 코드 중복** — 가이드에서 호흡 영역과 발성 영역이 모두 `gb` 코드. 의도인가, 오타인가? (출처: developer_guide.md §2.5)
