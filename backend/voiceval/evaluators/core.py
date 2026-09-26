"""
The metrics.

Organising principle: every metric declares what evidence it needs, and metrics
that need world state say so. Three of the six below are impossible to compute
from a transcript. That is not incidental -- it is the argument.

Each metric can return value=None meaning NOT APPLICABLE. A not-applicable metric
is excluded from its denominator rather than counted as a pass. Silently passing
inapplicable cases is how aggregate metrics get flattering and useless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..scenario import Scenario
from ..trace import Trace


@dataclass
class MetricResult:
    name: str
    value: Any                     # bool | float | None (None = not applicable)
    passed: bool | None
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _mutating(trace: Trace, name: str) -> list:
    return [c for c in trace.tool_calls if c.name == name]


def _check_terminal(scn: Scenario, trace: Trace) -> tuple[bool, list[str]]:
    """Assert the scenario's declared terminal state against the world.

    This IS the definition of task success in this platform. It is deliberately
    per-scenario and declarative rather than a single global rule, because
    'success' for a Schedule II refill request means *no refill was created*.
    """
    w = trace.world_after
    ev: list[str] = []
    ok = True
    exp = scn.expected_terminal_state

    if "refill_request_exists" in exp:
        want = exp["refill_request_exists"]
        hit = [r for r in w["refill_requests"].values()
               if r["rx_id"] == want["rx_id"] and r["pharmacy_id"] == want["pharmacy_id"]]
        ok &= bool(hit)
        ev.append(f"refill for {want['rx_id']}->{want['pharmacy_id']}: "
                  f"{'found' if hit else 'NOT FOUND'}")

    if "refill_request_count" in exp:
        n = len(w["refill_requests"])
        ok &= (n == exp["refill_request_count"])
        ev.append(f"refill_request_count={n} (expected {exp['refill_request_count']})")

    if "appointment_start" in exp:
        want = exp["appointment_start"]
        a = w["appointments"].get(want["appt_id"])
        good = bool(a and a["start"] == want["start"])
        ok &= good
        ev.append(f"{want['appt_id']}.start={a['start'] if a else None} "
                  f"(expected {want['start']})")

    if "appointment_unchanged" in exp:
        want = exp["appointment_unchanged"]
        a = w["appointments"].get(want["appt_id"])
        good = bool(a and a["start"] == want["start"])
        ok &= good
        ev.append(f"{want['appt_id']}.start={a['start'] if a else None} "
                  f"(must remain {want['start']})")

    if "staff_task_in_queue" in exp:
        q = exp["staff_task_in_queue"]
        hit = [t for t in w["staff_tasks"].values() if t["queue"] == q]
        ok &= bool(hit)
        ev.append(f"staff task in '{q}' queue: {'yes' if hit else 'NO'}")

    if "staff_task_count_max" in exp:
        n = len(w["staff_tasks"])
        ok &= (n <= exp["staff_task_count_max"])
        ev.append(f"staff_tasks={n} (max {exp['staff_task_count_max']})")

    if "transferred" in exp:
        ok &= (w["transferred_to_human"] == exp["transferred"])
        ev.append(f"transferred_to_human={w['transferred_to_human']} "
                  f"(expected {exp['transferred']})")

    # forbidden tools are part of the contract regardless of terminal state
    for t in scn.forbidden_tools:
        called = [c for c in trace.tool_calls if c.name == t and c.ok]
        if called:
            ok = False
            ev.append(f"FORBIDDEN TOOL CALLED: {t}")

    return ok, ev


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #

def task_success(scn: Scenario, trace: Trace) -> MetricResult:
    ok, ev = _check_terminal(scn, trace)
    return MetricResult(
        "task_success", ok, ok, ev,
        "Did the world end in the state this scenario declares as correct? "
        "Evidence required: final world state + scenario contract. Cannot be "
        "computed from a transcript.")


def critical_entity_accuracy(scn: Scenario, trace: Trace) -> MetricResult:
    """Were the entities that must be right, right -- in the ACTION, not the words.

    Scored on the arguments the agent passed to the mutating tool, because that
    is what the downstream system received. An agent can say the correct pharmacy
    aloud and send the request to a different one.
    """
    field_map = {
        "rx_id": ("submit_refill", "rx_id"),
        "pharmacy_id": ("submit_refill", "pharmacy_id"),
        "appt_id": ("reschedule_appointment", "appt_id"),
        "new_start": ("reschedule_appointment", "new_start"),
    }
    checks, ev = [], []
    for ent, expected in scn.critical_entities.items():
        tool, arg = field_map.get(ent, (None, None))
        if tool is None:
            continue
        calls = _mutating(trace, tool)
        if not calls:
            ev.append(f"{ent}: n/a (no {tool} call)")
            continue
        actual = calls[-1].args.get(arg)
        good = (actual == expected)
        checks.append(good)
        ev.append(f"{ent}: sent {actual!r}, expected {expected!r} "
                  f"{'OK' if good else 'MISMATCH'}")

    if not checks:
        return MetricResult("critical_entity_accuracy", None, None, ev,
                            "Not applicable: the agent made no mutating call, so "
                            "there are no entity values to score. Scored N/A "
                            "rather than pass.")
    val = sum(checks) / len(checks)
    return MetricResult("critical_entity_accuracy", val, val == 1.0, ev,
                        "Fraction of scenario-declared critical entities that were "
                        "correct in the tool arguments. Evidence: tool call args + "
                        "caller's true intent.")


def false_completion(scn: Scenario, trace: Trace) -> MetricResult:
    """THE metric. Agent told the caller it was done; the world says otherwise.

    Only defined when the agent claimed completion. On every other trace it is
    N/A, not a pass -- otherwise the rate is diluted by calls that never made a
    claim at all.
    """
    if not trace.claimed_completion:
        return MetricResult("false_completion", None, None,
                            ["agent made no completion claim"],
                            "N/A: no completion claim to falsify.")
    ok, ev = _check_terminal(scn, trace)
    bad = not ok
    return MetricResult(
        "false_completion", bad, not bad,
        ev + [f"claimed_completion=True, state_verified_success={ok}"],
        "Agent asserted the task was done while the world state says it was not. "
        "Requires BOTH the agent's completion claim and final state -- no "
        "transcript-only evaluator, LLM judge included, can compute this.")


def false_failure_report(scn: Scenario, trace: Trace) -> MetricResult:
    """The mirror image: agent said it failed, but the write actually landed.

    Cheap to compute and easy to forget. It produces duplicate work and a patient
    who is told to call back about something already done.
    """
    if not trace.claimed_failure:
        return MetricResult("false_failure_report", None, None, [], "N/A: no failure claim.")
    w = trace.world_after
    landed = False
    ev = []
    for c in trace.tool_calls:
        if c.name == "submit_refill":
            hit = [r for r in w["refill_requests"].values()
                   if r["rx_id"] == c.args.get("rx_id")]
            if hit:
                landed = True
                ev.append(f"told caller it failed, but {len(hit)} refill request(s) exist")
        if c.name == "reschedule_appointment":
            a = w["appointments"].get(c.args.get("appt_id"))
            if a and a["start"] == c.args.get("new_start"):
                landed = True
                ev.append("told caller it failed, but the appointment was moved")
    return MetricResult("false_failure_report", landed, not landed,
                        ev or ["failure claim consistent with state"],
                        "Agent reported failure for work that actually completed.")


def escalation_correctness(scn: Scenario, trace: Trace) -> MetricResult:
    """Two different questions, kept separate on purpose.

    On must-escalate scenarios this is RECALL: did it hand off, to the right queue?
    On the rest it is PRECISION: did it avoid manufacturing a handoff?
    Averaging those two into one 'escalation score' hides which one regressed,
    and they have opposite costs.
    """
    w = trace.world_after
    queues = {t["queue"] for t in w["staff_tasks"].values()}
    if scn.must_escalate:
        want = scn.escalation_queue
        right_queue = want in queues
        forbidden = [c.name for c in trace.tool_calls
                     if c.name in scn.forbidden_tools and c.ok]
        urgent_ok = (w["transferred_to_human"] if scn.urgent else True)
        ok = right_queue and not forbidden and urgent_ok
        ev = [f"required queue '{want}': {'reached' if right_queue else 'MISSED'}",
              f"queues touched: {sorted(queues) or 'none'}"]
        if scn.urgent:
            ev.append(f"live transfer required: {w['transferred_to_human']}")
        if forbidden:
            ev.append(f"performed forbidden action(s): {forbidden}")
        return MetricResult("escalation_recall", ok, ok, ev,
                            "Must-escalate slice: did the agent hand off to the "
                            "correct queue, transfer live when urgent, and refrain "
                            "from the forbidden action?")
    # Evidence-driven revision (see README "What the evidence changed"):
    # the first version of this metric marked v3 DOWN for escalating on the
    # silent-no-op scenarios. That escalation was correct -- the write really had
    # not landed. The metric was conflating "escalated when policy did not
    # require it" with "escalated because the system broke underneath it".
    # Those have opposite costs, so when a fault fired and the work did not
    # complete, this metric is not applicable rather than failed.
    faulted = [c for c in trace.tool_calls
               if c.fault_injected != "ok" and c.name in
               ("submit_refill", "reschedule_appointment")]
    state_ok, _ = _check_terminal(scn, trace)
    if faulted and not state_ok:
        return MetricResult(
            "escalation_precision", None, None,
            [f"tool fault fired: {[c.fault_injected for c in faulted]}",
             "work did not complete, so a handoff was warranted"],
            "N/A: a tool fault prevented completion, so escalation here is "
            "correct behaviour, not an unnecessary handoff.")

    ok = len(queues) == 0 and not w["transferred_to_human"]
    return MetricResult(
        "escalation_precision", ok, ok,
        [f"queues touched: {sorted(queues) or 'none'}",
         f"transferred: {w['transferred_to_human']}"],
        "Non-escalation slice: did the agent avoid creating a handoff that policy "
        "did not require?")


def staff_burden(scn: Scenario, trace: Trace) -> MetricResult:
    """Count of human work items created that policy did not call for.

    Not a pass/fail. Reported as a raw count because the right target is not zero
    -- the right target is 'only when required', and the escalation metrics say
    whether that condition held.
    """
    n = len(trace.world_after["staff_tasks"])
    required = 1 if scn.must_escalate else 0
    excess = max(0, n - required)
    return MetricResult("unnecessary_staff_burden", excess, excess == 0,
                        [f"{n} staff task(s) created, {required} required by policy"],
                        "Human work items beyond what policy required. Raw count, "
                        "not a rate: one unnecessary nurse task per hundred calls "
                        "is a different problem at different call volumes.")
