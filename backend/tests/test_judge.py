"""Tests for the judge seam.

The thing most worth testing here is not the judge's accuracy -- it is that a
MISSING judge degrades to N/A and never to a pass. An evaluator that silently
passes when its backend is unreachable turns a broken pipeline into a green
dashboard, which is the exact failure mode this whole project is about.
"""
import json

import pytest

from kyroneval.evaluators import closure, judge
from kyroneval.runner import run_scenario
from kyroneval.scenario import Scenario

SCN = {s.id: s for s in Scenario.load_all()}


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KYRONEVAL_JUDGE", raising=False)


def test_missing_judge_is_na_never_a_pass(no_credentials, tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "CACHE", tmp_path / "empty.json")
    scn = SCN["refill-ordinary-keep-pharmacy"]
    tr = run_scenario(scn, "v1_conservative", "t")
    for fn in (closure.judge_clarity, closure.grounded_closure_v4):
        r = fn(scn, tr)
        assert r.value is None and r.passed is None, f"{r.name} must be N/A, not a verdict"


def test_deterministic_half_survives_an_unavailable_judge(no_credentials, tmp_path, monkeypatch):
    """v3 must be completely unaffected by whether the judge is reachable."""
    monkeypatch.setattr(judge, "CACHE", tmp_path / "empty.json")
    scn = SCN["refill-hard-silent-noop"]
    tr = run_scenario(scn, "v1_conservative", "t")
    assert closure.grounded_closure_v3(scn, tr).passed is False
    assert closure.grounded_closure_v4(scn, tr).passed is None


def _record(monkeypatch, tmp_path, scn_id, agent, payload):
    """Write a cassette entry the way a real recording would, then replay it."""
    scn, cache_file = SCN[scn_id], tmp_path / "c.json"
    monkeypatch.setattr(judge, "CACHE", cache_file)
    tr = run_scenario(scn, agent, "t")
    prompt = judge._render(tr.transcript, closure._final_agent_turn(tr))
    key = judge._key("test-model", prompt)
    cache_file.write_text(json.dumps(
        {key: {"model": "test-model", "prompt_version": judge.PROMPT_VERSION,
               "response": payload}}))
    return scn, tr


def test_cassette_replays_without_any_credential(no_credentials, tmp_path, monkeypatch):
    scn, tr = _record(monkeypatch, tmp_path, "refill-hard-silent-noop", "v1_conservative",
                      {"verdict": "clear", "confidence": 0.9, "reasoning": "states status and next step",
                       "quoted_evidence": "your Lisinopril refill is on its way"})
    r = closure.judge_clarity(scn, tr)
    assert r.passed is True
    assert any("cassette" in e for e in r.evidence)
    # clear closing + action that never landed = v4 fails, which is the whole point
    assert closure.grounded_closure_v4(scn, tr).passed is False


def test_fabricated_quote_is_flagged(no_credentials, tmp_path, monkeypatch):
    """A deterministic check on the judge itself: if it cannot quote its own input
    verbatim, its reasoning is not grounded in the evidence it was handed."""
    scn, tr = _record(monkeypatch, tmp_path, "refill-ordinary-keep-pharmacy", "v1_conservative",
                      {"verdict": "clear", "confidence": 0.95, "reasoning": "sounds fine",
                       "quoted_evidence": "I have booked your MRI for Tuesday"})
    r = closure.judge_clarity(scn, tr)
    assert any("WARNING" in e for e in r.evidence)


def test_prompt_version_change_invalidates_the_cassette(no_credentials, tmp_path, monkeypatch):
    """Editing the prompt must force a re-record. Otherwise historical scores are
    attributed to a prompt that no longer exists."""
    scn, tr = _record(monkeypatch, tmp_path, "resched-ordinary", "v1_conservative",
                      {"verdict": "clear", "confidence": 0.9, "reasoning": "ok",
                       "quoted_evidence": "you're moved to"})
    assert closure.judge_clarity(scn, tr).passed is True
    monkeypatch.setattr(judge, "PROMPT_VERSION", "closure-judge-v2-edited")
    assert closure.judge_clarity(scn, tr).passed is None, \
        "a changed prompt must miss the cassette, not silently reuse old verdicts"
