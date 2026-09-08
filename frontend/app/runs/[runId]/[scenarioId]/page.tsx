"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { get, post } from "@/lib/api";
import { ApiDown, Loading, Tier, Verdict } from "../../../ui";
import { METRIC_META, PRIMARY } from "../../../metrics";

const FAULT_COPY: Record<string, string> = {
  silent_noop: "returned success and wrote nothing",
  timeout: "timed out, nothing written",
  timeout_after_write: "write landed, agent saw a timeout",
  error: "upstream rejected",
};

export default function ScenarioDetail(
  { params }: { params: Promise<{ runId: string; scenarioId: string }> }) {
  const { runId, scenarioId } = use(params);
  const [d, setD] = useState<any>();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [metric, setMetric] = useState("task_success");
  const [verdict, setVerdict] = useState("agree");
  const [note, setNote] = useState("");

  const load = () => get<any>(`/api/runs/${runId}/scenarios/${scenarioId}`)
    .then(setD).catch(e => setErr(String(e)));
  useEffect(() => { load(); }, [runId, scenarioId]);
  if (err) return <ApiDown e={err} />;
  if (!d) return <Loading />;

  const t = d.trace, scn = d.scenario;

  const submit = async () => {
    setBusy(true);
    try {
      await post("/api/reviews", { run_id: runId, scenario_id: scenarioId,
        metric, verdict, reviewer: "reviewer", note });
      setNote(""); await load();
    } finally { setBusy(false); }
  };

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="note" style={{ marginBottom: 6 }}>
            <Link href={`/runs/${runId}`} style={{ color: "var(--accent)" }}>← {runId}</Link>
          </div>
          <h1>{scn.title}</h1>
          <p className="lede">
            <code className="mono">{scenarioId}</code> <Tier t={scn.tier} />{" "}
            <span className="tier">{scn.workflow}</span>
            <br />{scn.why_interesting}
          </p>
        </div>
      </div>

      {scn.must_escalate && (
        <div className="callout" style={{ marginBottom: 20 }}>
          <b>Policy: this call must escalate.</b> {scn.escalation_reason} Required queue:{" "}
          <code className="mono">{scn.escalation_queue}</code>
          {scn.urgent && <> · live transfer required</>}
          {scn.forbidden_tools?.length > 0 && <> · forbidden:{" "}
            <code className="mono">{scn.forbidden_tools.join(", ")}</code></>}
        </div>
      )}

      <div className="grid2">
        <div className="stack">
          <div className="panel">
            <div className="panel-h">
              <h2>Conversation</h2>
              <span className="sub">outcome: <code className="mono">{t.outcome}</code></span>
            </div>
            <div className="turns">
              {t.turns.map((x: any) => (
                <div key={x.idx} className={`turn ${x.speaker}`}>
                  <div className="who">{x.speaker}</div>
                  <div className="txt">
                    {x.text}
                    {x.act && <code className="act">act: {x.act}</code>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-h">
              <h2>Agent configuration</h2>
              <span className="sub">the version under test</span>
            </div>
            <div className="delta-list">
              {Object.entries(d.agent_config)
                .filter(([k]) => !["label", "description"].includes(k))
                .map(([k, v]) => (
                  <div key={k}>{k}: <b>{String(v)}</b></div>
                ))}
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="panel">
            <div className="panel-h">
              <h2>Tool calls</h2>
              <span className="sub">what the downstream systems actually received</span>
            </div>
            {t.tool_calls.map((c: any) => (
              <div className="tool" key={c.seq}>
                <div className="tool-h">
                  <span className="tool-n">{c.name}</span>
                  <span className={`b ${c.ok ? "pass" : "fail"}`}>{c.ok ? "ok" : c.error}</span>
                  {c.fault_injected !== "ok" && (
                    <span className="b warn" title={FAULT_COPY[c.fault_injected]}>
                      fault: {c.fault_injected}
                    </span>
                  )}
                  {c.attempt > 1 && <span className="b info">attempt {c.attempt}</span>}
                </div>
                <div className="args">{JSON.stringify(c.args)}</div>
                {c.fault_injected !== "ok" && (
                  <div className="note" style={{ marginTop: 5 }}>
                    {FAULT_COPY[c.fault_injected]}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="panel">
            <div className="panel-h">
              <h2>World state delta</h2>
              <span className="sub">the ground truth</span>
            </div>
            <div className="delta-list">
              {t.state_delta.map((s: string, i: number) => (
                <div key={i} className={s.includes("no state change") ? "none" : ""}>{s}</div>
              ))}
            </div>
            {t.claimed_completion && t.state_delta[0] === "(no state change)" && (
              <div className="callout bad" style={{ margin: "0 14px 14px" }}>
                The agent told the caller this was done. Nothing changed. This is the
                divergence no transcript-based evaluator can see.
              </div>
            )}
          </div>

          {t.notes?.length > 0 && (
            <div className="panel">
              <div className="panel-h"><h2>Agent notes</h2></div>
              <div className="delta-list">{t.notes.map((n: string, i: number) =>
                <div key={i}>{n}</div>)}</div>
            </div>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panel-h">
          <h2>Why each metric produced its result</h2>
          <span className="sub">expand for the evidence the evaluator used</span>
        </div>
        {PRIMARY.filter(m => d.metrics[m]).map(m => {
          const r = d.metrics[m];
          return (
            <details className="metric" key={m}>
              <summary>
                <span className="m-name">{METRIC_META[m]?.label ?? m}</span>
                {typeof r.value === "number" && r.value !== 0 && r.value !== 1 &&
                  <span className="note">{r.value}</span>}
                <Verdict p={r.passed} />
              </summary>
              <div className="ev">
                <div className="why">{r.explanation}</div>
                <ul>{r.evidence.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
              </div>
            </details>
          );
        })}
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panel-h">
          <h2>Human review</h2>
          <span className="sub">
            override an evaluator, or confirm it. Overrides are stored, never used to
            silently rewrite the metric.
          </span>
        </div>
        <div className="form">
          <div className="line">
            <select value={metric} onChange={e => setMetric(e.target.value)}>
              {PRIMARY.filter(m => d.metrics[m]).map(m =>
                <option key={m} value={m}>{METRIC_META[m]?.label ?? m}</option>)}
            </select>
            {["agree", "override_pass", "override_fail"].map(v => (
              <button key={v} className={`ghost ${verdict === v ? "on" : ""}`}
                      onClick={() => setVerdict(v)}>{v.replace("_", " ")}</button>
            ))}
          </div>
          <textarea rows={2} placeholder="Why? This is the label that trains the next evaluator revision."
                    value={note} onChange={e => setNote(e.target.value)} />
          <div className="line">
            <button onClick={submit} disabled={busy}>{busy ? "Saving…" : "Save review"}</button>
            <span className="note">{d.reviews.length} review(s) on this scenario</span>
          </div>
        </div>
        {d.reviews.length > 0 && (
          <table>
            <thead><tr><th>Metric</th><th>Verdict</th><th>Note</th><th>When</th></tr></thead>
            <tbody>
              {d.reviews.map((r: any) => (
                <tr key={r.id}>
                  <td className="mono">{r.metric}</td>
                  <td><span className={`b ${r.verdict === "agree" ? "info" :
                    r.verdict === "override_pass" ? "pass" : "fail"}`}>{r.verdict}</span></td>
                  <td>{r.note}</td>
                  <td className="note">{r.created_at.replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
