"""BI봇 웹 화면 서버.

실행:
    uvicorn server:app --port 8000      # bi_agent/ 폴더에서
    → 브라우저에서 http://localhost:8000

혼자 쓰는 로컬 도구로 만들었다. 진행 중인 건은 서버 메모리에 있고, 단계마다 outputs/projects/ 에도 저장된다.
각 단계 호출은 에이전트가 끝날 때까지 기다렸다가 프로젝트 전체 상태를 돌려준다. 화면은 그 상태로 다시 그린다.
"""

import threading

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import WEB_SEARCH, AgentError
from tools import BASE_DIR, list_documents, load_growth_notes, read_document
from workflow import FlowError, Project, make_case

app = FastAPI(title="BI봇")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# 프로젝트 id → (프로젝트, 잠금). 같은 건에 두 단계가 동시에 돌지 않게 잠근다.
PROJECTS: dict[str, tuple[Project, threading.Lock]] = {}


def _run(project_id: str, action):
    """잠금을 잡고 단계를 실행한 뒤 상태를 돌려준다. 오류는 화면에 보여줄 문장으로 바꾼다."""
    if project_id not in PROJECTS:
        raise HTTPException(404, "진행 중인 건이 없습니다. 처음부터 다시 시작해 주세요.")
    project, lock = PROJECTS[project_id]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "이전 단계가 아직 진행 중입니다.")
    try:
        action(project)
        return project.to_dict()
    except FlowError as exc:
        raise HTTPException(400, str(exc))
    except AgentError as exc:
        raise HTTPException(502, f"에이전트 실패: {exc}. 다시 시도해 주세요.")
    except anthropic.AuthenticationError:
        raise HTTPException(401, "인증 실패: ANTHROPIC_API_KEY 환경변수를 확인하세요.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "요청 한도 초과: 잠시 후 다시 시도하세요.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"API 오류 {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "연결 오류: 네트워크를 확인하세요.")
    finally:
        lock.release()


class Intake(BaseModel):
    requester: str = ""
    dept: str = ""
    decision_maker: str = ""
    request: str
    deadline: str = ""
    mode: str = "실전"
    trap: str = ""  # 케이스 연습일 때만 (화면에는 끝나고 공개)


class Answer(BaseModel):
    answer: str = ""
    used_recommended: bool = False


class InterviewIn(BaseModel):
    answers: list[Answer]
    notes: list[str] = []
    skip: bool = False


class RetryIn(BaseModel):
    instruction: str = ""


class SpecIn(BaseModel):
    selections: dict[str, list[bool]]
    memo: str = ""
    docs: list[bool] = []


class DocFile(BaseModel):
    name: str
    data: str  # base64


class DocsIn(BaseModel):
    files: list[DocFile]


class RefineIn(BaseModel):
    answers: list[Answer]
    finish: bool = False


class ReportIn(BaseModel):
    report_type: str


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/config")
def config():
    return {"web_search": WEB_SEARCH}


@app.post("/api/case")
def case():
    """연습용 가상 요청. 폼을 채우는 데 쓴다."""
    try:
        data, log = make_case()
    except (AgentError, anthropic.APIError) as exc:
        raise HTTPException(502, f"케이스 생성 실패: {exc}")
    return {"case": data, "log": log}


@app.post("/api/project")
def create(body: Intake):
    if not body.request.strip():
        raise HTTPException(400, "요청 원문을 적어 주세요.")
    if body.mode not in ("실전", "훈련"):
        raise HTTPException(400, "모드는 실전 또는 훈련입니다.")
    project = Project(body.model_dump())
    PROJECTS[project.id] = (project, threading.Lock())
    return _run(project.id, lambda p: p.start())


@app.get("/api/project/{pid}")
def get(pid: str):
    return _run(pid, lambda p: None)


@app.post("/api/project/{pid}/interview")
def interview(pid: str, body: InterviewIn):
    return _run(pid, lambda p: p.answer_interview([a.model_dump() for a in body.answers], body.notes, body.skip))


@app.post("/api/project/{pid}/research/{track}")
def retry(pid: str, track: str, body: RetryIn):
    return _run(pid, lambda p: p.retry_track(track, body.instruction))


@app.post("/api/project/{pid}/spec")
def spec(pid: str, body: SpecIn):
    return _run(pid, lambda p: p.build_spec(body.selections, body.memo, body.docs))


@app.post("/api/project/{pid}/docs")
def docs(pid: str, body: DocsIn):
    return _run(pid, lambda p: p.read_docs([f.model_dump() for f in body.files]))


@app.post("/api/project/{pid}/refine")
def refine(pid: str, body: RefineIn):
    return _run(pid, lambda p: p.refine_spec([a.model_dump() for a in body.answers], body.finish))


@app.post("/api/project/{pid}/approve")
def approve(pid: str, body: ReportIn):
    return _run(pid, lambda p: p.approve(body.report_type))


@app.post("/api/project/{pid}/extra")
def extra(pid: str, body: ReportIn):
    return _run(pid, lambda p: p.extra_report(body.report_type))


@app.get("/api/growth")
def growth():
    return {"notes": load_growth_notes(limit=200)}


@app.get("/api/documents")
def documents():
    return {"documents": list_documents()}


@app.get("/api/document")
def document(path: str):
    try:
        return {"content": read_document(path)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))
