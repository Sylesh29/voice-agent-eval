"""Aggregation. Sliced by default, because the aggregate is the thing that lies."""
from __future__ import annotations

from typing import Any, Callable

from ..scenario import Scenario
from ..trace import Trace
from . import closure, core

EVALUATORS: list[Callable] = [
    core.task_success,
    core.critical_entity_accuracy,
    core.false_completion,
    core.false_failure_report,
    core.escalation_correctness,
    core.staff_burden,
    closure.caller_closure_v1,
    closure.grounded_closure_v2,
    closure.grounded_closure_v3,
]


def evaluate_trace(scn: Scenario, trace: Trace) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for fn in EVALUATORS:
        r = fn(scn, trace)
        out[r.name] = {"value": r.value, "passed": r.passed,
                       "evidence": r.evidence, "explanation": r.explanation}
    return out


def _slices(scn: Scenario) -> dict[str, str]:
    return {
        "tier": scn.tier,
        "workflow": scn.workflow,
        "fault_injected": "yes" if scn.fault_policy else "no",
        "must_escalate": "yes" if scn.must_escalate else "no",
    }


def aggregate(scenarios: list[Scenario], traces: list[Trace],
              evals: dict[str, dict[str, dict]]) -> dict[str, Any]:
    """Returns {metric: {"overall": {...}, "by_<slice>": {value: {...}}}}.

    Every cell carries n_applicable alongside the rate. A rate without its
    denominator is how a 2-of-2 slice gets read as a trend.
    """
    by_id = {s.id: s for s in scenarios}
    metrics: set[str] = set()
    for e in evals.values():
        metrics |= set(e)

    def cell(names: list[str], metric: str) -> dict:
        vals = []
        for sid in names:
            m = evals.get(sid, {}).get(metric)
            if m is None or m["passed"] is None:
                continue
            vals.append(bool(m["passed"]))
        n = len(vals)
        return {"n_applicable": n, "n_passed": sum(vals),
                "rate": (sum(vals) / n) if n else None}

    all_ids = [t.scenario_id for t in traces]
    out: dict[str, Any] = {}
    for m in sorted(metrics):
        entry: dict[str, Any] = {"overall": cell(all_ids, m)}
        for slice_name in ("tier", "workflow", "fault_injected", "must_escalate"):
            buckets: dict[str, list[str]] = {}
            for sid in all_ids:
                key = _slices(by_id[sid])[slice_name]
                buckets.setdefault(key, []).append(sid)
            entry[f"by_{slice_name}"] = {k: cell(v, m) for k, v in sorted(buckets.items())}
        out[m] = entry
    return out
