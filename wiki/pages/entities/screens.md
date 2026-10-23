---
title: 프로토타입 화면 목록
type: entity
sources: [prototype/therapy_ui_v4.html, docs/developer_guide.md §2, §10]
updated: 2026-10-23
---

# 프로토타입 화면 목록 (therapy_ui_v4.html)

단일 HTML 파일. `goto('<id>')`로 `screen-<id>` 전환. 브라우저에서 바로 연다.

| 화면 id | 이름 | 내용 | 관련 |
|---------|------|------|------|
| splash | 스플래시 | 로고4(250px), "끊어진 말과 마음을 다시 잇다", 시작하기 | [[naming]] |
| setup | 초기 설정 | 성함 / 태어난 해 / 뇌졸중 진단일 → 병기 카드 | [[golden-time]] |
| eum | 앱 선택 | 말이음(블루) / 마음이음 카드 | [[naming]] |
| home | 말이음 홈 | 인사말, D-day, streak, 메뉴(중증도 진단·오늘 상태 측정·맞춤 훈련·자유 훈련·변화 추적), 시작하기 | |
| rppg | 오늘 상태 측정 | 30초 측정 → 우울도 | [[rppg]] |
| severity | 중증도 진단 | 과제 목록 → 녹음(텔레프롬프터) → 완료 | [[severity-assessment]] |
| tasks | 맞춤 훈련 목록 | COMBO 기반 과제 세트 | [[two-axis-system]] |
| all-ex | 자유 훈련 | 16개 운동 자유 선택 | [[exercises]] |
| run | 운동 실행 | Phase A 영상 → B/B-read/C | [[exercises]] |
| result | 세션 완료 | 결과, 레벨 변동, 스탬프, 가족 공유, 기분 선택 | [[rewards]] |

"변화 추적" 메뉴는 아직 연결된 화면이 없다.

## 프로토타입 컨트롤 바 (상단 검정 바)

우울(rPPG) 높음/보통/낮음 · 중증도 중도/중등도/경도 · 모드 통합/집중 · 레벨 Lv.1~4 · 화면 직접 이동

## 이전 버전

`therapy_ui.html` → `_v2` → `_v3` → `_v4`(현행). 스플래시 시안: `splash_variants.html`, `splash_v2_preview.html`.
디자인 규칙은 [[ui-guidelines]].
