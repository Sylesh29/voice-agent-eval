"""CLI: run a scenario suite through an agent and write an inspectable artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluators.aggregate import aggregate, evaluate_trace
from .runner import run_suite
from .scenario import Scenario


def cmd_run(args) -> None:
    scenarios = Scenario.load_all()
    run = run_suite(args.agent, scenarios, run_id=args.run_id)
    evals = {t.scenario_id: evaluate_trace(
        next(s for s in scenarios if s.id == t.scenario_id), t) for t in run.traces}
    agg = aggregate(scenarios, run.traces, evals)

    payload = run.to_dict()
    payload["evals"] = evals
    payload["aggregate"] = agg

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{run.run_id}.json"
    p.write_text(json.dumps(payload, indent=2))
    print(f"wrote {p}")

    for m in ("task_success", "false_completion", "escalation_recall",
              "escalation_precision", "critical_entity_accuracy",
              "caller_closure_v1", "unnecessary_staff_burden"):
        if m in agg:
            c = agg[m]["overall"]
            print(f"  {m:28s} {c['n_passed']}/{c['n_applicable']}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="kyroneval")
    sub = ap.add_subparsers(required=True)
    r = sub.add_parser("run")
    r.add_argument("--agent", required=True)
    r.add_argument("--out", default="../artifacts/runs")
    r.add_argument("--run-id", default=None)
    r.set_defaults(func=cmd_run)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
