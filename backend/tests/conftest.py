"""
Test-suite guarantees about the network.

This file exists because of a bug worth remembering. `test_missing_judge_is_na_never_a_pass`
deleted the API-key environment variables and asserted the judge degrades to N/A. It passed
on the machine it was written on — and it passed for the wrong reason: that machine's egress
blocked api.groq.com, so the call failed and produced N/A by accident.

On a machine with working network the same test resolved a key from the gitignored `.env`
(which `config.load_env()` re-populates into os.environ *after* monkeypatch removed it),
made a real API call, got a real verdict, and failed.

Two lessons, both of which this file encodes:

1. Deleting an environment variable is not the same as removing a credential, once you have
   a `.env` loader that puts it back.
2. A test that passes because the network was down is not passing. It is an
   environment-dependent assertion wearing a green tick — the same shape as an evaluator
   that scores well because the evidence it needed was missing, which is the defect this
   whole project is about.

So the guarantee is now structural rather than per-test: no test can reach the network, and
any attempt fails loudly instead of silently succeeding somewhere else.
"""
from __future__ import annotations

import pytest

from kyroneval import config
from kyroneval.evaluators import judge

CREDENTIAL_VARS = ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                   "KYRONEVAL_JUDGE", "JUDGE_PROVIDER", "JUDGE_MODEL")


@pytest.fixture(autouse=True)
def no_live_api(monkeypatch):
    """Applied to every test. Removes credentials, disables the .env loader that would
    put them back, and makes any outbound HTTP call an immediate loud failure."""
    for var in CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "SEARCH", [])
    monkeypatch.setattr(config, "_loaded", True)

    def _blocked(*_a, **_kw):
        raise RuntimeError(
            "A test attempted a live HTTP request. The suite must never spend money or "
            "depend on network reachability — patch _call_api or use a cassette instead.")

    monkeypatch.setattr(judge, "_request", _blocked)
