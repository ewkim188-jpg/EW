---
title: 중증도 진단 (평가 체계)
type: concept
sources: [README.md, docs/developer_guide.md §6, prototype/therapy_ui_v4.html:2647-2700]
updated: 2026-10-23
---

# 중증도 진단 (평가 체계)

결과 `sev` = severe(중도) / moderate(중등도) / mild(경도). [[two-axis-system]]의 과제 조합에 쓰인다.

## 초기 평가 — 3가지 과제, 약 5분

| # | 과제 | 측정 영역 | 측정 항목 | 코드 |
|---|------|----------|----------|------|
| 1 | 모음 발성 (아·이·우) | 호흡 + 발성 | MPT, HNR/jitter/shimmer, F0, 음량 | `SEV_VOWELS` (예상 1분) |
| 2 | 퍼터커 DDK | 조음 | 음절 반복 속도, 정확도 | `SEV_DDK` |
| 3 | 단어 읽기 | 조음 + 운율 | 명료도, 조음 정확도, 말속도 | `SEV_WORDS` (**27개**) |

- 프로토타입 v4: 과제 목록 → 녹음 → 완료 뷰. 진행률 바, "시작하기/이어하기/결과 보기" 버튼. (커밋 01faefa, 3ca1719)
- 단어 읽기는 **텔레프롬프터** 모드로 단어를 크게 하나씩 보여준다. (커밋 ec923d0, `sev-rec-teleprompter`)
- 녹음 전 환경 세팅(캘리브레이션) 단계 있음 (`sevCalibrated`, 커밋 acb4726).

## 미니 평가 (매 세션 60초)

"아~~~" 3초, /퍼터커/ 5회, 기준 단어 5개 → 일별 추이 데이터.

## 재평가 주기

병기에 따라 2/4/8/12주 → [[golden-time]]

## 미해결

- 문서 "30개" vs 코드 27개
- 측정값 → 중증도 임계값 미정
→ [[open-questions]]
