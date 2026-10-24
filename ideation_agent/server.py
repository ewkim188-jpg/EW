"""Ideation Agent 웹 서버. 계약은 CONTRACT.md.

실행:
    cd ideation_agent
    uvicorn server:app --port 8001     → 브라우저에서 http://localhost:8001

혼자 쓰는 로컬 도구로 만들었다. 진행 중인 세션은 메모리에, 단계마다 outputs/sessions/ 에도 저장된다(장기 메모리).
에이전트 호출은 끝날 때까지 기다렸다가 세션 상태 전체를 돌려준다.
"""

import json
import os
import threading
from urllib.parse import quote

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from agents import BASE_DIR, PACKS, WEB_SEARCH, AgentError
from workflow import REPORT_TYPES, FlowError, Session, limits, list_sessions

app = FastAPI(title="Ideation Agent")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# 세션 id → (세션, 잠금). 같은 세션에서 두 작업이 동시에 돌지 않게 잠근다
SESSIONS: dict[str, tuple[Session, threading.Lock]] = {}


def _run(sid: str, action):
    """잠금을 잡고 단계를 실행한 뒤 상태를 돌려준다. 오류는 화면에 보여줄 문장으로 바꾼다."""
    if sid not in SESSIONS:
        raise HTTPException(404, "세션이 없습니다. 갤러리에서 이어하거나 새로 시작해 주세요.")
    session, lock = SESSIONS[sid]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "이전 작업이 아직 진행 중입니다.")
    try:
        result = action(session)
        return result if result is not None else session.to_dict()
    except FlowError as exc:
        raise HTTPException(exc.status, str(exc))
    except AgentError as exc:
        raise HTTPException(502, f"에이전트 실패: {exc}. 다시 시도해 주세요.")
    except anthropic.AuthenticationError:
        raise HTTPException(401, "인증 실패: ANTHROPIC_API_KEY 환경변수를 확인하세요.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "요청 한도 초과: 잠시 후 다시 시도하세요.")
    except anthropic.APITimeoutError:
        raise HTTPException(504, "에이전트 응답 시간 초과: 다시 시도해 주세요.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"API 오류 {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "연결 오류: 네트워크를 확인하세요.")
    finally:
        lock.release()


class Intake(BaseModel):
    role: str = ""
    area: str = ""
    problem: str = ""
    idea: str = ""
    pack: str = "healthcare"


class Answer(BaseModel):
    answer: str = ""
    used_recommended: bool = False


class Extra(BaseModel):
    question: str = ""
    answer: str = ""


class InterviewIn(BaseModel):
    answers: list[Answer] = []
    extra: list[Extra] = []
    skip: bool = False


class FileIn(BaseModel):
    name: str
    data: str  # base64


class UploadIn(BaseModel):
    files: list[FileIn]


class RetryIn(BaseModel):
    instruction: str = ""


class SpecIn(BaseModel):
    selections: dict[str, list[bool]] = {}
    docs: list[bool] = []
    memo: str = ""


class CritiqueIn(BaseModel):
    answers: list[Answer] = []
    finish: bool = False


class ApproveIn(BaseModel):
    confirmed: StrictBool = False  # "yes"·1 같은 값을 true 로 바꿔 받지 않는다
    report_type: str = ""


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/config")
def config():
    return {"packs": [{"id": k, "name": v} for k, v in PACKS.items()], "report_types": REPORT_TYPES,
            "limits": limits(), "web_search": WEB_SEARCH}


@app.post("/api/session")
def create(body: Intake):
    try:
        session = Session(body.model_dump(exclude={"pack"}), body.pack)
    except FlowError as exc:
        raise HTTPException(exc.status, str(exc))
    SESSIONS[session.id] = (session, threading.Lock())
    return _run(session.id, lambda s: s.start())


@app.get("/api/session/{sid}")
def get(sid: str):
    return _run(sid, lambda s: None)


@app.post("/api/session/{sid}/interview")
def interview(sid: str, body: InterviewIn):
    return _run(sid, lambda s: s.interview([a.model_dump() for a in body.answers],
                                          [e.model_dump() for e in body.extra], body.skip))


@app.post("/api/session/{sid}/upload")
def upload(sid: str, body: UploadIn):
    return _run(sid, lambda s: s.upload([f.model_dump() for f in body.files]))


@app.post("/api/session/{sid}/research/{track}/retry")
def retry_track(sid: str, track: str, body: RetryIn):
    return _run(sid, lambda s: s.retry_track(track, body.instruction))


@app.post("/api/session/{sid}/spec")
def spec(sid: str, body: SpecIn):
    return _run(sid, lambda s: s.build_spec(body.selections, body.docs, body.memo))


@app.post("/api/session/{sid}/critique")
def critique(sid: str):
    return _run(sid, lambda s: s.critique())


@app.post("/api/session/{sid}/answer_critique")
def answer_critique(sid: str, body: CritiqueIn):
    return _run(sid, lambda s: s.answer_critique([a.model_dump() for a in body.answers], body.finish))


@app.post("/api/session/{sid}/approve")
def approve(sid: str, body: ApproveIn):
    return _run(sid, lambda s: s.approve(body.confirmed, body.report_type))


@app.post("/api/session/{sid}/report/accept")
def accept_report(sid: str):
    return _run(sid, lambda s: s.accept_report())


@app.post("/api/session/{sid}/report/retry")
def retry_report(sid: str):
    return _run(sid, lambda s: s.retry_report())


@app.post("/api/session/{sid}/demo")
def demo(sid: str):
    return _run(sid, lambda s: s.make_demo())


@app.get("/api/session/{sid}/download")
def download(sid: str, kind: str, fmt: str = "md"):
    if fmt not in ("md", "html"):
        raise HTTPException(400, "fmt 는 md 또는 html 입니다.")
    title, md = _run(sid, lambda s: s.document(kind))
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:60] or "ideation"
    body, media = (md, "text/markdown") if fmt == "md" else (_html(title, md), "text/html")
    # 한글 파일 이름은 RFC 5987 형식으로
    return Response(body, media_type=f"{media}; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe)}.{fmt}"})


def _html(title: str, md: str) -> str:
    """서버 없이 열어도 보이도록 마크다운 렌더러를 파일 안에 넣은 독립 HTML."""
    vendor = os.path.join(BASE_DIR, "static", "vendor")
    js = "".join(open(os.path.join(vendor, f), encoding="utf-8").read() + "\n" for f in ("marked.min.js", "purify.min.js"))
    data = json.dumps(md, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title.replace("<", "&lt;")}</title><style>
body{{font:15px/1.7 "Pretendard","Malgun Gothic","Apple SD Gothic Neo",sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1d2330}}
table{{border-collapse:collapse;display:block;overflow-x:auto}}th,td{{border:1px solid #ddd;padding:5px 9px;vertical-align:top}}th{{background:#f5f6fa}}
blockquote{{border-left:4px solid #c2410c;background:#fdebe3;margin:10px 0;padding:8px 14px}}h1,h2{{color:#312e81}}h3{{color:#4f46e5}}
</style><script>{js}</script></head><body><div id="c"></div>
<script>document.getElementById("c").innerHTML=DOMPurify.sanitize(marked.parse({data}));</script></body></html>"""


@app.get("/api/sessions")
def sessions():
    return {"sessions": list_sessions()}


@app.post("/api/sessions/{sid}/resume")
def resume(sid: str):
    if sid not in SESSIONS:
        try:
            SESSIONS[sid] = (Session.load(sid), threading.Lock())
        except FlowError as exc:
            raise HTTPException(exc.status, str(exc))
    return _run(sid, lambda s: None)
