---
title: rPPG 기분(우울도) 측정
type: concept
sources: [docs/developer_guide.md §2.3]
updated: 2026-10-23
---

# rPPG 기분(우울도) 측정

카메라 기반 **비접촉 심박 측정**(remote photoplethysmography) → 심박변동성(HRV) → 우울/스트레스 수준 `dep`.
[[two-axis-system]]의 "기분 축" 입력. 마음이음(구 마음벗)의 핵심 기능.

## 흐름

안내 → "측정 시작" → 30초 카운트다운(실시간 BPM/HRV) → 결과 + 훈련 처방 미리보기

## 결과 매핑 (프로토타입 고정값)

| HRV | 심박 | dep | 훈련 |
|-----|------|-----|------|
| 18ms | 88bpm | high | 최소 과제 |
| 38ms | 74bpm | mid | 균형 |
| 58ms | 65bpm | low | 최대 도전 |

- 집중 모드: 측정은 하지만 결과는 항상 "정상 — 스트레스 없음", HRV 62ms 고정.
- 홈 "시작하기" = 상태측정 → 맞춤훈련 순차 진행 (`startDailyFlow`, prototype/therapy_ui_v4.html:3065).
- 결과 화면에 기분 자가선택 UI도 있음 (회색→파랑→초록 그라데이션, 커밋 52fdfe5).

## 미해결

실제 HRV 경계값·임상 근거 → [[open-questions]]
