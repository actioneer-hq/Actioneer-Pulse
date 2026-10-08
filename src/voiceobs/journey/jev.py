"""Jev judge (System-One decision model): every classification field, one request per call.

`jev_questions` turns a journey into the question list ONCE per script version; every call sends
the same questions with its transcript as the state, and Jev answers them all in parallel.
`to_judgment` maps Jev's numbers (yes/no probability, choice distribution, score) to typed results.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from voiceobs.journey.model import Journey
from voiceobs.judge.schema import AnsweredBy, Objective, Sentiment

THRESHOLD = 0.5
COMPLETED = "Completed"  # ended_by when the call ended normally (no branch caused it)
LANGUAGES = ["Hindi", "English", "Bengali", "Gujarati", "Kannada", "Malayalam", "Marathi",
             "Odia", "Punjabi", "Tamil", "Telugu", "Urdu"]

_ANSWERED_BY = {
    "a live person": AnsweredBy.HUMAN,
    "the phone's own assistant screening the call (asks for name and reason)": AnsweredBy.CALL_SCREENER,
    "a recording or carrier announcement (e.g. 'the person you are trying to reach is not available')":
        AnsweredBy.RECORDING,
    "voicemail": AnsweredBy.VOICEMAIL,
    "an IVR menu": AnsweredBy.IVR,
    "cannot tell": AnsweredBy.UNKNOWN,
}
_OBJECTIVE = {
    "fully achieved": Objective.ACHIEVED,
    "partly achieved (a softer outcome, e.g. a callback or a link sent)": Objective.PARTIAL,
    "not achieved": Objective.NOT_ACHIEVED,
}
_SENTIMENT_SCALE = (-2.0, 2.0)  # very negative .. very positive

# Why a failure happened — decides where the fix goes (script / model training data). Derived in code
# (journey/merge.py), never asked: every journey item comes from the script, so a failed one was not
# followed; only what the script never covered (in_script=false, unscripted moments) is a script gap.
Cause = Literal["script_gap", "not_followed"]


# ── question spec ────────────────────────────────────────────────────────────────────
class JevQuestion(BaseModel):
    key: str                                      # stable join key
    kind: Literal["yes_no", "choice", "score"]
    text: str                                     # the statement / question put to Jev
    options: list[str] | None = None              # choice only
    scale: tuple[float, float] | None = None      # score only


def _branch_key(stage: str | None, if_: str) -> str:
    return f"branch:{stage or 'anytime'}:{if_}"


def jev_questions(j: Journey, languages: list[str] = LANGUAGES) -> list[JevQuestion]:
    q = [
        JevQuestion(key="answered_by", kind="choice", text="Who or what did the agent talk to?",
                    options=list(_ANSWERED_BY)),
        JevQuestion(key="language.primary", kind="choice",
                    text="Which language did the customer mostly speak?", options=languages),
        *[JevQuestion(key=f"language.secondary:{lang}", kind="yes_no",
                      text=f"Besides the main language, {lang} is also used in the conversation.")
          for lang in languages],
        *[JevQuestion(key=f"stage:{s.stage}", kind="yes_no",
                      text=f"In this call, this already happened: {s.done_when} "
                           f"(the stage '{s.stage}'). Answer no if it did not happen.")
          for s in j.funnel],
    ]
    for key, part in (("opening", j.opening), ("closing", j.closing)):
        if part:
            q.append(JevQuestion(key=f"{key}:done", kind="yes_no",
                                 text=f"In this call, this happened: {part.done_when}. "
                                      "Answer no if it did not happen."))
    for stage, b in j.branches():
        if getattr(b, "standard", False):
            continue  # Pulse's standard rules have their own questions below
        where = f" during '{stage}'" if stage else ""
        key = _branch_key(stage, b.if_)
        q.append(JevQuestion(key=f"{key}:happened", kind="yes_no",
                             text=f"In this call{where}, the customer themselves did this: {b.if_}. "
                                  "Answer no if it never came up, or if only the agent brought it up."))
        q.append(JevQuestion(key=f"{key}:handled", kind="yes_no",
                             text=f"In this call, when this happened ({b.if_}), the agent did this: "
                                  f"{b.then}. Answer no if the agent did not, or if it never came up."))
    for g in j.guardrails:
        q.append(JevQuestion(key=f"guardrail:{g.rule}", kind="yes_no",
                             text=f"In this call, an agent line clearly breaks this rule: {g.rule}. "
                                  "Answer yes only if you can point to that line; answer no if the "
                                  "situation the rule is about never came up."))
    q += [
        JevQuestion(key="standard:non_human_continued", kind="yes_no",
                    text="In this call, the agent kept talking or pitching to a machine (IVR, voicemail, "
                         "recording or the phone's own assistant) instead of identifying once and ending. "
                         "Answer no if a live person answered."),
        JevQuestion(key="standard:callback_requested", kind="yes_no",
                    text="In this call, the customer asked to be called back. Answer no if they did not."),
        JevQuestion(key="standard:callback_handled", kind="yes_no",
                    text="In this call, the agent confirmed a specific callback time. Answer no if it did "
                         "not, or if no callback was asked for."),
        JevQuestion(key="standard:escalation_requested", kind="yes_no",
                    text="In this call, the customer asked to speak to a human. Answer no if they did not."),
        JevQuestion(key="standard:escalation_handled", kind="yes_no",
                    text="In this call, the agent acknowledged the request for a human and handed over or "
                         "arranged a callback. Answer no if it did not, or if no human was asked for."),
        JevQuestion(key="objective", kind="choice", text=f"Objective: {j.objective}. Was it…",
                    options=list(_OBJECTIVE)),
        JevQuestion(key="ended_by", kind="choice", text="What ended the call?",
                    options=[b.if_ for _, b in j.branches()] + [COMPLETED]),
        JevQuestion(key="sentiment", kind="score",
                    text="The customer's overall sentiment (-2 very negative … +2 very positive).",
                    scale=_SENTIMENT_SCALE),
    ]
    return q


# ── typed results ────────────────────────────────────────────────────────────────────
class StageReached(BaseModel):
    stage: str
    reached: bool
    p: float


class BranchResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stage: str | None                       # None = anytime branch
    if_: str = Field(alias="if")
    happened: bool
    handled: bool | None                    # None when it didn't happen
    p_happened: float
    p_handled: float | None
    cause: Cause | None = None              # set by merge when it happened and was not handled


class GuardrailResult(BaseModel):
    rule: str
    broken: bool
    p: float
    cause: Cause | None = None              # set by merge when broken


class StandardRules(BaseModel):
    non_human_continued: bool | None        # None when a live person answered
    callback_requested: bool
    callback_handled: bool | None
    escalation_requested: bool
    escalation_handled: bool | None
    callback_cause: Cause | None = None     # set by merge when requested and not handled
    escalation_cause: Cause | None = None


class JevJudgment(BaseModel):
    format: Literal["full"] = "full"
    answered_by: AnsweredBy
    answered_by_p: float
    primary_language: str
    secondary_languages: list[str]
    opening_done: bool | None = None    # None when the journey has no opening
    furthest_stage: str | None          # last stage reached (None = ended during the first)
    stages: list[StageReached]
    closing_done: bool | None = None    # None when the journey has no closing
    branches: list[BranchResult]
    guardrails: list[GuardrailResult]
    standard: StandardRules
    objective_achieved: Objective
    ended_by: str
    sentiment: Sentiment


# Jev answers: yes_no -> probability; choice -> {option: probability}; score -> number.
JevAnswers = dict[str, float | dict[str, float]]


def _pick(dist: dict[str, float]) -> tuple[str, float]:
    best = max(dist, key=dist.get)
    return best, dist[best]


def _sentiment(score: float) -> Sentiment:
    order = [Sentiment.VERY_NEGATIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL,
             Sentiment.POSITIVE, Sentiment.VERY_POSITIVE]
    lo, hi = _SENTIMENT_SCALE
    i = round((min(max(score, lo), hi) - lo) / (hi - lo) * (len(order) - 1))
    return order[i]


def to_judgment(j: Journey, a: JevAnswers, languages: list[str] = LANGUAGES) -> JevJudgment:
    def yes(key: str) -> float:
        return float(a.get(key, 0.0))

    who, who_p = _pick(a["answered_by"])
    answered_by = _ANSWERED_BY[who]
    primary, _ = _pick(a["language.primary"])
    branches = []
    for stage, b in j.branches():
        if getattr(b, "standard", False):
            continue
        key = _branch_key(stage, b.if_)
        p_h = yes(f"{key}:happened")
        happened = p_h >= THRESHOLD
        p_ok = yes(f"{key}:handled") if happened else None
        handled = (p_ok >= THRESHOLD) if happened else None
        branches.append(BranchResult(stage=stage, **{"if": b.if_}, happened=happened,
                                     handled=handled, p_happened=p_h, p_handled=p_ok))
    furthest, stages = _funnel(j, yes)
    human = answered_by == AnsweredBy.HUMAN
    cb, esc = yes("standard:callback_requested"), yes("standard:escalation_requested")
    return JevJudgment(
        answered_by=answered_by, answered_by_p=who_p,
        primary_language=primary,
        secondary_languages=[lang for lang in languages if lang != primary
                             and yes(f"language.secondary:{lang}") >= THRESHOLD],
        opening_done=(yes("opening:done") >= THRESHOLD) if j.opening else None,
        closing_done=(yes("closing:done") >= THRESHOLD) if j.closing else None,
        furthest_stage=furthest, stages=stages,
        branches=branches,
        guardrails=[GuardrailResult(rule=g.rule, broken=yes(f"guardrail:{g.rule}") >= THRESHOLD,
                                    p=yes(f"guardrail:{g.rule}"))
                    for g in j.guardrails],
        standard=_standard(yes, human, cb, esc),
        objective_achieved=_OBJECTIVE[_pick(a["objective"])[0]],
        ended_by=_pick(a["ended_by"])[0],
        sentiment=_sentiment(float(a.get("sentiment", 0.0))),
    )


def _funnel(j: Journey, yes) -> tuple[str | None, list[StageReached]]:
    """Furthest stage = scanning from the LAST stage back, the first one reached. Every stage up to it
    counts as reached (a call can't get to stage 4 without passing 1-3), so the funnel has no holes."""
    names = [s.stage for s in j.funnel]
    last = next((i for i in range(len(names) - 1, -1, -1)
                 if yes(f"stage:{names[i]}") >= THRESHOLD), -1)
    stages = [StageReached(stage=n, reached=i <= last, p=yes(f"stage:{n}")) for i, n in enumerate(names)]
    return (names[last] if last >= 0 else None), stages


def _standard(yes, human: bool, cb: float, esc: float) -> StandardRules:
    cb_ok = (yes("standard:callback_handled") >= THRESHOLD) if cb >= THRESHOLD else None
    esc_ok = (yes("standard:escalation_handled") >= THRESHOLD) if esc >= THRESHOLD else None
    return StandardRules(
        non_human_continued=None if human else yes("standard:non_human_continued") >= THRESHOLD,
        callback_requested=cb >= THRESHOLD, callback_handled=cb_ok,
        escalation_requested=esc >= THRESHOLD, escalation_handled=esc_ok,
    )


# ── short calls (<= SHORT_MAX customer turns): enum-only, decision model only ─────────
SHORT_MAX = 3
OPENING_END = "Ended during the opening"


class ShortJudgment(BaseModel):
    format: Literal["short"] = "short"
    answered_by: AnsweredBy
    answered_by_p: float
    primary_language: str
    furthest_stage: str | None          # None = ended during the opening
    objective_achieved: Objective
    sentiment: Sentiment


def customer_turns(transcript: dict) -> int | None:
    """How many times the customer spoke, from a `transcript.resolve` dict (None = can't tell)."""
    lines = transcript.get("lines")
    if lines is not None:
        return sum(1 for ln in lines if ln.get("role") == "caller" and (ln.get("text") or "").strip())
    text = transcript.get("text")
    if text:
        return sum(1 for ln in text.splitlines()
                   if ln.strip().lower().startswith(("customer:", "caller:", "user:")))
    return None


def is_short(transcript: dict) -> bool:
    n = customer_turns(transcript)
    return n is not None and n <= SHORT_MAX


def short_questions(j: Journey, languages: list[str] = LANGUAGES) -> list[JevQuestion]:
    return [
        JevQuestion(key="answered_by", kind="choice", text="Who or what did the agent talk to?",
                    options=list(_ANSWERED_BY)),
        JevQuestion(key="language.primary", kind="choice",
                    text="Which language did the customer mostly speak?", options=languages),
        JevQuestion(key="furthest_stage", kind="choice",
                    text="How far did this call get before it ended? Stages, in order: "
                         + " → ".join(f"{s.stage} ({s.done_when})" for s in j.funnel),
                    options=[OPENING_END, *(s.stage for s in j.funnel)]),
        JevQuestion(key="objective", kind="choice", text=f"Objective: {j.objective}. Was it…",
                    options=list(_OBJECTIVE)),
        JevQuestion(key="sentiment", kind="score",
                    text="The customer's overall sentiment (-2 very negative … +2 very positive).",
                    scale=_SENTIMENT_SCALE),
    ]


def to_short(j: Journey, a: JevAnswers) -> ShortJudgment:
    who, who_p = _pick(a["answered_by"])
    stage, _ = _pick(a["furthest_stage"])
    return ShortJudgment(
        answered_by=_ANSWERED_BY[who], answered_by_p=who_p,
        primary_language=_pick(a["language.primary"])[0],
        furthest_stage=None if stage == OPENING_END else stage,
        objective_achieved=_OBJECTIVE[_pick(a["objective"])[0]],
        sentiment=_sentiment(float(a.get("sentiment", 0.0))),
    )


# ── where things happened (decision model, no LLM) ───────────────────────────────────
class TimelineEntry(BaseModel):
    """The part of the journey (a stage's exact name, Opening or Closing) an agent turn belongs to."""

    turn: int = Field(ge=0)
    item: str


def agent_turns(lines: list[dict]) -> list[int]:
    return list(dict.fromkeys(ln["turn_index"] for ln in lines
                              if ln.get("role") != "caller" and "turn_index" in ln))


def timeline_questions(j: Journey, lines: list[dict]) -> list[JevQuestion]:
    """One choice per agent turn: which part of the call it is in. Asked with the judge questions."""
    parts = (["Opening"] if j.opening else []) + [s.stage for s in j.funnel] + (["Closing"] if j.closing else [])
    guide = " → ".join(parts)
    return [JevQuestion(key=f"turn:{t}", kind="choice", options=parts,
                        text=f"Which part of the call is the agent's turn [{t}] in? The parts, in order: {guide}")
            for t in agent_turns(lines)]


def to_timeline(a: JevAnswers, lines: list[dict]) -> list[TimelineEntry]:
    out = []
    for t in agent_turns(lines):
        dist = a.get(f"turn:{t}")
        if isinstance(dist, dict) and dist:
            out.append(TimelineEntry(turn=t, item=_pick(dist)[0]))
    return out


def locate_questions(failures: list[tuple[int, str]], lines: list[dict]) -> list[JevQuestion]:
    """`failures` = (id, description). One choice each: the agent turn where it went wrong."""
    turns = agent_turns(lines)
    if not turns:
        return []
    texts = {t: " ".join(ln.get("text") or "" for ln in lines
                         if ln.get("turn_index") == t and ln.get("role") != "caller")[:60] for t in turns}
    options = [f"[{t}] {texts[t]}" for t in turns]
    return [JevQuestion(key=f"locate:{i}", kind="choice", options=options,
                        text=f"At which agent turn did this go wrong: {what}")
            for i, what in failures]


def to_turns(a: JevAnswers, failures: list[tuple[int, str]], lines: list[dict]) -> dict[int, int | None]:
    turns = agent_turns(lines)
    out: dict[int, int | None] = {}
    for i, _ in failures:
        dist = a.get(f"locate:{i}")
        if isinstance(dist, dict) and dist:
            best, p = _pick(dist)
            out[i] = int(best[1: best.index("]")]) if p >= THRESHOLD and best.startswith("[") else None
        else:
            out[i] = None
    return {i: (t if t in turns else None) for i, t in out.items()}
