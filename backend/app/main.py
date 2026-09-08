"""
Read/write API for the evaluation platform.

Scope note: no auth, no pagination, no rate limiting. Single-user local tool.
Those are the right things to omit at this size and the wrong things to omit at
the size described in Part 7.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import ROOT, connect, seed

app = FastAPI(title="Kyron Eval")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
con = connect()
seed(con)

SCENARIOS = {
    s["id"]: s for s in json.loads(
        (ROOT / "backend" / "kyroneval" / "scenarios" / "dataset.json").read_text()
    )["scenarios"]
}


@app.post("/api/reseed")
def reseed():
    return {"runs_loaded": seed(con)}


@app.get("/api/scenarios")
def scenarios():
    return list(SCENARIOS.values())


@app.get("/api/runs")
def runs():
    out = []
    for r in con.execute("SELECT * FROM runs ORDER BY created_at DESC"):
        agg = json.loads(r["aggregate_json"])
        out.append({
            "run_id": r["run_id"], "agent_id": r["agent_id"],
            "created_at": r["created_at"], "dataset_version": r["dataset_version"],
            "config_fingerprint": r["config_fingerprint"],
            "headline": {m: agg[m]["overall"] for m in
                         ("task_success", "false_completion", "escalation_recall",
                          "grounded_closure_v3") if m in agg},
        })
    return out


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    r = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such run")
    rows = con.execute(
        "SELECT * FROM scenario_results WHERE run_id=? ORDER BY scenario_id",
        (run_id,)).fetchall()
    reviews = {}
    for rv in con.execute("SELECT * FROM reviews WHERE run_id=?", (run_id,)):
        reviews.setdefault(rv["scenario_id"], []).append(dict(rv))
    return {
        "run_id": r["run_id"], "agent_id": r["agent_id"],
        "created_at": r["created_at"], "config_fingerprint": r["config_fingerprint"],
        "aggregate": json.loads(r["aggregate_json"]),
        "scenarios": [{
            "scenario_id": x["scenario_id"], "outcome": x["outcome"],
            "claimed_completion": bool(x["claimed_completion"]),
            "escalated": bool(x["escalated"]),
            "tier": SCENARIOS[x["scenario_id"]]["tier"],
            "workflow": SCENARIOS[x["scenario_id"]]["workflow"],
            "title": SCENARIOS[x["scenario_id"]]["title"],
            "metrics": json.loads(x["metrics_json"]),
            "reviews": reviews.get(x["scenario_id"], []),
        } for x in rows],
    }


@app.get("/api/runs/{run_id}/scenarios/{scenario_id}")
def scenario_detail(run_id: str, scenario_id: str):
    x = con.execute(
        "SELECT * FROM scenario_results WHERE run_id=? AND scenario_id=?",
        (run_id, scenario_id)).fetchone()
    if not x:
        raise HTTPException(404, "no such result")
    from kyroneval.agents.configs import AGENT_CONFIGS
    run = con.execute("SELECT agent_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return {
        "run_id": run_id, "scenario": SCENARIOS[scenario_id],
        "agent_config": AGENT_CONFIGS.get(run["agent_id"], {}),
        "trace": json.loads(x["trace_json"]),
        "metrics": json.loads(x["metrics_json"]),
        "reviews": [dict(r) for r in con.execute(
            "SELECT * FROM reviews WHERE run_id=? AND scenario_id=? ORDER BY id DESC",
            (run_id, scenario_id))],
    }


@app.get("/api/compare")
def compare(a: str, b: str):
    """Per-scenario metric diff between two runs, regressions first.

    This is the endpoint the whole product exists for: 'what changed, and did
    anything get worse' is the question a release decision actually asks.
    """
    def load(rid):
        r = con.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
        if not r:
            raise HTTPException(404, f"no such run: {rid}")
        rows = con.execute("SELECT * FROM scenario_results WHERE run_id=?",
                           (rid,)).fetchall()
        return r, {x["scenario_id"]: json.loads(x["metrics_json"]) for x in rows}

    ra, ma = load(a)
    rb, mb = load(b)
    agg_a, agg_b = json.loads(ra["aggregate_json"]), json.loads(rb["aggregate_json"])

    metrics = sorted(set(agg_a) | set(agg_b))
    slice_diff = []
    for m in metrics:
        row = {"metric": m, "slices": []}
        for sl in ("overall",):
            ca, cb = agg_a.get(m, {}).get(sl), agg_b.get(m, {}).get(sl)
            row["slices"].append({"slice": sl, "a": ca, "b": cb})
        for sl_name in ("by_tier", "by_workflow", "by_fault_injected", "by_must_escalate"):
            for k in sorted(set(agg_a.get(m, {}).get(sl_name, {})) |
                            set(agg_b.get(m, {}).get(sl_name, {}))):
                row["slices"].append({
                    "slice": f"{sl_name.replace('by_', '')}={k}",
                    "a": agg_a.get(m, {}).get(sl_name, {}).get(k),
                    "b": agg_b.get(m, {}).get(sl_name, {}).get(k)})
        slice_diff.append(row)

    per_scenario = []
    for sid in sorted(set(ma) | set(mb)):
        changes = []
        for metric in sorted(set(ma.get(sid, {})) | set(mb.get(sid, {}))):
            pa = ma.get(sid, {}).get(metric, {}).get("passed")
            pb = mb.get(sid, {}).get(metric, {}).get("passed")
            if pa != pb:
                # A metric becoming NOT APPLICABLE is not a regression. Getting
                # this wrong made the first version of this view cry wolf on
                # refill-hard-timeout-then-retry, which actually improved.
                if pa is True and pb is False:
                    direction = "regression"
                elif pb is True and pa is False:
                    direction = "improvement"
                elif pb is None:
                    direction = "now_not_applicable"
                elif pa is None:
                    direction = "now_applicable"
                else:
                    direction = "changed"
                changes.append({"metric": metric, "a": pa, "b": pb,
                                "direction": direction})
        if changes:
            per_scenario.append({
                "scenario_id": sid, "title": SCENARIOS[sid]["title"],
                "tier": SCENARIOS[sid]["tier"], "changes": changes,
                "worst": ("regression" if any(c["direction"] == "regression"
                                          for c in changes)
                      else "improvement" if any(c["direction"] == "improvement"
                                                for c in changes)
                      else "neutral")})
    per_scenario.sort(key=lambda x: (x["worst"] != "regression", x["scenario_id"]))
    return {"a": a, "b": b, "agent_a": ra["agent_id"], "agent_b": rb["agent_id"],
            "slice_diff": slice_diff, "per_scenario": per_scenario}


@app.get("/api/failure-patterns")
def failure_patterns():
    """Group failing scenarios by mechanism, not by scenario.

    'Which failure patterns appear repeatedly' is a different question from
    'which scenarios failed', and it is the one that turns into engineering work.
    """
    buckets: dict[str, dict] = {}
    for x in con.execute("SELECT * FROM scenario_results"):
        metrics = json.loads(x["metrics_json"])
        trace = json.loads(x["trace_json"])
        faults = {c["fault_injected"] for c in trace["tool_calls"]
                  if c["fault_injected"] != "ok"}
        for name, m in metrics.items():
            if m["passed"] is not False:
                continue
            mech = (f"{name} after {sorted(faults)[0]}" if faults else name)
            b = buckets.setdefault(mech, {"mechanism": mech, "count": 0,
                                          "runs": set(), "scenarios": set()})
            b["count"] += 1
            b["runs"].add(x["run_id"])
            b["scenarios"].add(x["scenario_id"])
    out = [{**b, "runs": sorted(b["runs"]), "scenarios": sorted(b["scenarios"])}
           for b in buckets.values()]
    out.sort(key=lambda x: -x["count"])
    return out


@app.get("/api/calibration")
def calibration():
    p = ROOT / "artifacts" / "calibration" / "closure_calibration.json"
    if not p.exists():
        raise HTTPException(404, "run `python -m kyroneval.calibrate` first")
    return json.loads(p.read_text())


class ReviewIn(BaseModel):
    run_id: str
    scenario_id: str
    metric: str
    verdict: str          # agree | override_pass | override_fail
    reviewer: str = "reviewer"
    note: str = ""


@app.post("/api/reviews")
def add_review(r: ReviewIn):
    if r.verdict not in ("agree", "override_pass", "override_fail"):
        raise HTTPException(400, "bad verdict")
    con.execute(
        "INSERT INTO reviews (run_id,scenario_id,metric,verdict,reviewer,note,created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (r.run_id, r.scenario_id, r.metric, r.verdict, r.reviewer, r.note,
         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return {"ok": True}


@app.get("/api/reviews")
def list_reviews():
    return [dict(x) for x in con.execute(
        "SELECT * FROM reviews ORDER BY id DESC")]
