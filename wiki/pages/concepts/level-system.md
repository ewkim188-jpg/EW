---
title: 레벨 시스템
type: concept
sources: [docs/developer_guide.md §3]
updated: 2026-10-23
---

# 레벨 시스템

운동별로 Lv.1~4(지속발성만 Lv.5)를 두고 자동 승급·강등한다. [[two-axis-system]]의 "난이도 축".

## 규칙 (Motor Learning Theory, Maas et al. 2008)

- **3회 연속 목표 달성 → 레벨업** (최대 레벨 미만일 때)
- **3회 연속 목표 실패 → 레벨다운** (Lv.1 초과일 때) + "괜찮아요, 천천히 다시 쌓아가요"
- 성공↔실패가 바뀌면 연속 카운트 리셋. 레벨 변경 후 카운트 0.

## 상태 변수

```javascript
LEVELS[exerciseId] = [{lv, goal, goalTxt, max, desc}, ...]
playerLvl[exerciseId] = 현재 레벨
lvStreak[exerciseId]  = +N(연속 성공) / -N(연속 실패)
```

Python으로 쓰면 (같은 로직):

```python
def check_level_change(ex_id, success):
    s = streak.get(ex_id, 0)
    streak[ex_id] = (s + 1 if s >= 0 else 1) if success else (s - 1 if s <= 0 else -1)
    if streak[ex_id] >= 3 and level[ex_id] < max_level(ex_id):
        level[ex_id] += 1; streak[ex_id] = 0      # 레벨업
    elif streak[ex_id] <= -3 and level[ex_id] > 1:
        level[ex_id] -= 1; streak[ex_id] = 0      # 레벨다운
```

## "낮을수록 좋은" 지표 주의

#6 피치조절(오차 Hz), #14 천천히읽기(어/분)는 **값이 작아야 성공**. 성공 판정 시 방향을 운동별로 둬야 한다.
운동별 레벨 목표는 [[exercises]].

## UI 표현 (출처: §7)

레벨업 토스트 = 주황 그라디언트, 레벨다운 = 보라, 2.5초. → [[ui-guidelines]]

## 미해결

컨트롤 바 Lv.1~4 vs #3 Lv.5, 성공 기준 확정 → [[open-questions]]
