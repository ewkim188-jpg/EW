"""제약 BI 팀 전담 AI 에이전트 (CLI).

실행:
    python agent.py                # 모드는 에이전트가 첫 대화에서 판단
    python agent.py --mode owner   # BI 담당자(오너) 모드로 시작
    python agent.py --mode customer

대화 중 명령어:
    /exit   종료
    /reset  대화 초기화
    /save   지금까지의 대화를 outputs/ 에 마크다운으로 저장
    여러 줄 입력: 첫 줄에 \"\"\" 를 입력하고, 끝낼 때 다시 \"\"\" 입력
"""

import argparse
import re
from datetime import datetime

import anthropic

from tools import BASE_DIR, OUTPUT_DIR, TOOLS, agents_for_prompt, execute_tool

MODEL = "claude-opus-5-5"
MAX_TOKENS = 64_000
EFFORT = "high"  # 분석·리뷰 품질이 중요하므로 high. 비용을 줄이려면 "medium"
MAX_TOOL_ROUNDS = 25  # 한 번의 질문에 도구를 연달아 부르는 최대 횟수

PROMPT_FILE = BASE_DIR / "prompts" / "bi_agent_prompt.md"
COMPANY_FILE = BASE_DIR / "company_context.md"

TOOL_GUIDE = """
<agent_team>
당신은 오너의 BI Agent Team에서 오케스트레이터 자리에 있다. 데이터를 직접 돌리지 않는다.
당신의 일은 BI의 첫 창구이자 지휘자로서: 문제를 정의하고 → 알맞은 봇에게 정확한 요청서를 넘기고 →
돌아온 결과를 해석해 "그래서 무엇을"까지 끌고 가는 것이다.

{agents}

일하는 순서 (가설-검증 루프):
1. 가설 수립: 모드별 흐름(오너 모드 분석 설계 / 내부고객 모드 STEP 1~3)으로 핵심 질문과 원인 가설을 구조화한다.
2. 증거 수집: 숫자는 분석봇, 외부 사실(경쟁·규제·학회)은 이데에게 create_handoff로 요청서를 만든다.
   가설별로 필요한 증거를 번호 붙여 나눈다. 서로 의존하지 않는 요청은 동시에 만든다.
3. 해석: 오너가 결과를 붙여넣으면 가설마다 채택/부분 채택/기각을 판정하고, 숫자 → 왜 → 그래서 무엇을 순서로 정리한다.
   대응 전략을 깊게 짜야 하면 전략봇에게, 정식 보고서로 만들어야 하면 보고서봇에게 넘긴다.
4. 발행 게이트: 숫자나 사실 주장이 담긴 산출물은 발행 전에 반드시 리뷰봇(정확성) → 컴봇(규제) 순서로 검토 요청서를 만든다.
   게이트를 통과했다는 회신이 오기 전에는 "발행 가능"이라고 말하지 않는다.
5. 저장: 요청서·해석·보고 문안은 save_output으로 저장한다.

원칙:
- 분석봇·이데의 결과로 확인되지 않은 숫자를 사실처럼 말하지 않는다. 요청 전 단계의 숫자는 "가정" 또는 "예시"로 표시한다.
- 언론 추정치는 "(언론 추정, 실데이터 검증 필요)"로 표기한다.
- 당신이 직접 계산·검수하지 않는다. 해당 봇이 있으면 반드시 요청서로 넘긴다.
- 최종 결정은 오너가 한다. 당신은 권고까지만 한다.

분석봇 요청서 양식 (create_handoff의 request에 이 구조로 쓴다):
```
## 목적
누가 무엇을 결정하는 데 쓰는지 한 줄
## 핵심 질문
## 검증할 가설
1. ...
## 계산 요청
| # | 지표 | 정의(분자/분모) | 단위 | 기간 | 쪼개는 기준 |
## 범위
제품 / 경쟁품·시장 정의 / 지역·채널
## 데이터 소스
UBIST / IQVIA / HIRA / 자사 출하 등과, 소스를 고른 이유 (예: 항암제는 원내 비중이 커서 UBIST 제외)
## 산출 형태
표 / 차트 / 원자료 등
## 확인해야 할 데이터 이슈
시차, 커버리지, 정의 차이, 이상치
```

이데 요청서 양식:
```
## 목적
## 확인할 사실·이벤트
1. ...
## 범위
대상 제품·경쟁사 / 기간 / 소스 (뉴스·식약처·심평원·학회 등)
## 회신 형식
항목별 사실 + 출처 링크 + 날짜, 확인 못한 것은 "미확인"
```

리뷰봇 요청서 양식:
```
## 검수 대상
산출물 원문
## 근거 자료
수치의 원본(분석봇 결과·데이터 소스)과 출처 링크
## 중점 검수 항목
재검산할 숫자, 확인할 출처, 논리 비약이 의심되는 지점
## 회신 요청
PASS / FAIL과 FAIL 시 구체적 수정 지시
```

컴봇 요청서 양식:
```
## 검토 대상
문안 원문, 자료, 또는 데이터 활용 방식
## 사용처
내부 보고 / 영업 현장 / 대외 / 학술 등
## 우려 지점
허가사항 범위, 비교 표현, 개별 의사·병원 데이터 활용 등
## 회신 요청
가능 여부와 수정안
```
</agent_team>
"""

MODE_HINT = {
    "owner": "이번 대화의 상대는 BI 담당자(오너)다. [오너 모드]로 시작한다.",
    "customer": "이번 대화의 상대는 내부고객(현업)이다. [내부고객 모드 · STEP 1]로 시작한다.",
}


def build_system_prompt(mode: str | None) -> str:
    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    # company_context.md 에 오너가 채운 회사 정보로 프롬프트의 <company_context> 블록을 교체
    if COMPANY_FILE.exists():
        company = COMPANY_FILE.read_text(encoding="utf-8").strip()
        prompt = re.sub(
            r"<company_context>.*?</company_context>",
            lambda _: company,
            prompt,
            flags=re.DOTALL,
        )
    prompt += "\n" + TOOL_GUIDE.replace("{agents}", agents_for_prompt())
    if mode:
        prompt += f"\n<session_mode>\n{MODE_HINT[mode]}\n</session_mode>\n"
    return prompt


class BIAgent:
    def __init__(self, mode: str | None = None):
        self.client = anthropic.Anthropic()
        self.system = build_system_prompt(mode)
        self.messages: list[dict] = []
        self.transcript: list[tuple[str, str]] = []  # /save 용 (역할, 텍스트)

    def reset(self):
        self.messages = []
        self.transcript = []

    def _call(self):
        """스트리밍으로 한 번 호출하고 텍스트는 실시간 출력, 완성된 메시지를 돌려준다."""
        with self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self.system,
            messages=self.messages,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},  # 시스템 프롬프트·이전 대화를 캐시해 비용 절감
            # 안전 분류기가 요청을 거절하면 서버가 권장 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            return stream.get_final_message()

    def ask(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        self.transcript.append(("사용자", user_text))
        answer_parts: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            print("\nBI 에이전트> ", end="", flush=True)
            response = self._call()
            print()

            if response.stop_reason == "refusal":
                # 거절된 턴은 대화 기록에 남기지 않는다 (마지막 사용자 입력도 되돌림)
                print("[요청이 처리되지 않았습니다. 표현을 바꿔 다시 시도해 주세요.]")
                self._rollback_to_last_user_text()
                return

            # 응답 블록(thinking·tool_use 포함)을 수정 없이 그대로 기록에 붙인다
            self.messages.append({"role": "assistant", "content": response.content})
            answer_parts += [b.text for b in response.content if b.type == "text"]

            if response.stop_reason == "max_tokens":
                print("[응답이 길이 제한에 걸려 잘렸습니다. '이어서'라고 입력하면 계속합니다.]")
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
                print(f"  · 도구 실행: {block.name}")
                output, is_error = execute_tool(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                })
            self.messages.append({"role": "user", "content": results})
        else:
            print(f"[도구 호출이 {MAX_TOOL_ROUNDS}회를 넘어 멈췄습니다. 계속하려면 '이어서'라고 입력하세요.]")

        self.transcript.append(("BI 에이전트", "\n".join(answer_parts)))

    def _rollback_to_last_user_text(self):
        while self.messages:
            msg = self.messages.pop()
            if msg["role"] == "user" and isinstance(msg["content"], str):
                break
        if self.transcript:
            self.transcript.pop()

    def save_transcript(self) -> str:
        OUTPUT_DIR.mkdir(exist_ok=True)
        path = OUTPUT_DIR / f"대화_{datetime.now():%Y%m%d_%H%M%S}.md"
        body = "\n\n".join(f"### {who}\n\n{text}" for who, text in self.transcript)
        path.write_text(f"# BI 에이전트 대화 기록\n\n{body}\n", encoding="utf-8")
        return str(path.relative_to(BASE_DIR))


def read_user_input() -> str:
    first = input("\n나> ")
    if first.strip() != '"""':
        return first
    lines = []
    while (line := input()).strip() != '"""':
        lines.append(line)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="제약 BI 팀 전담 AI 에이전트")
    parser.add_argument("--mode", choices=["owner", "customer"], help="대화 모드를 미리 지정")
    args = parser.parse_args()

    agent = BIAgent(mode=args.mode)
    print("BI 에이전트를 시작합니다. (/exit 종료 · /reset 초기화 · /save 대화 저장 · \"\"\" 여러 줄 입력)")

    while True:
        try:
            text = read_user_input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/reset":
            agent.reset()
            print("대화를 초기화했습니다.")
            continue
        if text == "/save":
            print(f"저장 완료: {agent.save_transcript()}")
            continue

        try:
            agent.ask(text)
        except anthropic.AuthenticationError:
            print("\n[인증 실패] ANTHROPIC_API_KEY 환경변수를 확인하세요.")
            break
        except anthropic.RateLimitError:
            print("\n[요청 한도 초과] 잠시 후 다시 시도하세요.")
            agent._rollback_to_last_user_text()
        except anthropic.APIStatusError as exc:
            print(f"\n[API 오류 {exc.status_code}] {exc.message}")
            agent._rollback_to_last_user_text()
        except anthropic.APIConnectionError:
            print("\n[연결 오류] 네트워크를 확인하세요.")
            agent._rollback_to_last_user_text()


if __name__ == "__main__":
    main()
