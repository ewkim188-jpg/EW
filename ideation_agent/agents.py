"""Ideation Agent 의 에이전트들.

각 에이전트는 Claude 호출 한 번(+검색)이고, 결과를 strict 스키마의 submit 도구로 제출한다.
에이전트에게 주는 도구는 submit(결과 제출)과 web_search(Scout·Researcher만) 뿐이다.
파일 읽기·쓰기·셸 같은 도구는 어떤 에이전트에게도 주지 않는다 (하네스 1: 안전한 인프라, p.26).

| 에이전트        | 패턴                         | 교안      |
|-----------------|------------------------------|-----------|
| Interviewer     | 반복 패턴                    | p.60      |
| Scout           | 도구 사용 (빠른 탐색)        | p.27      |
| Researcher × 3  | 병렬 처리 + 검색 도구        | p.59·p.31 |
| DocReader       | 그라운딩                     | p.21      |
| Planner         | 계층적 작업 분해             | p.57      |
| Critic          | 검토·비판 패턴               | p.61      |
| Writer          | 순차 처리 (1쪽)              | p.58      |
| Architect       | 계층적 작업 분해 (2쪽 5계층) | p.57      |
| DemoArchitect   | 순차 처리 (데모 설계서)      | p.58·p.65 |
"""

import json
import os
import re
import threading
import time

import anthropic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16_000
MAX_AGENT_LOOPS = 8          # 에이전트 한 번에 검색·재촉을 포함해 주고받는 최대 횟수
AGENT_TIMEOUT_SEC = 150      # 에이전트 호출 한 번의 시간 한도 (하네스 4: 중단 조건)
LLM_SEMAPHORE = threading.Semaphore(8)  # 동시에 나가는 Claude 호출 최대 8개

# 회사 PC에서 외부 검색을 막아야 하면 IDEATION_WEB_SEARCH=0 으로 실행한다
WEB_SEARCH = os.environ.get("IDEATION_WEB_SEARCH", "1") != "0"

AGENTS_FILE = os.path.join(BASE_DIR, "prompts", "agents.md")
PACK_DIR = os.path.join(BASE_DIR, "packs")
PACKS = {"healthcare": "헬스케어 (한국)", "general": "일반 (산업 무관)"}

# 실행 로그에 보여줄 에이전트별 패턴과 교안 페이지 (블랙박스 방지, p.17)
TRACE_META = {
    "Interviewer": ("반복 패턴", "p.60"),
    "Scout": ("도구 사용 (빠른 탐색: web_search)", "p.27"),
    "Researcher": ("병렬 처리 + 검색 도구", "p.59·p.31"),
    "ResearchTeam": ("병렬 처리 (시장 / 리스크 / 데이터)", "p.59"),
    "DocReader": ("그라운딩 (사내 문서 요약 · 주입 방어)", "p.21"),
    "Planner": ("계층적 작업 분해 (명세)", "p.57"),
    "Critic": ("검토·비판 패턴 (CFO·현장·법무 시각)", "p.61"),
    "Writer": ("순차 처리 (1쪽 요약)", "p.58"),
    "Architect": ("계층적 작업 분해 (2쪽 5계층)", "p.57"),
    "QualityCheck": ("자동 피드백 루프 (품질 검사)", "p.26"),
    "DemoArchitect": ("순차 처리 (데모 설계서)", "p.58·p.65"),
}

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None and os.environ.get("IDEATION_FAKE") == "1":  # 가짜 모드: API 키 없이 흐름 확인
        from fake_claude import FakeClient
        _client = FakeClient()
    if _client is None:
        # 요청 한 번의 시간 한도. 넘으면 SDK 가 오류를 낸다
        _client = anthropic.Anthropic(timeout=AGENT_TIMEOUT_SEC, max_retries=1)
    return _client


class AgentError(Exception):
    pass


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _tag(text: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, flags=re.DOTALL)
    if not m:
        raise KeyError(f"<{name}> 블록이 없습니다")
    return m.group(1).strip()


def background(pack: str) -> str:
    """모든 에이전트 공통 배경 = 공통 규칙 + 산업 팩."""
    if pack not in PACKS:
        raise ValueError(f"없는 산업 팩: {pack}")
    common = _tag(_read(AGENTS_FILE), "common")
    return f"<common>\n{common}\n</common>\n\n{_read(os.path.join(PACK_DIR, pack + '.md')).strip()}"


def role(name: str) -> str:
    return _tag(_read(AGENTS_FILE), name)


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


def _search_results(content: list) -> dict[str, str]:
    """웹 검색 결과 메타데이터에서 {URL: 제목}을 뽑는다. 출처는 여기서만 만든다 (그라운딩, p.21)."""
    found = {}
    for b in content:
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            for r in b.content:
                if getattr(r, "url", None):
                    found[r.url] = getattr(r, "title", "") or r.url
    return found


def run_agent(name: str, role_name: str, pack: str, user: str | list, schema: dict, *,
              effort: str = "high", search: bool = False, max_searches: int = 4) -> tuple[dict, int, dict[str, str]]:
    """에이전트 하나를 돌려 (제출 결과, 걸린 ms, 검색으로 받은 {URL: 제목})을 돌려준다."""
    tools = [{
        "name": "submit",
        "description": "결과를 제출한다. 작업이 끝나면 반드시 이 도구로 한 번 제출한다.",
        "input_schema": schema,
        "strict": True,  # 스키마에 맞는 입력만 오도록 보장
    }]
    if search and WEB_SEARCH:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches})

    system = [
        # 공통 배경은 같은 팩이면 모든 에이전트가 같으므로 캐시한다
        {"type": "text", "text": background(pack), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"<your_role>\n{role(role_name)}\n</your_role>"},
    ]
    messages: list[dict] = [{"role": "user", "content": user}]
    results: dict[str, str] = {}
    start = time.time()

    for _ in range(MAX_AGENT_LOOPS):
        if time.time() - start > AGENT_TIMEOUT_SEC:
            raise AgentError(f"{name}: {AGENT_TIMEOUT_SEC}초 안에 끝나지 않았습니다")
        with LLM_SEMAPHORE:
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
            raise AgentError(f"{name}: 요청이 처리되지 않았습니다 (refusal)")
        content = _echo_safe(resp.content)
        results |= _search_results(content)

        submit = next((b for b in content if b.type == "tool_use" and b.name == "submit"), None)
        if submit is not None and resp.stop_reason != "max_tokens":
            return submit.input, int((time.time() - start) * 1000), results

        messages.append({"role": "assistant", "content": content})
        if resp.stop_reason == "pause_turn":  # 서버 검색이 길어져 잠시 멈춘 경우 그대로 이어간다
            continue
        reminder = "작업을 마무리하고 submit 도구로 결과를 제출하라. 길면 줄여서 제출한다."
        pending = [b for b in content if b.type == "tool_use"]
        if pending:
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                 "content": "입력이 잘렸거나 처리되지 않았습니다. " + reminder} for b in pending]})
        else:
            messages.append({"role": "user", "content": reminder})

    raise AgentError(f"{name}: {MAX_AGENT_LOOPS}회 안에 결과를 제출하지 못했습니다")


def ground_sources(items: list[dict], results: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """에이전트가 적은 source_urls 중 실제 검색 결과에 있던 것만 남겨 번호를 붙인다.
    돌려주는 값: (items: source_urls 대신 sources=[번호]), (sources: [{n, title, url}])."""
    numbered: dict[str, int] = {}
    out = []
    for it in items:
        nums = []
        for u in it.pop("source_urls", []):
            if u in results:  # 검색 결과에 없던 URL(지어낸 출처)은 버린다
                numbered.setdefault(u, len(numbered) + 1)
                nums.append(numbered[u])
        out.append({**it, "sources": sorted(set(nums))})
    sources = [{"n": n, "title": results[u], "url": u} for u, n in numbered.items()]
    return out, sources


# ---------------------------------------------------------------------------
# 스키마 (strict 도구는 모든 속성이 required, additionalProperties=false 여야 한다)
# ---------------------------------------------------------------------------

def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
URLS = arr(S)
PATTERN = enum("계층적 작업 분해", "순차 처리", "병렬 처리", "반복 패턴", "검토·비판", "Human-in-the-Loop", "도구 사용", "그라운딩")
SLIDE = enum("p.57", "p.58", "p.59", "p.60", "p.61", "p.62")
TOOL_TYPE = enum("MCP", "API", "검색", "RAG", "DB")
PERSPECTIVE = enum("CFO", "현장 책임자", "법무·보안")

INTERVIEW_SCHEMA = obj(
    hypothesis=S, confidence=I, gaps=S, ready=B,
    questions=arr(obj(title=S, question=S, axis=S, recommended=S)),
)
SCOUT_SCHEMA = obj(facts=arr(obj(fact=S, why=S, source_urls=URLS)))
RESEARCH_SCHEMA = obj(queries=arr(S), findings=arr(obj(text=S, source_urls=URLS)))
DOC_SCHEMA = obj(docs=arr(obj(name=S, summary=S, key_points=arr(S), cautions=S)))
SPEC_SCHEMA = obj(
    name=S, one_liner=S,
    fit_check=obj(verdict=enum("에이전트", "단순 자동화가 낫다", "사람 업무로 남긴다"), reason=S),
    problem=S, solution_role=S, users=S,
    agents=arr(obj(name=S, role=S, pattern=PATTERN, tools=S)),
    systems=arr(obj(name=S, type=TOOL_TYPE, access=enum("읽기", "쓰기", "읽기·쓰기"), purpose=S)),
    do_not=arr(S), hitl=arr(S), stop_conditions=arr(S),
    kpis=arr(obj(name=S, measure=S, target=S)),
    open_issues=arr(S),
)
CRITIC_SCHEMA = obj(
    verdict=enum("PASS", "FAIL"),
    scores=arr(obj(perspective=PERSPECTIVE, score=I, comment=S)),
    questions=arr(obj(perspective=PERSPECTIVE, question=S, recommended=S)),
)
WRITER_SCHEMA = obj(title=S, markdown=S)
ARCHITECT_SCHEMA = obj(
    channel=arr(S),
    agents=arr(obj(name=S, role=S, pattern=PATTERN, slide=SLIDE)),
    tools=arr(obj(name=S, type=TOOL_TYPE, purpose=S)),
    data=arr(obj(name=S, scope=enum("사내", "외부"), use=S)),
    governance=obj(permissions=S, stop_conditions=S, audit_log=S, human_approval=S),
    roadmap=arr(obj(phase=S, period=S, goal=S, deliverables=S)),
)
DEMO_SCHEMA = obj(title=S, markdown=S)


def as_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)
