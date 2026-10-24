# CONTRACT — Ideation Agent API 계약서

화면(`static/index.html`)과 서버(`server.py`)·워크플로(`workflow.py`)는 이 계약만 보고 맞춘다.
키 이름을 바꾸려면 이 문서를 먼저 고친다.

## 공통

- 모든 응답은 JSON. 오류는 `{"detail": "사람이 읽을 문장"}` + HTTP 상태 코드.
- 세션 상태(`State`)를 돌려주는 API는 모두 아래 `State` 전체를 돌려준다. 화면은 받은 상태로 다시 그린다.

| 코드 | 뜻 |
|---|---|
| 400 | 입력 오류, 잘못된 단계, 한도 초과, **승인 체크 없음(`confirmed` 가 true 아님)** |
| 403 | **승인 전 보고서·다운로드 요청** |
| 404 | 세션 없음 |
| 409 | 같은 세션에서 다른 작업 진행 중, 또는 품질 미달 보고서를 받기·다시 만들기 전에 다운로드 |
| 413 | 업로드 크기·개수 초과 |
| 502 / 503 / 429 / 401 | 에이전트·API 오류 |

## 단계 (`step`)

| step | 이름 | 다음으로 가는 API |
|---|---|---|
| 1 | 아이디어 입력 | `POST /api/session` |
| 2 | 인터뷰 | `POST /api/session/{id}/interview` (신뢰도 ≥ 90, 최대 3라운드, 또는 skip) |
| 3 | 리서치 | `POST /api/session/{id}/spec` |
| 4 | 명세 정리 | `POST /api/session/{id}/critique` |
| 5 | 비판 답변 | `POST /api/session/{id}/answer_critique` (PASS, 최대 2회, 또는 finish) |
| 6 | 최종 확인 | `POST /api/session/{id}/approve` |
| 7 | 결과물 | (다운로드, 받기/다시 만들기, 데모 설계서) |

## API

| 메서드 · 경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/config` | — | `{packs: [{id, name}], report_types: {id: label}, limits: Limits, web_search: bool}` |
| `POST /api/session` | `{role, area, problem, idea, pack}` | `State` (step 2, 인터뷰 1라운드 포함) |
| `GET /api/session/{id}` | — | `State` |
| `POST /api/session/{id}/interview` | `{answers: [{answer, used_recommended}], extra: [{question, answer}], skip}` | `State` |
| `POST /api/session/{id}/upload` | `{files: [{name, data(base64)}]}` | `State` |
| `POST /api/session/{id}/research/{track}/retry` | `{instruction}` | `State` |
| `POST /api/session/{id}/spec` | `{selections: {track: [bool]}, docs: [bool], memo}` | `State` (step 4) |
| `POST /api/session/{id}/critique` | `{}` | `State` (step 5, 비판 1회차) |
| `POST /api/session/{id}/answer_critique` | `{answers: [{answer, used_recommended}], finish}` | `State` |
| `POST /api/session/{id}/approve` | `{confirmed, report_type}` | `State` (step 7). `confirmed` 가 true 아니면 400 |
| `POST /api/session/{id}/report/accept` | `{}` | `State` (품질 미달을 경고 배지와 함께 받음) |
| `POST /api/session/{id}/report/retry` | `{}` | `State` (최대 2회) |
| `POST /api/session/{id}/demo` | `{}` | `State` (데모 설계서 생성) |
| `GET /api/session/{id}/download?kind=report\|research\|demo&fmt=md\|html` | — | 파일. 승인 전 403, 품질 미달 미결정 409 |
| `GET /api/sessions` | — | `{sessions: [{id, title, created, step, pack}]}` (장기 메모리 갤러리) |
| `POST /api/sessions/{id}/resume` | — | `State` (디스크 스냅샷에서 이어하기) |

## State

```
{
  id, created, step, pack, pack_name,
  intake: {role, area, problem, idea},
  rounds: [{hypothesis, confidence, gaps, ready,
            questions: [{title, question, axis, recommended, answer, used_recommended}],
            extra: [{question, answer}],
            facts: [{fact, why, sources: [Source]}], facts_warning}],
  tracks: {market|risk|data: {title, queries, findings: [{text, sources: [int], selected}],
                              sources: [Source], warning, retries, error}},
  docs: [{name, kind, summary, key_points, cautions, selected}],
  memo,
  spec: Spec | null,
  critic_rounds: [{verdict, scores: [{perspective, score, comment}],
                   questions: [{perspective, question, recommended, answer, used_recommended}]}],
  approved, report_type,
  report: {title, writer_md, architect: Architect, architect_md,
           quality: {passed, issues: [str], auto_retried, retries, accepted}} | null,
  demo_md: str | null,
  log: [{agent, pattern, slide, ms, note, at}],
  limits: Limits, report_types, tracks_meta
}
Source = {n, title, url}          # 실제 검색 결과(메타데이터)에서만 만든다
Limits = {interview, early_stop, critic, retries, report_retries, extra, upload_files, upload_mb}
```

`Spec`, `Architect` 의 필드는 `agents.py` 의 `SPEC_SCHEMA`, `ARCHITECT_SCHEMA` 가 정본이다.
