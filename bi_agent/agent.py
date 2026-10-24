"""BI봇 CLI. 웹 화면(server.py)과 같은 엔진(core.py)을 터미널에서 쓴다. 주로 점검용.

실행:
    python agent.py               # 실전 모드
    python agent.py --mode 훈련

대화 중 명령어:
    /mode 실전|훈련|케이스   모드 바꾸기
    /save                    대화를 outputs/ 에 저장
    /reset                   대화 초기화
    /exit                    종료
    여러 줄 입력: 첫 줄에 \"\"\" 를 입력하고, 끝낼 때 다시 \"\"\" 입력
"""

import argparse

import anthropic

from core import MODES, BIAgent
from tools import STAGES


def print_event(event: dict) -> None:
    kind = event["type"]
    if kind == "text":
        print(event["text"], end="", flush=True)
    elif kind == "stage":
        print(f"\n  ▶ 단계: {event['label']}  {event.get('note', '')}")
    elif kind == "review":
        marks = " · ".join(f"{r['critic']} {r['verdict']} {r['score']}/5" for r in event["results"])
        print(f"\n  ◆ 검토 {event['round']}/{event['max_rounds']}회차 [{event['title']}] {marks}")
    elif kind == "doc":
        print(f"\n  · 저장: {event['title']} (outputs/{event['path']})")
    elif kind == "growth":
        n = event["note"]
        print(f"\n  · 성장 기록: [{n['capability']}·{n['kind']}] {n['observation']}")
    elif kind == "notice":
        print(f"\n[{event['text']}]")
    elif kind == "done":
        print()


def read_user_input() -> str:
    first = input("\n나> ")
    if first.strip() != '"""':
        return first
    lines = []
    while (line := input()).strip() != '"""':
        lines.append(line)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BI봇 (CLI)")
    parser.add_argument("--mode", choices=MODES, default="실전")
    args = parser.parse_args()

    agent = BIAgent(mode=args.mode)
    print(f"BI봇을 시작합니다. 모드: {agent.mode}  단계: {' → '.join(STAGES.values())}")
    print("(/mode 실전|훈련|케이스 · /save · /reset · /exit · \"\"\" 여러 줄 입력)")

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
            agent = BIAgent(mode=agent.mode)
            print("대화를 초기화했습니다.")
            continue
        if text == "/save":
            print(f"저장 완료: {agent.save_transcript()}")
            continue
        if text.startswith("/mode"):
            try:
                agent.set_mode(text.split(maxsplit=1)[1].strip())
                print(f"모드: {agent.mode}")
            except (IndexError, ValueError):
                print(f"사용법: /mode {'|'.join(MODES)}")
            continue

        print("\nBI봇> ", end="", flush=True)
        try:
            for event in agent.ask(text):
                print_event(event)
        except anthropic.AuthenticationError:
            print("\n[인증 실패] ANTHROPIC_API_KEY 환경변수를 확인하세요.")
            break
        except anthropic.RateLimitError:
            print("\n[요청 한도 초과] 잠시 후 다시 시도하세요.")
            agent.rollback_to_last_user_text()
        except anthropic.APIStatusError as exc:
            print(f"\n[API 오류 {exc.status_code}] {exc.message}")
            agent.rollback_to_last_user_text()
        except anthropic.APIConnectionError:
            print("\n[연결 오류] 네트워크를 확인하세요.")
            agent.rollback_to_last_user_text()
        except Exception as exc:  # 도구 입력 JSON 파싱 실패 등
            print(f"\n[처리 중 오류] {type(exc).__name__}: {exc}")
            agent.rollback_to_last_user_text()


if __name__ == "__main__":
    main()
