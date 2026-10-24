# Revenium metering for the closure judge

The customer is an AI evaluation team, and the platform is my own voice agent evaluator. Its one paid component is an LLM judge that grades whether the agent's closing line was clear to a patient.

This folder meters it through [Revenium](https://www.revenium.ai) so every judge call carries its cost, its customer, its trace, and its grounding check.

## What changed

Nothing in `backend/`. The judge there talks to providers over stdlib `urllib` on purpose (no SDK to pin, cassette replay for reviewers), so nothing can intercept it. This sidecar reuses the judge's own system prompt, renderer, parser, and quote check, and sends the calls through the official provider SDKs instead, with Revenium's middleware imported:

```python
import revenium_middleware.openai             # instruments the OpenAI SDK on import

client.chat.completions.create(
    model=model, messages=[...],
    usage_metadata={
        "organizationName": "Harbor Pediatrics",   # which customer this spend belongs to
        "productName": "voice-agent-eval",
        "agent": "closure-judge-v1",
        "task_type": "llm-judge",
        "trace_id": "<batch>-<agent version>-<scenario>",
        "retry_number": 0,
    },
)
```

The deterministic quote check runs on every verdict and is reported as a metered tool call (`quote-verifier`), so its pass rate sits next to the judge's spend.

The three clinic names are fictional. Each agent version stands in for a different customer's voice agent, which gives the dashboard something real to group by.

## Run it

From the repo root:

```bash
uv pip install -r integrations/revenium/requirements.txt
cp integrations/revenium/.env.example integrations/revenium/.env   # then fill in keys

python integrations/revenium/meter_judge.py --dry-run --smoke   # prints the metadata, calls nothing
python integrations/revenium/meter_judge.py --smoke             # one real call
python integrations/revenium/meter_judge.py                     # 17 scenarios x 3 agent versions x each model
python integrations/revenium/meter_judge.py --runaway 40        # simulated retry storm on one customer
```

A full run with `gpt-4o-mini` and `gpt-4o` is 102 judge calls at roughly 700 input tokens each, well under a dollar. Anthropic models work the same way (`--models anthropic:claude-haiku-4-5,anthropic:claude-sonnet-4-5`).

## First real run (Oct 23 2026)

| model | calls | errors | quote ok | vs labels | vs gpt-4o | p50 ms |
|---|---|---|---|---|---|---|
| gpt-4o-mini | 51 | 0 | 100% | 21/21 | 51/51 | 1445 |
| gpt-4o | 51 | 0 | 100% | 21/21 | ref | 1356 |

204 metering events delivered (102 completions, 102 tool events), 0 failed. Both judges marked the same 3 of 51 closings unclear, one per customer. The honest caveat: 48 of 51 cases are easy, so full agreement here says the cheap judge is safe on this dataset, not that it is safe on harder traffic. The production answer is to run the cheap judge everywhere and send low confidence verdicts to the reference model.

## What the summary means

| column | meaning |
|---|---|
| quote ok | share of verdicts whose cited quote appears verbatim in the transcript |
| vs labels | agreement with my hand labels; only 21 labels and 20 are "clear", so read with the kappa caveat in the main README |
| vs ref | agreement with the last model in `--models`, the most trusted one; this is the number that decides whether the cheap judge can take the bulk of the traffic |

## Why `--runaway`

The original judge once lost 37 of 51 calls to rate limiting during a recording run. A retry loop without a cap is exactly how an eval job quietly multiplies its own cost. The flag replays that failure on purpose, against one customer, so a Revenium spike or budget alert has something real to catch.

## Hard stop (Oct 23 2026)

Rule in Revenium Guardrails: Total Cost, grouped by organization, $0.12 daily, Enforce a hard stop on, shadow mode off. SDK side, in `.env`:

```
REVENIUM_CIRCUIT_BREAKER_ENABLED=true
REVENIUM_TEAM_ID=<team id>
REVENIUM_ENFORCEMENT_BASE_URL=https://api.revenium.ai/profitstream
REVENIUM_CB_POLL_INTERVAL_SECONDS=10
REVENIUM_CACHE_DIR=integrations/revenium/.cache
```

`python integrations/revenium/check_rules.py` prints what the SDK can see; `watch_rule.py` polls until a rule trips.

What happened:

1. A 40 call storm on Harbor Pediatrics ($0.104) went through. The rule only counts spend from its own creation, so Harbor was still under the limit.
2. A second wave, one call at a time, was blocked on call 26: `Request blocked by Revenium enforcement rule: Judge hard stop per customer`. The provider was never called.
3. Without `REVENIUM_CACHE_DIR`, a fresh process lets its first call through before the first rule poll (fail open by design). With the cache, the first call is blocked too.

Things I'd raise with the Revenium team:

- The enforcement endpoint needs the `/profitstream` base path; the default derived from `REVENIUM_METERING_BASE_URL` returns 404.
- The rule is grouped by organization, but the enforcement payload returns `groupBreakdown: null`, so SDK 0.10.1 falls back to the rule level `breached` flag. Once Harbor tripped it, Maple Family Practice, still under its own limit, was blocked as well. Per customer blocking did not work in this run.
- Email is not available as a channel on enforcing rules, so alerting by email needs a second, notify only rule.
