import type { DayType, Weekday } from "./types";

/** Days and time-window logic shared by commutes, the guided Ask form and heatmap defaults. */

export const WEEKDAY_TO_DAY_TYPE: Record<Weekday, DayType> = {
  mon: "wkd",
  tue: "wkd",
  wed: "wkd",
  thu: "wkd",
  fri: "wkd",
  sat: "sat",
  sun: "sun",
};

export function dayTypesFor(days: readonly Weekday[]): Set<DayType> {
  return new Set(days.map((d) => WEEKDAY_TO_DAY_TYPE[d]));
}

/** "07:30" → 450. Returns NaN for malformed input. */
export function parseHHMM(value: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value);
  if (!m) return NaN;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 24 || min > 59 || (h === 24 && min !== 0)) return NaN;
  return h * 60 + min;
}

export function isValidWindow(start: string, end: string): boolean {
  const s = parseHHMM(start);
  const e = parseHHMM(end);
  return Number.isFinite(s) && Number.isFinite(e) && e > s;
}

/**
 * Does clock hour `hour` (covering [hour:00, hour+1:00)) overlap the half-open window
 * [start, end)? A 07:30–08:30 window overlaps hours 7 and 8; 07:00–08:00 only hour 7.
 */
export function hourOverlapsWindow(hour: number, start: string, end: string): boolean {
  const s = parseHHMM(start);
  const e = parseHHMM(end);
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return false;
  const hs = hour * 60;
  const he = hs + 60;
  return hs < e && he > s;
}

export function hoursInWindow(start: string, end: string): number[] {
  const hours: number[] = [];
  for (let h = 0; h < 24; h++) if (hourOverlapsWindow(h, start, end)) hours.push(h);
  return hours;
}

/**
 * Current day type and clock hour in the agency's time zone (cells are local clock hours).
 * Used to preselect the "right now" heatmap cell.
 */
export function nowInZone(
  timeZone: string,
  now: Date = new Date(),
): { dayType: DayType; hour: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    hour: "numeric",
    hourCycle: "h23",
  }).formatToParts(now);
  const weekday = parts.find((p) => p.type === "weekday")?.value ?? "Mon";
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0") % 24;
  const dayType: DayType = weekday === "Sat" ? "sat" : weekday === "Sun" ? "sun" : "wkd";
  return { dayType, hour };
}

/**
 * Service-day ordering for hour axes: transit days run roughly 4 AM → 3 AM, so 12–3 AM
 * belong at the bottom of the heatmap, after 11 PM, not at the top.
 */
export const SERVICE_DAY_START_HOUR = 4;
export function serviceHourOrder(hour: number): number {
  return (hour - SERVICE_DAY_START_HOUR + 24) % 24;
}
