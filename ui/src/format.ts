export const ms = (v: number | null | undefined): string =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;

export const secs = (v: number | null | undefined): string =>
  v == null ? "—" : v >= 60 ? `${Math.floor(v / 60)}m ${Math.round(v % 60)}s` : `${v.toFixed(1)}s`;

export const when = (t: string | null): string =>
  t ? new Date(t).toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }) : "—";

/** Nearest-rank percentile over the values that exist. */
export function pct(xs: (number | null)[], p: number): number | null {
  const v = xs.filter((x): x is number => x != null).sort((a, b) => a - b);
  return v.length ? v[Math.min(v.length - 1, Math.floor(p * v.length))] : null;
}
