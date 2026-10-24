# Ideation Agent — 업무 특화 에이전트 설계 봇

업무 문제·아이디어 한 줄을 넣으면 여러 에이전트가 협업해 **업무 특화 AI 에이전트의 설계**(명세 + 보고서 1쪽·2쪽 + 데모 설계서)를 만든다.
사용자는 문서를 쓰지 않는다. **질문에 답하고, 고르고, 승인하는 작업 관리자**다 (교안 p.13).

aSSIST 05장 실습 Ideation Agent의 흐름·에이전트 구성·하네스를 따랐다. 만드는 방법 정리는 `../bi_agent/에이전트_만드는_방법.md`.
산업 팩으로 **헬스케어(기본)**·일반을 고를 수 있어 어느 업무에나 쓴다.

## 실행

```bash
cd ideation_agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...                  # 또는 `ant auth login`
uvicorn server:app --port 8001                # 브라우저에서 http://localhost:8001

IDEATION_FAKE=1 uvicorn server:app --port 8001        # 가짜 모드: API 키 없이 흐름 확인 (내용은 예시)
IDEATION_WEB_SEARCH=0 uvicorn server:app --port 8001  # 외부 웹 검색 끄기
```

## 7단계 흐름 (교안 p.13 · p.57~62)

| # | 단계 | 사용자가 하는 일 | 에이전트 (패턴 · 교안) |
|---|---|---|---|
| 1 | 아이디어 입력 | 산업 팩, 역할, 업무 영역, 문제, 아이디어 한 줄 | — (p.9 업무 특화) |
| 2 | 인터뷰 (최대 3라운드) | 질문에 답, **질문 직접 추가(라운드당 3개)** | Interviewer (반복 p.60) + Scout (빠른 탐색 p.27). 확신도 ≥ 90이면 조기 종료 |
| 3 | 리서치 3개 동시 | **발견 취사선택, 내 자료 업로드, 메모**, 트랙 재조사(최대 2회) | Researcher ×3 (병렬 p.59: 유사 사례·시장 / 리스크·규제 / 데이터·연동) + DocReader (그라운딩 p.21) |
| 4 | 명세 정리 | 확인 | Planner (계층적 작업 분해 p.57). **적합성 판정**(에이전트 / 단순 자동화 / 사람 업무) 포함 |
| 5 | 비판 답변 (최대 2회) | **CFO·현장·법무/보안 비판 질문에 방어** | Critic (검토·비판 p.61) → Planner 수정 |
| 6 | 최종 확인 & 형식 선택 | **"명세를 확인했습니다" 체크(필수)** + 보고서 3종 중 선택 | 서버 하네스 (p.62·p.26) |
| 7 | 결과물 | **품질 미달이면 받을지·다시 만들지 결정** | Writer 1쪽 ∥ Architect 2쪽 5계층 (병렬 p.59) → QualityCheck → DemoArchitect (p.58·p.65) |

결과물: 보고서(1쪽 + 2쪽 실행 방안) MD·HTML, 리서치 보고서, 데모 제작 설계서(코딩 에이전트용 오케스트레이터 프롬프트 포함).

## 사람이 개입하는 5곳 (p.62) — 모두 서버 코드가 강제

| 게이트 | 코드 (`workflow.py`) |
|---|---|
| ① 인터뷰 답변 + 질문 직접 추가 | `_merge_answers`: 추가 질문을 다음 에이전트 컨텍스트에 병합 |
| ② 리서치 선별 + 자료 업로드 | `_apply_review`: 선택 안 한 발견·문서는 명세 근거에서 제외 |
| ③ 비판 질문 답변 | `answer_critique`: 최대 2회 루프 후 승인 단계로 |
| ④ "명세를 확인했습니다" 승인 | `approve`: `confirmed` 가 true 아니면 **HTTP 400**, 승인 전 보고서·다운로드는 **HTTP 403** |
| ⑤ 품질 미달 보고서 처리 | `accept_report`(경고 배지 붙여 다운로드 허용) / `retry_report`(최대 2회). 결정 전 다운로드는 **HTTP 409** |

## 하네스 (p.25~26) — grep 한 줄로 점검

| 요소 | 구현 | 점검 |
|---|---|---|
| 1. 안전한 인프라 | 에이전트 도구는 `submit`(결과 제출)과 `web_search`(Scout·Researcher만) 뿐. 파일·셸 도구 없음 | `grep -n "web_search" agents.py` |
| 2. 도구·권한 제한 | 업로드 PDF·TXT·MD·PNG·JPG, 5MB, 세션 누적 3개, **매직바이트 검사**, 메모리에서만 읽고 원본 미저장 | `grep -n "UPLOAD_" workflow.py` |
| 3. 자동 피드백 루프 | Critic 루프 + 2쪽 실행 방안 엄격 기준(5계층·패턴 3종·도구 유형 2종·거버넌스 4칸·3단계 로드맵)을 `_norm_implementation` 이 검사, 미달 시 자동 1회 재생성 | `grep -n "def _norm_implementation" workflow.py` |
| 4. 중단 조건 | 인터뷰 3, 비판 2, 재조사 2, 재생성 2, 동시 호출 8(`LLM_SEMAPHORE`), 에이전트 150초, 입력 글자수 | `grep -n "^MAX_\|LLM_SEMAPHORE\|AGENT_TIMEOUT" *.py` |

그 밖에:
- **그라운딩**: 출처 링크는 에이전트가 적은 URL이 아니라 실제 검색 결과 메타데이터에 있던 것만 남긴다. 0건이면 "검색 근거 없음 — 모델 지식일 수 있음" 경고.
- **관측성**: 모든 호출을 agent · pattern · slide · ms 로 실행 로그에 표시 (`agents.TRACE_META`).
- **메모리**: 단기 = 세션 컨텍스트로 다음 에이전트에 전달. 장기 = `outputs/sessions/*.json` 스냅샷 + 화면의 **갤러리**에서 이어하기.

## 테스트

```bash
python tests/test_flow.py        # 가짜 모드, API 키 불필요. 7단계 흐름과 하네스 46개 항목
python tests/smoke_agents.py     # 실제 API. 업로드 문서 속 프롬프트 주입("PWNED")을 DocReader 가 따르지 않는지 (p.26·p.68)
```

## 산업 팩

`packs/healthcare.md`(기본), `packs/general.md`. 팩은 모든 에이전트의 공통 배경에 들어간다.
새 산업은 `packs/<id>.md` 를 만들고 `agents.PACKS` 에 한 줄 추가한다.
헬스케어 팩의 규제 내용은 출발점일 뿐이다. 에이전트는 검색으로 최신 내용을 확인하고, 최종 판단은 법무·컴플라이언스가 한다.

## 파일

| 파일 | 내용 |
|---|---|
| `CONTRACT.md` | API 계약서 (화면·서버가 맞추는 기준) |
| `agents.py` | 에이전트 실행기, 스키마, TRACE_META, 동시 호출·타임아웃 |
| `workflow.py` | 7단계 진행, HITL 5대 게이트, 업로드 검사, 품질 검사 |
| `server.py` / `static/index.html` | 웹 화면 |
| `prompts/agents.md` | 에이전트별 역할 프롬프트 |
| `packs/*.md` | 산업 팩 |
| `fake_claude.py` | 가짜 모드 |

## 주의

- 업로드 자료와 입력 내용은 Claude API로 전송된다. 사내 규정상 외부 전송이 안 되는 자료(환자 정보 등)는 올리지 않는다.
- `outputs/` 는 `.gitignore` 로 저장소에서 빠진다. 이 저장소는 공개 저장소다.
- 관리자 비밀번호 잠금(원본의 팀 갤러리용)은 혼자 쓰는 로컬 도구라 넣지 않았다.
