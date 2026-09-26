"""
Closure-metric calibration: human labels vs evaluator v1 vs evaluator v2.

Produces artifacts/calibration/closure_calibration.json, which is the evidence
behind the README's claim that 19/21 agreement was misleading.
"""
from __future__ import annotations

import json
from collections import Counter
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
        jc = ev.get("judge_clarity", {}).get("passed")
        v4p = ev.get("grounded_closure_v4", {}).get("passed")
        judge = None if jc is None else ("clear" if jc else "unclear")
        v4 = None if v4p is None else ("clear" if v4p else "unclear")
        # Reference = a SECOND human labelling pass with world state revealed.
        # Deliberately not derived from any evaluator, so the comparison is not
        # circular.
        grounded = L["label_with_state"]
        rows.append({
            "run": L["run"], "scenario": sid,
            "human_transcript_only": L["label"],
            "grounded_truth": grounded,
            "evaluator_v1": v1, "evaluator_v2": v2, "evaluator_v3": v3,
            "evaluator_v4": v4, "judge_clarity": judge,
            "judge_reasoning": next(
                (e for e in (ev.get("judge_clarity", {}).get("evidence") or [])
                 if e.startswith("reasoning:")), ""),
            "judge_quote_verified": next(
                (e.endswith("True") for e in (ev.get("judge_clarity", {}).get("evidence") or [])
                 if e.startswith("quote appears verbatim")), None),
            "state_verified_task_success": ev["task_success"]["passed"],
            "claimed_completion": trace["claimed_completion"],
            "note": L["note"],
        })

    def compare(pred_key: str, truth_key: str) -> dict:
        """Agreement between two raters, ALWAYS reported with its denominator.

        The first version of this function silently dropped rows where the
        predictor produced no verdict. When 37 of 51 judge calls were lost to rate
        limiting, it reported accuracy 1.0 / kappa 1.0 over the survivors -- a
        perfect score that meant nothing, computed by excluding the evidence.

        That is the same defect this whole platform is built to catch, in my own
        evaluator, on a number that flattered me. So coverage is now a first-class
        field and anything below full coverage is marked NOT REPORTABLE.
        """
        n_total = len(rows)
        pairs = [(r[pred_key], r[truth_key]) for r in rows if r.get(pred_key) is not None]
        n = len(pairs)
        excluded = n_total - n
        base = {"n_scored": n, "n_total": n_total, "n_excluded_no_verdict": excluded,
                "coverage": round(n / n_total, 3) if n_total else 0.0,
                "reportable": excluded == 0 and n > 0}
        if not pairs:
            return {**base, "unavailable": True,
                    "why": "the predictor produced no verdicts at all"}
        p = [x for x, _ in pairs]
        t = [y for _, y in pairs]
        agree = sum(x == y for x, y in zip(p, t))
        cm: dict[str, int] = {}
        for x, y in zip(t, p):
            cm[f"truth={x},pred={y}"] = cm.get(f"truth={x},pred={y}", 0) + 1
        minority = min(Counter(t).values()) if t else 0
        return {**base,
                "agreement": agree, "accuracy": round(agree / n, 3),
                "cohens_kappa": round(_kappa(t, p), 3),
                "minority_class_n": minority,
                "kappa_rests_on_n_items": minority,
                "confusion": cm,
                "disagreements": [r["scenario"] + " @" + r["run"] for r in rows
                                  if r.get(pred_key) is not None
                                  and r[pred_key] != r[truth_key]]}

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
        # HEAD TO HEAD. Both of these see ONLY the transcript, and so did the human
        # who produced `human_transcript_only`. This is the only apples-to-apples
        # measurement of whether the judge beats the regex it replaced.
        "regex_clarity_vs_human_transcript_only": compare("evaluator_v1", "human_transcript_only"),
        "judge_clarity_vs_human_transcript_only": compare("judge_clarity", "human_transcript_only"),
        "v4_vs_grounded_truth": compare("evaluator_v4", "grounded_truth"),
        "rows": rows,
        "judge_quote_audit": {
            "note": ("A deterministic check ON the judge: does its cited evidence appear "
                     "verbatim in the transcript it was given? An evaluator that cannot "
                     "quote its own input is not grounded in it."),
            "unverified_quotes": [
                r["scenario"] + " @" + r["run"] for r in rows
                if r.get("judge_quote_verified") is False],
        },
    }
    d = ROOT / "artifacts" / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    (d / "closure_calibration.json").write_text(json.dumps(out, indent=2))

    def show(label: str, c: dict) -> None:
        if c.get("unavailable"):
            print(f"{label:42s}: NO VERDICTS ({c['why']})")
            return
        flag = "" if c["reportable"] else "   <-- NOT REPORTABLE"
        print(f"{label:42s}: acc {c['accuracy']:.3f}  kappa {c['cohens_kappa']:+.3f}  "
              f"n={c['n_scored']}/{c['n_total']} "
              f"(coverage {c['coverage']:.0%}, minority class n={c['minority_class_n']})"
              f"{flag}")
        if not c["reportable"]:
            print(f"{'':44s}{c['n_excluded_no_verdict']} trace(s) produced no verdict and "
                  "were EXCLUDED. Do not quote this number.")
        if c["disagreements"]:
            for x in c["disagreements"]:
                print(f"{'':46s}- {x}")

    for label, k in [
        ("v1 lexical vs human (both transcript-only)", "v1_vs_human_transcript_only"),
        ("v1 lexical vs state-aware human", "v1_vs_grounded_truth"),
        ("v2 contract-grounded vs state-aware", "v2_vs_grounded_truth"),
        ("v3 assertion-grounded vs state-aware", "v3_vs_grounded_truth"),
        ("HEAD-TO-HEAD regex clarity vs human", "regex_clarity_vs_human_transcript_only"),
        ("HEAD-TO-HEAD judge clarity vs human", "judge_clarity_vs_human_transcript_only"),
        ("v4 judge+grounding vs state-aware", "v4_vs_grounded_truth"),
    ]:
        show(label, out[k])

    audit = out["judge_quote_audit"]["unverified_quotes"]
    print(f"\njudge quote audit: {len(audit)} citation(s) NOT found verbatim in the "
          f"transcript{': ' + ', '.join(audit) if audit else ''}")


if __name__ == "__main__":
    main()
