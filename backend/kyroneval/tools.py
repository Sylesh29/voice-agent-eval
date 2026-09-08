"""
The tool layer the agent acts through, plus the fault injector.

Design note (this is the most consequential file in the repo):

A real voice agent does not fail mainly by saying the wrong words. It fails when
a downstream system misbehaves and the agent's *narration* stops matching reality.
So the fault modes here are not "random errors" -- each one is chosen to produce a
specific, nameable divergence between transcript and world state:

  ok                  : baseline
  error               : loud failure. Agent knows. Good agents escalate.
  timeout             : loud failure, no write. Retry may succeed.
  timeout_after_write : write LANDED but agent saw a timeout. A retrying agent
                        double-writes; an agent that gives up tells the patient
                        it failed when it actually succeeded (false NEGATIVE).
  silent_noop         : returns {"ok": True} and writes NOTHING. The agent has no
                        way to know. This is the one that generates false
                        completion, and the reason state-verified scoring exists.

`silent_noop` is not a strawman. It is what a 200-response from a partner API that
dropped the message on the floor looks like from inside an agent, and it is
invisible to every transcript-only evaluator including an LLM judge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .world import RefillRequest, StaffTask, World

FaultMode = str  # "ok" | "error" | "timeout" | "timeout_after_write" | "silent_noop"


class ToolTimeout(Exception):
    pass


@dataclass
class ToolCall:
    seq: int
    name: str
    args: dict[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None
    fault_injected: FaultMode = "ok"
    attempt: int = 1


@dataclass
class ToolLayer:
    """Wraps the World. Every mutation the agent makes goes through here.

    fault_policy maps tool name -> list of FaultMode applied per successive call
    to that tool. A one-element list applies to every call; a list like
    ["timeout", "ok"] makes the first attempt fail and a retry succeed, which is
    how we test recovery behaviour rather than just failure behaviour.
    """
    world: World
    fault_policy: dict[str, list[FaultMode]] = field(default_factory=dict)
    calls: list[ToolCall] = field(default_factory=list)
    _counts: dict[str, int] = field(default_factory=dict)

    # ---------------------------------------------------------------- faults --

    def _fault_for(self, name: str) -> FaultMode:
        n = self._counts.get(name, 0)
        self._counts[name] = n + 1
        policy = self.fault_policy.get(name)
        if not policy:
            return "ok"
        return policy[min(n, len(policy) - 1)]

    def _record(self, name, args, ok, result=None, error=None, fault="ok") -> dict:
        attempt = self._counts.get(name, 1)
        self.calls.append(
            ToolCall(seq=len(self.calls) + 1, name=name, args=args, ok=ok,
                     result=result, error=error, fault_injected=fault, attempt=attempt)
        )
        return {"ok": ok, "result": result, "error": error}

    def _guarded(self, name: str, args: dict, write: Callable[[], Any]) -> dict:
        """Run a mutating tool under the fault policy."""
        fault = self._fault_for(name)

        if fault == "error":
            return self._record(name, args, False, error="upstream_rejected", fault=fault)
        if fault == "timeout":
            return self._record(name, args, False, error="timeout", fault=fault)
        if fault == "timeout_after_write":
            write()  # the write really lands
            return self._record(name, args, False, error="timeout", fault=fault)
        if fault == "silent_noop":
            # Looks exactly like success to the agent. Nothing is written.
            return self._record(name, args, True, result={"accepted": True},
                                fault=fault)
        return self._record(name, args, True, result=write(), fault=fault)

    # ------------------------------------------------------------- read-only --

    def lookup_patient(self, name: str, dob: str) -> dict:
        p = self.world.find_patient(name, dob)
        return self._record("lookup_patient", {"name": name, "dob": dob},
                            ok=p is not None,
                            result=({"patient_id": p.patient_id, "name": p.name} if p else None),
                            error=None if p else "not_found")

    def get_prescriptions(self, patient_id: str) -> dict:
        rx = [
            {"rx_id": r.rx_id, "drug": r.drug, "strength": r.strength,
             "refills_remaining": r.refills_remaining, "pharmacy_id": r.pharmacy_id,
             "dea_schedule": r.dea_schedule}
            for r in self.world.rx_for_patient(patient_id)
        ]
        return self._record("get_prescriptions", {"patient_id": patient_id}, True, rx)

    def list_pharmacies(self, query: str) -> dict:
        q = query.lower().strip()
        hits = [
            {"pharmacy_id": p.pharmacy_id, "name": p.name, "address": p.address}
            for p in self.world.pharmacies.values()
            if q in p.name.lower() or q in p.address.lower()
        ]
        return self._record("list_pharmacies", {"query": query}, True, hits)

    def get_appointments(self, patient_id: str) -> dict:
        appts = [
            {"appt_id": a.appt_id, "provider": a.provider, "clinic": a.clinic,
             "start": a.start, "kind": a.kind}
            for a in self.world.appts_for_patient(patient_id)
        ]
        return self._record("get_appointments", {"patient_id": patient_id}, True, appts)

    def find_slots(self, provider: str) -> dict:
        s = [{"provider": x.provider, "start": x.start}
             for x in self.world.slots if x.open and x.provider == provider]
        return self._record("find_slots", {"provider": provider}, True, s)

    # -------------------------------------------------------------- mutating --

    def submit_refill(self, rx_id: str, pharmacy_id: str) -> dict:
        def write():
            req_id = self.world.next_id("REQ")
            self.world.refill_requests[req_id] = RefillRequest(
                request_id=req_id, rx_id=rx_id, pharmacy_id=pharmacy_id, status="queued"
            )
            return {"request_id": req_id}
        return self._guarded("submit_refill",
                             {"rx_id": rx_id, "pharmacy_id": pharmacy_id}, write)

    def reschedule_appointment(self, appt_id: str, new_start: str) -> dict:
        def write():
            appt = self.world.appointments.get(appt_id)
            if appt is None:
                return {"error": "no_such_appointment"}
            slot = next((s for s in self.world.slots
                         if s.provider == appt.provider and s.start == new_start and s.open),
                        None)
            if slot is None:
                return {"error": "slot_unavailable"}
            # free the old slot, take the new one
            for s in self.world.slots:
                if s.provider == appt.provider and s.start == appt.start:
                    s.open = True
            slot.open = False
            appt.start = new_start
            return {"appt_id": appt_id, "start": new_start}
        return self._guarded("reschedule_appointment",
                             {"appt_id": appt_id, "new_start": new_start}, write)

    def create_staff_task(self, queue: str, reason: str, payload: dict | None = None) -> dict:
        def write():
            tid = self.world.next_id("TASK")
            self.world.staff_tasks[tid] = StaffTask(
                task_id=tid, queue=queue, reason=reason, payload=payload or {}
            )
            return {"task_id": tid}
        return self._guarded("create_staff_task",
                             {"queue": queue, "reason": reason}, write)

    def transfer_to_human(self, reason: str) -> dict:
        def write():
            self.world.transferred_to_human = True
            self.world.transfer_reason = reason
            return {"transferred": True}
        return self._guarded("transfer_to_human", {"reason": reason}, write)

    # ------------------------------------------------- read-after-write ------
    # These exist so an agent CAN detect a silent no-op. They read true world
    # state and are deliberately not subject to the fault policy: the point of
    # the v3 experiment is to test whether verification helps, not to model a
    # verification endpoint that is itself unreliable. Called out as a
    # simplification in the README.

    def verify_refill(self, rx_id: str, pharmacy_id: str) -> dict:
        hit = any(r.rx_id == rx_id and r.pharmacy_id == pharmacy_id
                  for r in self.world.refill_requests.values())
        return self._record("verify_refill", {"rx_id": rx_id, "pharmacy_id": pharmacy_id},
                            True, {"found": hit})

    def verify_appointment(self, appt_id: str, expected_start: str) -> dict:
        a = self.world.appointments.get(appt_id)
        ok = bool(a and a.start == expected_start)
        return self._record("verify_appointment",
                            {"appt_id": appt_id, "expected_start": expected_start},
                            True, {"matches": ok,
                                   "actual_start": a.start if a else None})
