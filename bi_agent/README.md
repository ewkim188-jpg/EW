# BI봇 — BI 분석 설계 에이전트

오너(제약 BI 담당자) 전용. 현업 요청을 받으면 6단계를 거쳐 **BI 분석 명세와 산출물**을 만들고,
그 과정에서 **오너가 분석력 있고 인사이트 있는 BI 전문가로 크도록** 코칭한다.
화면 흐름은 aSSIST "Ideation Agent"(아이디어 발굴 → 심층 인터뷰 → 다각도 리서치 → 명세 & 비판 → 최종 승인 → 보고서 완성)를 따랐다.

역할 경계: **BI봇은 무엇을, 어떤 기준으로 볼지 정한다. 계산은 이데, 배분은 오케스트레이터, 발행 직전 검수는 리뷰봇·컴봇이 한다.**

## 실행

```bash
cd bi_agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # 또는 `ant auth login`
uvicorn server:app --port 8000      # 브라우저에서 http://localhost:8000
# 외부 웹 검색을 막아야 하면: BI_WEB_SEARCH=0 uvicorn server:app --port 8000
```

## 6단계

| 단계 | 에이전트 (일하는 패턴) | 오너가 하는 일 |
|---|---|---|
| 1 요청 접수 | (CaseMaker: 연습용 가상 요청) | 요청자·의사결정자·요청 원문·기한, 실전/훈련 선택 |
| 2 진단 인터뷰 | Interviewer (반복 패턴) ⇄ Scout (도구 사용·빠른 탐색) | 질문 3개에 답. 가설 신뢰도 80% 이상이면 자동으로 다음 단계 (최대 3라운드) |
| 3 다각도 리서치 | Researcher × 3 (병렬 처리 + 검색 도구), DocReader (그라운딩) | 데이터·지표 / 시장·경쟁 이벤트 / 분석 방법·벤치마크 근거 선택, 트랙별 재조사(최대 2회), **사내 자료 올리기**(PDF·TXT·MD·CSV 최대 5개), 메모 |
| 4 명세 & 비판 | Planner (계층적 작업 분해) → Critic (검토·비판 패턴) | 검증단(경영진·현업·데이터/컴플라이언스) 비판 질문에 방어 → 기준 통과(세 관점 모두 4점 이상)까지 반복 (최대 3회) |
| 5 최종 승인 | — (사람 승인 지점) | 명세·가드레일 확인 체크(필수), 산출물 형태 선택 |
| 6 산출물 완성 | Reporter ∥ Architect ∥ Coach (병렬) | 고른 산출물 + 오케스트레이터 요청서가 함께 나온다. 다른 형태 추가 생성, MD·HTML 다운로드 |

오른쪽 **실행 로그(LIVE TRACE)**에 에이전트·패턴·걸린 ms가 쌓인다. 패턴 설명은 `agents.py`의 `TRACE_META` 한곳에서 관리한다.
(참조: Ideation Agent 교안 p.17 "블랙박스" 문제 — 에이전트끼리 무슨 일이 일어나는지 보이게 만드는 장치)

## 코칭 장치

- **훈련 모드**: 추천 답변·추천 방어 논리를 잠가 둔다. 직접 15자 이상 쓰면 열린다. "모르겠어요·보기"나 "추천대로"를 쓴 답은 표시되어 Coach 평가에서 빠진다.
- **Coach** (6단계): 6가지 능력(질문·데이터·가설·소왓·경영진·도메인) 점수, 잘한 점, "당신의 문장 → 한 단계 위 버전", 다음에 해 볼 것.
- **성장 기록**: `memory/growth_log.jsonl`. 최근 30개가 Interviewer·Coach·CaseMaker에 들어가 약점을 겨냥한다.
- **케이스 연습**: CaseMaker가 함정 하나를 숨긴 가상 요청을 만든다. 함정은 6단계에서 공개된다.

## 믿을 수 있게 하는 장치

- 에이전트 결과는 `strict` 도구로 받아 스키마가 보장된다.
- 출처 URL이 실제 검색 결과에 없으면 ⚠ 표시 (지어낸 출처 걸러내기).
- Critic이 PASS라고 해도 3점 이하 관점이 있으면 코드가 FAIL로 바꾼다.
- Critic은 Planner의 대화를 보지 못하고 명세만 본다 (작성자 편향 제거).
- 케이스 함정은 끝날 때까지 에이전트·화면에 숨긴다.
- 올린 사내 문서는 원문을 저장하지 않고 DocReader 요약만 남긴다. 문서 안의 지시문은 따르지 않도록 지시하고(주입 방어), 개인 식별 정보는 요약에 옮기지 않는다. 사내 문서 내용은 Claude API로 전송된다는 점에 유의한다.

## 파일

| 파일 | 내용 |
|---|---|
| `prompts/bi_agent_prompt.md` | 오너가 준 원본 프롬프트. 수정하지 않는다 (지식·원칙 블록만 공통 배경으로 쓴다) |
| `prompts/agents.md` | 에이전트별 역할 프롬프트 (`<interviewer>`, `<planner>` 등) |
| `company_context.md` | 회사·제품 정보 |
| `agents.py` | 에이전트 실행기, 결과 스키마 |
| `workflow.py` | 6단계 진행과 상태 (반복·병렬·순차 처리가 여기 있다) |
| `server.py` / `static/index.html` | 웹 화면 |
| `tools.py` | 문서 저장, 오케스트레이터 요청서, 성장 기록 |

## 저장 위치 (저장소에 올라가지 않음)

- `outputs/projects/<id>.json` 건별 전체 기록, `outputs/docs/` 산출물, `outputs/handoffs/` 오케스트레이터 요청서
- `memory/growth_log.jsonl` 성장 기록 (손으로 고치거나 지워도 된다)

## 비용 감각 (한 건 기준)

인터뷰 2~3라운드(Interviewer·Scout) + 리서치 3 + 명세·비판 2~6 + 산출물·코칭 2 ≈ Claude 호출 10~15회.
Interviewer·Planner·Critic·Coach는 effort `high`, Researcher·Reporter는 `medium`, Scout는 `low`.
