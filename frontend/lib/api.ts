export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export type Cell = { n_applicable: number; n_passed: number; rate: number | null };

export function pct(c?: Cell | null) {
  if (!c || c.rate === null || c.n_applicable === 0) return "—";
  return `${Math.round(c.rate * 100)}%`;
}
