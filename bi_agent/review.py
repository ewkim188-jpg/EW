"""검토·비판 패턴: 초안 하나를 비평가 3명이 동시에(병렬) 검토한다.

BI봇이 문서 초안을 쓰면 review_draft 도구로 이 모듈을 부른다.
- 비평가 3명은 서로 독립이라 병렬로 돌린다 (ThreadPoolExecutor).
- 모두 PASS 해야 통과. 하나라도 FAIL 이면 BI봇이 고쳐서 다시 부른다 → 기준을 넘을 때까지 반복.
- 같은 문서는 최대 MAX_ROUNDS 번까지 검토한다. 그래도 못 넘으면 남은 문제를 오너에게 넘긴다.

비평가는 별도의 Claude 호출이다. 초안을 쓴 BI봇의 대화 맥락을 보지 않으므로 '작성자 편향' 없이 본다.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import anthropic

from tools import BASE_DIR

MODEL = "claude-opus-5-5"
CRITIC_EFFORT = "medium"  # 비평은 범위가 좁아 medium 으로 충분. 더 엄격하게 하려면 "high"
CRITIC_MAX_TOKENS = 16_000
MAX_ROUNDS = 3
PASS_SCORE = 4  # 5점 만점에 이 점수 이상이고 '치명'·'중요' 문제가 없어야 PASS

CRITICS = {
    "논리": {
        "capabilities": "질문·가설",
        "focus": (
            "- 핵심 질문이 누군가의 의사결정과 연결되는가? 요청받은 분석과 실제 필요한 분석이 섞여 있지 않은가?\n"
            "- 이슈 트리가 빠짐·겹침 없이(MECE) 쪼개졌는가?\n"
            "- 가설마다 대안 가설이 있고, 무엇이 나오면 기각되는지 정해져 있는가?\n"
            "- 상관을 인과처럼 쓴 곳이 없는가? 결론으로 가는 연결고리가 빠진 곳은?"
        ),
    },
    "데이터": {
        "capabilities": "데이터·도메인",
        "focus": (
            "- 지표마다 분자·분모·단위·시장 정의가 명확한가? 처방액/출하액/청구액이 섞이지 않았는가?\n"
            "- 소스별 사각지대(UBIST 원외 한정, 원내 비중 큰 항암제, 시차·커버리지)를 해석에 반영했는가?\n"
            "- 비교 기준(기저효과, 계절성, 영업일수, 제네릭 등재 시점)이 공정한가?\n"
            "- 급여·약가·LOE·경쟁 출시 같은 제약 이벤트를 빠뜨리지 않았는가?\n"
            "- 출처 없는 숫자를 사실처럼 쓴 곳이 없는가? 개인정보·공정경쟁규약상 문제 소지가 있는 데이터 활용은?"
        ),
    },
    "실행": {
        "capabilities": "소왓·경영진",
        "focus": (
            "- 결론이 먼저 오고, '그래서 무엇을'이 결정과 연결되는가?\n"
            "- 작업 분해가 계층적(목표 → 하위 질문 → 작업)이고, 작업마다 담당·선행 작업·완료 기준이 있는가?\n"
            "- 선행 작업이 없는 작업은 병렬 그룹으로 묶였고, 앞 결과에 따라 범위가 바뀌는 작업은 순차로 되어 있는가?\n"
            "- 받는 쪽(오케스트레이터·이데)이 되묻지 않고 바로 실행할 수 있을 만큼 구체적인가?\n"
            "- 본부장·대표가 던질 반문을 미리 막았는가? 빈칸이 [확인 필요]와 확인 방법으로 채워졌는가?"
        ),
    },
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "score": {"type": "integer", "description": "1~5점"},
        "summary": {"type": "string", "description": "한 줄 판정 이유"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["치명", "중요", "사소"]},
                    "where": {"type": "string", "description": "문서의 어느 부분"},
                    "problem": {"type": "string"},
                    "fix": {"type": "string", "description": "구체적인 수정안"},
                },
                "required": ["severity", "where", "problem", "fix"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "score", "summary", "issues"],
    "additionalProperties": False,
}


def _critic_system(name: str) -> str:
    company = (BASE_DIR / "company_context.md").read_text(encoding="utf-8")
    c = CRITICS[name]
    return (
        f"당신은 제약회사 BI 산출물의 '{name}' 비평가다. 담당 관점: {c['capabilities']}.\n"
        "다른 관점(다른 비평가가 본다)은 평가하지 않는다. 문서를 고쳐 쓰지 말고, 문제와 수정안만 낸다.\n\n"
        f"<check_points>\n{c['focus']}\n</check_points>\n\n"
        "<rules>\n"
        "- 깐깐하게 본다. 좋게 봐주지 않는다. 하지만 트집도 잡지 않는다: 결론이나 실행을 바꾸는 문제만 '치명'·'중요'다.\n"
        "- 수정안은 작성자가 바로 반영할 수 있게 구체적으로 쓴다 (\"더 명확히\" 같은 말 금지).\n"
        f"- {PASS_SCORE}점 이상이고 '치명'·'중요' 문제가 없을 때만 PASS.\n"
        "- 문서에 '[확인 필요]'로 표시된 빈칸은 정직한 표시이므로 감점하지 않는다. 확인 방법이 빠졌으면 지적한다.\n"
        "- 회사 내부 사정은 아래 정보 밖으로 추측하지 않는다.\n"
        "- 한국어로 답한다.\n"
        "</rules>\n\n"
        f"{company}"
    )


@dataclass
class ReviewState:
    """세션 하나의 검토 기록. 문서 제목별 검토 횟수와 마지막 결과."""
    rounds: dict[str, int] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)  # 제목 → "pass" | "fail" | "exhausted"

    def can_save(self, title: str) -> bool:
        return self.status.get(title) in ("pass", "exhausted")


def _run_critic(client: anthropic.Anthropic, name: str, doc_type: str, context: str, draft: str) -> dict:
    user = (
        f"<doc_type>{doc_type}</doc_type>\n"
        f"<background>\n{context}\n</background>\n"
        f"<draft>\n{draft}\n</draft>\n\n"
        "위 초안을 당신의 관점에서 검토하라."
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=CRITIC_MAX_TOKENS,
        system=_critic_system(name),
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": CRITIC_EFFORT, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
        cache_control={"type": "ephemeral"},  # 비평가 시스템 프롬프트는 매번 같으므로 캐시
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return {"critic": name, "verdict": "ERROR", "score": 0,
                "summary": f"비평가 응답 실패 ({response.stop_reason})", "issues": []}
    text = next(b.text for b in reversed(response.content) if b.type == "text")
    result = json.loads(text)
    # 모델이 판정 기준과 다르게 PASS 를 주는 경우를 코드로 한 번 더 막는다
    blocking = [i for i in result["issues"] if i["severity"] in ("치명", "중요")]
    if result["score"] < PASS_SCORE or blocking:
        result["verdict"] = "FAIL"
    result["critic"] = name
    return result


def review_draft(client: anthropic.Anthropic, state: ReviewState,
                 doc_type: str, title: str, context: str, draft: str) -> tuple[str, dict]:
    """비평가 3명을 병렬로 돌리고, (BI봇에게 돌려줄 결과, 화면 이벤트)를 돌려준다."""
    rnd = state.rounds.get(title, 0) + 1
    state.rounds[title] = rnd

    with ThreadPoolExecutor(max_workers=len(CRITICS)) as pool:
        futures = [pool.submit(_run_critic, client, name, doc_type, context, draft) for name in CRITICS]
        results = []
        for f in futures:
            try:
                results.append(f.result())
            except Exception as exc:  # 비평가 하나가 실패해도 나머지 결과는 살린다
                results.append({"critic": "?", "verdict": "ERROR", "score": 0,
                                "summary": f"{type(exc).__name__}: {exc}", "issues": []})

    passed = all(r["verdict"] == "PASS" for r in results)
    if passed:
        state.status[title] = "pass"
        instruction = "모든 비평가 PASS. 사소한 지적은 반영할 만하면 반영하고 save_document 로 저장해도 된다."
    elif rnd >= MAX_ROUNDS:
        state.status[title] = "exhausted"
        instruction = (f"최대 {MAX_ROUNDS}회 검토에도 통과하지 못했다. 더 반복하지 말고, 남은 '치명'·'중요' 문제를 "
                       "오너에게 표로 보여주고 어떻게 할지 판단을 받는다. 저장은 가능하지만 남은 문제를 문서 끝에 적는다.")
    else:
        state.status[title] = "fail"
        instruction = (f"{rnd}회차 FAIL. '치명'·'중요' 문제를 모두 반영해 초안을 고친 뒤, 같은 title 로 review_draft 를 다시 부른다. "
                       "반영하지 않기로 한 지적이 있으면 이유를 context 에 적는다.")

    payload = {"round": rnd, "max_rounds": MAX_ROUNDS, "passed": passed, "results": results,
               "instruction": instruction}
    event = {"type": "review", "title": title, "round": rnd, "max_rounds": MAX_ROUNDS,
             "passed": passed, "status": state.status[title], "results": results}
    return json.dumps(payload, ensure_ascii=False), event


REVIEW_TOOL = {
    "name": "review_draft",
    "description": (
        "문서 초안을 비평가 3명(논리·데이터·실행)에게 동시에 검토받는다. 기준을 넘을 때까지 고쳐서 다시 부른다 "
        f"(같은 title 로 최대 {MAX_ROUNDS}회). BI 분석 요청서·지표 정의서·모델 설계서·SFE·런칭 설계서는 "
        "이 검토를 통과해야 save_document 로 저장할 수 있다. 훈련 모드에서는 오너가 쓴 초안을 검토받는 데도 쓴다."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string", "description": "문서 종류. save_document 의 doc_type 과 같게"},
            "title": {"type": "string", "description": "문서 제목. 다시 검토받을 때와 저장할 때 같은 제목을 쓴다"},
            "context": {"type": "string", "description": "비평가가 알아야 할 배경: 목적, 의사결정자, 오너가 확인해 준 사실, 지난 회차 지적 중 반영하지 않은 것과 이유"},
            "draft": {"type": "string", "description": "검토받을 초안 전문 (마크다운)"},
        },
        "required": ["doc_type", "title", "context", "draft"],
        "additionalProperties": False,
    },
    "eager_input_streaming": True,
}

# 검토를 통과해야 저장할 수 있는 문서 종류 (리뷰 메모·기타는 검토 없이 저장 가능)
GATED_DOC_TYPES = {"BI 분석 요청서", "지표 정의서", "모델 설계서", "SFE·런칭 설계서"}
