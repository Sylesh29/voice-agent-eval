"use client";
import { Cell, pct } from "@/lib/api";

/** Status is a dot plus its word. Never colour alone — this reads the same in
 *  greyscale and to a colourblind reviewer. */
export function Verdict({ p }: { p: boolean | null }) {
  if (p === null || p === undefined) return <span className="b na">n/a</span>;
  return <span className={`b ${p ? "pass" : "fail"}`}>{p ? "pass" : "fail"}</span>;
}

export function Rate({ c, meter = false }: { c?: Cell | null; meter?: boolean }) {
  if (!c || c.n_applicable === 0)
    return <span className="b na" title="no applicable scenarios in this slice">n/a</span>;
  const r = c.rate ?? 0;
  return (
    <span>
      <span className="rate">{pct(c)}</span>
      <span className="den">{c.n_passed}/{c.n_applicable}</span>
      {meter && (
        <span className={`meter ${r === 1 ? "ok" : r < 0.7 ? "bad" : ""}`}>
          <i style={{ width: `${Math.round(r * 100)}%` }} />
        </span>
      )}
    </span>
  );
}

/** Delta between two cells. Denominators stay visible because a 2-scenario slice
 *  moving 50 points is one scenario changing its mind. */
export function Delta({ a, b }: { a?: Cell | null; b?: Cell | null }) {
  if (!a || !b || a.rate === null || b.rate === null) return <span className="delta flat">—</span>;
  const d = Math.round((b.rate - a.rate) * 100);
  return <span className={`delta ${d > 0 ? "up" : d < 0 ? "down" : "flat"}`}>
    {d > 0 ? "+" : ""}{d}pp
  </span>;
}

export function Stat({ k, v, tone }: { k: string; v: string; tone?: "pass" | "fail" }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className={`v ${tone ?? ""}`}>{v}</div>
    </div>
  );
}

/** Coverage, always shown next to any agreement number.
 *
 *  This component exists because the CLI once reported accuracy 1.000 / kappa
 *  1.000 for the judge over the 14 of 51 calls that survived rate limiting,
 *  silently dropping the rest from the denominator. A rate without its coverage
 *  is not a result. */
export function Coverage({ c }: { c: any }) {
  if (!c || c.n_total === undefined) return null;
  const full = c.reportable;
  return (
    <div style={{ marginTop: 10 }}>
      <span className={`b ${full ? "pass" : "fail"}`}>
        {full ? "full coverage" : "not reportable"}
      </span>
      <div className="note" style={{ marginTop: 5 }}>
        scored {c.n_scored}/{c.n_total} traces ({Math.round((c.coverage ?? 0) * 100)}%)
        {c.minority_class_n !== undefined &&
          <> · κ rests on <b>{c.minority_class_n}</b> minority-class trace
            {c.minority_class_n === 1 ? "" : "s"}</>}
      </div>
      {!full && (
        <div className="note" style={{ marginTop: 4, color: "var(--fail)" }}>
          {c.n_excluded_no_verdict} trace(s) produced no verdict and were excluded.
          Do not quote this number.
        </div>
      )}
    </div>
  );
}

export function Tier({ t }: { t: string }) {
  return <span className={`tier ${t}`}>{t.replace("control_", "control · ")}</span>;
}

export function Loading() {
  return <div className="empty">Loading…</div>;
}

export function ApiDown({ e }: { e: string }) {
  return (
    <div className="callout bad" style={{ marginTop: 28 }}>
      <b>Cannot reach the API.</b> Start it with{" "}
      <code className="mono">cd backend &amp;&amp; .venv/bin/uvicorn app.main:app --port 8000</code>
      <div className="note" style={{ marginTop: 7 }}>{e}</div>
    </div>
  );
}
