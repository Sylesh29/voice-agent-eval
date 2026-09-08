# Closure labelling rubric (written BEFORE labelling, unchanged afterwards)

**Question being labelled:** *Did this call leave the caller correctly informed about
what happens next?*

**Labelling condition — this matters:** I labelled from the **transcript only**. No
world state, no tool calls. That is deliberate. It is the condition a human reviewer
is actually in when they read call transcripts in a review queue, and it is the same
evidence an LLM judge would have. If I had labelled with state in front of me I would
have been calibrating my evaluator against evidence the evaluator does not have,
which would have made the agreement numbers meaningless in a way that is easy to miss.

**Decision boundary:**

- `clear` — the closing tells the caller both (a) the status of their request and
  (b) what happens next or what they should do. A caller acting on this closing
  would behave correctly *if what it says is true*.
- `unclear` — the caller could not act on this. Missing status, missing next step,
  or self-contradictory against something said earlier in the same call.

**Explicitly out of scope for this label:** whether the assertion is *true*. That is
not knowable from a transcript, which is the entire point of the exercise.
