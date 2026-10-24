"""6단계 워크플로. 한 건(프로젝트)의 상태를 들고 단계마다 에이전트를 부른다.

1 요청 접수 → 2 진단 인터뷰(Interviewer ⇄ Scout 반복) → 3 다각도 리서치(Researcher 3개 병렬)
→ 4 명세 & 비판(Planner ⇄ Critic 반복) → 5 최종 승인(오너) → 6 산출물 완성(Reporter ∥ Coach)

상태는 서버 메모리에 있고, 단계가 끝날 때마다 outputs/projects/<id>.json 에도 저장한다.
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from agents import (CASE_SCHEMA, COACH_SCHEMA, CRITIC_SCHEMA, INTERVIEW_SCHEMA, REPORT_SCHEMA, RESEARCH_SCHEMA,
                    SCOUT_SCHEMA, SPEC_SCHEMA, AgentError, as_json, run_agent)
from tools import OUTPUT_DIR, growth_log_for_prompt, record_growth_note, save_document

MAX_INTERVIEW_ROUNDS = 3
READY_CONFIDENCE = 80
MAX_CRITIC_ROUNDS = 3
MAX_TRACK_RETRIES = 2
MAX_EXTRA_NOTES = 3

TRACKS = {
    "data": {"title": "데이터·지표",
             "focus": "이 질문에 쓸 데이터 소스(UBIST·IQVIA·HIRA·자사 출하·CRM 등), 지표 정의, 소스별 사각지대·시차, 데이터 사용 적정성"},
    "market": {"title": "시장·경쟁 이벤트",
               "focus": "관련 제품·경쟁품의 LOE·제네릭 등재·급여 확대/약가 인하·신약 출시·가이드라인 변화와 그 시점. 숫자 해석에 영향을 주는 이벤트 타임라인"},
    "method": {"title": "분석 방법·벤치마크",
               "focus": "이런 질문을 제약 BI가 보통 어떻게 푸는지(매출 분해·Source of Business·uptake 벤치마크·세그먼테이션 등), 경영진이 던지는 반문, 흔한 함정"},
}

REPORT_TYPES = {
    "exec": "경영진 보고형",
    "orchestrator": "오케스트레이터 요청서형",
    "reply": "현업 회신형",
}

PATTERNS = {
    "Interviewer": "반복 패턴", "Scout": "도구 사용 (빠른 탐색)",
    "Researcher": "병렬 처리 + 검색 도구", "ResearchTeam": "병렬 처리",
    "Planner": "계층적 작업 분해", "Critic": "검토·비판 패턴", "Reporter": "순차 처리",
    "Coach": "성장 기록", "Architect": "계층적 작업 분해", "CaseMaker": "케이스 생성",
}

PROJECT_DIR = OUTPUT_DIR / "projects"


class FlowError(Exception):
    """오너에게 그대로 보여줄 수 있는 진행 오류 (잘못된 단계에서 호출 등)."""


def make_case() -> tuple[dict, dict]:
    case, sec, _ = run_agent("case_maker", "연습용 가상 요청을 하나 만들어라.\n\n" + growth_log_for_prompt(),
                             CASE_SCHEMA, effort="medium")
    return case, {"agent": "CaseMaker", "seconds": sec, "pattern": PATTERNS["CaseMaker"]}


class Project:
    def __init__(self, intake: dict):
        self.id = uuid.uuid4().hex[:12]
        self.created = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.intake = intake  # requester, dept, decision_maker, request, deadline, mode(실전/훈련), trap(케이스면)
        self.step = 1
        self.rounds: list[dict] = []        # 인터뷰 라운드
        self.tracks: dict[str, dict] = {}   # 리서치 트랙
        self.research_memo = ""
        self.spec_rounds: list[dict] = []   # {spec, critic, answers}
        self.approved = False
        self.report: dict | None = None
        self.extra_reports: list[dict] = []
        self.coaching: dict | None = None
        self.log: list[dict] = []
        self.error: str | None = None

    # ---- 공통 ----
    def _log(self, agent: str, seconds: float, note: str = ""):
        self.log.append({"agent": agent, "seconds": seconds, "pattern": PATTERNS.get(agent.split("_")[0], ""),
                         "note": note, "at": datetime.now().strftime("%H:%M:%S")})

    def _context(self) -> str:
        """지금까지의 진행을 에이전트에게 넘길 문자열."""
        intake = {k: v for k, v in self.intake.items() if k != "trap"}  # 케이스 함정은 에이전트에게 숨긴다
        rounds = [{"hypothesis": r["hypothesis"], "qa": [{"q": q["question"], "a": q.get("answer", "")} for q in r["questions"]],
                   "owner_notes": r.get("notes", []), "scout_facts": [f["fact"] for f in r.get("facts", [])]}
                  for r in self.rounds]
        return f"<intake>\n{as_json(intake)}\n</intake>\n<interview>\n{as_json(rounds)}\n</interview>"

    def save(self):
        PROJECT_DIR.mkdir(parents=True, exist_ok=True)
        (PROJECT_DIR / f"{self.id}.json").write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["intake"] = {k: v for k, v in self.intake.items() if k != "trap" or self.step == 6}  # 함정은 끝나고 공개
        d["tracks_meta"] = {k: v["title"] for k, v in TRACKS.items()}
        d["report_types"] = REPORT_TYPES
        d["limits"] = {"interview": MAX_INTERVIEW_ROUNDS, "critic": MAX_CRITIC_ROUNDS,
                       "retries": MAX_TRACK_RETRIES, "notes": MAX_EXTRA_NOTES}
        return d

    # ---- 1·2단계: 인터뷰 ----
    def start(self):
        self._interview()
        self.step = 2
        self.save()

    def _interview(self):
        user = (f"{self._context()}\n<mode>{self.intake.get('mode', '실전')}</mode>\n"
                f"{growth_log_for_prompt()}\n\n인터뷰 {len(self.rounds) + 1}라운드를 진행하라.")
        out, sec, _ = run_agent("interviewer", user, INTERVIEW_SCHEMA)
        out["questions"] = out["questions"][:3]
        out["confidence"] = max(0, min(100, out["confidence"]))
        out["facts"], out["notes"] = [], []
        self.rounds.append(out)
        self._log("Interviewer", sec, f"{len(self.rounds)}라운드 · 신뢰도 {out['confidence']}%")

    def answer_interview(self, answers: list[dict], notes: list[str], skip: bool = False) -> None:
        """answers: [{answer, used_recommended}] (질문 순서대로). skip=True 면 바로 리서치로."""
        if self.step != 2:
            raise FlowError("인터뷰 단계가 아닙니다.")
        cur = self.rounds[-1]
        for q, a in zip(cur["questions"], answers):
            q["answer"] = a.get("answer", "").strip()
            q["used_recommended"] = bool(a.get("used_recommended"))
        cur["notes"] = [n.strip() for n in notes if n.strip()][:MAX_EXTRA_NOTES]

        done = skip or cur["ready"] or len(self.rounds) >= MAX_INTERVIEW_ROUNDS
        if not done:
            # 순차 처리: Scout 가 찾은 사실이 다음 질문의 입력이 된다
            facts, sec, urls = run_agent("scout", self._context() + "\n\n최근 라운드 답변에서 확인할 외부 사실을 찾아라.",
                                         SCOUT_SCHEMA, effort="low", search=True, max_searches=3)
            for f in facts["facts"]:
                f["sources"] = _mark_verified(f["sources"], urls)
            cur["facts"] = facts["facts"]
            self._log("Scout", sec, f"사실 {len(facts['facts'])}건")
            self._interview()
            done = self.rounds[-1]["ready"]
        if done:
            self.step = 3
            self.research()
        self.save()

    # ---- 3단계: 다각도 리서치 (병렬) ----
    def _run_track(self, key: str, instruction: str = "") -> dict:
        t = TRACKS[key]
        user = (f"{self._context()}\n<track>{t['title']}: {t['focus']}</track>\n"
                + (f"<owner_instruction>{instruction}</owner_instruction>\n" if instruction else "")
                + "\n이 트랙을 조사하라.")
        out, sec, urls = run_agent("researcher", user, RESEARCH_SCHEMA, effort="medium", search=True)
        out["sources"] = _mark_verified(out["sources"], urls)
        out["findings"] = [{**f, "selected": True} for f in out["findings"]]
        out["title"] = t["title"]
        self._log(f"Researcher_{key}", sec, f"발견 {len(out['findings'])}건")
        return out

    def research(self):
        start = datetime.now()
        with ThreadPoolExecutor(max_workers=len(TRACKS)) as pool:
            futures = {k: pool.submit(self._run_track, k) for k in TRACKS}
            for k, f in futures.items():
                try:
                    self.tracks[k] = {**f.result(), "retries": 0}
                except Exception as exc:  # 한 트랙이 실패해도 나머지는 살린다. 화면에서 다시 조사 가능
                    self.tracks[k] = {"title": TRACKS[k]["title"], "queries": [], "findings": [], "sources": [],
                                      "retries": 0, "error": str(exc)}
        self._log("ResearchTeam", round((datetime.now() - start).total_seconds(), 1), "3개 트랙 동시 조사")

    def retry_track(self, key: str, instruction: str):
        if self.step != 3 or key not in TRACKS:
            raise FlowError("리서치 단계가 아니거나 없는 트랙입니다.")
        used = self.tracks.get(key, {}).get("retries", 0)
        if used >= MAX_TRACK_RETRIES:
            raise FlowError(f"이 트랙은 이미 {MAX_TRACK_RETRIES}회 다시 조사했습니다.")
        self.tracks[key] = {**self._run_track(key, instruction), "retries": used + 1}
        self.save()

    # ---- 4단계: 명세 & 비판 (반복) ----
    def _selected_research(self) -> str:
        picked = []
        for t in self.tracks.values():
            for f in t["findings"]:
                if f.get("selected"):
                    refs = [s for s in t["sources"] if s["n"] in f["cites"]]
                    picked.append({"track": t["title"], "finding": f["text"], "sources": [s["url"] for s in refs]})
        return f"<research>\n{as_json(picked)}\n</research>\n<owner_memo>{self.research_memo}</owner_memo>"

    def build_spec(self, selections: dict[str, list[bool]], memo: str):
        if self.step != 3:
            raise FlowError("리서치 단계가 아닙니다.")
        for key, flags in selections.items():
            for f, on in zip(self.tracks.get(key, {}).get("findings", []), flags):
                f["selected"] = bool(on)
        self.research_memo = memo.strip()
        self._plan_and_critique(revision_note="")
        self.step = 4
        self.save()

    def _plan_and_critique(self, revision_note: str):
        prev = self.spec_rounds[-1] if self.spec_rounds else None
        user = f"{self._context()}\n{self._selected_research()}\n"
        if prev:
            qa = [{"perspective": q["perspective"], "question": q["question"], "owner_answer": q.get("answer", "")}
                  for q in prev["critic"]["questions"]]
            user += f"<previous_spec>\n{as_json(prev['spec'])}\n</previous_spec>\n<critic_qa>\n{as_json(qa)}\n</critic_qa>\n"
        user += revision_note + "\nBI 분석 명세를 " + ("고쳐 써라." if prev else "써라.")
        spec, sec, _ = run_agent("planner", user, SPEC_SCHEMA)
        self._log("Planner", sec, f"명세 {len(self.spec_rounds) + 1}판 · 작업 {len(spec['tasks'])}개")

        # 순차 처리: Critic 은 완성된 명세만 본다 (Planner 의 대화 맥락 없음 → 작성자 편향 없음)
        history = [q["question"] for r in self.spec_rounds for q in r["critic"]["questions"]]
        cuser = (f"<intake>\n{as_json({k: v for k, v in self.intake.items() if k != 'trap'})}\n</intake>\n"
                 f"<spec>\n{as_json(spec)}\n</spec>\n<previous_questions>\n{as_json(history)}\n</previous_questions>\n\n"
                 f"{len(self.spec_rounds) + 1}회차 비판 검증을 하라.")
        critic, csec, _ = run_agent("critic", cuser, CRITIC_SCHEMA)
        # 모델이 기준과 다르게 PASS 를 주는 경우를 코드로 한 번 더 막는다
        if any(s["score"] < 4 for s in critic["scores"]):
            critic["verdict"] = "FAIL"
        critic["questions"] = critic["questions"][:3]
        self.spec_rounds.append({"spec": spec, "critic": critic})
        self._log("Critic", csec, f"{len(self.spec_rounds)}회차 · {critic['verdict']}")

    def refine_spec(self, answers: list[dict], finish: bool):
        """answers: [{answer, used_recommended}]. finish=True 면 '이 정도면 충분함' → 승인 단계."""
        if self.step != 4:
            raise FlowError("명세 & 비판 단계가 아닙니다.")
        cur = self.spec_rounds[-1]
        for q, a in zip(cur["critic"]["questions"], answers):
            q["answer"] = a.get("answer", "").strip()
            q["used_recommended"] = bool(a.get("used_recommended"))
        # 기준 통과(PASS) 또는 최대 회차면 반복을 멈춘다
        if finish or cur["critic"]["verdict"] == "PASS" or len(self.spec_rounds) >= MAX_CRITIC_ROUNDS:
            self.step = 5
        else:
            self._plan_and_critique(revision_note="오너의 방어 답변을 반영하라. 답이 비어 있는 질문은 명세에서 스스로 보완하라.\n")
        self.save()

    # ---- 5·6단계: 승인 → 산출물 + 코칭 (병렬) ----
    def approve(self, report_type: str):
        if self.step != 5:
            raise FlowError("승인 단계가 아닙니다.")
        if report_type not in REPORT_TYPES:
            raise FlowError("산출물 형태를 골라 주세요.")
        self.approved = True
        with ThreadPoolExecutor(max_workers=2) as pool:
            fr = pool.submit(self._make_report, report_type, "Architect" if report_type == "orchestrator" else "Reporter")
            fc = pool.submit(self._coach)
            self.report = fr.result()
            try:
                self.coaching = fc.result()
            except AgentError as exc:  # 코칭이 실패해도 산출물은 살린다
                self.coaching = {"error": str(exc)}
        self.step = 6
        self.save()

    def extra_report(self, report_type: str):
        if self.step != 6 or report_type not in REPORT_TYPES:
            raise FlowError("산출물 단계가 아니거나 없는 형태입니다.")
        agent = "Architect" if report_type == "orchestrator" else "Reporter"
        self.extra_reports.append(self._make_report(report_type, agent))
        self.save()

    def _make_report(self, report_type: str, agent: str) -> dict:
        spec = self.spec_rounds[-1]["spec"]
        user = (f"<intake>\n{as_json({k: v for k, v in self.intake.items() if k != 'trap'})}\n</intake>\n"
                f"<spec>\n{as_json(spec)}\n</spec>\n<report_type>{REPORT_TYPES[report_type]}</report_type>\n\n산출물을 써라.")
        out, sec, _ = run_agent("reporter", user, REPORT_SCHEMA, effort="medium")
        self._log(agent, sec, REPORT_TYPES[report_type])
        if report_type == "orchestrator":
            from tools import handoff_to_orchestrator
            _, ev = handoff_to_orchestrator(out["title"], "", out["markdown"])
        else:
            _, ev = save_document("기타", f"{REPORT_TYPES[report_type]} {out['title']}", out["markdown"])
        return {"type": report_type, "label": REPORT_TYPES[report_type], "title": out["title"],
                "markdown": out["markdown"], "path": ev["path"]}

    def _coach(self) -> dict:
        owner = {
            "interview": [{"q": q["question"], "a": q.get("answer", ""), "used_recommended": q.get("used_recommended", False),
                           "recommended": q["recommended"]} for r in self.rounds for q in r["questions"]],
            "notes": [n for r in self.rounds for n in r.get("notes", [])],
            "research_memo": self.research_memo,
            "critic_defense": [{"q": q["question"], "a": q.get("answer", ""), "used_recommended": q.get("used_recommended", False),
                                "recommended": q["recommended"]} for s in self.spec_rounds for q in s["critic"]["questions"]],
            "final_critic_scores": self.spec_rounds[-1]["critic"]["scores"],
        }
        trap = f"<case_trap>{self.intake['trap']}</case_trap>\n" if self.intake.get("trap") else ""
        user = (f"{self._context()}\n<owner_inputs>\n{as_json(owner)}\n</owner_inputs>\n{trap}"
                f"<mode>{self.intake.get('mode', '실전')}</mode>\n{growth_log_for_prompt()}\n\n이번 건의 코칭 피드백을 써라."
                + (" 케이스 함정을 오너가 찾았는지도 평가하라." if trap else ""))
        out, sec, _ = run_agent("coach", user, COACH_SCHEMA)
        for n in out["growth_notes"][:2]:
            record_growth_note(n["capability"], n["kind"], n["observation"], n["next_time"])
        self._log("Coach", sec, f"성장 기록 {min(2, len(out['growth_notes']))}건")
        return out


def _mark_verified(sources: list[dict], urls: set[str]) -> list[dict]:
    """에이전트가 낸 출처가 실제 검색 결과에 있었는지 표시한다."""
    return [{**s, "verified": s["url"] in urls} for s in sources]
