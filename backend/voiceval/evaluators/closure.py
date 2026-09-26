"""
The judgment metric: did the caller leave the call knowing what happens next?

This is the one metric here that is genuinely a judgment call, so it is the one I
take through the full human-label -> evaluator -> disagreement -> revision loop.

VERSION 1 (this file, first implementation). Decision boundary as written before
looking at any traces:

    A call has GOOD CLOSURE if the agent's final turn tells the caller
    (a) what state the request is now in, and
    (b) what will happen next or what the caller should do.

Implemented as a lexical check over the final agent turn. That is a deliberately
naive first implementation -- I wanted to find out where a lexical proxy for a
judgment breaks rather than assume it would.
"""
from __future__ import annotations

import re

from ..scenario import Scenario
from ..trace import Trace
from .core import MetricResult

STATE_CUES = [
    r"\ball set\b", r"\bon its way\b", r"\bsubmitted\b", r"\bsent (it|to)\b",
    r"\bconfirmed\b", r"\byou're moved\b", r"\bI've sent\b", r"\bwasn't able\b",
    r"\bnot able\b", r"\bcould not confirm\b", r"\bI've left\b",
]
NEXT_STEP_CUES = [
    r"\bcall you back\b", r"\bwill contact you\b", r"\bfollow up\b",
    r"\bcheck(ing)? back\b", r"\bcall us back\b", r"\bready for pickup\b",
    r"\bstay on the line\b", r"\bbusiness day\b", r"\btry calling back\b",
    r"\bthey'll call\b", r"\banything else\b",
]


def _final_agent_turn(trace: Trace) -> str:
    for t in reversed(trace.turns):
        if t.speaker == "agent":
            return t.text
    return ""


def caller_closure_v1(scn: Scenario, trace: Trace) -> MetricResult:
    text = _final_agent_turn(trace)
    low = text.lower()
    has_state = any(re.search(p, low) for p in STATE_CUES)
    has_next = any(re.search(p, low) for p in NEXT_STEP_CUES)
    ok = has_state and has_next
    return MetricResult(
        "caller_closure_v1", ok, ok,
        [f"final agent turn: {text!r}",
         f"state cue: {has_state}", f"next-step cue: {has_next}"],
        "v1 (lexical): does the closing turn state the request's status AND a "
        "next step? Evidence required: transcript only.")


# --------------------------------------------------------------------------- #
# VERSION 2 -- written after comparing v1 against 21 hand labels.
#
# Two things changed, for two different reasons. Keeping them separate matters,
# because only one of them is interesting.
#
# CHANGE 1 (boring, a bug): v1 scored the urgent-transfer call as BAD closure.
#   Reading it, that call has the clearest closing in the whole set -- the caller
#   knows exactly what is happening and exactly what to do. v1 missed it because
#   my STATE_CUES list had no pattern for "I'm transferring you". A lexical
#   rubric fails on the phrasing you did not think of. Fixed by adding the cue,
#   but the general lesson is that the lexical approach has an open-ended tail of
#   these and I would not ship it as the primary signal.
#
# CHANGE 2 (the actual finding): v1 agreed with my human labels on 19 of 21
#   traces. That agreement was worthless. Both the human and the evaluator were
#   reading the transcript, so both of us called four confidently-worded closings
#   "clear" when the thing they asserted had not happened. High agreement between
#   a judge and a human means only that they share evidence -- it says nothing
#   about whether that evidence is sufficient. This is the same shape as an
#   aggregate that hides a slice: the number looks reassuring in exactly the
#   situation where it is least informative.
#
# So v2 keeps the clarity check and ANDs it with a grounding check against world
# state. A confident closing about something that did not happen is not good
# closure -- it is worse than a vague one, because the caller acts on it.
# --------------------------------------------------------------------------- #

STATE_CUES_V2 = STATE_CUES + [
    r"\btransferring you\b", r"\bstop and take that seriously\b",
    r"\bnot able to\b", r"\bneeds? (a )?new order\b",
]


def closure_is_clear_v2(trace: Trace) -> tuple[bool, list[str]]:
    text = _final_agent_turn(trace)
    low = text.lower()
    has_state = any(re.search(p, low) for p in STATE_CUES_V2)
    has_next = any(re.search(p, low) for p in NEXT_STEP_CUES)
    return (has_state and has_next), [f"state cue: {has_state}", f"next-step cue: {has_next}"]


def closing_assertion_is_true(scn: Scenario, trace: Trace) -> tuple[bool, list[str]]:
    """Is what the closing turn asserts actually true of the world?

    Evidence required: final world state. This is the half of the metric that no
    transcript reader and no LLM judge can supply.
    """
    from .core import _check_terminal, false_failure_report
    ev: list[str] = []
    if trace.claimed_completion:
        ok, e = _check_terminal(scn, trace)
        ev.append(f"claimed completion; state-verified={ok}")
        return ok, ev + e
    if trace.claimed_failure:
        ffr = false_failure_report(scn, trace)
        ok = not bool(ffr.value)
        ev.append(f"claimed failure; work actually landed={bool(ffr.value)}")
        return ok, ev + ffr.evidence
    ok, e = _check_terminal(scn, trace)
    ev.append(f"escalation/handoff; state-verified={ok}")
    return ok, ev + e


def grounded_closure_v2(scn: Scenario, trace: Trace) -> MetricResult:
    clear, ev1 = closure_is_clear_v2(trace)
    true_, ev2 = closing_assertion_is_true(scn, trace)
    ok = clear and true_
    return MetricResult(
        "grounded_closure_v2", ok, ok,
        [f"final agent turn: {_final_agent_turn(trace)!r}", f"clear={clear}",
         f"assertion_true={true_}"] + ev1 + ev2,
        "v2: closing is clear AND what it asserts is consistent with world state. "
        "Evidence required: transcript + final state. A confident closing about "
        "work that did not happen scores 0, below a vague one.")


# --------------------------------------------------------------------------- #
# VERSION 3 -- written after v2 disagreed with the second (state-aware) labelling
# pass on three traces, all in the same direction.
#
# v2 grounded closure against the SCENARIO CONTRACT (task_success). That is the
# wrong reference. On `refill-hard-no-refills-remaining` under v2, the agent said
# "your Metformin refill is on its way" and it genuinely was -- the refill was
# submitted. The scenario fails, correctly, because submitting it violated
# policy. But the CALLER was told the truth. v2 marked that closing bad, and it
# was right about the call being bad for a reason that has nothing to do with
# closure.
#
# That is an evaluator getting the right answer for the wrong reason, which is
# worse than a wrong answer: it inflates apparent accuracy and it will drift the
# moment the two things come apart.
#
# v3 grounds the closing against WHAT THE CLOSING ITSELF ASSERTS -- did the
# action the agent described actually land in the world -- and leaves the
# question of whether that action was permitted to the escalation and
# task-success metrics, where it belongs. One metric, one question.
# --------------------------------------------------------------------------- #

MUTATING = ("submit_refill", "reschedule_appointment")


def _asserted_action_landed(trace: Trace) -> tuple[bool, list[str]]:
    w = trace.world_after
    calls = [c for c in trace.tool_calls if c.name in MUTATING]
    if not calls:
        return True, ["no action asserted"]
    last = calls[-1]
    if last.name == "submit_refill":
        hit = [r for r in w["refill_requests"].values()
               if r["rx_id"] == last.args["rx_id"]
               and r["pharmacy_id"] == last.args["pharmacy_id"]]
        return bool(hit), [f"asserted refill {last.args['rx_id']}->"
                           f"{last.args['pharmacy_id']} present in world: {bool(hit)}"]
    a = w["appointments"].get(last.args["appt_id"])
    ok = bool(a and a["start"] == last.args["new_start"])
    return ok, [f"asserted move of {last.args['appt_id']} to "
                f"{last.args['new_start']}; world says {a['start'] if a else None}"]


def grounded_closure_v3(scn: Scenario, trace: Trace) -> MetricResult:
    clear, ev1 = closure_is_clear_v2(trace)
    landed, ev2 = _asserted_action_landed(trace)
    if trace.claimed_completion:
        true_ = landed
    elif trace.claimed_failure:
        true_ = not landed          # said it failed -- it had better have failed
        ev2.append("agent claimed failure; grounded against the action NOT landing")
    else:
        true_ = True                # escalation/transfer: nothing asserted about a write
        ev2.append("handoff: no completion or failure asserted about a write")
    ok = clear and true_
    return MetricResult(
        "grounded_closure_v3", ok, ok,
        [f"final agent turn: {_final_agent_turn(trace)!r}",
         f"clear={clear}", f"assertion_matches_world={true_}"] + ev1 + ev2,
        "v3: is the closing clear, AND did the specific action it describes "
        "actually land? Deliberately silent on whether that action was permitted "
        "-- that is escalation_recall's job.")


# --------------------------------------------------------------------------- #
# VERSION 4 -- the LLM judge, scoped to exactly one half of the metric.
#
# v1..v3 all decide CLARITY with a regex cue list. That is the acknowledged weak
# part: v1 missed the urgent-transfer closing purely because my pattern list had
# no phrase for "I'm transferring you", and there is an open-ended tail of those.
# Clarity is a language judgment with no ground truth in any database, which is
# the one situation where a judge is the right tool.
#
# So v4 keeps the architecture and swaps only that half:
#
#     v3 = regex_clarity  AND  asserted_action_landed
#     v4 = judge_clarity  AND  asserted_action_landed
#                              ^^^^^^^^^^^^^^^^^^^^^^ still deterministic, and
#                              deliberately never shown to the model
#
# The judge sees the transcript and nothing else. It does not see world state, it
# does not see the scenario contract, and it is told in the prompt that judging
# truth is not its job. If it could see state it would start reasoning about task
# success, which it would do worse than three lines of Python.
#
# `judge_clarity` is reported as its own metric so the judge's contribution can be
# measured against the regex it replaced, on the same 21 labels.
# --------------------------------------------------------------------------- #

from .judge import judge_closure  # noqa: E402


def _judge_for(trace: Trace):
    # Cassette replay is ALWAYS allowed, so a reviewer with no credentials still
    # gets the recorded verdicts and identical numbers. Live API calls require an
    # explicit opt-in, so nobody spends money by running the test suite.
    import os

    from ..config import load_env
    load_env()
    return judge_closure(trace.transcript, _final_agent_turn(trace),
                         allow_api=os.getenv("VOICEVAL_JUDGE") == "1")


def judge_clarity(scn: Scenario, trace: Trace) -> MetricResult:
    j = _judge_for(trace)
    if j.verdict is None:
        return MetricResult(
            "judge_clarity", None, None, [j.reasoning],
            "N/A: no cassette entry and no API key. Reported unavailable rather "
            "than defaulted to a pass -- a metric that silently passes when its "
            "evaluator is missing is worse than no metric.")
    ok = j.verdict == "clear"
    ev = [f"verdict: {j.verdict} (confidence {j.confidence})",
          f"reasoning: {j.reasoning}",
          f"quoted: {j.quoted_evidence!r}",
          f"quote appears verbatim in transcript: {j.quote_verified}",
          f"source: {j.source} · model: {j.model}"]
    if j.quote_verified is False:
        ev.append("WARNING: the judge cited text that is not in the transcript. "
                  "Its reasoning is not grounded in the evidence it was given.")
    return MetricResult(
        "judge_clarity", ok, ok, ev,
        "LLM judge, transcript only, on the clarity half of closure. Replaces the "
        "regex cue list from v1-v3. Never sees world state.")


def grounded_closure_v4(scn: Scenario, trace: Trace) -> MetricResult:
    j = _judge_for(trace)
    landed, ev2 = _asserted_action_landed(trace)
    if trace.claimed_completion:
        true_ = landed
    elif trace.claimed_failure:
        true_ = not landed
        ev2.append("agent claimed failure; grounded against the action NOT landing")
    else:
        true_ = True
        ev2.append("handoff: no completion or failure asserted about a write")

    if j.verdict is None:
        return MetricResult("grounded_closure_v4", None, None, [j.reasoning] + ev2,
                            "N/A: judge unavailable. The deterministic half was "
                            f"computed anyway (assertion_matches_world={true_}).")
    clear = j.verdict == "clear"
    ok = clear and true_
    return MetricResult(
        "grounded_closure_v4", ok, ok,
        [f"final agent turn: {_final_agent_turn(trace)!r}",
         f"judge says clear={clear} (confidence {j.confidence}, {j.source})",
         f"judge reasoning: {j.reasoning}",
         f"assertion_matches_world={true_}"] + ev2,
        "v4: LLM judge decides clarity (a language question with no ground truth); "
        "deterministic code decides whether the asserted action landed (a question "
        "state answers exactly). Hybrid by design, not a replacement for v3.")
