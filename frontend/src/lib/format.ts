import type { DayType, RouteInfo, Weekday } from "./types";

const MINUS = "−";

/** Signed minutes with one decimal under 10 min: 210 → "+3.5 min", −45 → "−0.8 min". */
export function formatDelay(
  seconds: number | null | undefined,
  opts: { unit?: boolean } = {},
): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const unit = opts.unit === false ? "" : " min";
  const minutes = seconds / 60;
  const abs = Math.abs(minutes);
  const rounded = abs >= 10 ? Math.round(abs).toString() : (Math.round(abs * 10) / 10).toFixed(1);
  if (rounded === "0.0" || rounded === "0") return `0${unit}`;
  return `${minutes < 0 ? MINUS : "+"}${rounded}${unit}`;
}

/** Spoken form for screen readers: "3.5 minutes late", "0.8 minutes early". */
export function describeDelay(seconds: number | null | undefined): string {
  if (seconds == null) return "no data";
  const abs = Math.abs(seconds / 60);
  const value = abs >= 10 ? Math.round(abs).toString() : (Math.round(abs * 10) / 10).toString();
  if (value === "0") return "on schedule";
  return `${value} ${value === "1" ? "minute" : "minutes"} ${seconds < 0 ? "early" : "late"}`;
}

export function formatPct(pct: number | null | undefined, digits = 0): string {
  if (pct == null || Number.isNaN(pct)) return "—";
  return `${pct.toFixed(digits)}%`;
}

const numberFormat = new Intl.NumberFormat("en-US");
export function formatCount(n: number | null | undefined): string {
  return n == null ? "—" : numberFormat.format(n);
}

/** Compact duration: 45 → "45 s", 190 → "3 min", 7500 → "2 h 5 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 90) return `${s} s`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h < 48) return m ? `${h} h ${m} min` : `${h} h`;
  return `${Math.round(h / 24)} days`;
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "unknown";
  const diff = (now.getTime() - t) / 1000;
  if (diff < 0) return "just now";
  if (diff < 45) return "just now";
  return `${formatDuration(diff)} ago`;
}

export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // dateStyle/timeStyle can't be combined with timeZoneName, so spell the fields out.
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(d);
}

export function formatClock(iso: string | Date, timeZone?: string): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone }).format(
    d,
  );
}

/** "2026-10-12" → "Oct 12, 2026" without time-zone drift. */
export function formatDate(isoDate: string, opts: { year?: boolean } = {}): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: opts.year === false ? undefined : "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function hourLabel(hour: number): string {
  const h = ((hour % 24) + 24) % 24;
  const suffix = h < 12 ? "AM" : "PM";
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${twelve} ${suffix}`;
}

export function hourRangeLabel(hour: number): string {
  return `${hourLabel(hour)}–${hourLabel(hour + 1)}`;
}

/** "07:30" → "7:30 AM". */
export function formatHHMM(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (h == null || m == null || Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const suffix = h < 12 ? "AM" : "PM";
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${twelve}:${m.toString().padStart(2, "0")} ${suffix}`;
}

export const DAY_TYPE_LABEL: Record<DayType, string> = {
  wkd: "Weekdays",
  sat: "Saturday",
  sun: "Sunday",
};

export const DAY_TYPE_SHORT: Record<DayType, string> = {
  wkd: "Weekday",
  sat: "Sat",
  sun: "Sun",
};

export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

const WEEKDAY_ORDER: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** ["mon".."fri"] → "Mon–Fri"; ["sat","sun"] → "Sat, Sun"; all → "Every day". */
export function formatDays(days: readonly Weekday[]): string {
  const set = new Set(days);
  const sorted = WEEKDAY_ORDER.filter((d) => set.has(d));
  if (sorted.length === 7) return "Every day";
  if (sorted.length === 0) return "No days";
  const runs: Weekday[][] = [];
  for (const d of sorted) {
    const last = runs[runs.length - 1];
    const prev = last?.[last.length - 1];
    if (last && prev && WEEKDAY_ORDER.indexOf(d) === WEEKDAY_ORDER.indexOf(prev) + 1) last.push(d);
    else runs.push([d]);
  }
  return runs
    .map((run) => {
      const first = run[0]!;
      const last = run[run.length - 1]!;
      return run.length >= 3
        ? `${WEEKDAY_LABEL[first]}–${WEEKDAY_LABEL[last]}`
        : run.map((d) => WEEKDAY_LABEL[d]).join(", ");
    })
    .join(", ");
}

const ROUTE_TYPE_LABEL: Record<number, string> = {
  0: "Light rail",
  1: "Subway",
  2: "Commuter rail",
  3: "Bus",
  4: "Ferry",
};

export function routeTypeLabel(type: number): string {
  return ROUTE_TYPE_LABEL[type] ?? "Transit";
}

/** Short label for chips: "1", "Red Line". */
export function routeShortLabel(route: Pick<RouteInfo, "id" | "short_name" | "long_name">): string {
  return route.short_name?.trim() || route.long_name?.trim() || route.id;
}

/** Name for headings: "Route 1" for buses, "Red Line" for named lines. */
export function routeName(
  route: Pick<RouteInfo, "id" | "short_name" | "long_name" | "type">,
): string {
  const short = route.short_name?.trim();
  if (short) return route.type === 3 ? `Route ${short}` : short;
  return route.long_name?.trim() || route.id;
}

/** Full label: "Route 1 · Harvard Square - Nubian Station" or "Red Line". */
export function routeFullLabel(
  route: Pick<RouteInfo, "id" | "short_name" | "long_name" | "type">,
): string {
  const short = route.short_name?.trim();
  const long = route.long_name?.trim();
  if (short && long) return `${route.type === 3 ? "Route " : ""}${short} · ${long}`;
  return long || (short ? `${route.type === 3 ? "Route " : ""}${short}` : route.id);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}
