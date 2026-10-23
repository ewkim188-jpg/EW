---
title: 2축 독립 조절 시스템
type: concept
sources: [README.md, docs/developer_guide.md §2.4, §3.5]
updated: 2026-10-23
---

# 2축 독립 조절 시스템

훈련을 **두 축으로 따로** 조절한다. 이 앱의 핵심 아이디어.

| 축 | 입력 | 조절 대상 | 관련 |
|----|------|----------|------|
| 기분 | [[rppg]] HRV → `dep` (high/mid/low) | **몇 가지** 할지 (3~9개) | |
| 난이도 | 운동 결과 누적 | **얼마나 어렵게** (Lv.1~5) | [[level-system]] |

- 우울 높은 날: 과제 3개만, 하지만 **레벨 목표는 유지**
- 그래도 우울 때문에 3회 연속 실패 → 자동 강등 (난이도 축이 스스로 흡수)

## 과제 조합 `COMBOS[dep + '-' + sev]` (출처: developer_guide.md §2.4)

`sev`는 [[severity-assessment]] 결과.

| dep \ sev | severe | moderate | mild |
|-----------|--------|----------|------|
| high | 3개, 5~7분 | 4개, 7~10분 | 4개, 8~10분 |
| mid | 5개, 10~13분 | 5개, 12~15분 | 6개, 13~15분 |
| low | 6개, 15~18분 | 7개, 18~20분 | 9개, 20~25분 |

**집중 모드** (`mode='focus'`): 우울 정상 전제, 중증도만 사용 — severe 16개(40~50분), moderate 12개, mild 9개.
→ 중증일수록 *더 많이* 하는 구조 (통합 모드와 반대 방향). 의도 확인 필요 시 [[open-questions]].

각 COMBO: `tag, strat, msg(격려), dur, ids[], results, resMsg, pct`.

## 이론 근거

인지부하이론, Yerkes-Dodson 법칙, 행동활성화이론 → [[theories]]
