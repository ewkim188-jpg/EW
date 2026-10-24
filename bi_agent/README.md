# BI 에이전트

제약회사 BI 팀 전담 AI 에이전트입니다. `prompts/bi_agent_prompt.md`의 역할 정의(오너 모드 / 내부고객 모드, 7개 BI 업무 영역, 원칙)를 시스템 프롬프트로 쓰고, 로컬 데이터 파일을 pandas로 직접 분석합니다.

## 구성

| 파일 | 역할 |
|------|------|
| `agent.py` | CLI 대화 루프 (Claude API, 스트리밍, 도구 호출) |
| `tools.py` | 에이전트가 쓰는 도구: 파일 목록, 데이터 미리보기, Python 실행, 산출물 저장 |
| `prompts/bi_agent_prompt.md` | 에이전트 역할·원칙 프롬프트 |
| `company_context.md` | **회사 고유 정보 — 직접 채워 넣으세요.** 프롬프트의 `<company_context>`를 대체합니다 |
| `data/` | 분석할 데이터(UBIST·IQVIA 엑셀, 자사 매출 CSV 등)를 넣는 폴더 |
| `outputs/` | 요청서·보고서 초안·대화 기록이 저장되는 폴더 |

## 실행

```bash
cd bi_agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python agent.py                  # 모드는 에이전트가 판단
python agent.py --mode owner     # 오너(BI 담당자) 모드
python agent.py --mode customer  # 내부고객 모드
```

대화 중 명령: `/exit` 종료 · `/reset` 초기화 · `/save` 대화를 `outputs/`에 저장 · `"""` 로 감싸서 여러 줄 입력

## 동작 방식

- 데이터 질문을 받으면 `list_data_files` → `preview_data`로 실제 컬럼을 확인하고 `run_python`으로 계산합니다. 숫자는 실행 결과에서만 가져오도록 지시되어 있습니다.
- **`run_python`은 실행 전에 코드를 화면에 보여주고 승인(y)을 받습니다.** 한국어 주석이 달린 pandas 코드이므로 읽어 보고 승인하세요.
- 파일 접근은 `data/`(읽기)와 `outputs/`(쓰기)로 제한됩니다. 단, 승인한 `run_python` 코드는 일반 Python과 같은 권한으로 실행됩니다.
- 모델: `claude-opus-5-5`, adaptive thinking, effort `high`. 비용을 줄이려면 `agent.py`의 `EFFORT`를 `"medium"`으로 바꾸세요.
- 안전 분류기가 요청을 거절하면 서버 측 fallback(`fallbacks="default"`)으로 자동 재시도합니다.
- 시스템 프롬프트와 이전 대화는 프롬프트 캐싱으로 재사용해 비용을 줄입니다.

## 데이터 보안

- `data/`와 `outputs/`의 파일은 `.gitignore`로 저장소에 올라가지 않습니다 (`data/예시_*` 가상 데이터만 예외).
- 대화 내용과 도구 결과(데이터 미리보기·분석 출력)는 Anthropic API로 전송됩니다. 환자·개인 식별 정보는 넣지 말고, 외부 벤더 데이터는 계약상 사용 범위를 확인하세요.

## 해볼 만한 첫 질문

- (오너) `data 폴더의 예시 데이터로 자사A 점유율 추이 보고, 경영진용 한 줄 결론 써줘`
- (내부고객) `우리 품목 매출이 요즘 빠지는 것 같은데 자료 좀 받을 수 있을까요?`

`data/예시_월별처방액_가상데이터.csv`는 테스트용 **가상 데이터**입니다.
