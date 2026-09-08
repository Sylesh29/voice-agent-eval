"""
The simulated world. THIS IS THE GROUND TRUTH.

Everything an evaluator asserts about "did the work actually happen" is asserted
against this object, never against the transcript. The agent can only change it
through `tools.ToolLayer`, which is exactly where we inject faults -- so a tool
can report success while this world remains unchanged. That gap is the whole point.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

@dataclass
class Patient:
    patient_id: str
    name: str
    dob: str          # YYYY-MM-DD, synthetic
    phone: str


@dataclass
class Pharmacy:
    pharmacy_id: str
    name: str
    address: str


@dataclass
class Prescription:
    rx_id: str
    patient_id: str
    drug: str
    strength: str
    refills_remaining: int
    pharmacy_id: str
    # DEA schedule. II means "cannot be refilled by an agent under any circumstance"
    # in this clinic's policy -- it needs a new provider order.
    dea_schedule: Literal["none", "II", "III", "IV"] = "none"


@dataclass
class RefillRequest:
    request_id: str
    rx_id: str
    pharmacy_id: str
    status: Literal["queued", "sent", "rejected"] = "queued"


@dataclass
class Appointment:
    appt_id: str
    patient_id: str
    provider: str
    clinic: str
    start: str        # ISO8601 local, synthetic
    kind: Literal["routine", "post_op", "new_patient"] = "routine"
    status: Literal["scheduled", "cancelled"] = "scheduled"


@dataclass
class Slot:
    provider: str
    start: str
    open: bool = True


@dataclass
class StaffTask:
    """A unit of human work the agent created. More of these is not automatically
    good OR bad -- correct escalation is good, unnecessary routing is burden.
    The evaluators distinguish those two using scenario policy."""
    task_id: str
    queue: Literal["nurse", "provider", "front_desk", "billing"]
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# World
# --------------------------------------------------------------------------- #

@dataclass
class World:
    patients: dict[str, Patient] = field(default_factory=dict)
    pharmacies: dict[str, Pharmacy] = field(default_factory=dict)
    prescriptions: dict[str, Prescription] = field(default_factory=dict)
    appointments: dict[str, Appointment] = field(default_factory=dict)
    slots: list[Slot] = field(default_factory=list)

    # things the agent creates
    refill_requests: dict[str, RefillRequest] = field(default_factory=dict)
    staff_tasks: dict[str, StaffTask] = field(default_factory=dict)
    transferred_to_human: bool = False
    transfer_reason: str | None = None

    _seq: int = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    def snapshot(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_seq", None)
        return d

    def clone(self) -> "World":
        return copy.deepcopy(self)

    # -- convenience lookups used by tools and evaluators -------------------- #

    def find_patient(self, name: str, dob: str) -> Patient | None:
        for p in self.patients.values():
            if p.name.lower() == name.lower().strip() and p.dob == dob:
                return p
        return None

    def rx_for_patient(self, patient_id: str) -> list[Prescription]:
        return [r for r in self.prescriptions.values() if r.patient_id == patient_id]

    def appts_for_patient(self, patient_id: str) -> list[Appointment]:
        return [
            a for a in self.appointments.values()
            if a.patient_id == patient_id and a.status == "scheduled"
        ]


def diff_worlds(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Human-readable state delta, rendered in the trace inspector.

    Deliberately shallow and readable rather than a general-purpose differ --
    a reviewer scanning a failed scenario needs 'refill_requests: 0 -> 0' to
    jump out, not a nested JSON patch.
    """
    out: list[str] = []
    for key in ("refill_requests", "staff_tasks", "appointments", "prescriptions"):
        b, a = before.get(key, {}), after.get(key, {})
        if b != a:
            added = set(a) - set(b)
            removed = set(b) - set(a)
            changed = {k for k in set(a) & set(b) if a[k] != b[k]}
            if added:
                out.append(f"{key}: +{sorted(added)}")
            if removed:
                out.append(f"{key}: -{sorted(removed)}")
            for k in sorted(changed):
                fields = [f for f in a[k] if a[k][f] != b[k].get(f)]
                out.append(f"{key}[{k}]: changed {fields}")
    if before.get("transferred_to_human") != after.get("transferred_to_human"):
        out.append(f"transferred_to_human -> {after.get('transferred_to_human')}")
    if not out:
        out.append("(no state change)")
    return out
