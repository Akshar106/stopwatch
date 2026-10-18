import { formatDelay } from "./format";
import { dayTypesFor, hourOverlapsWindow } from "./schedule";
import type { Cell, StopCells, TrendPoint, Weekday } from "./types";

/**
 * Personal commute summaries, computed in the browser from the public route file
 * (docs/04 §8.2: the server never reads analytics for a user request).
 *
 * Cell percentiles can't be averaged, so p50/p90 for a window spanning several cells are
 * approximated from the merged delay histogram and labelled "approximate" in the UI.
 */

export interface Percentile {
  /** Seconds. For open-ended buckets this is the bucket's finite edge. */
  value_s: number;
  /** "lt": the true value is below value_s; "gt": above; null: interpolated inside a bucket. */
  bound: "lt" | "gt" | null;
}

/**
 * Percentile from bucket counts. Bucket i spans [edges[i-1], edges[i]); the first and last
 * buckets are open-ended. Interpolates linearly inside a closed bucket.
 */
export function histogramPercentile(
  hist: readonly number[],
  edges: readonly number[],
  q: number,
): Percentile | null {
  if (hist.length !== edges.length + 1) return null;
  const total = hist.reduce((a, b) => a + b, 0);
  if (total <= 0) return null;
  const target = Math.min(Math.max(q, 0), 1) * total;
  let cumulative = 0;
  for (let i = 0; i < hist.length; i++) {
    const count = hist[i] ?? 0;
    if (count > 0 && cumulative + count >= target) {
      if (i === 0) return { value_s: edges[0]!, bound: "lt" };
      if (i === hist.length - 1) return { value_s: edges[edges.length - 1]!, bound: "gt" };
      const lo = edges[i - 1]!;
      const hi = edges[i]!;
      const fraction = (target - cumulative) / count;
      return { value_s: Math.round(lo + fraction * (hi - lo)), bound: null };
    }
    cumulative += count;
  }
  return { value_s: edges[edges.length - 1]!, bound: "gt" };
}

export function mergeHistograms(cells: readonly Cell[], buckets: number): number[] {
  const merged = new Array<number>(buckets).fill(0);
  for (const cell of cells) {
    if (cell.hist.length !== buckets) continue;
    cell.hist.forEach((count, i) => (merged[i] = (merged[i] ?? 0) + count));
  }
  return merged;
}

export function cellsInWindow(
  cells: readonly Cell[],
  days: readonly Weekday[],
  windowStart: string,
  windowEnd: string,
): Cell[] {
  const dayTypes = dayTypesFor(days);
  return cells.filter(
    (c) => dayTypes.has(c.day) && hourOverlapsWindow(c.hour, windowStart, windowEnd),
  );
}

export interface WindowSummary {
  cells: Cell[];
  n: number;
  enoughData: boolean;
  /** n-weighted over cells that report on-time %. */
  on_time_pct: number | null;
  p50: Percentile | null;
  p90: Percentile | null;
  canceled: number;
  skipped: number;
  hist: number[];
}

export function summarizeWindow(
  stop: Pick<StopCells, "cells">,
  days: readonly Weekday[],
  windowStart: string,
  windowEnd: string,
  edges: readonly number[],
  minSamples: number,
): WindowSummary {
  const cells = cellsInWindow(stop.cells, days, windowStart, windowEnd);
  const n = cells.reduce((sum, c) => sum + c.n, 0);
  let weighted = 0;
  let weight = 0;
  for (const c of cells) {
    if (c.on_time_pct != null && c.n > 0) {
      weighted += c.on_time_pct * c.n;
      weight += c.n;
    }
  }
  const hist = mergeHistograms(cells, edges.length + 1);
  const enoughData = n >= minSamples;
  return {
    cells,
    n,
    enoughData,
    on_time_pct: enoughData && weight > 0 ? weighted / weight : null,
    p50: enoughData ? histogramPercentile(hist, edges, 0.5) : null,
    p90: enoughData ? histogramPercentile(hist, edges, 0.9) : null,
    canceled: cells.reduce((sum, c) => sum + c.canceled, 0),
    skipped: cells.reduce((sum, c) => sum + c.skipped, 0),
    hist,
  };
}

export interface TrendComparison {
  latest: TrendPoint;
  /** n-weighted on-time % over up to 4 weeks before the latest one. */
  previous_on_time_pct: number | null;
  delta_pts: number | null;
  weeks_compared: number;
}

/** Route-level: latest week vs the previous (up to) 4 weeks. Trend is oldest-first. */
export function compareTrend(trend: readonly TrendPoint[]): TrendComparison | null {
  const latest = trend[trend.length - 1];
  if (!latest) return null;
  const previous = trend.slice(Math.max(0, trend.length - 5), trend.length - 1);
  let weighted = 0;
  let weight = 0;
  for (const p of previous) {
    if (p.on_time_pct != null && p.n > 0) {
      weighted += p.on_time_pct * p.n;
      weight += p.n;
    }
  }
  const previousPct = weight > 0 ? weighted / weight : null;
  return {
    latest,
    previous_on_time_pct: previousPct,
    delta_pts:
      previousPct != null && latest.on_time_pct != null ? latest.on_time_pct - previousPct : null,
    weeks_compared: previous.length,
  };
}

/** "≈ +3.5 min", "under −1.0 min", "over +20 min". */
export function formatPercentile(p: Percentile | null): string {
  if (!p) return "—";
  if (p.bound === "lt") return `under ${formatDelay(p.value_s)}`;
  if (p.bound === "gt") return `over ${formatDelay(p.value_s)}`;
  return `≈ ${formatDelay(p.value_s)}`;
}
