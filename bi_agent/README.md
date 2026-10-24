# BI 에이전트

한국다이이찌산쿄(DSKR) BI 팀 전담 AI 에이전트입니다. `prompts/bi_agent_prompt.md`의 역할 정의(오너 모드 / 내부고객 모드, 7개 BI 업무 영역, 원칙)를 시스템 프롬프트로 씁니다.

**데이터는 직접 돌리지 않습니다.** 오너의 BI Agent Team에서 오케스트레이터 자리를 맡아, 문제를 정의하고 각 봇에 요청서를 넘긴 뒤 결과를 해석합니다.

```
질문 → [BI 에이전트] 가설 수립 → 요청서 ─┬→ 분석봇: 숫자 계산
                                      └→ 이데: 외부 정보 수집
       ← 결과 붙여넣기 → [BI 에이전트] 가설 판정·해석 → (전략봇·보고서봇)
       → 발행 게이트: 리뷰봇(정확성) → 컴봇(규제) → 발행
```

## 구성

| 파일 | 역할 |
|------|------|
| `agent.py` | CLI 대화 루프 (Claude API, 스트리밍, 도구 호출), 에이전트 팀 운영 지침 |
| `tools.py` | 도구 2개(`create_handoff` 요청서 생성, `save_output` 산출물 저장)와 **전문 에이전트 목록(`AGENTS`)** |
| `prompts/bi_agent_prompt.md` | 에이전트 역할·원칙 프롬프트 |
| `company_context.md` | 회사 고유 정보(제품 목록 등). 프롬프트의 `<company_context>`를 대체합니다 |
| `outputs/` | 산출물 폴더. `outputs/handoffs/`에 에이전트별 요청서가 쌓입니다 |

## 전문 에이전트 등록

`tools.py`의 `AGENTS`에 정의합니다. `role`이 비어 있는 에이전트에는 요청서를 만들지 않습니다.

| 이름 | 역할 |
|------|------|
| 이데 | 외부 정보 수집 (뉴스·학회·규제·경쟁사) — **[확인 필요]** 시장 시그널 페이지에는 data-analyst로 표기 |
| 분석봇 | 정량 분석 (실적·마켓셰어·포캐스팅 Gap) |
| 전략봇 | 전략·시사점 도출 |
| 보고서봇 | 보고서·브리핑·실행계획 작성 |
| 리뷰봇 | 정확성 게이트 (재검산·출처·논리) |
| 컴봇 (compliance-bot) | 규제 게이트 (허가사항·off-label·내부/외부 구분) |
| 비서봇 | **[역할 확인 필요]** |

출처: 'BI Agent Team' 구현 결과보고서(2026-07). 봇 정의는 `tools.py`의 `AGENTS`에서 바꿉니다.

## 실행

```bash
cd bi_agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python agent.py                  # 모드는 에이전트가 판단
python agent.py --mode owner     # 오너(BI 담당자) 모드
python agent.py --mode customer  # 내부고객 모드
```

대화 중 명령: `/exit` 종료 · `/reset` 초기화 · `/save` 대화를 `outputs/`에 저장 · `"""` 로 감싸서 여러 줄 입력 (봇 결과를 붙여넣을 때 사용)

## 사용 흐름 예시

1. `릭시아나 제네릭 진입 후 3개월 영향 보고 싶어` → BI 에이전트가 가설을 세우고 분석봇·이데 요청서를 만듭니다 (화면 출력 + `outputs/handoffs/` 저장).
2. 요청서를 각 봇에 전달하고, 받은 결과를 `"""`로 감싸 붙여넣습니다.
3. BI 에이전트가 해석하고 경영진용(결론 1줄 + 근거 3개 + 권고 1개) 문안을 씁니다. 발행 전에는 리뷰봇 → 컴봇 검토 요청서를 만듭니다.

## 참고

- 모델: `claude-opus-5-5`, adaptive thinking, effort `high`. 비용을 줄이려면 `agent.py`의 `EFFORT`를 `"medium"`으로 바꾸세요.
- 안전 분류기가 요청을 거절하면 서버 측 fallback(`fallbacks="default"`)으로 자동 재시도합니다.
- 대화 내용은 Anthropic API로 전송됩니다. 봇 결과를 붙여넣을 때 환자·개인 식별 정보는 빼세요.
