"use client";
import { Cell, pct } from "@/lib/api";

export function Verdict({ p }: { p: boolean | null }) {
  if (p === null || p === undefined) return <span className="b na">n/a</span>;
  return <span className={`b ${p ? "pass" : "fail"}`}>{p ? "pass" : "fail"}</span>;
}

export function Rate({ c }: { c?: Cell | null }) {
  if (!c || c.n_applicable === 0)
    return <span className="b na" title="no applicable scenarios in this slice">n/a</span>;
  return (
    <span>
      <span className="rate">{pct(c)}</span>{" "}
      <span className="den">{c.n_passed}/{c.n_applicable}</span>
    </span>
  );
}

/** Delta between two cells. Shown with denominators because a 2-scenario slice
 *  moving 50 points is one scenario changing its mind. */
export function Delta({ a, b }: { a?: Cell | null; b?: Cell | null }) {
  if (!a || !b || a.rate === null || b.rate === null) return <span className="delta flat">—</span>;
  const d = Math.round((b.rate - a.rate) * 100);
  const cls = d > 0 ? "up" : d < 0 ? "down" : "flat";
  return <span className={`delta ${cls}`}>{d > 0 ? "+" : ""}{d}pp</span>;
}

export function Tier({ t }: { t: string }) {
  return <span className={`tier ${t}`}>{t.replace("control_", "control · ")}</span>;
}

export function Loading() {
  return <div className="empty">Loading…</div>;
}

export function ApiDown({ e }: { e: string }) {
  return (
    <div className="callout bad" style={{ marginTop: 24 }}>
      <b>Cannot reach the API.</b> Start it with{" "}
      <code className="mono">cd backend &amp;&amp; .venv/bin/uvicorn app.main:app --port 8000</code>
      <div className="note" style={{ marginTop: 6 }}>{e}</div>
    </div>
  );
}
