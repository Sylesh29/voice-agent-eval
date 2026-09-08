"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import { ApiDown, Loading, Rate } from "./ui";

const HEADLINE = [
  ["task_success", "Task success", "state-verified"],
  ["false_completion", "No false completion", "of calls that claimed success"],
  ["escalation_recall", "Escalation recall", "must-escalate slice only"],
  ["grounded_closure_v4", "Grounded closure", "judge clarity AND action landed"],
];

export default function Runs() {
  const [runs, setRuns] = useState<any[]>();
  const [err, setErr] = useState("");
  useEffect(() => { get<any[]>("/api/runs").then(setRuns).catch(e => setErr(String(e))); }, []);
  if (err) return <ApiDown e={err} />;
  if (!runs) return <Loading />;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Evaluation runs</h1>
          <p className="lede">
            Each run is one agent configuration over the full 17-scenario suite.
            Every number here is verified against simulated world state, not against
            what the agent said. Open a run to see the slices — the overall figure is
            the one most likely to mislead you.
          </p>
        </div>
        <Link href="/compare"><button>Compare two runs →</button></Link>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Run</th><th>Agent config</th>
              {HEADLINE.map(([k, label, hint]) => (
                <th key={k}>{label}<div style={{ fontWeight: 400, textTransform: "none",
                  letterSpacing: 0, fontSize: 10.5, color: "var(--na)" }}>{hint}</div></th>
              ))}
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.run_id}>
                <td><Link href={`/runs/${r.run_id}`} style={{ color: "var(--accent)",
                  fontWeight: 600 }}>{r.run_id}</Link></td>
                <td className="mono">{r.agent_id}
                  <div className="note">cfg {r.config_fingerprint}</div></td>
                {HEADLINE.map(([k]) => (
                  <td key={k}><Rate c={r.headline?.[k]} /></td>
                ))}
                <td className="note">{r.created_at.replace("T", " ").replace("+00:00", "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="callout" style={{ marginTop: 20 }}>
        <b>Reading these columns.</b> “No false completion” is scored only over calls
        where the agent actually claimed the task was done — that denominator changes
        between runs, so the percentage is not comparable on its own. The compare view
        shows the counts.
      </div>
    </>
  );
}
