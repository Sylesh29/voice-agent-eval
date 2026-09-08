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

PROVIDERS

Groq, Anthropic, and OpenAI. Groq is OpenAI-wire-compatible, so it shares a code path.
No SDK dependency on purpose -- stdlib urllib against the HTTP APIs, so the install list
stays four packages and there is nothing to pin.

Quick check before spending anything:

    python -m kyroneval.evaluators.judge --list-models   # what your key can actually reach
    python -m kyroneval.evaluators.judge --smoke         # one real call, end to end
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

from ..config import load_env

PROMPT_VERSION = "closure-judge-v1"
CACHE = Path(__file__).resolve().parents[3] / "artifacts" / "judge_cache" / "closure.json"
PROMPT_FILE = Path(__file__).parent / "judge_prompt.md"

# Groq rotates model availability faster than the other two, so treat this default as a
# starting point and confirm with --list-models. JUDGE_MODEL overrides it everywhere.
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o-2024-11-20",
}

# stdlib urllib sends "Python-urllib/3.x" by default, and Groq's Cloudflare edge
# rejects that signature outright with HTTP 403 "error code: 1010" -- which reads
# like an auth failure and is not one. Identify the client properly.
USER_AGENT = "kyron-eval/0.1 (closure-judge; +https://github.com/sylesh29)"

PROVIDERS = {
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
}


@dataclass
class JudgeVerdict:
    verdict: str | None          # "clear" | "unclear" | None when unavailable
    confidence: float | None
    reasoning: str
    quoted_evidence: str
    quote_verified: bool | None  # did the quote appear verbatim in the transcript?
    source: str                  # "cassette" | "api" | "unavailable" | "error"
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

def resolve_provider() -> tuple[str, str, str] | None:
    """(provider, api_key, model), or None when no credential is present.

    Reads a gitignored `.env` if one exists, so you set the key once instead of
    exporting it every shell. Real environment variables take precedence.

    JUDGE_PROVIDER pins the choice; otherwise the first configured provider in
    PROVIDERS order wins.
    """
    load_env()
    pinned = os.getenv("JUDGE_PROVIDER")
    order = [pinned] if pinned else list(PROVIDERS)
    for name in order:
        if name not in PROVIDERS:
            raise ValueError(f"unknown JUDGE_PROVIDER {name!r}; "
                             f"expected one of {sorted(PROVIDERS)}")
        env, _ = PROVIDERS[name]
        if os.getenv(env):
            return (name, os.environ[env],
                    os.getenv("JUDGE_MODEL", DEFAULT_MODELS[name]))
    return None


def _headers(provider: str, key: str) -> dict:
    base = {"content-type": "application/json", "accept": "application/json",
            "user-agent": USER_AGENT}
    if provider == "anthropic":
        return {**base, "x-api-key": key, "anthropic-version": "2023-06-01"}
    return {**base, "authorization": f"Bearer {key}"}


def _request(url: str, headers: dict, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Surface the provider's own message. A bare "HTTP 400" while debugging a
        # model name is the single most annoying error in this whole exercise.
        body = e.read().decode(errors="replace")[:600]
        hint = ""
        if "1010" in body:
            hint = ("\nCloudflare rejected the client signature (error 1010). This is "
                    "NOT an auth or model-name problem -- it means the User-Agent was "
                    "refused. Check that USER_AGENT is being sent.")
        elif e.code in (401, 403):
            hint = "\nCheck the API key, and that it belongs to the selected provider."
        elif e.code == 404:
            hint = "\nUsually a bad model name -- run `--list-models` and set JUDGE_MODEL."
        raise RuntimeError(f"{e.code} from {url}\n{body}{hint}") from None


def list_models() -> list[str]:
    prov = resolve_provider()
    if not prov:
        raise RuntimeError("no API key set (GROQ_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    provider, key, _ = prov
    _, base = PROVIDERS[provider]
    d = _request(f"{base}/models", _headers(provider, key))
    return sorted(m.get("id") or m.get("name") for m in d.get("data", []))


def _call_api(provider: str, key: str, model: str, system: str, user: str) -> str:
    """temperature=0 everywhere. Not determinism -- none of these APIs are deterministic
    even at 0 -- but it removes the sampling variance we can remove. The cassette is what
    actually makes results reproducible, which is the point of having one."""
    _, base = PROVIDERS[provider]
    if provider == "anthropic":
        d = _request(f"{base}/messages", _headers(provider, key),
                     {"model": model, "max_tokens": 512, "temperature": 0,
                      "system": system, "messages": [{"role": "user", "content": user}]})
        return d["content"][0]["text"]

    payload = {"model": model, "temperature": 0, "max_tokens": 1024,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if provider == "openai":
        payload["response_format"] = {"type": "json_object"}
    else:
        # Groq supports JSON mode on most but not all models, and rejects it loudly on
        # the rest. Try it, fall back to prompt-enforced JSON -- `_parse` is tolerant.
        try:
            return _request(f"{base}/chat/completions", _headers(provider, key),
                            {**payload, "response_format": {"type": "json_object"}}
                            )["choices"][0]["message"]["content"]
        except RuntimeError:
            pass
    d = _request(f"{base}/chat/completions", _headers(provider, key), payload)
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
    """Tolerant JSON extraction.

    Several Groq-hosted models are reasoning models that emit a <think> block before
    the answer, and most models will wrap JSON in a code fence given half a chance.
    Strip those, then take the last balanced object that parses -- last, because the
    answer follows the reasoning.
    """
    s = re.sub(r"<think>.*?</think>", "", raw, flags=re.S | re.I)
    s = re.sub(r"```(?:json)?\s*(.*?)```", r"\1", s, flags=re.S)
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    starts = [i for i, ch in enumerate(s) if ch == "{"]
    for start in reversed(starts):
        depth = 0
        for i in range(start, len(s)):
            depth += (s[i] == "{") - (s[i] == "}")
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except json.JSONDecodeError:
                    break
    raise ValueError(f"judge returned no parseable JSON object: {raw[:300]}")


def _norm(s: str) -> str:
    """Quote checking tolerates whitespace and smart punctuation, nothing else."""
    for a, b in (("—", "-"), ("’", "'"), ("“", '"'),
                 ("”", '"'), ("–", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #

def judge_closure(transcript: str, final_turn: str, *, allow_api: bool = True) -> JudgeVerdict:
    prompt = _render(transcript, final_turn)
    cache = _load_cache()

    prov = resolve_provider() if allow_api else None
    # A cassette entry is keyed by model, so replay has to find the model that recorded
    # it. Try the live model first, then any model present in the cassette.
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
    try:
        raw = _call_api(provider, key, model, _system_prompt(), prompt)
        parsed = _parse(raw)
    except Exception as e:
        # A failed judge call must not take down an evaluation run, and must not
        # become a pass. It becomes a visible N/A carrying the error.
        return JudgeVerdict(None, None, f"judge call failed: {e}", "", None,
                            "error", model)
    cache[_key(model, prompt)] = {"model": model, "prompt_version": PROMPT_VERSION,
                                  "provider": provider, "response": parsed}
    _save_cache(cache)
    return _verdict_from(parsed, transcript, "api", model)


def _verdict_from(p: dict, transcript: str, source: str, model: str) -> JudgeVerdict:
    quote = p.get("quoted_evidence", "") or ""
    # A deterministic check ON the judge. If the model cannot quote the transcript
    # verbatim, its reasoning is not grounded in the thing it was asked to read --
    # the same argument this whole platform makes, turned on the evaluator itself.
    verified = bool(quote) and _norm(quote) in _norm(transcript)
    verdict = p.get("verdict")
    if verdict not in ("clear", "unclear", None):
        verdict = None
    return JudgeVerdict(
        verdict=verdict,
        confidence=p.get("confidence"),
        reasoning=p.get("reasoning", ""),
        quoted_evidence=quote,
        quote_verified=verified,
        source=source,
        model=model,
    )


# --------------------------------------------------------------------------- #
# operator commands -- check the key and the model name before spending anything
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "--smoke"
    prov = resolve_provider()
    if not prov:
        sys.exit("no API key found. set GROQ_API_KEY (or ANTHROPIC_API_KEY / OPENAI_API_KEY).")
    provider, _, model = prov
    print(f"provider={provider}  model={model}")

    if arg == "--list-models":
        for m in list_models():
            print(("* " if m == model else "  ") + m)
        sys.exit(0)

    demo = ("CALLER: Hi, I need a refill.\n"
            "AGENT: I've submitted it - your Lisinopril refill is on its way to "
            "Riverside on Elm Street. I'd suggest checking back if you haven't heard "
            "anything by tomorrow.\nCALLER: Alright, thank you.")
    final = demo.split("AGENT: ")[1].split("\nCALLER")[0]
    v = judge_closure(demo, final)
    print(f"source={v.source}  verdict={v.verdict}  confidence={v.confidence}")
    print(f"reasoning: {v.reasoning}")
    print(f"quote: {v.quoted_evidence!r}  verbatim_in_transcript={v.quote_verified}")
    if v.verdict is None:
        sys.exit(f"\nFAILED -- {v.reasoning}\n"
                 "if this is a model-name error, run --list-models and set JUDGE_MODEL.")
    print("\nOK - key works, model responds, JSON parses.")
