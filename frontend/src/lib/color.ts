import type { RouteInfo } from "./types";

export type HeatmapMetric = "p50" | "on_time";

/**
 * One sequential palette for both metrics so "darker = worse" holds everywhere.
 * Early arrivals get a distinct hue (blue) because "too early" is a different failure.
 * Colors are paired with a text color chosen for ≥ 4.5:1 contrast, and every cell also
 * prints its value, so color is never the only encoding.
 */
const SEQ = ["#fdf6df", "#fde2a6", "#fbc06e", "#f3953f", "#dd5f22", "#a32a0f"] as const;
const EARLY = "#5b8fd1";

export interface ScaleBin {
  color: string;
  label: string;
  /** Inclusive lower bound (seconds or percent). */
  min: number;
}

export const DELAY_BINS: ScaleBin[] = [
  { min: -Infinity, color: EARLY, label: "Early (< −1 min)" },
  { min: -60, color: SEQ[0], label: "−1 to +1 min" },
  { min: 60, color: SEQ[1], label: "+1 to +2 min" },
  { min: 120, color: SEQ[2], label: "+2 to +3 min" },
  { min: 180, color: SEQ[3], label: "+3 to +5 min" },
  { min: 300, color: SEQ[4], label: "+5 to +10 min" },
  { min: 600, color: SEQ[5], label: "+10 min or more" },
];

export const ON_TIME_BINS: ScaleBin[] = [
  { min: 90, color: SEQ[0], label: "90% or more" },
  { min: 80, color: SEQ[1], label: "80–90%" },
  { min: 70, color: SEQ[2], label: "70–80%" },
  { min: 60, color: SEQ[3], label: "60–70%" },
  { min: 50, color: SEQ[4], label: "50–60%" },
  { min: -Infinity, color: SEQ[5], label: "Under 50%" },
];

export function delayBin(p50s: number): ScaleBin {
  let bin = DELAY_BINS[0]!;
  for (const b of DELAY_BINS) if (p50s >= b.min) bin = b;
  return bin;
}

export function onTimeBin(pct: number): ScaleBin {
  return ON_TIME_BINS.find((b) => pct >= b.min) ?? ON_TIME_BINS[ON_TIME_BINS.length - 1]!;
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return 0;
  const v = parseInt(m[1]!, 16);
  return (
    0.2126 * channel((v >> 16) & 255) + 0.7152 * channel((v >> 8) & 255) + 0.0722 * channel(v & 255)
  );
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const DARK_TEXT = "#14110f";
const LIGHT_TEXT = "#ffffff";

/** Whichever of near-black / white contrasts more with the background. */
export function readableTextOn(bg: string): string {
  return contrastRatio(bg, DARK_TEXT) >= contrastRatio(bg, LIGHT_TEXT) ? DARK_TEXT : LIGHT_TEXT;
}

/** GTFS colors are 6 hex digits without "#"; accept either, reject anything else. */
export function normalizeHex(value: string | null | undefined): string | null {
  if (!value) return null;
  const m = /^#?([0-9a-f]{6})$/i.exec(value.trim());
  return m ? `#${m[1]!.toUpperCase()}` : null;
}

const FALLBACK_BG = "#5A6472";

export function routeColors(route: Pick<RouteInfo, "color" | "text_color">): {
  bg: string;
  fg: string;
} {
  const bg = normalizeHex(route.color) ?? FALLBACK_BG;
  const declared = normalizeHex(route.text_color);
  // Respect the agency's text color only when it is actually readable.
  const fg = declared && contrastRatio(bg, declared) >= 4.5 ? declared : readableTextOn(bg);
  return { bg, fg };
}
