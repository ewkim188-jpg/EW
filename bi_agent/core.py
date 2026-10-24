"""BI봇 대화 엔진. 웹 화면(server.py)과 CLI(agent.py)가 같이 쓴다.

BIAgent.ask() 는 화면에 보낼 이벤트(dict)를 하나씩 내보내는 제너레이터다.
    {"type": "text", "text": ...}        모델이 쓰는 글 (조각 단위)
    {"type": "working"}                  모델 호출 시작 (생각 중 표시용)
    {"type": "tool", "name": ...}        도구 실행
    {"type": "stage" | "doc" | "growth"} 도구가 만든 화면 이벤트 (tools.py 참고)
    {"type": "notice", "text": ...}      잘림·거절 등 안내
    {"type": "done"}                     한 턴 종료
"""

import re
from collections.abc import Iterator
from datetime import datetime

import anthropic

from review import GATED_DOC_TYPES, REVIEW_TOOL, ReviewState, review_draft
from tools import BASE_DIR, OUTPUT_DIR, TOOLS, execute_tool, growth_log_for_prompt, validate_input

ALL_TOOLS = TOOLS + [REVIEW_TOOL]

MODEL = "claude-opus-5-5"
MAX_TOKENS = 64_000
EFFORT = "high"  # 분석·코칭 품질이 중요하므로 high. 비용을 줄이려면 "medium"
MAX_TOOL_ROUNDS = 25  # 한 번의 질문에 도구를 연달아 부르는 최대 횟수

PROMPT_FILE = BASE_DIR / "prompts" / "bi_agent_prompt.md"
COACH_FILE = BASE_DIR / "prompts" / "coach.md"
COMPANY_FILE = BASE_DIR / "company_context.md"

MODES = ["실전", "훈련", "케이스"]


def build_system_prompt() -> str:
    """원본 프롬프트 + 회사 정보 + 코칭 레이어 + 성장 기록."""
    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    # 오너 전용이므로 '누구세요?' 모드 선택 블록은 뺀다 (원본 파일은 수정하지 않는다)
    prompt = re.sub(r"<mode_selection>.*?</mode_selection>\s*", "", prompt, flags=re.DOTALL)
    # company_context.md 에 오너가 채운 회사 정보로 <company_context> 블록을 교체
    if COMPANY_FILE.exists():
        company = COMPANY_FILE.read_text(encoding="utf-8").strip()
        prompt = re.sub(r"<company_context>.*?</company_context>", lambda _: company, prompt, flags=re.DOTALL)
    prompt += "\n" + COACH_FILE.read_text(encoding="utf-8")
    # 성장 기록은 세션마다 달라질 수 있으므로 맨 끝에 둔다 (앞부분 캐시를 깨지 않도록)
    prompt += "\n" + growth_log_for_prompt() + "\n"
    return prompt


def _echo_safe(content: list) -> list:
    """서버 측 폴백이 응답 중간에 일어났으면, 폴백 경계 앞의 thinking·tool_use 블록은 다시 보내면 안 된다."""
    fallback_idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if fallback_idx < 0:
        return content
    drop = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(content) if i >= fallback_idx or b.type not in drop]


class BIAgent:
    def __init__(self, mode: str = "실전"):
        self.client = anthropic.Anthropic()
        self.system = build_system_prompt()
        self.messages: list[dict] = []
        self.transcript: list[tuple[str, str]] = []  # 대화 저장용 (누가, 텍스트)
        self.mode = mode
        self._mode_sent: str | None = None  # 모델에게 마지막으로 알린 모드
        self.stage: str | None = None
        self.reviews = ReviewState()  # 문서별 검토 횟수·통과 여부

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"모드는 {MODES} 중 하나여야 합니다.")
        self.mode = mode

    def _call(self) -> Iterator[dict | anthropic.types.beta.BetaMessage]:
        """스트리밍으로 한 번 호출한다. 글 조각은 이벤트로 내보내고, 마지막에 완성된 메시지를 내보낸다."""
        with self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self.system,
            messages=self.messages,
            tools=ALL_TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},  # 시스템 프롬프트·이전 대화를 캐시해 비용 절감
            # 안전 분류기가 요청을 거절하면 서버가 권장 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "text", "text": text}
            yield stream.get_final_message()

    def ask(self, user_text: str) -> Iterator[dict]:
        # 모드가 바뀌었을 때만 태그를 붙인다 (매번 붙이면 대화가 지저분해진다)
        content = user_text
        if self.mode != self._mode_sent:
            content = f"<mode>{self.mode}</mode>\n{user_text}"
            self._mode_sent = self.mode
        self.messages.append({"role": "user", "content": content})
        self.transcript.append(("오너", user_text))
        answer_parts: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            yield {"type": "working"}
            response = None
            for item in self._call():
                if isinstance(item, dict):
                    yield item
                else:
                    response = item

            if response.stop_reason == "refusal":
                # 거절된 턴은 대화 기록에 남기지 않는다 (마지막 사용자 입력도 되돌림)
                yield {"type": "notice", "text": "요청이 처리되지 않았습니다. 표현을 바꿔 다시 시도해 주세요."}
                self.rollback_to_last_user_text()
                yield {"type": "done"}
                return

            # 응답 블록(thinking·tool_use 포함)을 그대로 기록에 붙인다 (폴백 경계 앞 블록만 정리)
            self.messages.append({"role": "assistant", "content": _echo_safe(response.content)})
            answer_parts += [b.text for b in response.content if b.type == "text"]

            if response.stop_reason == "max_tokens":
                yield {"type": "notice", "text": "응답이 길이 제한에 걸려 잘렸습니다. '이어서'라고 입력하면 계속합니다."}
                if any(b.type == "tool_use" for b in response.content):
                    # 잘린 도구 호출은 실행하지 않고 오류로 돌려준다
                    self.messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                         "content": "출력 길이 제한으로 도구 입력이 잘려 실행하지 않았습니다."}
                        for b in response.content if b.type == "tool_use"
                    ]})
                break

            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            # 여러 도구 호출 결과는 한 개의 user 메시지로 모아서 돌려준다
            results = []
            for block in tool_uses:
                yield {"type": "tool", "name": block.name}
                output, is_error, event = self._run_tool(block.name, block.input)
                if event:
                    if event["type"] == "stage":
                        self.stage = event["stage"]
                    yield event
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})
        else:
            yield {"type": "notice", "text": f"도구 호출이 {MAX_TOOL_ROUNDS}회를 넘어 멈췄습니다. '이어서'라고 입력하세요."}

        self.transcript.append(("BI봇", "\n".join(answer_parts)))
        yield {"type": "done"}

    def _run_tool(self, name: str, args: dict) -> tuple[str, bool, dict | None]:
        """검토 도구와 검토 게이트는 세션 상태가 필요해서 여기서 처리하고, 나머지는 tools.py 로 넘긴다."""
        if name == "review_draft":
            error = validate_input(REVIEW_TOOL["input_schema"], args)
            if error:
                return error, True, None
            output, event = review_draft(self.client, self.reviews, **args)
            return output, False, event

        # 기준을 넘을 때까지 반복: 검토를 통과하지 않은 문서는 저장·전달하지 못하게 막는다
        if name == "save_document" and isinstance(args, dict) and args.get("doc_type") in GATED_DOC_TYPES:
            if not self.reviews.can_save(args.get("title", "")):
                return ("아직 review_draft 를 통과하지 않은 문서입니다. 같은 title 로 review_draft 를 먼저 부르세요. "
                        "(검토 상태: " + self.reviews.status.get(args.get("title", ""), "검토 전") + ")"), True, None
        if name == "handoff_to_orchestrator" and not any(
                v in ("pass", "exhausted") for v in self.reviews.status.values()):
            return "검토를 통과한 문서가 없습니다. 넘길 문서를 review_draft 로 먼저 검토받으세요.", True, None

        return execute_tool(name, args)

    def rollback_to_last_user_text(self) -> None:
        """마지막 사용자 입력(문자열 메시지)까지 대화를 되돌린다. API 오류·거절 때 쓴다."""
        while self.messages:
            msg = self.messages.pop()
            if msg["role"] == "user" and isinstance(msg["content"], str):
                break
        if self.transcript and self.transcript[-1][0] == "오너":
            self.transcript.pop()
        self._mode_sent = None  # 모드 태그가 든 메시지가 지워졌을 수 있으므로 다음에 다시 알린다

    def save_transcript(self) -> str:
        OUTPUT_DIR.mkdir(exist_ok=True)
        path = OUTPUT_DIR / f"대화_{datetime.now():%Y%m%d_%H%M%S}.md"
        body = "\n\n".join(f"### {who}\n\n{text}" for who, text in self.transcript)
        path.write_text(f"# BI봇 대화 기록\n\n{body}\n", encoding="utf-8")
        return f"outputs/{path.name}"
