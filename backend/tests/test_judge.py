"""Tests for the judge seam.

The thing most worth testing here is not the judge's accuracy -- it is that a
MISSING judge degrades to N/A and never to a pass. An evaluator that silently
passes when its backend is unreachable turns a broken pipeline into a green
dashboard, which is the exact failure mode this whole project is about.
"""
import json
import os

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


# --------------------------------------------------------------------------- #
# provider resolution + tolerant parsing
#
# These exist because the judge is the only part of the system that talks to a
# network, and every failure mode here is silent-ish: a wrong model name, a
# reasoning model that prepends its scratchpad, a model that fences its JSON.
# --------------------------------------------------------------------------- #

def test_groq_is_picked_up_and_is_openai_wire_compatible(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    provider, key, model = judge.resolve_provider()
    assert (provider, key) == ("groq", "gsk_test")
    assert model == judge.DEFAULT_MODELS["groq"]
    assert judge.PROVIDERS["groq"][1].endswith("/openai/v1")
    assert judge._headers("groq", key)["authorization"] == "Bearer gsk_test"


def test_judge_model_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("JUDGE_MODEL", "openai/gpt-oss-120b")
    assert judge.resolve_provider()[2] == "openai/gpt-oss-120b"


def test_switching_model_misses_the_cassette(no_credentials, tmp_path, monkeypatch):
    """Cassette keys include the model, so a model swap re-records rather than
    silently attributing one model's verdicts to another."""
    scn, tr = _record(monkeypatch, tmp_path, "resched-ordinary", "v1_conservative",
                      {"verdict": "clear", "confidence": 0.9, "reasoning": "ok",
                       "quoted_evidence": "you're moved to"})
    prompt = judge._render(tr.transcript, closure._final_agent_turn(tr))
    assert judge._key("test-model", prompt) != judge._key("other-model", prompt)


@pytest.mark.parametrize("raw", [
    '{"verdict":"clear","confidence":0.9,"reasoning":"r","quoted_evidence":"q"}',
    '```json\n{"verdict":"clear","confidence":0.9,"reasoning":"r","quoted_evidence":"q"}\n```',
    '<think>Let me consider {this} carefully.</think>\n'
    '{"verdict":"clear","confidence":0.9,"reasoning":"r","quoted_evidence":"q"}',
    'Here is my answer:\n{"verdict":"clear","confidence":0.9,"reasoning":"r","quoted_evidence":"q"}\nHope that helps.',
])
def test_parser_survives_fences_reasoning_blocks_and_chatter(raw):
    assert judge._parse(raw)["verdict"] == "clear"


def test_parser_raises_rather_than_inventing_a_verdict():
    with pytest.raises(ValueError):
        judge._parse("I think the closing was pretty good overall.")


def test_unparseable_response_becomes_na_not_a_pass(tmp_path, monkeypatch):
    """A judge that returns garbage must not crash the run and must not pass."""
    monkeypatch.setattr(judge, "CACHE", tmp_path / "c.json")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(judge, "_call_api", lambda *a, **k: "no json here")
    v = judge.judge_closure("CALLER: hi\nAGENT: bye", "bye")
    assert v.verdict is None and v.source == "error"
    assert not (tmp_path / "c.json").exists(), "a failed call must not be cached"


def test_out_of_vocabulary_verdict_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "CACHE", tmp_path / "c.json")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(judge, "_call_api", lambda *a, **k: json.dumps(
        {"verdict": "mostly clear", "confidence": 1.0, "reasoning": "r",
         "quoted_evidence": "bye"}))
    assert judge.judge_closure("CALLER: hi\nAGENT: bye", "bye").verdict is None


# --------------------------------------------------------------------------- #
# credential hygiene
#
# The assignment says plainly: do not commit API keys or credentials. That is
# easy to honour on purpose and easy to break by accident -- a stray .env, a key
# pasted into a config while debugging. So it is a test, not a good intention.
# --------------------------------------------------------------------------- #

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SECRET_SHAPES = [
    (r"gsk_[A-Za-z0-9]{20,}", "Groq key"),
    (r"sk-ant-[A-Za-z0-9\-_]{20,}", "Anthropic key"),
    (r"sk-[A-Za-z0-9]{32,}", "OpenAI key"),
    (r"(?i)\b(api[_-]?key|secret|token)\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']", "inline credential"),
]


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [REPO / p for p in out.split("\0") if p]


def test_no_credentials_in_any_tracked_file():
    offenders = []
    for path in _tracked_files():
        if path.name == "test_judge.py" or not path.is_file():
            continue          # this file necessarily contains the patterns themselves
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in SECRET_SHAPES:
            m = re.search(pattern, text)
            if m:
                offenders.append(f"{path.relative_to(REPO)}: {label} near {m.group(0)[:12]}...")
    assert not offenders, "credentials found in tracked files:\n" + "\n".join(offenders)


def test_dotenv_is_not_tracked():
    tracked = {p.name for p in _tracked_files()}
    assert ".env" not in tracked, ".env must never be committed"
    assert ".env.example" in tracked, "the template SHOULD be committed, with empty values"


def test_env_example_has_no_filled_values():
    text = (REPO / "backend" / ".env.example").read_text()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip().endswith("_API_KEY"):
            assert val.strip() == "", f"{key.strip()} in .env.example must be empty"


def test_real_env_var_beats_dotenv(monkeypatch, tmp_path):
    """An explicit export must win, or CI behaves differently from a laptop."""
    from kyroneval import config
    f = tmp_path / ".env"
    f.write_text("GROQ_API_KEY=from_file\n")
    monkeypatch.setattr(config, "SEARCH", [f])
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.setenv("GROQ_API_KEY", "from_export")
    config.load_env(force=True)
    assert os.environ["GROQ_API_KEY"] == "from_export"


def test_dotenv_populates_when_env_is_unset(monkeypatch, tmp_path):
    from kyroneval import config
    f = tmp_path / ".env"
    f.write_text("# comment\nGROQ_API_KEY=\"from_file\"\nKYRONEVAL_JUDGE=1\n")
    monkeypatch.setattr(config, "SEARCH", [f])
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config.load_env(force=True)
    assert os.environ["GROQ_API_KEY"] == "from_file"


def test_every_provider_sends_an_explicit_user_agent():
    """urllib defaults to "Python-urllib/3.x", which Groq's Cloudflare edge refuses
    with a 403 that looks exactly like an auth failure. Cost an hour once."""
    for provider in judge.PROVIDERS:
        h = judge._headers(provider, "k")
        assert h.get("user-agent") == judge.USER_AGENT
        assert "urllib" not in h["user-agent"].lower()


def test_auth_shape_is_right_per_provider():
    assert judge._headers("anthropic", "k")["x-api-key"] == "k"
    assert "authorization" not in judge._headers("anthropic", "k")
    for p in ("groq", "openai"):
        assert judge._headers(p, "k")["authorization"] == "Bearer k"


def test_agreement_is_never_reported_without_its_denominator():
    """Regression test for the worst bug in this project.

    Agreement computed over only the rows where the predictor happened to answer
    reported 1.0 when 37 of 51 judge calls had been lost to rate limiting. Any
    comparison with excluded rows must be marked NOT REPORTABLE and must carry
    its coverage.
    """
    from kyroneval import calibrate
    import inspect
    src = inspect.getsource(calibrate)
    for field in ("n_scored", "n_total", "n_excluded_no_verdict", "coverage",
                  "reportable", "minority_class_n"):
        assert field in src, f"compare() must expose {field}"
