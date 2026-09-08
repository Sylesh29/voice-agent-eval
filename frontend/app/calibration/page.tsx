"use client";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { ApiDown, Loading } from "../ui";

function Card({ title, c, tone }: { title: string; c: any; tone?: string }) {
  return (
    <div className="panel">
      <div className="panel-h"><h3>{title}</h3></div>
      <div style={{ padding: "16px 18px", display: "flex", gap: 26 }}>
        <div>
          <div className="note">Accuracy</div>
          <div style={{ fontSize: 26, fontWeight: 660, letterSpacing: "-.02em" }}>
            {Math.round(c.accuracy * 100)}%</div>
          <div className="note">{c.agreement}/{c.n}</div>
        </div>
        <div>
          <div className="note">Cohen&rsquo;s &kappa;</div>
          <div style={{ fontSize: 26, fontWeight: 660, letterSpacing: "-.02em",
            color: c.cohens_kappa < 0.2 ? "var(--fail)" : "var(--pass)" }}>
            {c.cohens_kappa.toFixed(3)}</div>
          <div className="note">{c.cohens_kappa < 0.2 ? "no better than chance" : "substantial"}</div>
        </div>
      </div>
      {c.disagreements.length > 0 && (
        <div style={{ padding: "0 18px 16px" }}>
          <div className="note" style={{ marginBottom: 5 }}>Disagreements:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {c.disagreements.map((s: string) =>
              <code key={s} className="mono" style={{ fontSize: 11.5 }}>{s}</code>)}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Calibration() {
  const [d, setD] = useState<any>();
  const [err, setErr] = useState("");
  useEffect(() => { get<any>("/api/calibration").then(setD).catch(e => setErr(String(e))); }, []);
  if (err) return <ApiDown e={err} />;
  if (!d) return <Loading />;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Evaluator calibration</h1>
          <p className="lede">
            Moving one judgment metric &mdash; &ldquo;did the caller leave correctly
            informed about what happens next?&rdquo; &mdash; from human judgment to an
            automated evaluator, across three revisions. 21 traces, hand-labelled twice:
            once from the transcript alone, once with world state revealed.
          </p>
        </div>
      </div>

      <div className="callout bad" style={{ marginBottom: 20 }}>
        <b>The finding.</b> {d.what_this_shows}
      </div>

      <div className="row">
        <div style={{ flex: 1, minWidth: 300 }}>
          <Card title="v1 (lexical) vs my transcript-only labels"
                c={d.v1_vs_human_transcript_only} />
          <div className="note" style={{ marginTop: 8, lineHeight: 1.6 }}>
            90% accuracy. &kappa; is negative &mdash; the evaluator and I agree slightly
            <i> less</i> than two raters guessing independently at the same base rate
            would. 20 of 21 traces are one class, so accuracy carries almost no
            information here. This is the number that would have shipped if I had
            stopped at &ldquo;the evaluator matches my labels&rdquo;.
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 300 }}>
          <Card title="v1 vs state-aware labels" c={d.v1_vs_grounded_truth} />
          <div className="note" style={{ marginTop: 8, lineHeight: 1.6 }}>
            The same evaluator against a second labelling pass made with world state in
            hand. Both the lexical evaluator and my own transcript-only judgment called
            confidently-worded closings &ldquo;clear&rdquo; when the thing they asserted
            had not happened.
          </div>
        </div>
      </div>

      <div className="row" style={{ marginTop: 20 }}>
        <div style={{ flex: 1, minWidth: 300 }}>
          <Card title="v2 (grounded on scenario contract)" c={d.v2_vs_grounded_truth} />
          <div className="note" style={{ marginTop: 8, lineHeight: 1.6 }}>
            Better, but right for the wrong reason on three traces: it marked closings
            bad because the <i>task</i> was disallowed, not because the caller was
            misinformed. An evaluator that lands the right verdict via the wrong
            evidence will drift the moment those two come apart.
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 300 }}>
          <Card title="v3 (grounded on the asserted action)" c={d.v3_vs_grounded_truth} />
          <div className="note" style={{ marginTop: 8, lineHeight: 1.6 }}>
            One question per metric: is the closing clear, and did the action it
            describes actually land? The single remaining disagreement is a real
            limitation, not noise &mdash; see the table below.
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panel-h">
          <h2>The 21 labelled traces</h2>
          <span className="sub">every label, both passes, and all three evaluator verdicts</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr><th>Scenario</th><th>Run</th><th>Human<br />(transcript only)</th>
                <th>Human<br />(with state)</th><th>Eval v1</th><th>Eval v2</th>
                <th>Eval v3</th><th>Note</th></tr>
            </thead>
            <tbody>
              {d.rows.map((r: any, i: number) => {
                const wrong = r.evaluator_v3 !== r.grounded_truth;
                const blind = r.human_transcript_only !== r.grounded_truth;
                return (
                  <tr key={i} className={wrong ? "regression" : ""}>
                    <td className="mono">{r.scenario}</td>
                    <td className="note">{r.run.replace(/_.*/, "")}</td>
                    <td><span className={`b ${r.human_transcript_only === "clear" ? "pass" : "fail"}`}>
                      {r.human_transcript_only}</span>
                      {blind && <div><span className="b warn" style={{ marginTop: 4 }}>
                        blind</span></div>}</td>
                    <td><span className={`b ${r.grounded_truth === "clear" ? "pass" : "fail"}`}>
                      {r.grounded_truth}</span></td>
                    {["evaluator_v1", "evaluator_v2", "evaluator_v3"].map(k => (
                      <td key={k}>
                        <span className={`b ${r[k] === r.grounded_truth ? "pass" : "fail"}`}>
                          {r[k]}</span>
                      </td>
                    ))}
                    <td className="note" style={{ maxWidth: 320 }}>{r.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
