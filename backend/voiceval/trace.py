"""Trace: everything that happened in one scenario run, for one agent."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .tools import ToolCall


@dataclass
class Turn:
    idx: int
    speaker: str            # "agent" | "caller"
    text: str
    act: str | None = None  # agent only: structured dialogue act
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    run_id: str
    scenario_id: str
    agent_id: str
    turns: list[Turn] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    world_before: dict[str, Any] = field(default_factory=dict)
    world_after: dict[str, Any] = field(default_factory=dict)
    state_delta: list[str] = field(default_factory=list)

    # Structured agent self-report. In production this comes from the agent's own
    # event stream, not from parsing words -- see README "what is real vs mocked".
    claimed_completion: bool = False
    claimed_failure: bool = False
    escalated: bool = False
    outcome: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def say(self, speaker: str, text: str, act: str | None = None, **meta) -> None:
        self.turns.append(Turn(len(self.turns) + 1, speaker, text, act, meta))

    @property
    def transcript(self) -> str:
        return "\n".join(f"{t.speaker.upper()}: {t.text}" for t in self.turns)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["transcript"] = self.transcript
        return d
