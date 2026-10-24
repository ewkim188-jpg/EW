"""BI 에이전트가 쓰는 로컬 도구 모음.

BI 에이전트는 데이터를 직접 돌리지 않는다. 계산·검토는 오너가 만든 전문 에이전트가 맡고,
BI 에이전트는 문제를 정의해 요청서를 만들고, 돌아온 결과를 해석한다.

- create_handoff : BI Agent Team 봇(분석봇·이데·리뷰봇·컴봇 등)에 넘길 요청서를 outputs/handoffs/ 에 저장
- save_output    : BI 분석 요청서, 보고서 초안 등을 outputs/ 에 저장

모든 파일 쓰기는 outputs/ 안으로 제한한다.
"""

from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
HANDOFF_DIR = OUTPUT_DIR / "handoffs"

# 오너가 운영하는 전문 에이전트 목록 (출처: 'BI Agent Team' 구현 결과보고서, 2026-07).
# 새 에이전트가 생기면 여기에 추가한다. role 이 비어 있는 에이전트에는 요청서를 만들지 않는다.
AGENTS = {
    "이데": {
        "id": "",
        "role": "외부 정보 수집. 뉴스·학회·규제·경쟁사 동향을 검색 기반으로 조사하고 출처·날짜와 함께 정리한다.",
        "when": "경쟁 이벤트·규제·급여 고시·학회 결과 등 외부 사실 확인이 필요할 때",
        # [확인 필요] 시장 시그널 페이지에는 '이데(data-analyst)'로 적혀 있어 보고서와 다르다
    },
    "분석봇": {
        "id": "",
        "role": "정량 분석. 실적·마켓셰어·포캐스팅 Gap 등을 원본 데이터를 직접 읽어 계산한다. 수치 날조 금지.",
        "when": "숫자가 필요한 모든 경우 (조회, 추이, 매출 분해, 세그먼트, 포캐스트 대비 실적, 시나리오)",
    },
    "전략봇": {
        "id": "",
        "role": "전략·시사점. 분석 결과에서 BI 시사점과 대응 방향을 도출한다 (예: 특허만료 방어전략).",
        "when": "검증된 분석 결과를 바탕으로 대응 전략·옵션 비교가 필요할 때",
    },
    "보고서봇": {
        "id": "",
        "role": "실행계획·보고서. 경영진이 읽을 보고서·브리핑·실행계획으로 종합한다.",
        "when": "결론이 정해진 뒤 정식 보고서·브리핑 형태로 만들 때",
    },
    "리뷰봇": {
        "id": "",
        "role": "검수(정확성 게이트). 발행 전 재검산·출처 확인·논리 검증을 하고, FAIL 시 원작업 봇에 반려한다.",
        "when": "숫자나 사실 주장이 들어간 모든 산출물을 발행하기 전 (필수)",
    },
    "컴봇": {
        "id": "compliance-bot",
        "role": "규제 점검(규제 게이트). 허가사항 기반 표현만 허용하고 off-label 표현을 차단하며, 내부용/외부용을 구분한다.",
        "when": "모든 산출물을 발행하기 전 (필수). 특히 제품 메시지·대외 자료, 개별 의사·병원 단위 데이터 활용",
    },
    "비서봇": {
        "id": "",
        "role": "",  # [확인 필요] 보고서에 없음. 오너에게 역할을 확인한 뒤 채운다
        "when": "",
    },
}


def _safe_path(root: Path, rel: str) -> Path:
    """root 밖으로 나가는 경로(../ 등)를 막는다."""
    path = (root / rel).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"{root.name}/ 폴더 밖의 경로는 쓸 수 없습니다: {rel}")
    return path


def agents_for_prompt() -> str:
    """시스템 프롬프트에 넣을 에이전트 목록."""
    lines = []
    for name, info in AGENTS.items():
        if info["role"]:
            label = f"{name} ({info['id']})" if info["id"] else name
            lines.append(f"- {label}: {info['role']}\n  언제: {info['when']}")
        else:
            lines.append(f"- {name}: [역할 확인 필요] 역할이 정해지기 전에는 요청서를 만들지 말고, "
                         f"필요해 보이면 오너에게 {name}의 역할을 묻는다.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 도구 구현
# ---------------------------------------------------------------------------

def create_handoff(agent: str, title: str, request: str) -> str:
    info = AGENTS.get(agent)
    if info is None:
        raise ValueError(f"등록되지 않은 에이전트입니다: {agent}. 사용 가능: {list(AGENTS)}")
    if not info["role"]:
        raise ValueError(f"{agent}의 역할이 아직 정해지지 않았습니다. 오너에게 역할을 먼저 확인하세요.")

    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
    file = HANDOFF_DIR / f"{stamp}_{agent}_{safe_title}.md"
    file.write_text(
        f"# [{agent} 요청] {title}\n\n"
        f"- 받는 에이전트: {agent} ({info['id']})\n"
        f"- 작성: BI 에이전트 / {datetime.now():%Y-%m-%d %H:%M}\n\n"
        f"{request}\n",
        encoding="utf-8",
    )
    # 오너가 바로 복사해 해당 에이전트에 붙여넣을 수 있도록 화면에도 보여준다
    print("\n" + "=" * 70)
    print(f"[{agent}에게 보낼 요청서] {title}")
    print("-" * 70)
    print(request)
    print("=" * 70)
    return f"요청서 저장 완료: {file.relative_to(BASE_DIR)}. 오너가 {agent}에게 전달한다."


def save_output(filename: str, content: str) -> str:
    file = _safe_path(OUTPUT_DIR, filename)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return f"저장 완료: outputs/{file.relative_to(OUTPUT_DIR)}"


# ---------------------------------------------------------------------------
# Claude에 넘기는 도구 정의 (JSON Schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "create_handoff",
        "description": "오너의 BI Agent Team 봇에게 넘길 작업 요청서를 만들어 저장하고 화면에 보여준다. "
                       "숫자 계산은 분석봇, 외부 정보 수집은 이데, 발행 전 검수는 리뷰봇→컴봇에게 맡긴다. "
                       "요청서는 받는 에이전트가 되묻지 않고 바로 실행할 수 있을 만큼 구체적으로 쓴다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": list(AGENTS), "description": "받는 에이전트 이름"},
                "title": {"type": "string", "description": "요청 제목 한 줄. 예: 릭시아나 LOE 후 월별 점유율 추이"},
                "request": {"type": "string", "description": "요청서 본문 (마크다운). 시스템 프롬프트의 요청서 양식을 따른다."},
            },
            "required": ["agent", "title", "request"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "save_output",
        "description": "BI 분석 요청서, 보고서 초안, 결과 해석 등 텍스트 산출물을 outputs/ 폴더에 저장한다. "
                       "마크다운(.md) 형식을 권장한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "outputs/ 기준 파일명. 예: 요청서_A품목_점유율하락.md"},
                "content": {"type": "string", "description": "저장할 내용"},
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]

_HANDLERS = {
    "create_handoff": create_handoff,
    "save_output": save_output,
}


def _validate(name: str, args: dict) -> str | None:
    """스트리밍으로 받은 입력은 서버가 검증하지 않으므로 여기서 스키마를 확인한다."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), None)
    if schema is None:
        return f"알 수 없는 도구: {name}"
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


def execute_tool(name: str, args: dict) -> tuple[str, bool]:
    """(결과 문자열, 오류 여부)를 돌려준다."""
    error = _validate(name, args)
    if error:
        return error, True
    try:
        return _HANDLERS[name](**args), False
    except Exception as exc:  # 도구 오류는 Claude에게 돌려줘서 스스로 고치게 한다
        return f"{type(exc).__name__}: {exc}", True
