"""BI봇 에이전트들. 각 에이전트는 Claude 호출 한 번(+검색)이고, 결과를 submit 도구로 구조화해 제출한다.

| 에이전트          | 패턴                     | 하는 일                                   |
|-------------------|--------------------------|-------------------------------------------|
| Interviewer       | 반복 패턴                | 가설·신뢰도·질문 3개                      |
| Scout             | 도구 사용 (빠른 탐색)    | 라운드 사이 사실 확인                     |
| Researcher × 3    | 병렬 처리 + 검색 도구    | 트랙별 조사 (workflow.py 가 동시에 돌림)  |
| Planner           | 계층적 작업 분해         | BI 분석 명세                              |
| Critic            | 검토·비판 패턴           | 검증단 비판 질문                          |
| DocReader         | 그라운딩                 | 오너가 올린 사내 문서 요약 (주입 방어)    |
| Reporter / Coach  | 순차 처리 / 병렬 처리    | 산출물 / 오너 코칭·성장 기록              |
| Architect         | 계층적 작업 분해         | 오케스트레이터 요청서 (reporter 역할 사용)|
| CaseMaker         | —                        | 연습용 가상 요청                          |
"""

import json
import os
import re
import time

import anthropic

from tools import BASE_DIR

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16_000
MAX_LOOPS = 8  # 검색·재촉을 포함해 에이전트 한 번에 주고받는 최대 횟수

# 회사 PC에서 외부 검색을 막아야 하면 BI_WEB_SEARCH=0 으로 실행한다
WEB_SEARCH = os.environ.get("BI_WEB_SEARCH", "1") != "0"

PROMPT_FILE = BASE_DIR / "prompts" / "bi_agent_prompt.md"
AGENTS_FILE = BASE_DIR / "prompts" / "agents.md"
COMPANY_FILE = BASE_DIR / "company_context.md"

# 실행 로그에 보여줄 에이전트별 일하는 패턴 (Ideation Agent 의 TRACE_META 와 같은 역할)
TRACE_META = {
    "Interviewer": "반복 패턴 (라운드마다 가설·질문 갱신)",
    "Scout": "도구 사용 (빠른 탐색: web_search)",
    "Researcher": "병렬 처리 + 검색 도구",
    "ResearchTeam": "병렬 처리 (데이터 / 시장 / 방법)",
    "DocReader": "그라운딩 (사내 문서 요약 · 주입 방어)",
    "Planner": "계층적 작업 분해 (명세 초안)",
    "Critic": "검토·비판 패턴 (경영진·현업·데이터 시각)",
    "Reporter": "순차 처리 (승인된 명세 → 산출물)",
    "Architect": "계층적 작업 분해 (오케스트레이터 요청서)",
    "Coach": "성장 기록 (오너 답변 평가)",
    "CaseMaker": "케이스 생성",
}

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class AgentError(Exception):
    pass


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------

def _tag(text: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, flags=re.DOTALL)
    if not m:
        raise KeyError(f"<{name}> 블록이 없습니다")
    return m.group(1).strip()


def background() -> str:
    """모든 에이전트 공통 배경. 원본 프롬프트에서 대화 방식 블록은 빼고 지식·원칙만 쓴다."""
    src = PROMPT_FILE.read_text(encoding="utf-8")
    parts = [f"<{t}>\n{_tag(src, t)}\n</{t}>" for t in ("role", "bi_philosophy", "domain_knowledge", "principles")]
    parts.append(COMPANY_FILE.read_text(encoding="utf-8").strip())
    parts.append("<team>\n" + _tag(AGENTS_FILE.read_text(encoding="utf-8"), "team") + "\n</team>")
    return "\n\n".join(parts)


def role(name: str) -> str:
    return _tag(AGENTS_FILE.read_text(encoding="utf-8"), name)


# ---------------------------------------------------------------------------
# 실행기
# ---------------------------------------------------------------------------

def _echo_safe(content: list) -> list:
    """서버 측 폴백이 응답 중간에 일어났으면, 폴백 경계 앞의 thinking·tool_use 블록은 다시 보내면 안 된다."""
    idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if idx < 0:
        return content
    # 검색 호출(server_tool_use)은 결과 블록과 짝이 맞으면 남기고, 짝 없는 것만 버린다
    paired = {getattr(b, "tool_use_id", None) for b in content if b.type.endswith("_tool_result")}
    drop = {"thinking", "redacted_thinking", "tool_use"}
    return [b for i, b in enumerate(content)
            if i >= idx or (b.type not in drop and not (b.type == "server_tool_use" and b.id not in paired))]


def _search_urls(content: list) -> set[str]:
    """웹 검색 결과로 실제로 받은 URL. 에이전트가 지어낸 출처를 걸러내는 데 쓴다."""
    urls = set()
    for b in content:
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            urls |= {r.url for r in b.content if getattr(r, "url", None)}
    return urls


def run_agent(role_name: str, user: str | list, schema: dict, *, effort: str = "high",
              search: bool = False, max_searches: int = 4) -> tuple[dict, float, set[str]]:
    """에이전트 하나를 돌려 (제출 결과, 걸린 초, 검색으로 본 URL)을 돌려준다.
    user 는 문자열, 또는 문서 블록을 포함한 content 블록 목록(DocReader)이다."""
    tools = [{
        "name": "submit",
        "description": "결과를 제출한다. 작업이 끝나면 반드시 이 도구로 한 번 제출한다.",
        "input_schema": schema,
        "strict": True,  # 스키마에 맞는 입력만 오도록 보장
    }]
    if search and WEB_SEARCH:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches})

    system = [
        # 공통 배경은 모든 에이전트가 같으므로 캐시한다
        {"type": "text", "text": background(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"<your_role>\n{role(role_name)}\n</your_role>"},
    ]
    messages: list[dict] = [{"role": "user", "content": user}]
    seen_urls: set[str] = set()
    start = time.time()

    for _ in range(MAX_LOOPS):
        resp = client().beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            # 안전 분류기가 요청을 거절하면 서버가 권장 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise AgentError(f"{role_name}: 요청이 처리되지 않았습니다 (refusal)")
        content = _echo_safe(resp.content)
        seen_urls |= _search_urls(content)

        submit = next((b for b in content if b.type == "tool_use" and b.name == "submit"), None)
        if submit is not None and resp.stop_reason != "max_tokens":
            return submit.input, round(time.time() - start, 1), seen_urls

        messages.append({"role": "assistant", "content": content})
        if resp.stop_reason == "pause_turn":  # 서버 검색이 길어져 잠시 멈춘 경우 그대로 이어간다
            continue
        # 제출하지 않고 끝났거나 잘렸으면 다시 제출을 요청한다
        pending = [b for b in content if b.type == "tool_use"]
        reminder = "작업을 마무리하고 submit 도구로 결과를 제출하라. 길면 줄여서 제출한다."
        if pending:
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                 "content": "입력이 잘렸거나 처리되지 않았습니다. " + reminder} for b in pending]})
        else:
            messages.append({"role": "user", "content": reminder})

    raise AgentError(f"{role_name}: {MAX_LOOPS}회 안에 결과를 제출하지 못했습니다")


# ---------------------------------------------------------------------------
# 스키마 도우미 (strict 도구는 모든 속성이 required, additionalProperties=false 여야 한다)
# ---------------------------------------------------------------------------

def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
CAP = {"type": "string", "enum": ["질문", "데이터", "가설", "소왓", "경영진", "도메인"]}
SOURCES = arr(obj(n=I, title=S, url=S))

INTERVIEW_SCHEMA = obj(
    hypothesis=S, confidence=I, gaps=S, ready=B,
    questions=arr(obj(title=S, question=S, capability=CAP, recommended=S)),
)
SCOUT_SCHEMA = obj(facts=arr(obj(fact=S, why_it_matters=S, sources=SOURCES)))
RESEARCH_SCHEMA = obj(queries=arr(S), findings=arr(obj(text=S, cites=arr(I))), sources=SOURCES)
SPEC_SCHEMA = obj(
    title=S, one_liner=S,
    scq=obj(situation=S, complication=S, question=S),
    decision=obj(who=S, what=S, when=S),
    hypotheses=arr(obj(id=S, hypothesis=S, alternative=S, reject_if=S, data=S)),
    metrics=arr(obj(name=S, definition=S, source=S, blind_spot=S)),
    tasks=arr(obj(id=S, sub_question=S, task=S, owner_bot=S, depends_on=S, mode=S, done_when=S)),
    deliverable=S,
    do_not=arr(S), stop_conditions=arr(S), owner_checkpoints=arr(S), limitations=arr(S),
)
PERSPECTIVE = {"type": "string", "enum": ["경영진", "현업", "데이터·컴플라이언스"]}
CRITIC_SCHEMA = obj(
    verdict={"type": "string", "enum": ["PASS", "FAIL"]},
    scores=arr(obj(perspective=PERSPECTIVE, score=I, comment=S)),
    questions=arr(obj(perspective=PERSPECTIVE, question=S, recommended=S)),
)
REPORT_SCHEMA = obj(title=S, markdown=S)
COACH_SCHEMA = obj(
    capability_scores=arr(obj(capability=CAP, score=I, evidence=S)),
    strength=S,
    improvements=arr(obj(capability=CAP, your_text=S, better=S, why=S)),
    next_time=S,
    recommended_usage_note=S,
    growth_notes=arr(obj(capability=CAP, kind={"type": "string", "enum": ["강점", "약점", "개선"]},
                         observation=S, next_time=S)),
)
DOC_SCHEMA = obj(docs=arr(obj(name=S, summary=S, key_points=arr(S), relevance=S, cautions=S)))
CASE_SCHEMA = obj(requester=S, dept=S, decision_maker=S, request=S, deadline=S, trap=S, target_capability=CAP)


def as_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)
