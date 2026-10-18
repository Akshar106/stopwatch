import type { HeatmapMetric } from "./color";
import { DAY_TYPE_LABEL, describeDelay, formatDelay, hourRangeLabel, plural } from "./format";
import type { Cell, DayType } from "./types";

export interface CellKey {
  day: DayType;
  hour: number;
}

/** Cells with n < min_samples carry null stats (contracts §3) and render as "not enough data". */
export function hasEnoughData(cell: Cell, minSamples: number): boolean {
  return cell.n >= minSamples && cell.p50_s != null && cell.on_time_pct != null;
}

/** The value printed inside a heatmap cell: "+3.5" (minutes) or "61%". */
export function cellText(cell: Cell, metric: HeatmapMetric, minSamples: number): string {
  if (!hasEnoughData(cell, minSamples)) return "—";
  return metric === "p50"
    ? formatDelay(cell.p50_s, { unit: false })
    : `${Math.round(cell.on_time_pct!)}%`;
}

/**
 * Full spoken description of a heatmap cell. It starts with the visible value so the
 * accessible name contains the on-screen text (WCAG 2.5.3, label in name).
 */
export function cellLabel(cell: Cell, minSamples: number, metric: HeatmapMetric = "p50"): string {
  const when = `${DAY_TYPE_LABEL[cell.day]}, ${hourRangeLabel(cell.hour)}`;
  if (!hasEnoughData(cell, minSamples)) {
    return `${when}: not enough data (${plural(cell.n, "observed arrival")}, need ${minSamples})`;
  }
  const onTime = `${Math.round(cell.on_time_pct!)}% on time`;
  const delay = `typical delay ${describeDelay(cell.p50_s)}`;
  const arrivals = plural(cell.n, "arrival");
  return metric === "p50"
    ? `${cellText(cell, metric, minSamples)} min: ${when}, ${delay}, ${onTime}, ${arrivals}`
    : `${onTime}: ${when}, ${delay}, ${arrivals}`;
}

export function findCell(cells: readonly Cell[], key: CellKey | null): Cell | null {
  if (!key) return null;
  return cells.find((c) => c.day === key.day && c.hour === key.hour) ?? null;
}

/** "wkd-8" ⇄ {day, hour} for shareable URLs. */
export function parseCellKey(value: string | null): CellKey | null {
  const m = /^(wkd|sat|sun)-(\d{1,2})$/.exec(value ?? "");
  if (!m) return null;
  const hour = Number(m[2]);
  return hour >= 0 && hour <= 23 ? { day: m[1] as DayType, hour } : null;
}

export function formatCellKey(key: CellKey): string {
  return `${key.day}-${key.hour}`;
}

/** Minute labels for histogram buckets: [-60, 60, 180] → ["< −1", "−1–1", "1–3", "3+"]. */
export function bucketLabels(edges: readonly number[]): string[] {
  const m = (s: number) => {
    const v = s / 60;
    const text = Number.isInteger(v) ? String(Math.abs(v)) : Math.abs(v).toFixed(1);
    return v < 0 ? `−${text}` : text;
  };
  const labels: string[] = [];
  for (let i = 0; i <= edges.length; i++) {
    if (i === 0) labels.push(`< ${m(edges[0]!)}`);
    else if (i === edges.length) labels.push(`${m(edges[i - 1]!)}+`);
    else labels.push(`${m(edges[i - 1]!)}–${m(edges[i]!)}`);
  }
  return labels;
}
