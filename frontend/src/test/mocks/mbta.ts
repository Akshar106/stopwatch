import type { PredictionsDocument } from "../../lib/mbtaLive";

/** Fake MBTA V3 /predictions responses (JSON:API) relative to "now". */
export function mockPredictions(
  url: URL,
  now: Date = new Date(),
): PredictionsDocument & { jsonapi: { version: string } } {
  const stop = url.searchParams.get("filter[stop]") ?? "stop";
  const route = url.searchParams.get("filter[route]") ?? "route";
  const dir = Number(url.searchParams.get("filter[direction_id]") ?? 0);
  const plan: { inMin: number; lateMin: number; rel: string | null; status: string | null }[] = [
    { inMin: 2, lateMin: 1, rel: null, status: "Approaching" },
    { inMin: 9, lateMin: 0, rel: null, status: null },
    { inMin: 17, lateMin: 6, rel: null, status: null },
    { inMin: 25, lateMin: 0, rel: "CANCELLED", status: null },
  ];
  const iso = (ms: number) => new Date(Math.round(ms / 1000) * 1000).toISOString();
  const data = plan.map((p, i) => ({
    id: `prediction-${route}-${stop}-${i}`,
    type: "prediction" as const,
    attributes: {
      arrival_time: p.rel === "CANCELLED" ? null : iso(now.getTime() + p.inMin * 60_000),
      departure_time: null,
      schedule_relationship: p.rel,
      status: p.status,
      direction_id: dir,
    },
    relationships: {
      schedule: { data: { id: `schedule-${i}`, type: "schedule" } },
      trip: { data: { id: `trip-${i}`, type: "trip" } },
    },
  }));
  const included = plan.map((p, i) => ({
    id: `schedule-${i}`,
    type: "schedule" as const,
    attributes: {
      arrival_time: iso(now.getTime() + (p.inMin - p.lateMin) * 60_000),
      departure_time: null,
    },
  }));
  return { data, included, jsonapi: { version: "1.0" } };
}
