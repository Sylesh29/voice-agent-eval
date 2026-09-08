from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_runs_listed():
    ids = [r["run_id"] for r in c.get("/api/runs").json()]
    assert {"v1_conservative", "v2_automation_push", "v3_verified"} <= set(ids)


def test_run_detail_carries_metrics_and_slices():
    d = c.get("/api/runs/v1_conservative").json()
    assert len(d["scenarios"]) == 17
    agg = d["aggregate"]["task_success"]
    assert "by_tier" in agg and "overall" in agg
    assert agg["overall"]["n_applicable"] == 17


def test_compare_flags_regressions_not_na_transitions():
    d = c.get("/api/compare",
              params={"a": "v1_conservative", "b": "v2_automation_push"}).json()
    regs = [p["scenario_id"] for p in d["per_scenario"] if p["worst"] == "regression"]
    assert "resched-control-escalate-postop" in regs
    # a metric that becomes N/A is not a regression
    for p in d["per_scenario"]:
        for ch in p["changes"]:
            if ch["b"] is None:
                assert ch["direction"] == "now_not_applicable"


def test_scenario_detail_has_trace_tools_and_evidence():
    d = c.get("/api/runs/v1_conservative/scenarios/refill-hard-silent-noop").json()
    assert d["trace"]["claimed_completion"] is True
    assert d["trace"]["state_delta"] == ["(no state change)"]
    assert d["metrics"]["false_completion"]["passed"] is False
    assert d["metrics"]["false_completion"]["evidence"]


def test_review_roundtrip():
    body = {"run_id": "v1_conservative", "scenario_id": "refill-ordinary-keep-pharmacy",
            "metric": "task_success", "verdict": "agree", "note": "spot check"}
    assert c.post("/api/reviews", json=body).json()["ok"] is True
    got = c.get("/api/runs/v1_conservative").json()
    row = next(s for s in got["scenarios"]
               if s["scenario_id"] == "refill-ordinary-keep-pharmacy")
    assert len(row["reviews"]) >= 1


def test_bad_verdict_rejected():
    assert c.post("/api/reviews", json={
        "run_id": "v1_conservative", "scenario_id": "resched-ordinary",
        "metric": "task_success", "verdict": "lgtm"}).status_code == 400
