# Time log (wall clock, honest)

| Elapsed | What |
|---|---|
| 0:00 | Read the problem statement twice. Repo init, README assumptions + scope committed before any feature code. |
| 0:15 | World + fault-injecting tool layer. Chose `silent_noop` as the central fault because it is invisible to any transcript-based evaluator. |
| 0:30 | Scenario schema + 17-scenario dataset across 2 workflows, 4 tiers. |
| 0:45 | Caller sim, three agent configs (a config diff, not a prompt diff), runner, trace capture. |
| 1:00 | Six state-verified metrics + closure v1. First full run of all three agents. Results were not what I predicted — see Experiment. |
| 1:15 | Hand-labelled 21 traces from the transcript only, then a second pass with world state revealed. |
| 1:45 | Closure evaluator v1 -> v2 -> v3, each revision forced by a specific disagreement I investigated. Also revised escalation_precision after it penalised correct behaviour. |
| 2:15 | FastAPI + SQLite backend; Next.js UI (runs, sliced metrics, A/B compare, trace inspector, failure patterns, calibration, human review). |
| 2:45 | 20 tests. Mix-sensitivity exhibit — the reason the aggregate moved the way it did. |
| 3:00 | README: experiment, findings, production notes, AI use, known failures. Verified from a clean clone. |
| 3:30 | Closure v4: LLM judge on the clarity half only, deterministic grounding untouched. Cassette record/replay, versioned prompt, quote-verification check on the judge. 25 tests. |
| 3:45 | Groq support (OpenAI-wire-compatible), `--list-models` / `--smoke` preflight, tolerant parser for reasoning-model output. 35 tests. |
| 4:15 | Recorded the judge against the suite. 37 of 51 calls lost to rate limiting — and calibrate reported acc 1.000 / kappa 1.000 over the survivors, because it silently dropped rows with no verdict. Caught by inspecting a result that flattered me. Fixed both: retry-with-backoff, and coverage as a first-class field with NOT REPORTABLE below 100%. |
