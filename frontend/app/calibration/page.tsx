"use client";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { ApiDown, Coverage, Loading, Stat } from "../ui";

const PROGRESSION = [
  ["v1_vs_grounded_truth", "v1 — lexical cue list",
   "Clarity decided by regex. No world state."],
  ["v2_vs_grounded_truth", "v2 — grounded on the scenario contract",
   "Right verdict, wrong evidence, on three traces."],
  ["v3_vs_grounded_truth", "v3 — grounded on the asserted action",
   "One question per metric: is it clear, and did the described action land?"],
  ["v4_vs_grounded_truth", "v4 — LLM judge + grounding",
   "The judge owns clarity; code still owns whether the write landed."],
] as const;

function kappaTone(k: number) { return k < 0.2 ? "fail" : "pass"; }

export default function Calibration() {
  const [d, setD] = useState<any>();
  const [err, setErr] = useState("");
  useEffect(() => { get<any>("/api/calibration").then(setD).catch(e => setErr(String(e))); }, []);
  if (err) return <ApiDown e={err} />;
  if (!d) return <Loading />;

  const regex = d.regex_clarity_vs_human_transcript_only;
  const judge = d.judge_clarity_vs_human_transcript_only;
  const audit = d.judge_quote_audit?.unverified_quotes ?? [];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Evaluator calibration</h1>
          <p className="lede">
            Moving one judgment metric — <i>did the caller leave correctly informed about
            what happens next?</i> — from human judgment to an automated evaluator, across
            four revisions. 21 traces, hand-labelled twice: once from the transcript alone,
            once with world state revealed.
          </p>
        </div>
      </div>

      <div className="callout bad" style={{ marginBottom: 18 }}>
        <b>The finding.</b> {d.what_this_shows}
      </div>

      {/* ---- head to head: the only apples-to-apples comparison ---- */}
      <div className="panel">
        <div className="panel-h">
          <h2>Head-to-head — regex clarity vs LLM judge</h2>
          <span className="sub">
            Both see only the transcript, and so did the human who produced these labels.
            This is the only fair measurement of whether the judge earned its place.
          </span>
        </div>
        <div className="grid2" style={{ gap: 0 }}>
          {[["Regex cue list", regex], ["LLM judge", judge]].map(([name, c]: any) => (
            <div key={name} style={{ padding: "4px 0", borderRight: "1px solid var(--line-soft)" }}>
              <div style={{ padding: "14px 18px 0", fontWeight: 600, fontSize: 13 }}>{name}</div>
              {c?.unavailable ? (
                <div className="empty">No verdicts — {c.why}</div>
              ) : (
                <>
                  <div className="stats">
                    <Stat k="Accuracy" v={`${Math.round(c.accuracy * 100)}%`} />
                    <Stat k="Cohen's κ" v={c.cohens_kappa.toFixed(3)}
                          tone={kappaTone(c.cohens_kappa)} />
                  </div>
                  <div style={{ padding: "0 18px 16px" }}>
                    <Coverage c={c} />
                    {c.disagreements?.length > 0 && (
                      <div className="note" style={{ marginTop: 9 }}>
                        Disagrees on:{" "}
                        {c.disagreements.map((s: string) =>
                          <code key={s} className="mono" style={{ display: "block" }}>{s}</code>)}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="callout" style={{ marginTop: 18 }}>
        <b>Why the κ column matters more than the accuracy column.</b> The transcript-only
        labels are 20 <i>clear</i> to 1 <i>unclear</i>. At that split, accuracy is nearly
        uninformative — a rater that says “clear” every time scores 95%. κ corrects for
        chance agreement, which is why the regex reads −0.05 despite 90% accuracy. It also
        means the judge’s advantage rests entirely on the single minority-class trace, so
        the minority count is printed next to every κ on this page.
      </div>

      {/* ---- the four revisions ---- */}
      <div className="panel" style={{ marginTop: 18 }}>
        <div className="panel-h">
          <h2>Four revisions, each forced by an investigated disagreement</h2>
          <span className="sub">scored against the second, state-aware labelling pass</span>
        </div>
        <div className="scroll">
          <table>
            <thead>
              <tr><th style={{ minWidth: 300 }}>Evaluator</th><th>Accuracy</th><th>κ</th>
                <th>Coverage</th><th>Still disagrees on</th></tr>
            </thead>
            <tbody>
              {PROGRESSION.map(([key, name, blurb]) => {
                const c = d[key];
                if (!c) return null;
                return (
                  <tr key={key}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{name}</div>
                      <div className="note" style={{ maxWidth: 44 + 300 }}>{blurb}</div>
                    </td>
                    <td>{c.unavailable ? <span className="b na">n/a</span>
                      : <span className="rate">{Math.round(c.accuracy * 100)}%</span>}</td>
                    <td>{c.unavailable ? <span className="b na">n/a</span>
                      : <span className={`b ${kappaTone(c.cohens_kappa)}`}>
                          {c.cohens_kappa.toFixed(3)}</span>}</td>
                    <td>
                      {c.unavailable ? <span className="b na">none</span>
                        : <span className={`b ${c.reportable ? "pass" : "fail"}`}>
                            {c.n_scored}/{c.n_total}</span>}
                    </td>
                    <td>
                      {(c.disagreements ?? []).length === 0
                        ? <span className="note">—</span>
                        : c.disagreements.map((s: string) =>
                            <code key={s} className="mono" style={{ display: "block" }}>{s}</code>)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- the deterministic check on the judge ---- */}
      <div className="panel" style={{ marginTop: 18 }}>
        <div className="panel-h">
          <h2>Quote audit — a deterministic check on the judge itself</h2>
          <span className="sub">
            The judge must cite a span from the transcript; code checks it appears verbatim.
          </span>
        </div>
        {audit.length === 0 ? (
          <div className="empty">Every judge citation was found verbatim.</div>
        ) : (
          <div style={{ padding: "16px 18px" }}>
            <span className="b fail">{audit.length} ungrounded citation
              {audit.length === 1 ? "" : "s"}</span>
            <div className="note" style={{ marginTop: 8, lineHeight: 1.7, maxWidth: "78ch" }}>
              {audit.map((s: string) => <code key={s} className="mono"
                style={{ display: "block", marginBottom: 4 }}>{s}</code>)}
              On this trace the judge returned a correct verdict at 0.98 confidence and
              cited “<b>Baysen</b> Drug”. The transcript says “<b>Bayside</b> Drug”. It
              corrupted the pharmacy name — the critical entity of the workflow — inside a
              quote it asserted was verbatim. Reading its reasoning would never have
              surfaced that; three lines comparing the citation to the transcript did.
              This is why entity correctness is scored deterministically against tool
              arguments and never by a judge.
            </div>
          </div>
        )}
      </div>

      {/* ---- every label ---- */}
      <div className="panel" style={{ marginTop: 18 }}>
        <div className="panel-h">
          <h2>All 21 labelled traces</h2>
          <span className="sub">both labelling passes and all four evaluator verdicts</span>
        </div>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Scenario</th><th>Run</th>
                <th>Human<br />transcript only</th><th>Human<br />with state</th>
                <th>v1</th><th>Judge</th><th>v3</th><th>v4</th><th>Note</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r: any, i: number) => {
                const blind = r.human_transcript_only !== r.grounded_truth;
                const v4wrong = r.evaluator_v4 && r.evaluator_v4 !== r.grounded_truth;
                return (
                  <tr key={i} className={v4wrong ? "flag" : ""}>
                    <td className="mono">{r.scenario}</td>
                    <td className="note">{r.run.replace(/_.*/, "")}</td>
                    <td>
                      <span className={`b ${r.human_transcript_only === "clear" ? "pass" : "fail"}`}>
                        {r.human_transcript_only}</span>
                      {blind && <div className="note" style={{ marginTop: 3 }}>
                        state changed this</div>}
                    </td>
                    <td><span className={`b ${r.grounded_truth === "clear" ? "pass" : "fail"}`}>
                      {r.grounded_truth}</span></td>
                    {["evaluator_v1", "judge_clarity", "evaluator_v3", "evaluator_v4"].map(k => {
                      const truth = k === "judge_clarity" || k === "evaluator_v1"
                        ? r.human_transcript_only : r.grounded_truth;
                      if (!r[k]) return <td key={k}><span className="b na">n/a</span></td>;
                      return (
                        <td key={k}>
                          <span className={`b ${r[k] === truth ? "pass" : "fail"}`}>{r[k]}</span>
                        </td>
                      );
                    })}
                    <td className="note" style={{ maxWidth: 300 }}>{r.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "14px 18px", borderTop: "1px solid var(--line-soft)" }}
             className="note">
          v1 and the judge are scored against the <b>transcript-only</b> labels — that is the
          evidence they had. v3 and v4 are scored against the <b>state-aware</b> labels,
          because they see state. Comparing an evaluator to a label made from evidence it
          never had is how the first version of this page would have flattered the judge.
        </div>
      </div>
    </>
  );
}
