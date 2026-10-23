---
title: 데이터 모델
type: entity
sources: [docs/developer_guide.md §8]
updated: 2026-10-23
---

# 데이터 모델 (백엔드 설계안)

아직 백엔드 없음. 가이드의 설계안.

| 모델 | 주요 필드 | 관련 |
|------|----------|------|
| Patient | id, name, birthYear, strokeDate, severity, createdAt | [[golden-time]], [[severity-assessment]] |
| Session | id, patientId, date, mode, dep, sev, exercises[{exerciseId, level, measured, goal, success}], levelChanges[{exerciseId, from, to, dir}], stampId, completedAt | [[two-axis-system]], [[rewards]] |
| ExerciseProgress | patientId, exerciseId, currentLevel, streak, history[{date, measured, goal, success}] | [[level-system]] |

- `streak`은 프로토타입의 `lvStreak`(+N/-N)과 같은 의미.
- 추정: rPPG 원측정값(HRV, BPM)과 중증도 진단 원측정값을 저장할 모델이 아직 없다. 필요 시 추가.
