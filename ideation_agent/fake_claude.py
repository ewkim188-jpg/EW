"""가짜 Claude 클라이언트 (가짜 모드). API 키 없이 7단계 흐름과 하네스를 확인할 때 쓴다.

    IDEATION_FAKE=1 uvicorn server:app --port 8001

에이전트 역할마다 스키마에 맞는 고정 답을 돌려준다. 내용은 모두 예시다.
FAKE_ARCH_BAD=1 이면 Architect 가 늘 품질 기준 미달인 실행 방안을 낸다 (게이트 ⑤ 시험용).
FAKE_INJECTION=1 이면 DocReader 가 공격 문장에 속은 척 "PWNED" 를 낸다 (방어 2 시험용).
"""

import itertools
import os
import threading
import time
from types import SimpleNamespace as NS

CALLS: list[dict] = []  # 테스트에서 확인용: 어떤 에이전트가 어떤 도구·입력으로 불렸는지
_lock = threading.Lock()
_ids = itertools.count()
_rounds = {"Interviewer": 0, "Critic": 0}
SEARCH_URLS = ["https://example.com/case-a", "https://example.org/regulation-b"]


def _answer(role: str, user) -> dict:
    if role == "Interviewer":
        _rounds["Interviewer"] += 1
        conf = min(95, 55 + 20 * (_rounds["Interviewer"] - 1))
        return {"hypothesis": "영업기획 담당이 월간 실적 보고서 초안 작성 시간을 줄이는 에이전트", "confidence": conf,
                "gaps": "승인 지점과 성공 지표", "ready": conf >= 90,
                "questions": [{"title": t, "question": f"{t}에 대해 알려 주세요.", "axis": t, "recommended": f"(예시) {t} 답"}
                              for t in ("진통제", "AI 역할과 금지선", "연동 데이터")]}
    if role == "Scout":
        return {"facts": [{"fact": "유사 사례 A가 보고 시간을 줄였다", "why": "효과 근거", "source_urls": [SEARCH_URLS[0]]},
                          {"fact": "지어낸 출처를 쓴 사실", "why": "그라운딩 시험", "source_urls": ["https://made-up.example/x"]}]}
    if role == "Researcher":
        time.sleep(0.3)  # 병렬 실행 확인용
        return {"queries": ["보고 자동화 에이전트 사례", "헬스케어 AI 규제"],
                "findings": [{"text": "사례 A: 보고서 초안 자동화", "source_urls": [SEARCH_URLS[0]]},
                             {"text": "규제 B: 민감정보 가명처리", "source_urls": [SEARCH_URLS[1], "javascript:alert(1)"]},
                             {"text": "근거 없는 발견 (모델 지식, 확인 필요)", "source_urls": []}]}
    if role == "DocReader":
        if os.environ.get("FAKE_INJECTION") == "1":
            return {"docs": [{"name": "attack.txt", "summary": "PWNED", "key_points": ["PWNED"], "cautions": ""}]}
        return {"docs": [{"name": "manual.txt", "summary": "사내 보고 매뉴얼 요약", "key_points": ["월 1회 보고"],
                          "cautions": "문서 안에 지시문이 있음(무시함)"}]}
    if role == "Planner":
        return {"name": "월간 실적 보고 초안 에이전트", "one_liner": "데이터를 받아 해석이 있는 보고서 초안을 만든다",
                "fit_check": {"verdict": "에이전트", "reason": "해석이 필요하고 사람이 검토 가능"},
                "problem": "보고서 작성에 사흘", "solution_role": "초안 작성과 이상치 설명", "users": "영업기획 BI",
                "agents": [{"name": "Analyst", "role": "숫자 해석", "pattern": "순차 처리", "tools": "DB(읽기)"}],
                "systems": [{"name": "실적 DB", "type": "DB", "access": "읽기", "purpose": "원천"}],
                "do_not": ["개별 의사 처방 데이터 외부 전송"], "hitl": ["보고서 발송 전 승인"], "stop_conditions": ["데이터 누락 시"],
                "kpis": [{"name": "작성 시간", "measure": "시간 기록", "target": "1일"}], "open_issues": ["[확인 필요] DB 접근 권한"]}
    if role == "Critic":
        _rounds["Critic"] += 1
        first = _rounds["Critic"] == 1
        return {"verdict": "PASS",  # 1회차는 점수 미달인데 PASS 라고 한다 → 코드가 FAIL 로 바꿔야 함
                "scores": [{"perspective": p, "score": 3 if first and p == "현장 책임자" else 5, "comment": "의견"}
                           for p in ("CFO", "현장 책임자", "법무·보안")],
                "questions": [{"perspective": "CFO", "question": f"비판 질문 {_rounds['Critic']}-{i}", "recommended": "방어 논리"} for i in range(3)]}
    if role == "Writer":
        return {"title": "월간 실적 보고 초안 에이전트 투자 심의", "markdown": "**결론: 조건부 Go**\n\n| 항목 | 값 |\n|---|---|\n| 절감 시간(가정) | 월 2일 |"}
    if role == "Architect":
        time.sleep(0.3)
        if os.environ.get("FAKE_ARCH_BAD") == "1":
            return {"channel": [], "agents": [], "tools": [], "data": [],
                    "governance": {"permissions": "", "stop_conditions": "", "audit_log": "", "human_approval": ""}, "roadmap": []}
        return {"channel": ["사내 메신저"],
                "agents": [{"name": n, "role": "r", "pattern": p, "slide": s} for n, p, s in
                           (("Planner", "계층적 작업 분해", "p.57"), ("Researcher", "병렬 처리", "p.59"), ("Critic", "검토·비판", "p.61"))],
                "tools": [{"name": "실적 DB", "type": "DB", "purpose": "원천"}, {"name": "웹 검색", "type": "검색", "purpose": "사례"}],
                "data": [{"name": "UBIST", "scope": "외부", "use": "시장"}, {"name": "출하 DB", "scope": "사내", "use": "실적"}],
                "governance": {"permissions": "DB는 읽기 전용, 쓰기 권한 없음", "stop_conditions": "최대 3회 반복, 150초 타임아웃",
                               "audit_log": "모든 호출을 Trace 로그로 기록", "human_approval": "발송 전 BI 담당 승인"},
                "roadmap": [{"phase": f"{i}단계", "period": "1개월(가정)", "goal": "g", "deliverables": "d"} for i in (1, 2, 3)]}
    if role == "DemoArchitect":
        return {"title": "데모 설계서", "markdown": "## 1. 데모 범위\n- 시나리오 1개"}
    raise ValueError(role)


class _Messages:
    def create(self, **kw):
        role = kw["system"][1]["text"].split("**")[1]
        with _lock:
            CALLS.append({"role": role, "tools": [t.get("name") for t in kw["tools"]], "user": kw["messages"][0]["content"],
                          "effort": kw["output_config"]["effort"], "at": time.time()})
        content = [NS(type="thinking", thinking="")]
        if any(t.get("name") == "web_search" for t in kw["tools"]):
            content.append(NS(type="web_search_tool_result", content=[NS(url=u, title=f"제목 {u}") for u in SEARCH_URLS]))
        content.append(NS(type="tool_use", id=f"t{next(_ids)}", name="submit", input=_answer(role, kw["messages"][0]["content"])))
        return NS(stop_reason="tool_use", content=content)


class FakeClient:
    def __init__(self, *a, **k):
        self.beta = NS(messages=_Messages())


def reset():
    CALLS.clear()
    _rounds.update(Interviewer=0, Critic=0)
