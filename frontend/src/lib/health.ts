import type { Health, HealthStatus } from "./types";

/** The ingest job rewrites health.json every 5 minutes; contracts §3 marks stale after 15. */
export const STALE_AFTER_S = 15 * 60;

/**
 * The status written in health.json, except that a health file which itself stopped updating
 * (e.g. the whole ingest function is down, so nothing rewrites it) is treated as stale too.
 */
export function effectiveStatus(health: Health, now: Date = new Date()): HealthStatus {
  if (health.status === "stale" || health.status === "unknown") return health.status;
  const generated = Date.parse(health.generated_at);
  if (Number.isFinite(generated) && (now.getTime() - generated) / 1000 > STALE_AFTER_S)
    return "stale";
  return health.status;
}

export const STATUS_LABEL: Record<HealthStatus, string> = {
  ok: "Operational",
  degraded: "Degraded",
  stale: "Stale",
  unknown: "Unknown",
};

export const STATUS_DESCRIPTION: Record<HealthStatus, string> = {
  ok: "Live feed is being collected every minute.",
  degraded: "Collection is running but the feed is delayed or some recent ticks failed.",
  stale:
    "No successful collection in more than 15 minutes. Reliability numbers are unaffected, but today's data may have gaps.",
  unknown: "No collection data yet.",
};
