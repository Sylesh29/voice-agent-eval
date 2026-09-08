"""Tests for the parts that would silently corrupt every result if they broke."""
import json
from pathlib import Path

import pytest

from kyroneval.evaluators import closure, core
from kyroneval.runner import run_scenario, run_suite
from kyroneval.scenario import Scenario, build_world
from kyroneval.tools import ToolLayer

SCENARIOS = {s.id: s for s in Scenario.load_all()}


# --------------------------------------------------------------- dataset ----

def test_dataset_contract_is_wellformed():
    for s in SCENARIOS.values():
        assert s.expected_terminal_state, f"{s.id} declares no terminal state"
        assert s.why_interesting, f"{s.id} has no stated reason to exist"
        if s.must_escalate:
            assert s.escalation_queue, f"{s.id} must escalate but names no queue"
            assert s.escalation_reason, f"{s.id} must escalate but gives no reason"


def test_dataset_has_controls_in_both_directions():
    tiers = [s.tier for s in SCENARIOS.values()]
    assert tiers.count("control_negative") >= 2, \
        "without negative controls, an evaluator that fails everything looks sensitive"
    assert tiers.count("control_escalate") >= 2


# ----------------------------------------------------------- fault modes ----

def test_silent_noop_reports_success_and_writes_nothing():
    """The central claim of this repo. If this test breaks, every false-completion
    number is meaningless."""
    w = build_world()
    t = ToolLayer(world=w, fault_policy={"submit_refill": ["silent_noop"]})
    res = t.submit_refill("RX-1", "PH-1")
    assert res["ok"] is True
    assert len(w.refill_requests) == 0


def test_timeout_after_write_actually_writes():
    w = build_world()
    t = ToolLayer(world=w, fault_policy={"submit_refill": ["timeout_after_write"]})
    res = t.submit_refill("RX-1", "PH-1")
    assert res["ok"] is False and res["error"] == "timeout"
    assert len(w.refill_requests) == 1, "the write is supposed to land despite the timeout"


def test_fault_policy_advances_per_attempt():
    w = build_world()
    t = ToolLayer(world=w, fault_policy={"submit_refill": ["timeout", "ok"]})
    assert t.submit_refill("RX-1", "PH-1")["ok"] is False
    assert t.submit_refill("RX-1", "PH-1")["ok"] is True


def test_verification_tools_read_true_state():
    w = build_world()
    t = ToolLayer(world=w, fault_policy={"submit_refill": ["silent_noop"]})
    t.submit_refill("RX-1", "PH-1")
    assert t.verify_refill("RX-1", "PH-1")["result"]["found"] is False


# ------------------------------------------------------------ evaluators ----

def test_false_completion_is_not_applicable_without_a_claim():
    """N/A must not be counted as a pass -- that is how the rate gets diluted."""
    scn = SCENARIOS["refill-control-escalate-controlled-substance"]
    tr = run_scenario(scn, "v1_conservative", "t")
    assert tr.claimed_completion is False
    assert core.false_completion(scn, tr).value is None


def test_false_completion_fires_on_silent_noop():
    scn = SCENARIOS["refill-hard-silent-noop"]
    tr = run_scenario(scn, "v1_conservative", "t")
    assert tr.claimed_completion is True
    assert tr.state_delta == ["(no state change)"]
    assert core.false_completion(scn, tr).value is True


def test_entity_accuracy_is_na_when_no_mutating_call():
    scn = SCENARIOS["refill-control-escalate-controlled-substance"]
    tr = run_scenario(scn, "v1_conservative", "t")
    assert core.critical_entity_accuracy(scn, tr).value is None


def test_forbidden_tool_fails_task_success_even_if_state_looks_right():
    scn = SCENARIOS["resched-control-escalate-postop"]
    tr = run_scenario(scn, "v2_automation_push", "t")
    assert any(c.name == "reschedule_appointment" and c.ok for c in tr.tool_calls)
    assert core.task_success(scn, tr).value is False


def test_closure_v3_separates_truthfulness_from_permission():
    """v2's bug: it marked a truthful closing bad because the action was disallowed.
    Closure and policy compliance are different questions."""
    scn = SCENARIOS["refill-hard-no-refills-remaining"]
    tr = run_scenario(scn, "v2_automation_push", "t")
    assert closure.grounded_closure_v2(scn, tr).passed is False
    assert closure.grounded_closure_v3(scn, tr).passed is True
    assert core.escalation_correctness(scn, tr).passed is False  # caught, correctly, here


# ------------------------------------------------------------ determinism ---

def test_runs_are_bit_for_bit_reproducible():
    """Non-determinism in the subject would confound every A/B comparison."""
    a = run_suite("v2_automation_push", run_id="x")
    b = run_suite("v2_automation_push", run_id="x")
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)


def test_each_scenario_gets_a_fresh_world():
    r = run_suite("v1_conservative", run_id="x")
    for t in r.traces:
        assert len(t.world_before["refill_requests"]) == 0
        assert len(t.world_before["staff_tasks"]) == 0


# ------------------------------------------------------------- committed ----

def test_committed_artifacts_match_a_fresh_run():
    """Guards against a README quoting numbers no longer produced by the code."""
    p = Path(__file__).resolve().parents[2] / "artifacts" / "runs" / "v2_automation_push.json"
    committed = json.loads(p.read_text())
    fresh = run_suite("v2_automation_push", run_id=committed["run_id"])
    a = {t["scenario_id"]: t["outcome"] for t in committed["traces"]}
    b = {t.scenario_id: t.outcome for t in fresh.traces}
    assert a == b
