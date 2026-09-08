"""
LLM-as-judge, scoped deliberately narrowly.

WHERE THIS IS ALLOWED TO BE USED, AND WHY

The README argues against using a judge for questions that world state can answer, and
that argument stands. This judge is pointed at the one half of the closure metric that
state genuinely cannot answer: *is this closing clear to a patient?* That is a language
question with no ground truth in any database. The other half -- did the action the
closing describes actually land -- stays deterministic and is never shown to the model.

That split is the design. A judge that can see state will start reasoning about whether
the task succeeded, which is not its question and which it will do worse than three lines
of Python.

REPRODUCIBILITY

Judge calls are recorded to a committed cassette keyed by a hash of
(model, prompt version, rendered prompt). With a key set, a miss calls the API and records.
With no key, a hit replays from the cassette and a miss returns UNAVAILABLE -- never a
fabricated verdict, and never a silent pass. That keeps the submission runnable by a
reviewer with no credentials, and it is also the right production design: judge outputs
are expensive, and a metric you cannot recompute identically is a metric you cannot
regression-test.

No SDK dependency on purpose -- stdlib urllib against either provider's HTTP API, so the
install list stays four packages.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROMPT_VERSION = "closure-judge-v1"
CACHE = Path(__file__).resolve().parents[3] / "artifacts" / "judge_cache" / "closure.json"
PROMPT_FILE = Path(__file__).parent / "judge_prompt.md"

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o-2024-11-20",
}


@dataclass
class JudgeVerdict:
    verdict: str | None          # "clear" | "unclear" | None when unavailable
    confidence: float | None
    reasoning: str
    quoted_evidence: str
    quote_verified: bool | None  # did the quote appear verbatim in the transcript?
    source: str                  # "cassette" | "api" | "unavailable"
    model: str | None = None


# --------------------------------------------------------------------------- #
# cassette
# --------------------------------------------------------------------------- #

def _load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def _save_cache(d: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, indent=2, sort_keys=True))


def _key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}|{PROMPT_VERSION}|{prompt}".encode()).hexdigest()[:24]


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #

def _provider() -> tuple[str, str, str] | None:
    """Returns (provider, api_key, model) or None if no credential is present."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return ("anthropic", os.environ["ANTHROPIC_API_KEY"],
                os.getenv("JUDGE_MODEL", DEFAULT_MODELS["anthropic"]))
    if os.getenv("OPENAI_API_KEY"):
        return ("openai", os.environ["OPENAI_API_KEY"],
                os.getenv("JUDGE_MODEL", DEFAULT_MODELS["openai"]))
    return None


def _post(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _call_api(provider: str, key: str, model: str, system: str, user: str) -> str:
    """temperature=0 everywhere. Not determinism -- these APIs are not deterministic even
    at 0 -- but it removes the sampling variance we can remove. The cassette is what
    actually makes results reproducible, which is the point of having one."""
    if provider == "anthropic":
        d = _post("https://api.anthropic.com/v1/messages",
                  {"content-type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"},
                  {"model": model, "max_tokens": 512, "temperature": 0,
                   "system": system, "messages": [{"role": "user", "content": user}]})
        return d["content"][0]["text"]
    d = _post("https://api.openai.com/v1/chat/completions",
              {"content-type": "application/json", "authorization": f"Bearer {key}"},
              {"model": model, "temperature": 0, "max_tokens": 512,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]})
    return d["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# prompt + parsing
# --------------------------------------------------------------------------- #

def _system_prompt() -> str:
    return PROMPT_FILE.read_text()


def _render(transcript: str, final_turn: str) -> str:
    return (f"<transcript>\n{transcript}\n</transcript>\n\n"
            f"<closing_turn>\n{final_turn}\n</closing_turn>\n\n"
            "Grade the closing turn against the rubric. JSON only.")


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError(f"judge returned no JSON object: {raw[:200]}")
    return json.loads(m.group(0))


def _norm(s: str) -> str:
    """Quote checking tolerates whitespace and smart punctuation, nothing else."""
    s = s.replace("—", "-").replace("’", "'").replace("“", '"')
    s = s.replace("”", '"').replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #

def judge_closure(transcript: str, final_turn: str, *, allow_api: bool = True) -> JudgeVerdict:
    prompt = _render(transcript, final_turn)
    cache = _load_cache()

    prov = _provider() if allow_api else None
    # A cassette entry is keyed by model, so replay needs to find the model that
    # recorded it. Try the live model first, then any recorded model.
    candidates = [prov[2]] if prov else []
    candidates += [rec["model"] for rec in cache.values()]
    for model in dict.fromkeys(candidates):
        hit = cache.get(_key(model, prompt))
        if hit:
            return _verdict_from(hit["response"], transcript, "cassette", hit["model"])

    if not prov:
        return JudgeVerdict(None, None,
                            "No cassette entry and no API key set. Reported as "
                            "UNAVAILABLE rather than guessed.", "", None, "unavailable")

    provider, key, model = prov
    raw = _call_api(provider, key, model, _system_prompt(), prompt)
    parsed = _parse(raw)
    cache[_key(model, prompt)] = {"model": model, "prompt_version": PROMPT_VERSION,
                                  "response": parsed}
    _save_cache(cache)
    return _verdict_from(parsed, transcript, "api", model)


def _verdict_from(p: dict, transcript: str, source: str, model: str) -> JudgeVerdict:
    quote = p.get("quoted_evidence", "") or ""
    # A deterministic check ON the judge. If the model cannot quote the transcript
    # verbatim, its reasoning is not grounded in the thing it was asked to read --
    # the same argument this whole platform makes, turned on the evaluator itself.
    verified = bool(quote) and _norm(quote) in _norm(transcript)
    return JudgeVerdict(
        verdict=p.get("verdict"),
        confidence=p.get("confidence"),
        reasoning=p.get("reasoning", ""),
        quoted_evidence=quote,
        quote_verified=verified,
        source=source,
        model=model,
    )
