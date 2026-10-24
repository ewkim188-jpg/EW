"""BI봇이 쓰는 로컬 도구 모음.

BI봇은 무엇을, 어떤 기준으로 볼지 정한다. 계산은 이데, 배분은 오케스트레이터,
발행 직전 검수는 리뷰봇·컴봇이 한다. 그래서 BI봇의 도구는 '정의된 문서'를 다룬다.

- set_stage                : 화면 상단 진행 표시줄의 현재 단계를 바꾼다
- save_document            : BI 분석 요청서·지표 정의서·모델 설계서 등을 outputs/docs/ 에 저장
- handoff_to_orchestrator  : 오너가 승인한 문서를 오케스트레이터에 넘길 요청서로 outputs/handoffs/ 에 저장
- record_growth_note       : 오너의 성장 기록(강점·약점·개선)을 memory/growth_log.jsonl 에 추가
(검토·비판 도구 review_draft 는 세션 상태가 필요해서 review.py 와 core.py 에 있다)

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

# 화면 진행 표시줄의 단계 (prompts/coach.md 4절과 같아야 한다)
STAGES = {
    "intake": "요청 정리",
    "reframe": "문제 재정의",
    "design": "설계",
    "interpret": "해석",
    "sowhat": "So-what",
    "retro": "회고",
}

DOC_TYPES = ["BI 분석 요청서", "지표 정의서", "모델 설계서", "SFE·런칭 설계서", "리뷰 메모", "기타"]

# prompts/coach.md 2절의 6가지 능력
CAPABILITIES = ["질문", "데이터", "가설", "소왓", "경영진", "도메인"]
GROWTH_KINDS = ["강점", "약점", "개선"]

# 프롬프트에 넣을 성장 기록 최대 개수 (최근 것부터)
GROWTH_LOG_LIMIT = 30


def _safe_name(text: str, limit: int = 40) -> str:
    """파일 이름에 쓸 수 없는 문자를 _ 로 바꾼다. 한글은 그대로 둔다."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:limit]


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# 성장 기록 읽기 (세션 시작 때 시스템 프롬프트에 넣는다)
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
        return "<growth_log>\n아직 기록이 없다. 첫 대화다.\n</growth_log>"
    lines = [
        f"- {n['date']} [{n['capability']}·{n['kind']}] {n['observation']}"
        + (f" → 다음엔: {n['next_time']}" if n.get("next_time") else "")
        for n in notes
    ]
    return "<growth_log>\n" + "\n".join(lines) + "\n</growth_log>"


def list_documents() -> list[dict]:
    """화면 사이드바에 보여줄 저장 문서 목록 (최근 것이 위)."""
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


# ---------------------------------------------------------------------------
# 도구 구현. 각 함수는 (Claude에게 돌려줄 문자열, 화면에 보낼 이벤트 dict 또는 None)을 돌려준다.
# ---------------------------------------------------------------------------

def set_stage(stage: str, note: str = "") -> tuple[str, dict]:
    return (f"단계를 '{STAGES[stage]}'(으)로 바꿨습니다.",
            {"type": "stage", "stage": stage, "label": STAGES[stage], "note": note})


def save_document(doc_type: str, title: str, content: str) -> tuple[str, dict]:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    file = DOC_DIR / f"{_stamp()}_{_safe_name(doc_type)}_{_safe_name(title)}.md"
    file.write_text(
        f"# [{doc_type}] {title}\n\n- 작성: BI봇 / {datetime.now():%Y-%m-%d %H:%M}\n\n{content}\n",
        encoding="utf-8",
    )
    rel = str(file.relative_to(OUTPUT_DIR))
    return f"저장 완료: outputs/{rel}", {"type": "doc", "path": rel, "title": f"[{doc_type}] {title}"}


def handoff_to_orchestrator(title: str, documents: str, request: str) -> tuple[str, dict]:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    file = HANDOFF_DIR / f"{_stamp()}_오케스트레이터_{_safe_name(title)}.md"
    file.write_text(
        f"# [오케스트레이터 요청] {title}\n\n"
        f"- 보낸 곳: BI봇 / {datetime.now():%Y-%m-%d %H:%M}\n"
        f"- 오너 승인: 완료 (대화에서 확인)\n"
        f"- 첨부 문서: {documents or '없음'}\n\n"
        f"{request}\n",
        encoding="utf-8",
    )
    rel = str(file.relative_to(OUTPUT_DIR))
    return (f"요청서 저장 완료: outputs/{rel}. 오너가 오케스트레이터에 전달한다.",
            {"type": "doc", "path": rel, "title": f"[오케스트레이터 요청] {title}"})


def record_growth_note(capability: str, kind: str, observation: str, next_time: str = "") -> tuple[str, dict]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    note = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "capability": capability,
        "kind": kind,
        "observation": observation,
        "next_time": next_time,
    }
    with GROWTH_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    return "성장 기록에 추가했습니다.", {"type": "growth", "note": note}


# ---------------------------------------------------------------------------
# Claude에 넘기는 도구 정의 (JSON Schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "set_stage",
        "description": "화면 상단 진행 표시줄의 현재 업무 단계를 바꾼다. 단계가 바뀔 때마다 부른다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": list(STAGES), "description": "단계 코드"},
                "note": {"type": "string", "description": "이 단계에서 할 일 한 줄 (선택)"},
            },
            "required": ["stage"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_document",
        "description": "BI 분석 요청서, 지표 정의서, 모델 설계서, SFE·런칭 설계서, 리뷰 메모를 저장한다. "
                       "양식은 시스템 프롬프트를 따르고, 빈칸은 [확인 필요]로 채운다. "
                       "리뷰 메모·기타를 뺀 문서는 같은 title 로 review_draft 를 통과해야 저장된다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "enum": DOC_TYPES},
                "title": {"type": "string", "description": "문서 제목 한 줄. 예: 릭시아나 LOE 후 점유율 방어 분석"},
                "content": {"type": "string", "description": "문서 본문 (마크다운)"},
            },
            "required": ["doc_type", "title", "content"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "handoff_to_orchestrator",
        "description": "오너가 승인한 문서를 오케스트레이터에 넘길 요청서로 저장한다. "
                       "오너가 문서 전문을 보고 분명히 승인한 뒤에만 부른다. 개별 봇에게 직접 요청하지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "요청 제목 한 줄"},
                "documents": {"type": "string", "description": "함께 넘기는 저장 문서 경로 (쉼표로 구분, 없으면 빈 문자열)"},
                "request": {
                    "type": "string",
                    "description": "오케스트레이터에게 보낼 본문 (마크다운): 목적, 핵심 질문, 필요한 작업과 "
                                   "맡길 만한 봇(이데·서치봇 등) 제안, 기준 문서, 회신 형식, 발행 시 리뷰봇→컴봇 게이트 필요 여부",
                },
            },
            "required": ["title", "documents", "request"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "record_growth_note",
        "description": "오너의 성장 기록에 한 줄을 추가한다. 이번 대화에서 본 구체적 장면이 근거일 때만 부른다. "
                       "한 건에 보통 0~2개.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capability": {"type": "string", "enum": CAPABILITIES, "description": "6가지 능력 코드"},
                "kind": {"type": "string", "enum": GROWTH_KINDS},
                "observation": {"type": "string", "description": "본 것 한 문장. 예: 매출 감소 원인을 처방의 수 하나로만 봄"},
                "next_time": {"type": "string", "description": "다음에 해 볼 것 한 문장 (선택)"},
            },
            "required": ["capability", "kind", "observation"],
            "additionalProperties": False,
        },
    },
]

_HANDLERS = {
    "set_stage": set_stage,
    "save_document": save_document,
    "handoff_to_orchestrator": handoff_to_orchestrator,
    "record_growth_note": record_growth_note,
}


def validate_input(schema: dict, args: dict) -> str | None:
    """스트리밍으로 받은 입력은 서버가 검증하지 않으므로 여기서 스키마를 확인한다 (문자열 필드만 쓰는 도구용)."""
    if not isinstance(args, dict):
        return "도구 입력이 JSON 객체가 아닙니다."
    props = schema["properties"]
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"필수 입력 누락: {missing}"
    unknown = [k for k in args if k not in props]
    if unknown:
        return f"정의되지 않은 입력: {unknown}"
    for key, value in args.items():
        if not isinstance(value, str):
            return f"'{key}'의 타입이 string이 아닙니다."
        if "enum" in props[key] and value not in props[key]["enum"]:
            return f"'{key}'는 {props[key]['enum']} 중 하나여야 합니다."
    return None


def execute_tool(name: str, args: dict) -> tuple[str, bool, dict | None]:
    """(Claude에게 돌려줄 결과, 오류 여부, 화면 이벤트)를 돌려준다."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), None)
    if schema is None:
        return f"알 수 없는 도구: {name}", True, None
    error = validate_input(schema, args)
    if error:
        return error, True, None
    try:
        result, event = _HANDLERS[name](**args)
        return result, False, event
    except Exception as exc:  # 도구 오류는 Claude에게 돌려줘서 스스로 고치게 한다
        return f"{type(exc).__name__}: {exc}", True, None
