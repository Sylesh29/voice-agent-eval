"""
Agent versions under test.

These are the "prompt change" in this experiment, expressed as a config diff so
that the difference between two agent versions is inspectable in the UI rather
than buried in a wall of prose. In production the same fields would be derived
from a versioned prompt + policy bundle; the point of modelling it this way is
that a release gate needs to know *which* behavioural knob moved, not just that
the prompt text changed.

v1 -> v2 is the change actually tested in the experiment. It is a plausible,
well-intentioned product change: "we are routing too much to staff and callers
are hanging up unsure, so complete more yourself and confirm clearly."

v3 is the change I made AFTER looking at what v2 did.
"""

AGENT_CONFIGS: dict[str, dict] = {
    "v1_conservative": {
        "label": "v1 — conservative baseline",
        "description": (
            "Escalates on any tool failure. Reads the tool result body before "
            "confirming. Enforces both hard guardrails and prose policy rules."
        ),
        "retry_on_timeout": False,
        "trust_ok_envelope": False,      # also inspects result body for errors
        "staff_task_on_failure": True,
        "enforce_hard_guardrails": True,  # Sched II, urgent symptoms — code-level
        "enforce_soft_policy": True,      # zero refills, post-op window — prose-level
        "verify_after_write": False,
        "closing_style": "cautious",
    },
    "v2_automation_push": {
        "label": "v2 — automation push",
        "description": (
            "The change under test. Aimed at cutting unnecessary staff work and "
            "leaving callers with a clear confirmation. Retries transient "
            "failures, completes rather than routing whenever it believes it can, "
            "and always closes with a specific confirmation."
        ),
        "retry_on_timeout": True,
        "trust_ok_envelope": True,       # <- if the call did not raise, say it worked
        "staff_task_on_failure": False,
        "enforce_hard_guardrails": True,  # hard guardrails survive a prompt rewrite
        "enforce_soft_policy": False,     # prose policy guidance did not
        "verify_after_write": False,
        "closing_style": "warm",
    },
    "v3_verified": {
        "label": "v3 — automation push + read-after-write",
        "description": (
            "Built after reading the v2 results. Keeps v2's automation gains, "
            "restores the policy rules as code rather than prose, and reads back "
            "every write before telling the caller it is done."
        ),
        "retry_on_timeout": True,
        "trust_ok_envelope": False,
        "staff_task_on_failure": True,
        "enforce_hard_guardrails": True,
        "enforce_soft_policy": True,
        "verify_after_write": True,
        "closing_style": "grounded",
    },
}
