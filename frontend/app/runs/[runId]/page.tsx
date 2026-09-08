"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import { ApiDown, Loading, Rate, Tier, Verdict } from "../../ui";
import { METRIC_META, PRIMARY, SLICES, pick } from "../../metrics";

export default function RunDetail({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const [d, setD] = useState<any>();
  const [err, setErr] = useState("");
  useEffect(() => { get<any>(`/api/runs/${runId}`).then(setD).catch(e => setErr(String(e))); },
    [runId]);
  if (err) return <ApiDown e={err} />;
  if (!d) return <Loading />;

  const failing = d.scenarios.filter((s: any) =>
    Object.values(s.metrics).some((m: any) => m.passed === false));

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>{d.run_id}</h1>
          <p className="lede">
            Agent <code className="mono">{d.agent_id}</code> · config fingerprint{" "}
            <code className="mono">{d.config_fingerprint}</code> · {d.scenarios.length} scenarios ·{" "}
            {failing.length} with at least one failing metric.
          </p>
        </div>
        <Link href={`/compare?a=${d.run_id}`}><button className="ghost">Compare against another run →</button></Link>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2>Metrics by slice</h2>
          <span className="sub">
            Read across, not down. A metric that holds overall and collapses in one
            column is the case this platform exists to surface.
          </span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th style={{ minWidth: 260 }}>Metric</th>
                {SLICES.map(([k, label]) => <th key={k}>{label}</th>)}
              </tr>
            </thead>
            <tbody>
              {PRIMARY.filter(m => d.aggregate[m]).map(m => {
                const overall = pick(d.aggregate, m, "overall");
                const worst = SLICES.slice(1)
                  .map(([k]) => pick(d.aggregate, m, k))
                  .filter((c: any) => c && c.n_applicable > 0)
                  .reduce((acc: any, c: any) => (acc === null || c.rate < acc.rate ? c : acc), null);
                const diverges = overall && worst && overall.rate !== null &&
                  worst.rate !== null && overall.rate - worst.rate >= 0.34;
                return (
                  <tr key={m} className={diverges ? "regression" : ""}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{METRIC_META[m]?.label ?? m}</div>
                      <div className="note" style={{ maxWidth: 340 }}>{METRIC_META[m]?.question}</div>
                      {diverges && <span className="b warn" style={{ marginTop: 5 }}>
                        aggregate hides a slice
                      </span>}
                    </td>
                    {SLICES.map(([k]) => <td key={k}><Rate c={pick(d.aggregate, m, k)} /></td>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panel-h">
          <h2>Scenarios</h2>
          <span className="sub">Click through to the trace, the tool calls, and the state delta.</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Scenario</th><th>Tier</th><th>Outcome</th>
              <th>Task success</th><th>False completion</th><th>Escalation</th>
              <th>Closure v3</th><th>Review</th>
            </tr>
          </thead>
          <tbody>
            {d.scenarios.map((s: any) => {
              const esc = s.metrics.escalation_recall ?? s.metrics.escalation_precision;
              const anyFail = Object.values(s.metrics).some((m: any) => m.passed === false);
              return (
                <tr key={s.scenario_id} className={anyFail ? "regression" : ""}>
                  <td>
                    <Link href={`/runs/${d.run_id}/${s.scenario_id}`}
                          style={{ color: "var(--accent)", fontWeight: 600 }}>
                      {s.scenario_id}
                    </Link>
                    <div className="note" style={{ maxWidth: 380 }}>{s.title}</div>
                  </td>
                  <td><Tier t={s.tier} /></td>
                  <td className="mono">{s.outcome}</td>
                  <td><Verdict p={s.metrics.task_success?.passed} /></td>
                  <td>{s.metrics.false_completion?.passed === false
                    ? <span className="b fail">false completion</span>
                    : <Verdict p={s.metrics.false_completion?.passed} />}</td>
                  <td><Verdict p={esc?.passed} /></td>
                  <td><Verdict p={s.metrics.grounded_closure_v3?.passed} /></td>
                  <td>{s.reviews?.length
                    ? <span className="b info">{s.reviews.length} reviewed</span>
                    : <span className="note">—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
