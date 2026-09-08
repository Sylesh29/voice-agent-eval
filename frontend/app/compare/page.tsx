"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { get } from "@/lib/api";
import { ApiDown, Delta, Loading, Rate, Tier } from "../ui";
import { METRIC_META, PRIMARY } from "../metrics";

function CompareInner() {
  const sp = useSearchParams();
  const [runs, setRuns] = useState<any[]>();
  const [a, setA] = useState(sp.get("a") ?? "");
  const [b, setB] = useState(sp.get("b") ?? "");
  const [d, setD] = useState<any>();
  const [err, setErr] = useState("");

  useEffect(() => {
    get<any[]>("/api/runs").then(rs => {
      setRuns(rs);
      if (!a) setA(rs[rs.length - 1]?.run_id ?? "");
      if (!b) setB(rs[0]?.run_id ?? "");
    }).catch(e => setErr(String(e)));
  }, []);
  useEffect(() => {
    if (a && b) get<any>(`/api/compare?a=${a}&b=${b}`).then(setD).catch(e => setErr(String(e)));
  }, [a, b]);

  if (err) return <ApiDown e={err} />;
  if (!runs) return <Loading />;
  const regressions = d?.per_scenario.filter((p: any) => p.worst === "regression") ?? [];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Compare runs</h1>
          <p className="lede">
            The question a release decision actually asks is not &ldquo;did the average
            improve&rdquo; &mdash; it is &ldquo;did anything get worse, and does it
            matter&rdquo;. Regressions are listed first and the slice table is the
            primary view.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={a} onChange={e => setA(e.target.value)}>
            {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
          </select>
          <span className="note">&rarr;</span>
          <select value={b} onChange={e => setB(e.target.value)}>
            {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
          </select>
        </div>
      </div>

      {!d ? <Loading /> : (
        <>
          {regressions.length > 0 && (
            <div className="callout bad" style={{ marginBottom: 20 }}>
              <b>{regressions.length} scenario{regressions.length > 1 ? "s" : ""} regressed.</b>{" "}
              A change that improves the headline and regresses the safety slice is the
              specific failure this platform is built to catch &mdash; do not read the
              overall column on its own.
            </div>
          )}

          <div className="panel">
            <div className="panel-h">
              <h2>Metric deltas by slice</h2>
              <span className="sub">{d.agent_a} &rarr; {d.agent_b}. pp = percentage points.</span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr><th style={{ minWidth: 240 }}>Metric</th><th>Slice</th>
                    <th>{a}</th><th>{b}</th><th>&Delta;</th></tr>
                </thead>
                <tbody>
                  {d.slice_diff
                    .filter((row: any) => PRIMARY.includes(row.metric))
                    .sort((x: any, y: any) => PRIMARY.indexOf(x.metric) - PRIMARY.indexOf(y.metric))
                    .flatMap((row: any) => {
                      const vis = row.slices.filter(
                        (s: any) => (s.a?.n_applicable ?? 0) + (s.b?.n_applicable ?? 0) > 0);
                      return vis.map((s: any, i: number) => {
                        const worse = s.a?.rate != null && s.b?.rate != null && s.b.rate < s.a.rate;
                        return (
                          <tr key={row.metric + s.slice} className={worse ? "regression" : ""}>
                            {i === 0 && (
                              <td rowSpan={vis.length}>
                                <div style={{ fontWeight: 600 }}>
                                  {METRIC_META[row.metric]?.label ?? row.metric}</div>
                                <div className="note" style={{ maxWidth: 300 }}>
                                  {METRIC_META[row.metric]?.question}</div>
                              </td>
                            )}
                            <td className="mono">{s.slice}</td>
                            <td><Rate c={s.a} /></td>
                            <td><Rate c={s.b} /></td>
                            <td><Delta a={s.a} b={s.b} /></td>
                          </tr>
                        );
                      });
                    })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 20 }}>
            <div className="panel-h">
              <h2>Scenarios that changed</h2>
              <span className="sub">{d.per_scenario.length} of 17 &middot; regressions first</span>
            </div>
            {d.per_scenario.length === 0
              ? <div className="empty">No scenario changed verdict between these runs.</div>
              : (
                <table>
                  <thead><tr><th>Scenario</th><th>Tier</th><th>What changed</th></tr></thead>
                  <tbody>
                    {d.per_scenario.map((p: any) => (
                      <tr key={p.scenario_id}
                          className={p.worst === "regression" ? "regression" : ""}>
                        <td>
                          <Link href={`/runs/${b}/${p.scenario_id}`}
                                style={{ color: "var(--accent)", fontWeight: 600 }}>
                            {p.scenario_id}</Link>
                          <div className="note" style={{ maxWidth: 380 }}>{p.title}</div>
                        </td>
                        <td><Tier t={p.tier} /></td>
                        <td>
                          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                            {p.changes.map((c: any) => (
                              <div key={c.metric}
                                   style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                <span className={`b ${c.direction === "regression" ? "fail" :
                                  c.direction === "improvement" ? "pass" : "na"}`}>
                                  {c.direction.replace(/_/g, " ")}</span>
                                <span className="mono">
                                  {METRIC_META[c.metric]?.label ?? c.metric}</span>
                                <span className="note">{String(c.a)} &rarr; {String(c.b)}</span>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
        </>
      )}
    </>
  );
}

export default function Compare() {
  return <Suspense fallback={<Loading />}><CompareInner /></Suspense>;
}
