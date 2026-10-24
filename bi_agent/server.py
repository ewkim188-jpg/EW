"""BI봇 웹 화면 서버.

실행:
    uvicorn server:app --port 8000      # bi_agent/ 폴더에서
    → 브라우저에서 http://localhost:8000

혼자 쓰는 로컬 도구로 만들었다. 대화는 서버 메모리에만 있고, 서버를 끄면 사라진다.
남겨야 할 것은 '대화 저장' 버튼(outputs/)과 성장 기록(memory/)에 남는다.
"""

import json
import threading
import uuid

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import MODES, BIAgent
from tools import BASE_DIR, STAGES, list_documents, load_growth_notes, read_document

app = FastAPI(title="BI봇")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# 세션 id → (에이전트, 잠금). 같은 세션에 동시에 두 질문이 들어가지 않게 잠근다.
SESSIONS: dict[str, tuple[BIAgent, threading.Lock]] = {}


def _get(session_id: str) -> tuple[BIAgent, threading.Lock]:
    if session_id not in SESSIONS:
        raise HTTPException(404, "세션이 없습니다. 새 대화를 시작하세요.")
    return SESSIONS[session_id]


class NewSession(BaseModel):
    mode: str = "실전"


class ChatIn(BaseModel):
    session_id: str
    text: str
    mode: str


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/config")
def config():
    return {"modes": MODES, "stages": [{"code": k, "label": v} for k, v in STAGES.items()]}


@app.post("/api/session")
def new_session(body: NewSession):
    try:
        agent = BIAgent(mode=body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = (agent, threading.Lock())
    return {"session_id": session_id}


@app.post("/api/chat")
def chat(body: ChatIn):
    agent, lock = _get(body.session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "이전 답변이 아직 끝나지 않았습니다.")
    try:
        agent.set_mode(body.mode)
    except ValueError as exc:
        lock.release()
        raise HTTPException(400, str(exc))

    def events():
        # 한 줄에 JSON 하나씩 (NDJSON). 화면은 fetch 스트림으로 한 줄씩 읽는다.
        finished = False
        try:
            for event in agent.ask(body.text):
                if event["type"] == "done":
                    finished = True
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except anthropic.AuthenticationError:
            yield _error("인증 실패: ANTHROPIC_API_KEY 환경변수를 확인하세요.")
        except anthropic.RateLimitError:
            yield _error("요청 한도 초과: 잠시 후 다시 시도하세요.")
        except anthropic.APIStatusError as exc:
            yield _error(f"API 오류 {exc.status_code}: {exc.message}")
        except anthropic.APIConnectionError:
            yield _error("연결 오류: 네트워크를 확인하세요.")
        except Exception as exc:  # 도구 입력 JSON 파싱 실패 등. 대화가 반쯤 남지 않게 되돌린다
            yield _error(f"처리 중 오류: {type(exc).__name__}: {exc}")
        finally:
            # 오류나 브라우저 연결 끊김으로 턴이 끝나지 않았으면, tool_use 만 남은 대화가 되지 않게 되돌린다
            if not finished:
                agent.rollback_to_last_user_text()
            lock.release()

    return StreamingResponse(events(), media_type="application/x-ndjson")


def _error(text: str) -> str:
    return json.dumps({"type": "error", "text": text}, ensure_ascii=False) + "\n"


@app.post("/api/session/{session_id}/save")
def save(session_id: str):
    agent, _ = _get(session_id)
    return {"path": agent.save_transcript()}


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
