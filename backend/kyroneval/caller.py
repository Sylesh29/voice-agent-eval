"""
The simulated caller.

Honest description of what this is: a deterministic slot-answering caller with
scripted perturbations. It is NOT an LLM patient simulator and it does not
generate novel language.

Why that is the right call for an 8-hour build, stated plainly because it is the
biggest limitation in the repo: an LLM caller would produce more realistic
surface language but would make every run non-reproducible and would smuggle the
simulator's own cooperativeness into the results. A cooperative LLM patient makes
every agent look good -- that is the classic simulator bias, and it would
undermine the exact comparisons this platform exists to make. I chose
reproducibility and adversarial control over surface realism.

What this caller CAN model: entity ambiguity, mid-call correction, vagueness,
volunteered urgent information, and refusal to be led.
What it CANNOT model: interruption/barge-in, disfluency, emotional escalation,
accent and ASR interaction, and anything about audio. Metrics computed here do
not transfer to those failure modes.
"""
from __future__ import annotations

from typing import Any

from .scenario import Scenario
from .trace import Trace


class CallerSim:
    def __init__(self, scenario: Scenario, trace: Trace):
        self.scn = scenario
        self.trace = trace
        self.facts: dict[str, Any] = dict(scenario.caller.get("facts", {}))
        self.identity: dict[str, Any] = dict(scenario.caller.get("identity", {}))
        self.style = scenario.caller.get("style", "cooperative")
        self.beats = list(scenario.caller.get("beats", []))
        self._fired: set[int] = set()
        self.agent_turns = 0

    # --------------------------------------------------------------- beats --

    def _due_beat(self) -> dict | None:
        for i, b in enumerate(self.beats):
            if i in self._fired:
                continue
            if self.agent_turns >= b.get("at_turn", 999):
                self._fired.add(i)
                if b["type"] == "correction":
                    self.facts[b["field"]] = b["new_value"]
                return b
        return None

    # ------------------------------------------------------------ dialogue --

    def opening(self) -> str:
        text = self.scn.caller.get("goal", "I need some help.")
        self.trace.say("caller", f"Hi, {text.lower()}.")
        return text

    def _agent_says(self, text: str, act: str, **meta) -> None:
        self.agent_turns += 1
        self.trace.say("agent", text, act=act, **meta)

    def ask(self, agent_text: str, field: str, act: str = "request_slot") -> tuple[Any, dict | None]:
        """Agent asks for one slot. Returns (perceived_value, volunteered_beat).

        `perceived_value` is what the AGENT ends up with -- i.e. after any
        configured entity corruption. The caller's true intent stays in
        self.facts, which is what the evaluator scores against. That asymmetry is
        how a misheard entity is modelled without an ASR stack.
        """
        self._agent_says(agent_text, act, slot=field)

        beat = self._due_beat()
        truth = self.facts.get(field) if field not in ("name", "dob") else self.identity.get(field)

        # Vague callers do not answer a specific-value question on the first try.
        if self.style == "vague" and field in ("pharmacy_choice", "desired_start"):
            self.trace.say("caller", self._vague_text(field))
            if beat:
                self.trace.say("caller", beat["text"])
            return None, beat

        reply = self._answer_text(field, truth)
        if beat and beat["type"] == "correction":
            reply = beat["text"]
            truth = self.facts.get(field)
        self.trace.say("caller", reply)
        if beat and beat["type"] == "urgent_symptom":
            self.trace.say("caller", beat["text"])

        perceived = self.scn.entity_corruption.get(field, truth)
        return perceived, beat

    def offer(self, agent_text: str, options: list[str], field: str) -> tuple[Any, dict | None]:
        """Agent offers concrete options; caller picks the one matching its intent."""
        self._agent_says(agent_text, "offer_options", options=options, slot=field)
        beat = self._due_beat()
        want = self.facts.get(field)
        if want in options:
            self.trace.say("caller", f"{self._pretty(want)} works.")
            chosen = want
        elif self.facts.get("fallback_" + field.replace("desired_", "")) in options:
            chosen = self.facts["fallback_" + field.replace("desired_", "")]
            self.trace.say("caller", f"Then let's do {self._pretty(chosen)}.")
        else:
            self.trace.say("caller", "None of those really work for me.")
            chosen = None
        if beat:
            self.trace.say("caller", beat["text"])
        perceived = self.scn.entity_corruption.get(field, chosen)
        return perceived, beat

    def inform(self, agent_text: str, act: str = "inform") -> dict | None:
        """Agent states something; caller acknowledges. Beats can still fire."""
        self._agent_says(agent_text, act)
        beat = self._due_beat()
        if beat:
            self.trace.say("caller", beat["text"])
        else:
            self.trace.say("caller", "Okay.")
        return beat

    def close(self, agent_text: str, act: str) -> None:
        self._agent_says(agent_text, act)
        self.trace.say("caller", "Alright, thank you.")

    # ----------------------------------------------------------- rendering --

    def _vague_text(self, field: str) -> str:
        return {
            "pharmacy_choice": "The Riverside one, you know, the one near me.",
            "desired_start": "Sometime in early October if you have it. Mornings are better.",
        }.get(field, "I'm not sure exactly.")

    def _answer_text(self, field: str, truth: Any) -> str:
        if field == "name":
            return f"It's {truth}."
        if field == "dob":
            return f"{truth}."
        if field == "drug":
            return f"It's my {truth}."
        if field == "pharmacy_query":
            return f"{truth}, please."
        if field == "pharmacy_choice":
            return f"{self._pretty(truth)}, yes."
        if field == "desired_start":
            return f"{self._pretty(truth)} if you have it."
        return f"{truth}."

    def _pretty(self, v: Any) -> str:
        m = {"PH-1": "Riverside on Elm Street", "PH-2": "Riverside on Elmwood Avenue",
             "PH-3": "Bayside Drug on Harbor Road", "PH-4": "Northgate Pharmacy"}
        if isinstance(v, str) and v in m:
            return m[v]
        if isinstance(v, str) and "T" in v and v[:2] == "20":
            d, t = v.split("T")
            return f"{d} at {t}"
        return str(v)
