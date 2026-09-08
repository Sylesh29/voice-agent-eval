# Kyron Eval — an evaluation platform for a healthcare voice agent

**Author:** Sylesh Kona · **Window:** 8 hours, contiguous. Start/stop timestamps are in `TIMELOG.md` and the git history is the honest record.

---

## The one-sentence thesis

**A voice agent's transcript is not evidence that the work got done.** Every metric in this platform
is built to separate *what the agent said* from *what actually changed in the world*, because the
failure that matters most in patient access is the call that sounds perfect and leaves the refill
sitting in nobody's queue.

Everything below follows from that: the ground truth is simulated **tool/world state**, not the
transcript; the headline metric is **false completion**; and results are reported **sliced**, because
an aggregate can improve while the slice that can hurt a patient gets worse.

---

## Scope: what I chose to build, and what I deliberately did not

Full coverage of Parts 1–7 in eight hours would mean eight shallow things. I built one spine deeply.

**Built:**
- Part 1 — 2 workflows, a scenario dataset with ordinary / hard / must-escalate / negative-control cases, explicit ground-truth model.
- Part 2 — deterministic replay harness with a simulated caller, a mock tool layer with injectable faults, full trace capture.
- Part 3 — 6 metrics, including one judgment metric taken through the full human-label → evaluator → disagreement → revision loop.
- Part 4 — working FastAPI + SQLite + Next.js app: runs, sliced metrics, A/B compare, trace inspector, human override.
- Part 5 — a real A/B experiment with committed raw output.
- Parts 6/7 — findings and production notes, below.

**Deliberately not built** (and why):
- **No audio / speech stack.** ASR error is a real and important failure source, but simulating it convincingly is a day of work on its own and the evaluation *architecture* — state-verified scoring — is identical whether the misheard entity came from ASR or from an LLM. I inject entity corruption at the transcript layer instead and say so.
- **No LLM-as-judge as a primary metric.** See "Why there is no LLM judge here" below. The seam exists (`evaluators/judge.py`) and is unimplemented on purpose.
- **No auth, no multi-tenancy, no deployment.** Single-user local app.
- **No real LLM agent.** Both agents under test are deterministic rule-based policies. This is a real limitation and I discuss what it does and does not let me conclude.

---

## Stated assumptions

1. **The production voice agent already exists and is out of scope.** My system sits around it. The `Agent` protocol is the seam; the two agents in this repo are stand-ins that exist to be *told apart* by the platform.
2. **Ground truth is the final state of the simulated world plus the scenario's declared policy**, not a human reading the transcript. Where a conclusion genuinely cannot come from state (e.g. "did the caller leave with a clear understanding"), I say so explicitly and label by hand.
3. **A scenario's declared `must_escalate` is customer policy, not my opinion.** In production this comes from a per-customer policy document; here it is a field on the scenario.
4. **All data is synthetic.** Names, MRNs, medications, pharmacies, and phone numbers are invented. No credentials in the repo; the whole thing runs with no API keys.
5. **The reviewer will not provision anything.** SQLite, no Docker, no external services. `uv sync && uv run ...` and `npm i && npm run dev`.

## Ambiguities I resolved myself rather than asking

- "Evaluation platform" could mean an offline batch harness or an online production monitor. I built **offline/pre-release**, because the prompt's Part 5 is a pre-production A/B and that is where an 8-hour slice is most defensible. Part 7 covers what changes for online.
- The prompt does not define what counts as task completion. I made it **state-verified and per-scenario declared**, which is the strongest available definition and the one that makes false completion measurable.

---

*(Sections for metrics, the experiment, findings, production design, AI use, and known failures are filled in as the work lands.)*
