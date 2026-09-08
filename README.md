# Kyron Eval — an evaluation platform for a healthcare voice agent

**Sylesh Kona** · 8-hour take-home · all data synthetic · no API keys required to run anything here.

---

## The thesis

**A voice agent's transcript is not evidence that the work got done.**

Every metric in this platform separates *what the agent said* from *what actually changed
in the world*, because the failure that matters most in patient access is the call that
sounds perfect and leaves the refill sitting in nobody's queue.

Three consequences run through the whole submission:

1. **Ground truth is simulated tool/world state**, not the transcript.
2. **The headline metric is false completion** — the agent claimed the task was done and
   the world says otherwise. It is uncomputable from a transcript, by any evaluator,
   including an LLM judge.
3. **Results are reported sliced.** The experiment below produces a case where the
   headline moves 2 points and a safety slice moves 87.

---

## Run it

No Docker, no Postgres, no keys. Two terminals.

```bash
# 1. backend + evaluation engine
cd backend
uv venv --python 3.10 .venv && uv pip install --python .venv/bin/python \
    fastapi "uvicorn[standard]" pydantic pytest httpx
.venv/bin/python -m pytest tests -q                    # 20 tests
.venv/bin/python -m kyroneval.cli run --agent v1_conservative     --out ../artifacts/runs --run-id v1_conservative
.venv/bin/python -m kyroneval.cli run --agent v2_automation_push  --out ../artifacts/runs --run-id v2_automation_push
.venv/bin/python -m kyroneval.cli run --agent v3_verified         --out ../artifacts/runs --run-id v3_verified
.venv/bin/python -m kyroneval.calibrate       # evaluator-vs-human comparison
.venv/bin/python -m kyroneval.reweight        # mix-sensitivity exhibit
.venv/bin/uvicorn app.main:app --port 8000

# 2. UI
cd frontend && npm install && npm run dev     # http://localhost:3000
```

**The LLM judge runs from a committed cassette by default — no key needed.** Recorded
verdicts live in `artifacts/judge_cache/closure.json` and replay deterministically. To
re-record against a live model:

```bash
export GROQ_API_KEY=...             # or ANTHROPIC_API_KEY / OPENAI_API_KEY, auto-detected
export KYRONEVAL_JUDGE=1            # explicit opt-in, so the test suite never spends money

# confirm the key and model before spending anything
.venv/bin/python -m kyroneval.evaluators.judge --list-models
.venv/bin/python -m kyroneval.evaluators.judge --smoke

for a in v1_conservative v2_automation_push v3_verified; do
  .venv/bin/python -m kyroneval.cli run --agent $a --out ../artifacts/runs --run-id $a
done
.venv/bin/python -m kyroneval.calibrate
```

Three providers are supported (`JUDGE_PROVIDER` pins one, `JUDGE_MODEL` overrides the
model). Groq is OpenAI-wire-compatible so it shares a code path; the only real differences
are that model provisioning differs per account — a model available on one key 404s on
another, hence `--list-models` — and that several models on it are reasoning models that
emit a `<think>` block before the answer, which the response parser strips. A judge call that fails or returns unparseable output becomes a
visible **N/A carrying the error**, never a pass and never a crashed run.

With no key **and** no cassette entry, judge-backed metrics report **N/A — never a pass.**
An evaluator that silently passes when its backend is unreachable turns a broken pipeline
into a green dashboard, which is the failure mode this whole project is about.

Runs are already committed under `artifacts/`, so the UI has data before you run anything.
A test (`test_committed_artifacts_match_a_fresh_run`) fails if those artifacts drift from
what the code now produces — I did not want a README quoting numbers the code no longer makes.

**Where to look first:** `/compare` with `v1_conservative → v2_automation_push`, then
`/calibration`.

**Reproducibility, verified:** cloned fresh and re-ran the whole pipeline — 20 tests pass
and every committed run artifact comes back byte-identical apart from its `created_at`
timestamp. There is no seeded randomness anywhere; the agents and the caller are
deterministic by design (see below).

---

## What is real, mocked, and omitted

| | |
|---|---|
| **Real** | The LLM judge on the clarity half of closure (recorded to a committed cassette so it replays with no key). Scenario contracts, the simulated world and its state transitions, the fault injector, all six state-verified metrics, the closure evaluator and its three revisions, the human labels, the API, the database, the UI, the A/B experiment and every number quoted below. |
| **Mocked** | The agent (deterministic rule-based policy, not an LLM). The caller (deterministic slot-answerer with scripted perturbations, not an LLM patient). The EHR / pharmacy / scheduling systems. |
| **Omitted** | Audio and any speech stack. Auth, multi-tenancy, deployment. An LLM-backed *agent* or *caller*. Barge-in, disfluency, emotional escalation. |

### Where an LLM belongs here, and where it does not

Not a resource constraint — a deliberate placement I would defend.

The failure this platform is built to catch is a **fluent, confident, entirely
well-formed** claim that something happened when it did not. An LLM judge reading that
transcript has no access to the pharmacy queue. It will score it highly, correctly, and
uselessly. For verifiable fields, deterministic checks — state comparison, format
validation, read-after-write — dominate a judge, and the calibration section shows a
lexical evaluator and a *human* both failing in exactly this way on the same six traces.

A judge earns its cost on the opposite kind of question: one with no ground truth to
compare against. So there is exactly one in this repo, and it is scoped tightly.

The closure metric has two halves. *Is this closing clear to a patient?* is a language
judgment with no answer in any database — that is the judge's. *Did the action it describes
actually land?* is a question state answers exactly — that stays deterministic, and the
judge is never shown world state, the scenario contract, or the tool calls. `v4 =
judge_clarity AND asserted_action_landed`. The split is the design; see Part 3.

What I would not do is point a judge at a question state can answer. The same reasoning
applies to the agent and caller. An LLM caller produces better surface
language and destroys reproducibility, and a cooperative LLM patient makes every agent
look good — simulator bias that would corrupt the exact A/B comparison this platform
exists to make. A deterministic subject means a metric that moved can be attributed to a
specific behavioural rule rather than to sampling noise in the subject.

**Cost of that choice, stated plainly:** nothing here demonstrates anything about
language-understanding failures — hallucinated entities, instruction drift, injection via
caller speech. Any claim I made about "an LLM agent" would be unearned. The `Agent` seam
is a `run()` method; swapping one in is a new class, not a refactor.

---

## Part 1 — Modelling the problem

**Two workflows:** prescription refill / pharmacy change, and appointment reschedule.
Both were chosen because the transcript and the world can come apart in them: each has
crisp critical entities, a hard safety rule, and a soft policy rule.

**17 scenarios**, four tiers:

| Tier | n | Purpose |
|---|---|---|
| `ordinary` | 3 | Baseline. If an evaluator flags these, the evaluator is broken. |
| `hard` | 9 | Ambiguity, mid-call correction, and the four injected tool faults. |
| `control_escalate` | 3 | **The correct answer is to refuse.** Schedule II refill, post-op reschedule, urgent symptom mid-call. |
| `control_negative` | 2 | Nothing anomalous. Present so that an evaluator which fires on everything looks wrong instead of looking sensitive. |

Scenarios are **contracts, not scripts**. A scenario declares the caller's goal and true
intent, the policy that applies, the entities that must be correct, forbidden actions, and
the terminal world state that counts as success. Nothing asserts on the agent's phrasing —
an assertion on wording distinguishes agents that talk differently, not agents that behave
differently.

### Ground truth, and what it cannot cover

| Question | Ground truth | Source |
|---|---|---|
| Did the work happen? | Final simulated world state | `world.World` after the run |
| Were critical entities right? | Tool-call arguments vs the caller's declared true intent | trace + scenario |
| Should this have escalated? | Scenario policy field | customer policy, modelled as data |
| Did the caller leave correctly informed? | **Human label** — twice, once transcript-only and once with state | `kyroneval/labels/` |

**Cannot be established from a transcript alone:** whether a write landed; whether the
pharmacy the agent *sent to* is the one the caller *meant*; whether a duplicate was
created; whether an escalation was required. Every one of those is a metric here, and
every one needs state.

**What this sample does not represent.** It is adversarially enriched — 12 of 17 scenarios
are hard or must-escalate. It is not a frequency estimate of anything and I do not treat
it as one; the mix-sensitivity exhibit below exists specifically to make that concrete.
It also contains no multi-intent calls, no repeat callers, no interpreter or third-party
callers, no billing or clinical-message workflows, and two patients carry most of the load.

---

## Part 2 — The harness

`scenario → caller sim → agent → fault-injected tool layer → world → trace`.

Every run gets a **fresh world**, so no scenario can contaminate another. Traces capture
turns with structured dialogue acts, every tool call with its arguments and injected
fault, world snapshots before and after, and a rendered state delta.

**The fault modes are the design.** They are not random errors; each produces one
nameable divergence between transcript and reality:

| Fault | What the agent sees | What actually happens |
|---|---|---|
| `error` | loud failure | nothing written |
| `timeout` | loud failure | nothing written; a retry would work |
| `timeout_after_write` | loud failure | **the write landed** — a retry duplicates it |
| `silent_noop` | **success** | **nothing written** |

`silent_noop` is what a 200 from a partner API that dropped the message looks like from
inside an agent. It is invisible to every transcript-based evaluator. Half the interesting
results below come from it.

**What the harness can tell you:** how an agent handles ambiguity, correction, policy
boundaries, and the four failure shapes above; whether two configurations behave
differently and where.

**What it cannot:** anything about audio, ASR, latency, barge-in, or how a real caller
behaves when confused. Entity corruption is *injected* at the transcript layer rather than
emerging from mishearing. Reproducibility was bought at the cost of surface realism, and
the numbers do not transfer to those failure modes.

---

## Part 3 — What I measured

| Metric | Question | Evidence needed | Transcript alone? |
|---|---|---|---|
| `task_success` | Did the world reach the declared correct state? | state + contract | **no** |
| `critical_entity_accuracy` | Were the entities right *in the action*, not the words? | tool args + intent | **no** |
| `false_completion` | Of calls claiming success, how many actually succeeded? | claim + state | **no** |
| `false_failure_report` | Of calls claiming failure, how many actually failed? | claim + state | **no** |
| `escalation_recall` | On must-escalate: right queue, live transfer, forbidden action avoided? | state + policy | no |
| `escalation_precision` | On the rest: was a handoff manufactured? | state + policy | no |
| `unnecessary_staff_burden` | Human work items beyond what policy required | state | no |
| `grounded_closure_v3` | Is the closing clear **and** did the action it describes land? | transcript + state | partly |

**Deliberately not measured:** sentiment, generic helpfulness, conversational quality,
latency, containment rate. Containment in particular is dangerous to optimise directly —
`refill-control-escalate-urgent-symptom` is a call that *should* leave the agent, and
containment would score it as a loss.

Three design rules that shaped the numbers:

- **N/A is not a pass.** A metric that does not apply is excluded from its denominator.
  `false_completion` is only defined over calls that claimed completion; folding the
  others in as passes would dilute the rate with calls that never made a claim.
- **Precision and recall stay separate.** Averaging them into one "escalation score"
  hides which one regressed, and they have opposite costs.
- **Burden is a raw count, not a rate.** The right target is not zero handoffs — it is
  handoffs only when required, which the escalation metrics answer.

### Human judgment → automated evaluator

I took one judgment metric — *did the caller leave correctly informed about what happens
next?* — through the full loop. This produced the finding I care most about.

**Setup.** 21 traces, hand-labelled from the **transcript only** (`labels/RUBRIC.md`,
written before labelling). That is the condition a human reviewer is actually in, and the
same evidence an LLM judge would have. Then a **second pass with world state revealed**,
which is the reference the evaluators are scored against — a human judgment, not a
formula, so the comparison is not circular.

| | vs transcript-only human | vs state-aware human | κ |
|---|---|---|---|
| **v1** lexical | 19/21 (90%) | 15/21 (71%) | **−0.05** / −0.09 |
| **v2** grounded on scenario contract | — | 18/21 (86%) | 0.674 |
| **v3** grounded on the asserted action | — | **20/21 (95%)** | **0.859** |

**The finding: v1 agreed with my own transcript-only labels 19 times out of 21, and that
agreement was worthless.** Cohen's κ is *negative* — 20 of 21 traces are one class, so
90% accuracy carries essentially no information. Worse, the evaluator and I were wrong in
the *same direction* on six traces, because we were reading the same insufficient
evidence. **Agreement between two blind raters measures shared blindness.** If I had
stopped at "the evaluator matches my labels", I would have shipped it.

**Two revisions, each forced by a specific disagreement:**

- **v1 → v2.** Two changes. (a) A bug: v1 scored the *urgent-transfer* call as bad closure
  — the clearest closing in the set — because my cue list had no pattern for "I'm
  transferring you". A lexical rubric has an open-ended tail of these; that alone is why
  I would not ship it as a primary signal. (b) The real one: AND the clarity check with a
  grounding check against world state.
- **v2 → v3.** v2 got three traces right **for the wrong reason**. On
  `refill-hard-no-refills-remaining` under v2, the agent said "your Metformin refill is on
  its way" and it genuinely was — the scenario fails because submitting it violated
  policy, but the *caller was told the truth*. v2 marked the closing bad using evidence
  that had nothing to do with closure. An evaluator that reaches the right verdict via the
  wrong evidence inflates apparent accuracy and drifts the moment the two come apart. v3
  grounds against **what the closing itself asserts** and leaves permission to
  `escalation_recall`. One metric, one question.

**v3's remaining failure, stated precisely:** on `refill-hard-midcall-correction` the
agent accurately describes an action it should not have taken (wrong pharmacy). v3 passes
it, because the asserted action did land. Grounding against the agent's own assertion
cannot catch *confidently doing the wrong thing and describing it correctly*. That needs
the caller's intent, which is what `critical_entity_accuracy` covers — and does catch it.
I would rather have two metrics each answering one question cleanly than one metric with a
blind spot I have to remember.

Artifacts: `artifacts/calibration/closure_calibration.json`, `backend/kyroneval/labels/`.

### v4 — putting an LLM judge where it actually belongs

v1–v3 all decide **clarity** with a regex cue list, and that is the acknowledged weak half:
v1 missed the urgent-transfer closing — the clearest in the set — purely because my pattern
list had no phrase for "I'm transferring you". There is an open-ended tail of those. Clarity
is a language judgment with no ground truth in any database, which is the one situation
where a judge is the right tool.

So v4 changes **only that half**, and keeps the architecture:

```
v3 = regex_clarity  AND  asserted_action_landed
v4 = judge_clarity  AND  asserted_action_landed
                         ^^^^^^^^^^^^^^^^^^^^^ still deterministic, and deliberately
                                               never shown to the model
```

The judge sees the transcript and the closing turn. It does not see world state, the
scenario contract, or the tool calls, and its prompt tells it explicitly that judging
*truth* is not its job. A judge that can see state starts reasoning about task success —
which it does worse than three lines of Python, and at a thousand times the cost.

**The measurement this enables.** `caller_closure_v1` (regex clarity) and `judge_clarity`
answer the same question from the same evidence, and my 21 transcript-only human labels
were made from that same evidence. That is a clean head-to-head — reported in
`/calibration` as `regex_clarity_vs_human_transcript_only` vs
`judge_clarity_vs_human_transcript_only`. Replacing a component and *not measuring whether
it helped* is how evaluation stacks accumulate expensive machinery nobody has validated.

**Three engineering decisions worth defending:**

- **Cassette, not live calls.** Every judge call is recorded to
  `artifacts/judge_cache/closure.json`, keyed by `sha256(model | prompt_version | prompt)`.
  The model is in the key, so swapping models re-records rather than silently attributing
  one model's verdicts to another.
  A reviewer with no credentials replays the exact verdicts I got. This is not just a
  submission convenience — a metric you cannot recompute identically cannot be
  regression-tested, and judge outputs are the most expensive thing in any eval pipeline
  to recompute.
- **The prompt is versioned and frozen** (`evaluators/judge_prompt.md`). Editing it changes
  `PROMPT_VERSION`, which changes the cassette key, which forces a re-record. A test
  asserts this. An evaluator whose prompt can change without changing its version is an
  evaluator whose historical scores are attributed to a prompt that no longer exists.
- **A deterministic check on the judge itself.** The judge must return a `quoted_evidence`
  span, and code verifies that span appears verbatim in the transcript it was given. If it
  does not, the verdict is flagged as ungrounded. This is the project's own thesis pointed
  at the evaluator: do not take a fluent claim as evidence that the work was done.

**Unavailable is not a pass.** With no key and no cassette entry, `judge_clarity` and
`grounded_closure_v4` report N/A and are excluded from their denominators. v3 is completely
unaffected, and a test asserts that too — the deterministic spine must never depend on a
network call.

---

## Part 5 — The experiment

### What I tested and why

**v1 → v2 is a plausible, well-intentioned product change**, of the kind that actually
ships: *"we're routing too much to staff and callers are hanging up unsure — complete more
yourself, and always close with a clear confirmation."*

Expressed as a config diff rather than a prompt diff, so the change is inspectable and a
regression is attributable to one behavioural rule (`agents/configs.py`):

| | v1 | v2 |
|---|---|---|
| retry on timeout | no | **yes** |
| trust an `ok` envelope without reading the body | no | **yes** |
| create a staff task on failure | yes | **no** |
| enforce **hard guardrails** (Schedule II, urgent symptoms) | yes | yes |
| enforce **prose policy** (zero refills, post-op window) | yes | **no** |

That last row is the crux and it is not a strawman: **hard-coded guardrails survive a
prompt rewrite; policy expressed as prose guidance does not.** That asymmetry is, in my
experience, exactly how safety rules get quietly dropped.

### What I predicted

Aggregate task success would **rise** while the safety slices degraded — the classic shape
where a headline improvement hides a dangerous regression.

### What actually happened

| | v1 | v2 | v3 |
|---|---|---|---|
| Task success | 13/17 | **10/17** | 13/17 |
| False completion (of calls claiming success) | 3/11 · 27% | **7/15 · 47%** | **2/11 · 18%** |
| Escalation recall (must-escalate slice) | 4/4 | **2/4** | 4/4 |
| Escalation precision | 9/10 | 10/10 | 10/10 |
| Staff tasks created | 6 | **2** | 6 |
| Grounded closure v3 | 14/17 | 14/17 | **17/17** |

**My prediction was half wrong, and the half that was wrong is the interesting part.**
Aggregate task success *fell*, 13 → 10. v2 did exactly what it was designed to do on the
metrics it targeted — staff tasks cut by two-thirds, escalation precision perfect — and
broke two of four must-escalate scenarios while pushing false completion from 27% to 47%.

The reason the aggregate fell is that **my suite is adversarially enriched**: 12 of 17
scenarios are hard or must-escalate, so v2's regressions outnumber its wins. That is a
property of my sample, not of the system. Which raises the obvious question, and it is
worth an exhibit of its own.

### The aggregate reports the sample, not the system

`kyroneval/reweight.py` rescores the *same runs* under a production-shaped tier mix
(illustrative weights — I have no production data and am not claiming these are Kyron's):

| Metric | v1 | v2 | Δ |
|---|---|---|---|
| Task success | 0.96 | 0.94 | **−2pp** |
| No false completion | 0.96 | 0.93 | **−3pp** |
| Critical entities | 0.99 | 0.98 | −1pp |
| **Escalation recall (must-escalate slice)** | 1.00 | 0.13 | **−87pp** |

**Under a realistic call mix, every headline metric moves 1–3 points — indistinguishable
from noise, and it ships.** The one metric that does not move with the sample is the one
conditioned on the slice, and it falls off a cliff. This is the whole argument in one
table: a slice metric is invariant to the mix; an aggregate is a statement about your
sample. A release gate that reads aggregates would have approved v2.

### The failure I investigated closely

`refill-hard-timeout-after-write` — the write lands, the agent sees a timeout.

- **v1** does not retry, tells the caller it failed, opens a staff task. The refill *did*
  land. `false_failure_report` fires: the patient will call back about work already done,
  and a human now works a ticket for nothing. Task state is correct; the human-facing
  outcome is wrong in both directions.
- **v2** retries and creates a **duplicate** refill request. Two requests reach the
  pharmacy.
- **v3 — and this is the part I did not expect — does not fix it.** v3 adds read-after-write
  verification, which fixes both silent-no-op scenarios cleanly. But verification asks
  *"does a matching record exist?"*, and after a duplicate write the answer is yes. It
  confirms completion and the duplicate survives. It is the one false completion v3 has
  left besides the correction case.

**What that taught me, concretely:** read-after-write is not idempotency. Existence checks
fix lost writes and are blind to duplicated ones. The correct fix is a client-generated
idempotency key on the write, with verification reading back *that key* rather than
matching on fields. I did not implement it — it is the first thing I would do next, and I
would rather show the evidence that led me there than a version that quietly papers over it.

### What I would and would not conclude

**Would:** the v1 → v2 change is not safe to ship as written; the regression is
attributable to dropping prose policy enforcement plus trusting an `ok` envelope; a
release gate reading aggregates would not have caught it; read-after-write is necessary
and not sufficient.

**Would not:** anything about magnitude or frequency in production. n=17, deterministic
agents, no language model anywhere, no audio. These are *existence proofs of failure
mechanisms*, not rates. Every percentage here has a denominator under 20 and I have kept
the denominators visible in the UI for that reason.

---

## Part 6 — What I would put in front of the product team

**Three findings, ranked by what I would fix first.**

### 1. Silent tool failure is a system defect, not an agent defect — fix it in the platform

**Mechanism.** A write returns success and lands nowhere. The agent has no signal, tells
the patient it is done, and the call ends cleanly. In this suite it produced a false
completion in **every agent version** (`/patterns` flags mechanisms that appear across all
three — those are the ones a prompt change cannot fix).

**Why it matters.** This is the worst failure class in patient access because it is
invisible on both ends: the patient stops worrying, and no staff queue lights up. It
surfaces days later as a missed medication or a no-show, by which point it is
unattributable to the call.

**Intervention.** Read-after-write verification before any completion claim, plus a
client-generated idempotency key so verification distinguishes "landed once" from "landed
twice" (see the investigation above — verification alone does not do this). Agent language
should degrade honestly when verification fails, which is what v3 does.

**How I would verify it worked.** `false_completion` on the tool-fault slice, and a
production canary comparing agent completion claims against downstream system state on a
sampled basis — that reconciliation is the production version of this metric and is worth
building whether or not you build the rest.

### 2. Policy expressed as prose does not survive a prompt change

**Mechanism.** v2 dropped two policy rules that existed only as prompt guidance — zero
refills remaining, and the post-op reschedule window — while the hard-coded Schedule II
guardrail survived untouched. Escalation recall went 4/4 → 2/4. Nobody edited a safety
rule; they edited a paragraph about being more helpful.

**Why it matters.** A patient whose post-op follow-up gets moved outside its window is a
clinical risk, and the failure is silent — the call is polite, the caller is happy, the
metric that would catch it is not on the dashboard.

**Intervention.** Policy rules that carry clinical or regulatory weight belong in code as
preconditions on the tool call, not in the prompt. The prompt should explain them; the
tool layer should enforce them. Concretely: `submit_refill` should reject zero-refill and
Schedule II prescriptions server-side regardless of what the agent decides.

**How I would verify it worked.** A must-escalate regression gate that blocks release on
*any* drop, not a threshold — with n this small on the slice that matters, a percentage
target is theatre.

### 3. Corrections that arrive after a slot is filled are ignored

**Mechanism.** The caller says "actually, not Northgate — Bayside", after the agent has
already announced its choice. All three versions proceed to the original pharmacy and
confidently confirm it. Caught by `critical_entity_accuracy` on the tool arguments;
`grounded_closure_v3` misses it, correctly, since the described action did happen.

**Why it matters.** Medication delivered to the wrong pharmacy, and the patient was told
the right thing was happening. Low frequency in my sample (n=1) — I flag it as a mechanism
worth measuring, not a prioritised bug.

**Intervention.** Treat a filled slot as revisable until the mutating call, and re-confirm
any entity the caller mentions after it was set.

### Guardrails I would not trade away

Containment rate and staff-task volume are the two metrics most likely to be optimised
here, and both are dangerous alone. `refill-control-escalate-urgent-symptom` is a call
that *must* leave the agent; containment scores it as a loss. v2 cut staff tasks by
two-thirds and that looked like a win right up until you condition on whether the handoff
was required. Any automation-rate target should be paired with must-escalate recall as a
blocking gate.

### What I would need from production before acting on any of this

Frequency. Every number here comes from a 17-scenario synthetic suite chosen to make
failures visible. Before ranking these by business impact I would want: the real
distribution of call intents; the actual rate of ambiguous or failed tool responses from
each downstream integration (which I would get from trace ingestion, not from evaluation);
how often callers correct themselves mid-call; and a human-reviewed sample of calls where
the agent claimed completion, reconciled against downstream state. That last one is
directly this platform's `false_completion` metric pointed at production, and it is the
first thing I would build.

---

## Part 7 — Production design

Concrete priorities, not an architecture diagram.

**Ingestion.** Production traces arrive from the live agent's event stream, not a
simulator. The `Trace` schema is already the boundary: turns, tool calls with arguments
and outcomes, and — critically — **the downstream state the call asserted it changed**.
That last field is the one most likely to be missing in a real system and the one
everything here depends on; I would make emitting it a requirement on the agent, not a
best-effort join afterwards.

**Versioning.** Agent config, prompt, policy bundle, scenario set, and each evaluator all
need independent versions, and every result must record all five. This repo does a
degenerate version: a config fingerprint on every run. The reason to be strict is that
"the metric moved" has at least five possible causes and four of them are not the agent.
An evaluator revision must never silently rewrite historical scores — the calibration
story above is only legible because v1, v2 and v3 all still exist and all still run.

**Sampling for human review.** Not uniform. Stratify by outcome and route by
disagreement: everything where the agent claimed completion and reconciliation disagrees,
everything on a must-escalate policy path, and a small uniform sample as a control so the
review set does not become self-confirming. Human labels are the scarcest input and should
be spent where evaluators are least certain.

**Regression gates.** Sliced, not aggregate — that is the argument of Part 5. Must-escalate
recall and false completion on the tool-fault slice block a release on any drop. Aggregate
task success is a dashboard number, not a gate.

**Evaluator drift.** Evaluators are code and they rot. Keep a frozen golden set with human
labels, re-run every evaluator version against it on every change, and alert on the
*evaluator's* agreement with labels, not just on the agent's scores. The κ = −0.05 result
is the argument for tracking agreement properly rather than accuracy.

**Privacy.** Transcripts are PHI. De-identify at ingestion; keep the structured trace
(tool calls, state, outcomes) in the queryable store and the raw transcript in a separate,
access-controlled, short-retention store that the UI links to rather than embeds. Most
evaluation here runs on structure, not on words, which makes that split cheap — a useful
side effect of the state-verified design.

**Cost and latency.** Deterministic evaluators are effectively free and belong online on
100% of calls. Judge-based evaluators belong offline on a sample. Nothing here should sit
in the call path.

**Customer-specific policy.** Policy is already data on the scenario, not code in the
evaluator. In production it becomes a versioned per-customer policy bundle that both the
agent and the evaluators read, so an evaluator cannot drift from the contract it is
grading against.

**Turning findings into owned work.** The `/patterns` view groups failures by mechanism
rather than by scenario, because "which scenarios failed" is a test report and "which
mechanism keeps failing" is a ticket with an owner. A mechanism appearing across every
agent version is a system defect and should route to platform, not to whoever owns the
prompt.

---

## How I used AI

I used Claude heavily and I would work the same way at Kyron. Roughly: it wrote most of the
mechanical code — dataclasses, the React components, the CSS, table rendering, argument
parsing — from specifications I gave it, and I directed the design, the scenarios, the
metric definitions, and every interpretation of a result.

**Where it was unreliable or generic:**

- **First-pass metrics were the usual plausible list** — "helpfulness", "task completion",
  "sentiment" — aggregate, transcript-shaped, and exactly what the prompt warns about.
  The metric set here came from asking what a transcript *cannot* show.
- **It wanted to reach for an LLM judge** for the closure metric. That is the single worst
  place to put a judge in this problem and the calibration section is the evidence.
- **It smoothed over the two surprises rather than surfacing them.** When
  `escalation_precision` penalised v3 for correctly escalating after a tool fault, the
  suggested fix was to adjust the scenario so the metric passed. The right fix was that
  the metric was conflating two different things. Same with the κ result — the instinct
  was to present 90% accuracy as a success.
- **It could not tell me what my own experiment meant.** The prediction that aggregate
  task success would rise was mine, it was wrong, and understanding *why* it was wrong —
  sample enrichment — is what produced the mix-sensitivity exhibit, which is the best
  thing in this submission.

**One consequential decision I made rather than delegated:** making **simulated world
state the ground truth**, and accepting that this forced a deterministic agent, a
deterministic caller, and no LLM judge. That decision cost me all the realism an LLM-backed
stack would have bought, and it is the reason every interesting result here exists. False
completion, the mix-sensitivity finding, and the three closure revisions are all downstream
of it. The alternative — an LLM agent, an LLM caller, an LLM judge — would have produced a
far more impressive-looking demo that could not have told you whether the refill was sent.

---

## Known failures and limitations

Things I found and did not fix, or cannot claim.

1. **`grounded_closure_v3` cannot catch an accurate description of a wrong action.**
   Stated precisely in Part 3. Covered by a different metric; not covered by this one.
2. **Read-after-write does not catch duplicate writes.** Found by running v3. Needs
   idempotency keys. Not implemented.
3. **All three agents ignore late corrections.** Finding 3 above. n=1 in this sample.
4. **`escalation_precision` needed a mid-flight fix** because it marked correct escalation
   as unnecessary burden. Fixed by making it N/A when a tool fault prevented completion.
   The class of bug — a metric conflating two questions with opposite costs — is one I now
   expect to find more of.
5. **Denominators are tiny.** `escalation_recall` has n=4. A single scenario changing
   verdict moves it 25 points. The UI shows counts next to every percentage for this reason.
6. **Verification tools are not fault-injected.** `verify_refill` always reads true state.
   A real verification endpoint can fail too, and v3's numbers are optimistic by exactly
   that amount.
7. **The caller never gets confused, angry, or gives up.** Simulator bias in the
   cooperative direction, which flatters every agent equally — so comparisons survive it,
   but absolute numbers do not.
8. **Two patients carry most of the scenarios**, and both workflows are "modify one
   record". No multi-intent calls.

---

## Where the time went

Roughly: 15 min scope and assumptions before any code · 45 min world, tools, scenarios ·
30 min harness and agents · 45 min metrics, labelling, and three evaluator revisions ·
90 min backend, API, and UI · 30 min tests · the rest on the experiment, the
mix-sensitivity exhibit, and this document. `TIMELOG.md` and the git history are the
honest record.

**Intentionally not completed:** an LLM-backed agent and judge (reasoned above, not
skipped); audio; auth and deployment; idempotency keys; a fifth and sixth workflow. I chose
depth on one argument over coverage of eight sections.

**With another eight hours, in order:** idempotency keys and re-run the fault slice, since
that is a live open question rather than a polish item · an LLM-backed agent behind the
same `Agent` seam, to find out how much of this survives contact with a non-deterministic
subject · a judge-based evaluator for the one thing state cannot answer (was the
explanation actually understandable) calibrated the same way · scenario-level ambiguity
review, because `refill-hard-pharmacy-ambiguity` currently rewards a correct guess and I
do not think it should.
