# Pre-registered prediction — closure v4 (LLM judge)

**Written and committed BEFORE the judge was run against the suite.** The git timestamp
on this file precedes the commit that records the cassette. A prediction written after
seeing results is worth nothing, and I would rather be provably wrong than vaguely right.

Judge: `openai/gpt-oss-120b` via Groq, temperature 0, transcript only — no world state,
no scenario contract, no tool calls.

## What I expect

1. **The judge fixes v1's urgent-transfer miss.** The regex marked
   `refill-control-escalate-urgent-symptom` as *unclear* purely because my cue list had no
   phrase for "I'm transferring you". Any competent model reads that closing as the
   clearest in the set. This is the specific weakness the judge is here to fix.

2. **The judge may also catch `refill-hard-midcall-correction`.** The caller asks for
   Bayside and the agent confirms Northgate. That contradiction is *visible in the
   transcript*, so unlike the silent no-ops it is fair game for a transcript-only rater. My
   own transcript-only human label caught it; the regex did not. If the judge catches it,
   `judge_clarity` reaches 21/21 against the transcript-only labels and κ goes from −0.05
   to 1.0.

3. **The judge says "clear" on both silent-no-op closings — and that is correct.** Clarity
   is not truth. Those closings are well-formed; the calls are catastrophic. v4 must still
   fail them, and it will, via the deterministic grounding half. If the judge instead marks
   them unclear, it is reasoning about truth despite being told not to, and I would treat
   that as prompt leakage rather than as a win.

4. **v4 ≈ v3 against the state-aware labels (~20/21).** Grounding dominates the metric;
   swapping the clarity half should move it very little. If v4 moves a lot, something other
   than clarity changed and I need to find out what.

## The risk I am actually worried about

Models are trained to be helpful critics and tend to find fault when asked to grade. The
failure mode is **over-triggering "unclear"** on closings that are fine — which would show
up as new disagreements on the `ordinary` and `control_negative` scenarios, exactly where
a negative control is supposed to be boring. That is why those controls exist.

## Decision rule, fixed in advance

- If `judge_clarity` beats the regex on the transcript-only head-to-head → keep v4 as the
  reported closure metric, and state plainly what it cost: money, latency, and
  non-determinism that only the cassette contains.
- **If it ties or loses → ship the regex, and say so in the README.** "I replaced a
  20-line regex with an LLM, measured it, and the regex was as good" is a more useful
  result than an unmeasured upgrade, and it is the one I would want a teammate to report
  to me.

Either outcome gets written up. I am not running this to confirm that the judge helps.
