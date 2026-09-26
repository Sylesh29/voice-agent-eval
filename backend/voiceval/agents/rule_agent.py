"""
The agent under test.

This is a deterministic rule-based policy, not an LLM. That is a real limitation
and I want to be precise about what it costs and what it buys.

Costs: it cannot exhibit the failure modes that come from language understanding
itself -- hallucinated entities, instruction drift, prompt-injection from caller
speech. Any claim this platform makes about "an LLM agent" is unearned.

Buys: every run is reproducible, the difference between two agent versions is a
readable config diff instead of a prompt diff, and a regression is attributable
to a specific behavioural rule. For an experiment whose subject is *the
evaluation platform*, a deterministic subject is the right choice -- otherwise
non-determinism in the agent and error in the evaluator are confounded and I
cannot tell which one moved a metric.

The `Agent` seam is a plain `run()` method, so swapping in an LLM-backed agent is
a new class, not a refactor.
"""
from __future__ import annotations

from typing import Any

from ..caller import CallerSim
from ..scenario import Scenario
from ..tools import ToolLayer
from ..trace import Trace
from .configs import AGENT_CONFIGS

PRETTY = {"PH-1": "Riverside on Elm Street", "PH-2": "Riverside on Elmwood Avenue",
          "PH-3": "Bayside Drug on Harbor Road", "PH-4": "Northgate Pharmacy"}


def _pretty(v: Any) -> str:
    if isinstance(v, str) and v in PRETTY:
        return PRETTY[v]
    if isinstance(v, str) and "T" in v and v.startswith("20"):
        d, t = v.split("T")
        return f"{d} at {t}"
    return str(v)


class RuleAgent:
    def __init__(self, agent_id: str):
        self.id = agent_id
        self.cfg = AGENT_CONFIGS[agent_id]

    # ------------------------------------------------------------- helpers --

    def _escalate(self, caller: CallerSim, trace: Trace, tools: ToolLayer,
                  queue: str, reason: str, spoken: str, urgent: bool = False) -> None:
        tools.create_staff_task(queue=queue, reason=reason)
        if urgent:
            tools.transfer_to_human(reason=reason)
        trace.escalated = True
        trace.claimed_completion = False
        trace.outcome = "transferred_urgent" if urgent else "escalated"
        caller.close(spoken, act="escalate")

    def _handle_urgent(self, beat: dict | None, caller, trace, tools) -> bool:
        if not beat or beat.get("type") != "urgent_symptom":
            return False
        if not self.cfg["enforce_hard_guardrails"]:
            return False
        self._escalate(
            caller, trace, tools, queue="nurse",
            reason="Possible acute symptoms reported during the call.",
            spoken=("I want to stop and take that seriously — chest pressure and "
                    "shortness of breath need to be looked at right now. I'm "
                    "transferring you to a nurse, please stay on the line."),
            urgent=True,
        )
        return True

    def _write_succeeded(self, res: dict) -> bool | None:
        """Did the write land, as far as the agent can tell?

        Returns True / False / None(ambiguous). The v1-vs-v2 difference lives
        here: v2 treats a non-raising call as success and never inspects the
        result body, which is how a structured refusal inside an ok:true
        envelope becomes a confident false confirmation.
        """
        if self.cfg["trust_ok_envelope"]:
            return True if res.get("ok") else False
        if not res.get("ok"):
            return False
        body = res.get("result") or {}
        if isinstance(body, dict) and body.get("error"):
            return False
        return True

    def _closing(self, what: str, verified: bool | None) -> str:
        style = self.cfg["closing_style"]
        if style == "warm":
            return f"You're all set — {what}. Anything else I can help you with today?"
        if style == "grounded":
            if verified:
                return (f"I've confirmed it went through: {what}. If you don't hear "
                        "from them by tomorrow afternoon, call us back.")
            return (f"I tried to {what}, but I could not confirm it went through, so "
                    "I've left it with our staff. Someone will call you back within "
                    "one business day. Please don't assume it's done until then.")
        return (f"I've submitted it — {what}. I'd suggest checking back if you "
                "haven't heard anything by tomorrow.")

    def _failed_close(self, caller, trace, tools, what: str) -> None:
        trace.claimed_failure = True
        trace.claimed_completion = False
        if self.cfg["staff_task_on_failure"]:
            tools.create_staff_task(queue="front_desk",
                                    reason=f"Automation could not complete: {what}")
            trace.escalated = True
            trace.outcome = "escalated"
            caller.close(f"I wasn't able to {what} just now. I've left a note for our "
                         "staff and someone will call you back within one business day.",
                         act="state_failure")
        else:
            trace.outcome = "failed_stated"
            caller.close(f"I wasn't able to {what} right now. Please try calling back "
                         "later.", act="state_failure")

    # ----------------------------------------------------------------- run --

    def run(self, scn: Scenario, tools: ToolLayer, caller: CallerSim, trace: Trace) -> None:
        caller.opening()
        name, beat = caller.ask("Happy to help. Can I start with your full name?", "name")
        if self._handle_urgent(beat, caller, trace, tools):
            return
        dob, beat = caller.ask("Thanks. And your date of birth?", "dob")
        if self._handle_urgent(beat, caller, trace, tools):
            return

        pt = tools.lookup_patient(name or "", dob or "")
        if not pt["ok"]:
            self._failed_close(caller, trace, tools, "find your record")
            return
        patient_id = pt["result"]["patient_id"]

        if scn.workflow == "refill":
            self._refill(scn, tools, caller, trace, patient_id)
        else:
            self._reschedule(scn, tools, caller, trace, patient_id)

    # -------------------------------------------------------------- refill --

    def _refill(self, scn, tools, caller, trace, patient_id) -> None:
        drug, beat = caller.ask("Got it. Which medication needs refilling?", "drug")
        if self._handle_urgent(beat, caller, trace, tools):
            return

        rxs = tools.get_prescriptions(patient_id)["result"]
        rx = next((r for r in rxs if r["drug"].lower() == str(drug).lower()), None)
        if rx is None:
            self._failed_close(caller, trace, tools, "find that prescription")
            return

        # --- hard guardrail: controlled substances (survives a prompt rewrite) ---
        if self.cfg["enforce_hard_guardrails"] and rx["dea_schedule"] == "II":
            self._escalate(
                caller, trace, tools, queue="provider",
                reason="Schedule II controlled substance cannot be refilled without a new provider order.",
                spoken=("That one I'm not able to refill over the phone — it needs a "
                        "new order from your provider. I've sent it to their queue "
                        "and their office will contact you."))
            return

        # --- prose policy: zero refills remaining (did NOT survive v2) ---
        if self.cfg["enforce_soft_policy"] and rx["refills_remaining"] == 0:
            self._escalate(
                caller, trace, tools, queue="provider",
                reason="No refills remaining; requires a new provider order.",
                spoken=("You're out of refills on that one, so it needs your provider "
                        "to authorise a new order. I've sent it to them and they'll "
                        "follow up with you."))
            return

        q, beat = caller.ask("And which pharmacy should this go to?", "pharmacy_query")
        if self._handle_urgent(beat, caller, trace, tools):
            return
        matches = tools.list_pharmacies(str(q) if q else "")["result"]

        pharmacy_id = None
        if len(matches) == 1:
            pharmacy_id = matches[0]["pharmacy_id"]
            beat = caller.inform(
                f"I have {matches[0]['name']} at {matches[0]['address']}. I'll use that one.",
                act="confirm_entity")
            if self._handle_urgent(beat, caller, trace, tools):
                return
        else:
            opts = [m["pharmacy_id"] for m in matches] or ["PH-1"]
            listing = "; ".join(f"{m['name']} at {m['address']}" for m in matches)
            pharmacy_id, beat = caller.offer(
                f"I see more than one — {listing}. Which of those is it?",
                opts, "pharmacy_choice")
            if self._handle_urgent(beat, caller, trace, tools):
                return
            if pharmacy_id is None:
                self._failed_close(caller, trace, tools, "confirm your pharmacy")
                return

        res = tools.submit_refill(rx["rx_id"], pharmacy_id)
        ok = self._write_succeeded(res)
        if ok is False and self.cfg["retry_on_timeout"] and res.get("error") == "timeout":
            trace.notes.append("retried submit_refill after timeout")
            res = tools.submit_refill(rx["rx_id"], pharmacy_id)
            ok = self._write_succeeded(res)

        what = f"your {rx['drug']} refill is on its way to {_pretty(pharmacy_id)}"
        if ok:
            verified = None
            if self.cfg["verify_after_write"]:
                verified = tools.verify_refill(rx["rx_id"], pharmacy_id)["result"]["found"]
                if not verified:
                    trace.notes.append("read-after-write found no refill request")
                    self._failed_close(caller, trace, tools,
                                       "confirm the refill reached the pharmacy")
                    return
            trace.claimed_completion = True
            trace.outcome = "completed_claimed"
            caller.close(self._closing(what, verified), act="confirm_completion")
        else:
            self._failed_close(caller, trace, tools, "send that refill")

    # ---------------------------------------------------------- reschedule --

    def _reschedule(self, scn, tools, caller, trace, patient_id) -> None:
        appts = tools.get_appointments(patient_id)["result"]
        if not appts:
            self._failed_close(caller, trace, tools, "find an upcoming appointment")
            return

        if len(appts) == 1:
            appt = appts[0]
            beat = caller.inform(
                f"I see your {appt['start'].replace('T', ' at ')} with {appt['provider']}. "
                "Is that the one you want to move?", act="confirm_entity")
            if self._handle_urgent(beat, caller, trace, tools):
                return
        else:
            opts = [a["appt_id"] for a in appts]
            listing = "; ".join(f"{a['start'].replace('T',' at ')} with {a['provider']}"
                                for a in appts)
            chosen, beat = caller.offer(
                f"I see a few — {listing}. Which one?", opts, "appt_id")
            if self._handle_urgent(beat, caller, trace, tools):
                return
            appt = next((a for a in appts if a["appt_id"] == chosen), None)
            if appt is None:
                self._failed_close(caller, trace, tools, "identify the appointment")
                return

        # --- prose policy: post-op window (did NOT survive v2) ---
        if self.cfg["enforce_soft_policy"] and appt["kind"] == "post_op":
            self._escalate(
                caller, trace, tools, queue="nurse",
                reason="Post-operative visit cannot be moved outside the follow-up window without nurse review.",
                spoken=("That's a post-op follow-up, so I'm not able to move it myself "
                        "— a nurse has to review the timing first. I've sent it to them "
                        "and they'll call you back to sort out a new date."))
            return

        want, beat = caller.ask("When would you like to move it to?", "desired_start")
        if self._handle_urgent(beat, caller, trace, tools):
            return
        if want is None:
            slots = tools.find_slots(appt["provider"])["result"]
            opts = [s["start"] for s in slots]
            listing = "; ".join(_pretty(o) for o in opts)
            want, beat = caller.offer(f"Here's what {appt['provider']} has open: "
                                      f"{listing}. Which works?", opts, "desired_start")
            if self._handle_urgent(beat, caller, trace, tools):
                return
            if want is None:
                self._failed_close(caller, trace, tools, "find a time that works")
                return

        res = tools.reschedule_appointment(appt["appt_id"], str(want))
        ok = self._write_succeeded(res)

        # slot taken: a structured refusal inside an ok:true envelope
        body = res.get("result") or {}
        if ok is False and isinstance(body, dict) and body.get("error") == "slot_unavailable":
            slots = tools.find_slots(appt["provider"])["result"]
            opts = [s["start"] for s in slots]
            listing = "; ".join(_pretty(o) for o in opts)
            want, beat = caller.offer(
                f"That time was just taken. {appt['provider']} still has: {listing}. "
                "Would one of those work?", opts, "desired_start")
            if self._handle_urgent(beat, caller, trace, tools):
                return
            if want is None:
                self._failed_close(caller, trace, tools, "find another time")
                return
            res = tools.reschedule_appointment(appt["appt_id"], str(want))
            ok = self._write_succeeded(res)
        elif ok is False and res.get("error") == "timeout" and self.cfg["retry_on_timeout"]:
            trace.notes.append("retried reschedule_appointment after timeout")
            res = tools.reschedule_appointment(appt["appt_id"], str(want))
            ok = self._write_succeeded(res)

        what = f"you're moved to {_pretty(want)} with {appt['provider']}"
        if ok:
            verified = None
            if self.cfg["verify_after_write"]:
                verified = tools.verify_appointment(appt["appt_id"], str(want))["result"]["matches"]
                if not verified:
                    trace.notes.append("read-after-write found appointment unchanged")
                    self._failed_close(caller, trace, tools,
                                       "confirm the new appointment time")
                    return
            trace.claimed_completion = True
            trace.outcome = "completed_claimed"
            caller.close(self._closing(what, verified), act="confirm_completion")
        else:
            self._failed_close(caller, trace, tools, "move that appointment")
