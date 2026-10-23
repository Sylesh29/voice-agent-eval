"""
Meter the voice-agent-eval closure judge through Revenium.

WHAT THIS IS

The closure judge in backend/voiceval/evaluators/judge.py is the one place this platform
spends money on an LLM. It talks to providers over stdlib urllib on purpose, so nothing
intercepts it. This sidecar re-runs the same judge (same system prompt, same rendered
prompt, same tolerant parser, same deterministic quote check) through the official
provider SDKs with Revenium's middleware imported, so every call is metered with business
context attached.

Two lines of real integration work, everything else is attribution:

    import revenium_middleware.anthropic      # auto-instruments the Anthropic SDK
    client.messages.create(..., usage_metadata={...})

TENANTS

To show per customer attribution, each agent version stands in for a different customer's
voice agent being evaluated. The clinic names are fictional and say so on camera.

QUALITY, NOT JUST COST

Every verdict is compared to my hand labels in voiceval/labels/closure_labels.json, and
the deterministic quote check runs on every verdict and is reported to Revenium as a
metered tool call. That gives cost per model in Revenium and agreement per model locally,
which is the comparison an eval team actually needs: is the expensive judge worth it.

USAGE (from the repo root)

    python integrations/revenium/meter_judge.py --smoke
    python integrations/revenium/meter_judge.py
    python integrations/revenium/meter_judge.py --runaway 40
    python integrations/revenium/meter_judge.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
except ImportError:
    pass

from voiceval.evaluators import judge as J                     # noqa: E402
from voiceval.evaluators.closure import _final_agent_turn       # noqa: E402
from voiceval.runner import run_suite                           # noqa: E402

# Fictional customers. One per agent version, so the dashboard has something to group by.
TENANTS = {
    "v1_conservative": "Maple Family Practice",
    "v2_automation_push": "Harbor Pediatrics",
    "v3_verified": "Summit Orthopedics",
}
PRODUCT = "voice-agent-eval"
AGENT_NAME = "closure-judge-v1"
DEFAULT_MODELS = "openai:gpt-4o-mini,openai:gpt-4o"


# --------------------------------------------------------------------------- #
# provider clients, instrumented by import
# --------------------------------------------------------------------------- #

_clients: dict[str, object] = {}


def client_for(provider: str):
    if provider in _clients:
        return _clients[provider]
    if provider == "anthropic":
        import anthropic
        import revenium_middleware.anthropic  # noqa: F401  (instruments on import)
        _clients[provider] = anthropic.Anthropic()
    elif provider == "openai":
        import openai
        import revenium_middleware.openai  # noqa: F401  (instruments on import)
        _clients[provider] = openai.OpenAI()
    else:
        raise SystemExit(f"unsupported provider {provider!r}; use anthropic or openai")
    return _clients[provider]


def call_judge(provider: str, model: str, system: str, user: str, meta: dict) -> tuple[str, int, int]:
    """One judge call. Returns (raw text, input tokens, output tokens)."""
    c = client_for(provider)
    if provider == "anthropic":
        # No temperature: anthropic SDK 2.x removed sampling params from messages.create.
        r = c.messages.create(
            model=model, max_tokens=512, system=system,
            messages=[{"role": "user", "content": user}],
            usage_metadata=meta,
        )
        return r.content[0].text, r.usage.input_tokens, r.usage.output_tokens
    r = c.chat.completions.create(
        model=model, temperature=0, max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        usage_metadata=meta,
    )
    return r.choices[0].message.content, r.usage.prompt_tokens, r.usage.completion_tokens


# --------------------------------------------------------------------------- #
# work items
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    agent_id: str
    scenario_id: str
    transcript: str
    final_turn: str
    human_label: str | None


@dataclass
class Result:
    batch: str
    provider: str
    model: str
    tenant: str
    agent_id: str
    scenario_id: str
    trace_id: str
    retry_number: int
    verdict: str | None
    human_label: str | None
    agrees: bool | None
    quote_verified: bool | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    error: str = ""


def load_items(agents: list[str], limit: int | None) -> list[Item]:
    labels_path = REPO / "backend" / "voiceval" / "labels" / "closure_labels.json"
    labels = {(l["run"], l["scenario"]): l["label"]
              for l in json.loads(labels_path.read_text())["labels"]}
    items: list[Item] = []
    for agent_id in agents:
        run = run_suite(agent_id, run_id=f"{agent_id}-revenium")
        for t in run.traces[: limit or None]:
            items.append(Item(agent_id, t.scenario_id, t.transcript,
                              _final_agent_turn(t), labels.get((agent_id, t.scenario_id))))
    return items


def metadata(batch: str, item: Item, model: str, retry: int = 0) -> dict:
    meta = {
        "organizationName": TENANTS[item.agent_id],
        "productName": PRODUCT,
        "agent": AGENT_NAME,
        "task_type": "llm-judge",
        "trace_id": f"{batch}-{item.agent_id}-{item.scenario_id}",
        "trace_type": "voice-agent-eval",
        "trace_name": f"Closure judge: {item.scenario_id}",
        "transaction_name": "Grade closing turn",
        "environment": os.getenv("REVENIUM_ENVIRONMENT", "demo"),
        "subscriber": {"id": os.getenv("REVENIUM_SUBSCRIBER_ID", "eval-runner")},
        "retry_number": retry,
    }
    email = os.getenv("REVENIUM_SUBSCRIBER_EMAIL")
    if email:
        meta["subscriber"]["email"] = email
    return meta


def judge_one(batch: str, item: Item, provider: str, model: str, dry: bool, retry: int = 0) -> Result:
    meta = metadata(batch, item, model, retry)
    system, user = J._system_prompt(), J._render(item.transcript, item.final_turn)
    base = dict(batch=batch, provider=provider, model=model, tenant=meta["organizationName"],
                agent_id=item.agent_id, scenario_id=item.scenario_id,
                trace_id=meta["trace_id"], retry_number=retry, human_label=item.human_label)
    if dry:
        print(json.dumps({"model": f"{provider}:{model}", "usage_metadata": meta}))
        return Result(**base, verdict=None, agrees=None, quote_verified=None,
                      input_tokens=len(system + user) // 4, output_tokens=0, latency_ms=0)

    t0 = time.perf_counter()
    try:
        raw, tin, tout = call_judge(provider, model, system, user, meta)
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "BudgetExceededError":
            raise
        return Result(**base, verdict=None, agrees=None, quote_verified=None, input_tokens=0,
                      output_tokens=0, latency_ms=int((time.perf_counter() - t0) * 1000),
                      error=f"{type(e).__name__}: {e}"[:300])
    latency = int((time.perf_counter() - t0) * 1000)

    try:
        v = J._verdict_from(J._parse(raw), item.transcript, "api", model)
    except ValueError as e:
        return Result(**base, verdict=None, agrees=None, quote_verified=None, input_tokens=tin,
                      output_tokens=tout, latency_ms=latency, error=str(e)[:300])

    # The deterministic check on the judge, metered as a tool call so its pass rate sits
    # next to the judge's spend in Revenium.
    from revenium_middleware import report_tool_call
    report_tool_call(
        tool_id="quote-verifier", operation="verify_citation", duration_ms=1,
        success=bool(v.quote_verified),
        error_message=None if v.quote_verified else "judge cited text not in transcript",
        agent=AGENT_NAME, organization_name=meta["organizationName"], product_name=PRODUCT,
        trace_id=meta["trace_id"], usage_metadata={"judge_model": model},
    )
    agrees = None if item.human_label is None or v.verdict is None else v.verdict == item.human_label
    return Result(**base, verdict=v.verdict, agrees=agrees, quote_verified=v.quote_verified,
                  input_tokens=tin, output_tokens=tout, latency_ms=latency)


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def summarize(results: list[Result], models: list[tuple[str, str]]) -> str:
    """Per model: volume, tokens, grounding, and agreement.

    Two agreement columns, and the second matters more. The hand labels are 21 calls and
    20 of them are "clear", which is the kappa trap the README documents: raw agreement
    against them is close to meaningless. Agreement with the most expensive model in the
    run is the question a buyer actually has: does the cheap judge say the same thing?
    """
    rows = []
    by_model: dict[str, list[Result]] = {}
    for r in results:
        by_model.setdefault(f"{r.provider}:{r.model}", []).append(r)
    ref = f"{models[-1][0]}:{models[-1][1]}" if models else None
    ref_verdicts = {(r.agent_id, r.scenario_id): r.verdict
                    for r in by_model.get(ref, []) if r.verdict and r.retry_number == 0}

    head = (f"{'model':<34}{'calls':>6}{'errors':>7}{'in tok':>9}{'out tok':>9}"
            f"{'quote ok':>10}{'vs labels':>11}{'vs ref':>9}{'p50 ms':>8}")
    rows += [head, "-" * len(head)]
    for m, rs in by_model.items():
        ok = [r for r in rs if not r.error]
        graded = [r for r in ok if r.agrees is not None]
        quoted = [r for r in ok if r.quote_verified is not None]
        paired = [r for r in ok if r.verdict and (r.agent_id, r.scenario_id) in ref_verdicts]
        same = sum(r.verdict == ref_verdicts[(r.agent_id, r.scenario_id)] for r in paired)
        lat = sorted(r.latency_ms for r in ok) or [0]
        labels = f"{sum(r.agrees for r in graded)}/{len(graded)}" if graded else "n/a"
        vs_ref = "ref" if m == ref else (f"{same}/{len(paired)}" if paired else "n/a")
        qrate = f"{sum(r.quote_verified for r in quoted) / len(quoted):.0%}" if quoted else "n/a"
        rows.append(f"{m:<34}{len(rs):>6}{len(rs) - len(ok):>7}"
                    f"{sum(r.input_tokens for r in ok):>9}{sum(r.output_tokens for r in ok):>9}"
                    f"{qrate:>10}{labels:>11}{vs_ref:>9}{lat[len(lat) // 2]:>8}")
    errs = [r for r in results if r.error]
    if errs:
        rows.append(f"\nfirst error: {errs[0].error}")
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=os.getenv("JUDGE_MODELS", DEFAULT_MODELS),
                   help="comma list of provider:model")
    p.add_argument("--agents", default=",".join(TENANTS), help="agent versions to evaluate")
    p.add_argument("--limit", type=int, help="scenarios per agent version")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--smoke", action="store_true", help="one call with the first model, then stop")
    p.add_argument("--runaway", type=int, default=0,
                   help="simulate a retry storm: rejudge one scenario N times on one model")
    p.add_argument("--runaway-model", default=None, help="provider:model for the storm (default: last in --models)")
    p.add_argument("--runaway-agent", default="v2_automation_push", help="whose tenant absorbs the storm")
    p.add_argument("--dry-run", action="store_true", help="print the metadata, call nothing")
    args = p.parse_args()

    if not args.dry_run and not os.getenv("REVENIUM_METERING_API_KEY"):
        sys.exit("REVENIUM_METERING_API_KEY is not set. Copy .env.example to .env in this folder.")

    models = [tuple(m.split(":", 1)) for m in args.models.split(",") if m]
    agents = [a for a in args.agents.split(",") if a]
    batch = os.getenv("BATCH_ID") or f"b{datetime.now(timezone.utc):%m%d%H%M}{uuid.uuid4().hex[:4]}"

    items = load_items(agents, 1 if args.smoke else args.limit)
    if args.smoke:
        items, models = items[:1], models[:1]

    jobs: list[tuple[Item, str, str, int]] = []
    if args.runaway:
        prov, model = tuple((args.runaway_model or args.models.split(",")[-1]).split(":", 1))
        victim = next(i for i in items if i.agent_id == args.runaway_agent)
        jobs = [(victim, prov, model, n) for n in range(args.runaway)]
        print(f"retry storm: {args.runaway} calls on {prov}:{model}, "
              f"billed to {TENANTS[victim.agent_id]}")
    else:
        jobs = [(it, prov, model, 0) for prov, model in models for it in items]
        print(f"batch {batch}: {len(items)} transcripts x {len(models)} models = {len(jobs)} judge calls")

    results: list[Result] = []
    stopped = None
    with ThreadPoolExecutor(max_workers=1 if args.dry_run else args.workers) as pool:
        futs = [pool.submit(judge_one, batch, it, prov, model, args.dry_run, n)
                for it, prov, model, n in jobs]
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:  # BudgetExceededError from the circuit breaker
                stopped = e
                for other in futs:
                    other.cancel()
                break

    out = HERE / "runs" / f"{batch}.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(Result.__dataclass_fields__))
        w.writeheader()
        w.writerows(asdict(r) for r in results)

    print()
    print(summarize(results, [] if args.runaway else models))
    print(f"\nrows written to {out.relative_to(REPO)}")
    if stopped is not None:
        print(f"\nSTOPPED by Revenium cost control: {getattr(stopped, 'message', stopped)}")

    if not args.dry_run:
        import revenium_middleware as R
        pending = R.flush_metering(timeout_seconds=30)
        s = R.get_metering_status()
        print(f"revenium: {s.success_count} events delivered, {s.error_count} failed"
              + (f", {pending} still pending" if pending else "")
              + (f", last error: {s.last_error}" if s.last_error else ""))


if __name__ == "__main__":
    main()
