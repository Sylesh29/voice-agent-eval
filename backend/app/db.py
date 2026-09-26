"""SQLite persistence.

SQLite rather than Postgres on purpose: the reviewer should be able to run this
with no Docker and no provisioning. The access patterns here (a few hundred rows,
read-mostly, single writer) do not justify a server. Part 7 says what changes at
thousands of calls a day.

Run artifacts are the source of truth on disk; the DB is a queryable index over
them plus the one thing that is NOT reproducible from a run: human review.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "voiceval.db"
RUNS_DIR = ROOT / "artifacts" / "runs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  dataset_version TEXT,
  config_fingerprint TEXT,
  aggregate_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_results (
  run_id TEXT NOT NULL,
  scenario_id TEXT NOT NULL,
  outcome TEXT,
  claimed_completion INTEGER,
  escalated INTEGER,
  metrics_json TEXT NOT NULL,
  trace_json TEXT NOT NULL,
  PRIMARY KEY (run_id, scenario_id)
);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  scenario_id TEXT NOT NULL,
  metric TEXT NOT NULL,
  verdict TEXT NOT NULL,          -- agree | override_pass | override_fail
  reviewer TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews ON reviews(run_id, scenario_id);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def seed(con: sqlite3.Connection) -> int:
    """(Re)load run artifacts from disk. Idempotent -- reviews are never touched."""
    n = 0
    for p in sorted(RUNS_DIR.glob("*.json")):
        d = json.loads(p.read_text())
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?)",
            (d["run_id"], d["agent_id"], d["created_at"], d.get("dataset_version"),
             d.get("config_fingerprint"), json.dumps(d["aggregate"])))
        for t in d["traces"]:
            con.execute(
                "INSERT OR REPLACE INTO scenario_results VALUES (?,?,?,?,?,?,?)",
                (d["run_id"], t["scenario_id"], t["outcome"],
                 int(t["claimed_completion"]), int(t["escalated"]),
                 json.dumps(d["evals"][t["scenario_id"]]), json.dumps(t)))
        n += 1
    con.commit()
    return n
