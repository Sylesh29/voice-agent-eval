"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import { ApiDown, Loading } from "../ui";
import { METRIC_META } from "../metrics";

export default function Patterns() {
  const [d, setD] = useState<any[]>();
  const [err, setErr] = useState("");
  useEffect(() => { get<any[]>("/api/failure-patterns").then(setD).catch(e => setErr(String(e))); }, []);
  if (err) return <ApiDown e={err} />;
  if (!d) return <Loading />;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Failure patterns</h1>
          <p className="lede">
            Grouped by mechanism across every run, not by scenario. &ldquo;Which
            scenarios failed&rdquo; is a test report; &ldquo;which mechanism keeps
            failing&rdquo; is what turns into a ticket with an owner. A mechanism that
            appears in all three agent versions is a system problem, not an agent
            problem &mdash; changing the prompt will not fix it.
          </p>
        </div>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr><th>Mechanism</th><th>Occurrences</th><th>Appears in</th>
              <th>Scenarios</th></tr>
          </thead>
          <tbody>
            {d.map(p => {
              const allRuns = p.runs.length >= 3;
              return (
                <tr key={p.mechanism} className={allRuns ? "regression" : ""}>
                  <td>
                    <div style={{ fontWeight: 600 }} className="mono">{p.mechanism}</div>
                    {allRuns && <span className="b fail" style={{ marginTop: 5 }}>
                      present in every agent version &mdash; not a prompt problem
                    </span>}
                  </td>
                  <td className="rate">{p.count}</td>
                  <td>
                    <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                      {p.runs.map((r: string) =>
                        <span key={r} className="b na">{r.replace(/_.*/, "")}</span>)}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                      {p.scenarios.map((s: string) => (
                        <Link key={s} href={`/runs/${p.runs[0]}/${s}`} className="mono"
                              style={{ color: "var(--accent)" }}>{s}</Link>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
