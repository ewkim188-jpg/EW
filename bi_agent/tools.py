"""파일 저장·읽기 도구 모음.

- save_document           : 산출물을 outputs/docs/ 에 저장
- handoff_to_orchestrator : 오케스트레이터 요청서를 outputs/handoffs/ 에 저장
- record_growth_note      : 오너의 성장 기록(강점·약점·개선)을 memory/growth_log.jsonl 에 추가

모든 파일 쓰기는 outputs/ 와 memory/ 안으로 제한한다. 두 폴더 모두 .gitignore 로 저장소에서 제외한다.
"""

import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
DOC_DIR = OUTPUT_DIR / "docs"
HANDOFF_DIR = OUTPUT_DIR / "handoffs"
MEMORY_DIR = BASE_DIR / "memory"
GROWTH_FILE = MEMORY_DIR / "growth_log.jsonl"

# 프롬프트에 넣을 성장 기록 최대 개수 (최근 것부터)
GROWTH_LOG_LIMIT = 30


def _safe_name(text: str, limit: int = 40) -> str:
    """파일 이름에 쓸 수 없는 문자를 _ 로 바꾼다. 한글은 그대로 둔다."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:limit]


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _unique(path: Path) -> Path:
    """같은 이름의 파일이 있으면 __2, __3 … 을 붙인다."""
    n = 2
    while path.exists():
        path = path.with_name(f"{path.stem.rsplit('__', 1)[0]}__{n}{path.suffix}")
        n += 1
    return path


# ---------------------------------------------------------------------------
# 성장 기록
# ---------------------------------------------------------------------------

def load_growth_notes(limit: int = GROWTH_LOG_LIMIT) -> list[dict]:
    if not GROWTH_FILE.exists():
        return []
    notes = []
    for line in GROWTH_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            notes.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 손으로 고치다 깨진 줄은 건너뛴다
    return notes[-limit:]


def growth_log_for_prompt() -> str:
    notes = load_growth_notes()
    if not notes:
        return "<growth_log>\n아직 기록이 없다. 첫 건이다.\n</growth_log>"
    lines = [
        f"- {n['date']} [{n['capability']}·{n['kind']}] {n['observation']}"
        + (f" → 다음엔: {n['next_time']}" if n.get("next_time") else "")
        for n in notes
    ]
    return "<growth_log>\n" + "\n".join(lines) + "\n</growth_log>"


def record_growth_note(capability: str, kind: str, observation: str, next_time: str = "") -> dict:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    note = {"date": datetime.now().strftime("%Y-%m-%d"), "capability": capability, "kind": kind,
            "observation": observation, "next_time": next_time}
    with GROWTH_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    return note


# ---------------------------------------------------------------------------
# 문서 저장·목록·읽기
# ---------------------------------------------------------------------------

def save_document(doc_type: str, title: str, content: str) -> tuple[str, dict]:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    file = _unique(DOC_DIR / f"{_stamp()}_{_safe_name(title)}.md")
    file.write_text(f"# {title}\n\n- 작성: BI봇 / {datetime.now():%Y-%m-%d %H:%M}\n\n{content}\n", encoding="utf-8")
    rel = str(file.relative_to(OUTPUT_DIR))
    return f"저장 완료: outputs/{rel}", {"type": "doc", "path": rel, "title": title}


def handoff_to_orchestrator(title: str, documents: str, request: str) -> tuple[str, dict]:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    file = _unique(HANDOFF_DIR / f"{_stamp()}_오케스트레이터_{_safe_name(title)}.md")
    file.write_text(
        f"# [오케스트레이터 요청] {title}\n\n"
        f"- 보낸 곳: BI봇 / {datetime.now():%Y-%m-%d %H:%M}\n"
        f"- 오너 승인: 완료 (5단계 승인)\n"
        f"- 첨부 문서: {documents or '없음'}\n\n"
        f"{request}\n",
        encoding="utf-8",
    )
    rel = str(file.relative_to(OUTPUT_DIR))
    return f"요청서 저장 완료: outputs/{rel}", {"type": "doc", "path": rel, "title": f"[오케스트레이터 요청] {title}"}


def list_documents() -> list[dict]:
    """저장 문서 목록 (최근 것이 위)."""
    items = []
    for folder, kind in ((DOC_DIR, "문서"), (HANDOFF_DIR, "오케스트레이터 요청서")):
        if folder.exists():
            for f in folder.glob("*.md"):
                items.append({"kind": kind, "path": str(f.relative_to(OUTPUT_DIR)), "name": f.stem})
    return sorted(items, key=lambda x: x["name"], reverse=True)


def read_document(rel: str) -> str:
    path = (OUTPUT_DIR / rel).resolve()
    if OUTPUT_DIR.resolve() not in path.parents or path.suffix != ".md":
        raise ValueError("outputs/ 안의 .md 파일만 읽을 수 있습니다.")
    return path.read_text(encoding="utf-8")
