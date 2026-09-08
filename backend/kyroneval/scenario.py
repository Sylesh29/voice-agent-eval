"""
Scenario schema + the shared fixture world.

A scenario is a *contract*, not a script of expected words. It declares:
  - what the caller wants and what they actually know
  - what the clinic's policy says must happen (escalate? forbidden actions?)
  - which entities must be correct for the outcome to be safe
  - what the world must look like when the call ends

Nothing here references the agent's phrasing. That is deliberate: a scenario that
asserts on wording only distinguishes agents that talk differently, not agents
that *behave* differently, and the prompt is explicit that the latter is the point.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .world import (Appointment, Patient, Pharmacy, Prescription, Slot, World)

Tier = Literal["ordinary", "hard", "control_escalate", "control_negative"]


@dataclass
class Scenario:
    id: str
    workflow: Literal["refill", "reschedule"]
    tier: Tier
    title: str
    why_interesting: str

    caller: dict[str, Any]
    # what the agent *perceives* instead of what the caller said (ASR / extraction error)
    entity_corruption: dict[str, Any] = field(default_factory=dict)
    fault_policy: dict[str, list[str]] = field(default_factory=dict)

    # ---- policy (ground truth that does NOT come from the world) ----
    must_escalate: bool = False
    escalation_queue: str | None = None
    escalation_reason: str | None = None
    urgent: bool = False
    forbidden_tools: list[str] = field(default_factory=list)

    # ---- ground truth (asserted against the world) ----
    critical_entities: dict[str, Any] = field(default_factory=dict)
    expected_terminal_state: dict[str, Any] = field(default_factory=dict)
    evidence_unavailable: list[str] = field(default_factory=list)

    @staticmethod
    def load_all(path: str | Path | None = None) -> list["Scenario"]:
        p = Path(path) if path else Path(__file__).parent / "scenarios" / "dataset.json"
        raw = json.loads(p.read_text())
        return [Scenario(**s) for s in raw["scenarios"]]


# --------------------------------------------------------------------------- #
# Fixture world. Synthetic. Shared by every scenario so that cross-scenario
# comparisons mean something.
# --------------------------------------------------------------------------- #

def build_world() -> World:
    w = World()

    for p in [
        Patient("PT-1", "Maria Alvarez", "1975-03-11", "555-0142"),
        Patient("PT-2", "James Whitfield", "1962-08-04", "555-0177"),
        Patient("PT-3", "Dana Okonkwo", "1990-12-19", "555-0113"),
        Patient("PT-4", "Robert Lin", "1948-01-27", "555-0198"),
    ]:
        w.patients[p.patient_id] = p

    for ph in [
        Pharmacy("PH-1", "Riverside Pharmacy", "412 Elm St"),
        # Near-duplicate on purpose: "Riverside" is ambiguous, and "Elm St" vs
        # "Elmwood Ave" is exactly the kind of distinction a voice channel loses.
        Pharmacy("PH-2", "Riverside Pharmacy Elmwood", "88 Elmwood Ave"),
        Pharmacy("PH-3", "Bayside Drug", "9 Harbor Rd"),
        Pharmacy("PH-4", "Northgate Pharmacy", "1200 Northgate Mall"),
    ]:
        w.pharmacies[ph.pharmacy_id] = ph

    for rx in [
        Prescription("RX-1", "PT-1", "Lisinopril", "10mg", 2, "PH-1"),
        Prescription("RX-2", "PT-1", "Metformin", "500mg", 0, "PH-1"),
        Prescription("RX-3", "PT-2", "Oxycodone", "5mg", 0, "PH-3", dea_schedule="II"),
        Prescription("RX-4", "PT-3", "Sertraline", "50mg", 3, "PH-4"),
        Prescription("RX-5", "PT-4", "Warfarin", "5mg", 1, "PH-1"),
        Prescription("RX-6", "PT-3", "Alprazolam", "0.5mg", 1, "PH-4", dea_schedule="IV"),
    ]:
        w.prescriptions[rx.rx_id] = rx

    for a in [
        Appointment("AP-1", "PT-1", "Dr. Reyes", "Cardiology", "2026-09-22T09:00"),
        Appointment("AP-2", "PT-2", "Dr. Nakamura", "Orthopedics", "2026-09-15T14:00",
                    kind="post_op"),
        Appointment("AP-3", "PT-3", "Dr. Reyes", "Cardiology", "2026-10-01T11:00"),
        Appointment("AP-4", "PT-4", "Dr. Patel", "Primary Care", "2026-09-18T10:30"),
    ]:
        w.appointments[a.appt_id] = a

    w.slots = [
        Slot("Dr. Reyes", "2026-09-24T10:00"),
        Slot("Dr. Reyes", "2026-09-25T15:00"),
        Slot("Dr. Reyes", "2026-10-02T09:00"),
        Slot("Dr. Nakamura", "2026-09-16T09:00"),
        Slot("Dr. Nakamura", "2026-09-29T13:00"),
        Slot("Dr. Patel", "2026-09-19T08:00"),
        Slot("Dr. Patel", "2026-09-23T14:00"),
    ]
    # occupied slots mirroring the booked appointments
    w.slots.append(Slot("Dr. Reyes", "2026-09-22T09:00", open=False))
    w.slots.append(Slot("Dr. Nakamura", "2026-09-15T14:00", open=False))
    w.slots.append(Slot("Dr. Reyes", "2026-10-01T11:00", open=False))
    w.slots.append(Slot("Dr. Patel", "2026-09-18T10:30", open=False))
    return w
