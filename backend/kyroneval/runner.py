"""Runs scenarios through an agent and produces traces."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents.rule_agent import RuleAgent
from .caller import CallerSim
from .scenario import Scenario, build_world
from .tools import ToolLayer
from .trace import Trace
from .world import diff_worlds


def run_scenario(scn: Scenario, agent_id: str, run_id: str) -> Trace:
    world = build_world()                      # fresh world per scenario: no cross-talk
    tools = ToolLayer(world=world, fault_policy=scn.fault_policy)
    trace = Trace(run_id=run_id, scenario_id=scn.id, agent_id=agent_id)
    trace.world_before = world.snapshot()

    caller = CallerSim(scn, trace)
    RuleAgent(agent_id).run(scn, tools, caller, trace)

    trace.tool_calls = tools.calls
    trace.world_after = world.snapshot()
    trace.state_delta = diff_worlds(trace.world_before, trace.world_after)
    if trace.outcome == "unknown":
        trace.outcome = "abandoned"
    return trace


@dataclass
class Run:
    run_id: str
    agent_id: str
    created_at: str
    dataset_version: str
    traces: list[Trace] = field(default_factory=list)
    config_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "agent_id": self.agent_id,
            "created_at": self.created_at, "dataset_version": self.dataset_version,
            "config_fingerprint": self.config_fingerprint,
            "traces": [t.to_dict() for t in self.traces],
        }


def run_suite(agent_id: str, scenarios: list[Scenario] | None = None,
              run_id: str | None = None) -> Run:
    from .agents.configs import AGENT_CONFIGS
    scenarios = scenarios or Scenario.load_all()
    run_id = run_id or f"{agent_id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    cfg = json.dumps(AGENT_CONFIGS[agent_id], sort_keys=True)
    run = Run(
        run_id=run_id, agent_id=agent_id,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dataset_version=json.loads(
            (Path(__file__).parent / "scenarios" / "dataset.json").read_text()
        )["dataset_version"],
        config_fingerprint=hashlib.sha256(cfg.encode()).hexdigest()[:12],
    )
    run.traces = [run_scenario(s, agent_id, run_id) for s in scenarios]
    return run
