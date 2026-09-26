"""
Mix sensitivity: what the same run says under a different scenario mix.

Why this exists. My suite is 3 ordinary + 9 hard + 3 must-escalate + 2 negative
control. That is an adversarially enriched sample, chosen to make failures
visible, and it is NOT what a day of real calls looks like. So an aggregate
computed over it is not an estimate of anything.

The useful question is the other direction: if this same agent behaviour were
scored against a production-shaped mix, what would the headline number say? If
the headline flips direction while the per-slice results do not, then the
headline was reporting the sample, not the system.

The weights below are ILLUSTRATIVE. I have no production data and I am not
claiming these proportions are those of any real deployment. The point is the sensitivity, not the value.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MIXES = {
    "suite_uniform": {"ordinary": 1, "hard": 1, "control_escalate": 1, "control_negative": 1},
    # a plausible pre-production shape: most calls are unremarkable, a thin tail
    # is hard, a thinner tail is genuinely unsafe to automate
    "production_like": {"ordinary": 0.62, "control_negative": 0.28,
                        "hard": 0.08, "control_escalate": 0.02},
}


def weighted(agg: dict, metric: str, weights: dict[str, float]) -> float | None:
    m = agg.get(metric, {}).get("by_tier", {})
    num = den = 0.0
    for tier, w in weights.items():
        c = m.get(tier)
        if not c or c["n_applicable"] == 0:
            continue
        num += w * c["rate"]
        den += w
    return round(num / den, 3) if den else None


def main() -> None:
    runs = {p.stem: json.loads(p.read_text())
            for p in (ROOT / "artifacts" / "runs").glob("*.json")}
    metrics = ["task_success", "false_completion", "escalation_recall",
               "critical_entity_accuracy", "grounded_closure_v3"]
    out = {"caveat": __doc__.strip(), "mixes": MIXES, "results": {}}
    for mix, w in MIXES.items():
        out["results"][mix] = {
            m: {rid: weighted(r["aggregate"], m, w) for rid, r in sorted(runs.items())}
            for m in metrics
        }
    d = ROOT / "artifacts" / "experiment"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mix_sensitivity.json").write_text(json.dumps(out, indent=2))

    for mix in MIXES:
        print(f"\n--- {mix}")
        print(f"{'metric':28s} {'v1':>6s} {'v2':>6s} {'v3':>6s}   v1->v2")
        for m in metrics:
            r = out["results"][mix][m]
            v1, v2, v3 = r.get("v1_conservative"), r.get("v2_automation_push"), r.get("v3_verified")
            d_ = f"{(v2 - v1) * 100:+.0f}pp" if (v1 is not None and v2 is not None) else "  —"
            f = lambda x: f"{x:.2f}" if x is not None else "  — "
            print(f"{m:28s} {f(v1):>6s} {f(v2):>6s} {f(v3):>6s}   {d_}")


if __name__ == "__main__":
    main()
