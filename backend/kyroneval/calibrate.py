"""
Closure-metric calibration: human labels vs evaluator v1 vs evaluator v2.

Produces artifacts/calibration/closure_calibration.json, which is the evidence
behind the README's claim that 19/21 agreement was misleading.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "artifacts" / "runs"
LABELS = Path(__file__).parent / "labels" / "closure_labels.json"


def _kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa. Included precisely because it is the number that exposes
    how little 19/21 raw agreement means when one class is 20/21 of the sample."""
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def main() -> None:
    labels = json.loads(LABELS.read_text())["labels"]
    runs = {p.stem: json.loads(p.read_text()) for p in RUNS.glob("*.json")}

    rows = []
    for L in labels:
        run = runs[L["run"]]
        sid = L["scenario"]
        ev = run["evals"][sid]
        trace = next(t for t in run["traces"] if t["scenario_id"] == sid)
        v1 = "clear" if ev["caller_closure_v1"]["passed"] else "unclear"
        v2 = "clear" if ev["grounded_closure_v2"]["passed"] else "unclear"
        v3 = "clear" if ev["grounded_closure_v3"]["passed"] else "unclear"
        # Reference = a SECOND human labelling pass with world state revealed.
        # Deliberately not derived from any evaluator, so the comparison is not
        # circular.
        grounded = L["label_with_state"]
        rows.append({
            "run": L["run"], "scenario": sid,
            "human_transcript_only": L["label"],
            "grounded_truth": grounded,
            "evaluator_v1": v1, "evaluator_v2": v2, "evaluator_v3": v3,
            "state_verified_task_success": ev["task_success"]["passed"],
            "claimed_completion": trace["claimed_completion"],
            "note": L["note"],
        })

    def compare(pred_key: str, truth_key: str) -> dict:
        p = [r[pred_key] for r in rows]
        t = [r[truth_key] for r in rows]
        n = len(rows)
        agree = sum(x == y for x, y in zip(p, t))
        cm = {}
        for x, y in zip(t, p):
            cm[f"truth={x},pred={y}"] = cm.get(f"truth={x},pred={y}", 0) + 1
        return {"n": n, "agreement": agree, "accuracy": round(agree / n, 3),
                "cohens_kappa": round(_kappa(t, p), 3), "confusion": cm,
                "disagreements": [r["scenario"] + " @" + r["run"]
                                  for r in rows if r[pred_key] != r[truth_key]]}

    out = {
        "what_this_shows": (
            "Evaluator v1 and the human labeller both read only the transcript. "
            "They agree with each other almost perfectly. Both are wrong in the "
            "same direction against state-grounded truth, on exactly the traces "
            "where being wrong matters. Agreement between two blind raters "
            "measures shared blindness, not correctness."),
        "v1_vs_human_transcript_only": compare("evaluator_v1", "human_transcript_only"),
        "v1_vs_grounded_truth": compare("evaluator_v1", "grounded_truth"),
        "v2_vs_grounded_truth": compare("evaluator_v2", "grounded_truth"),
        "v3_vs_grounded_truth": compare("evaluator_v3", "grounded_truth"),
        "rows": rows,
    }
    d = ROOT / "artifacts" / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    (d / "closure_calibration.json").write_text(json.dumps(out, indent=2))

    print("v1 vs human (both transcript-only):",
          out["v1_vs_human_transcript_only"]["accuracy"],
          "kappa", out["v1_vs_human_transcript_only"]["cohens_kappa"])
    print("v1 vs grounded truth            :",
          out["v1_vs_grounded_truth"]["accuracy"],
          "kappa", out["v1_vs_grounded_truth"]["cohens_kappa"],
          out["v1_vs_grounded_truth"]["disagreements"])
    for k in ("v2_vs_grounded_truth", "v3_vs_grounded_truth"):
        print(f"{k:32s}:", out[k]["accuracy"], "kappa", out[k]["cohens_kappa"],
              out[k]["disagreements"])


if __name__ == "__main__":
    main()
