---
title: 프로젝트 개요
type: overview
sources: [README.md, docs/developer_guide.md §1, prototype/therapy_ui_v4.html]
updated: 2026-10-23
---

# 프로젝트 개요

뇌졸중 후 **마비말장애(dysarthria)** 환자를 위한 AI 기반 재활 앱. 이름은 문서와 프로토타입에서 다르다 → [[naming]].

## 구성

| 하위 앱 | 역할 | 핵심 |
|--------|------|------|
| 말이음 (구 말벗) | 언어 재활 | 음성 분석 → 중증도 판정 → 16가지 운동 처방 |
| 마음이음 (구 마음벗) | 우울 케어 | [[rppg]] 비접촉 심박 → 우울도 → 훈련량 조절 |

## 핵심 설계 원칙 (출처: README.md)

1. **비판 금지** — 실패해도 부정적 피드백 없음
2. **속도보다 반복** — 매일 하는 것이 핵심
3. **감정 케어 필수** — 우울도에 따라 훈련량 자동 조절

## 주요 시스템

- [[two-axis-system]] — 기분(과제 수) × 레벨(난이도) 독립 조절
- [[level-system]] — 3연속 성공/실패로 자동 승급·강등
- [[severity-assessment]] — 모음·DDK·단어읽기로 중증도 판정
- [[golden-time]] — 발병일 기준 병기·D-day·재평가 주기
- [[exercises]] — 4대 영역 × 16가지 운동
- [[rewards]] — 명소 스탬프 + 카카오톡 가족 공유
- [[ui-guidelines]] — 50+ 사용자용 UI 규칙
- [[data-model]] — 백엔드용 Patient / Session / ExerciseProgress

## 구현 현황

- 현재 산출물은 **단일 HTML 프로토타입**(`prototype/therapy_ui_v4.html`)뿐. 화면 목록은 [[screens]].
- 측정값은 시뮬레이션이며 실제 음성 분석·rPPG는 미구현 (출처: developer_guide.md §3.4 주석, §10 "70% 확률로 성공").
- 이론적 배경은 [[theories]], 미해결 쟁점은 [[open-questions]].
