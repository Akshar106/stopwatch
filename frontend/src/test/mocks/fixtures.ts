import type { Health, RouteDetail } from "../../lib/types.ts";

/**
 * URL → fixture file mapping shared by the Playwright mocks (e2e/support) and the
 * `vite --mode mock` dev server (mock-backend.plugin.ts). Loading is injected so this module
 * works in Node and in Vitest alike.
 */

export const FIXTURE_BUILD_ID = "20261019T081502Z";
const BUILD = `/data/v1/builds/${FIXTURE_BUILD_ID}/mbta`;

export const FIXTURE_FILES: Record<string, string> = {
  "/data/v1/manifest.json": "manifest.json",
  [`${BUILD}/stops.json`]: "mbta-stops.json",
  [`${BUILD}/routes.json`]: "mbta-routes.json",
  [`${BUILD}/routes/1.json`]: "mbta-route-1.json",
  [`${BUILD}/routes/Red.json`]: "mbta-route-Red.json",
  [`${BUILD}/coverage.json`]: "mbta-coverage.json",
  "/data/v1/health/mbta.json": "mbta-health.json",
  "/data/v1/validation/mbta.json": "mbta-validation.json",
};

export const ROUTE_DETAIL_FILES = ["mbta-route-1.json", "mbta-route-Red.json"];

/**
 * Fixture timestamps are fixed; shift the health file so it looks freshly written (60 s ago),
 * otherwise the client would correctly flag it as stale.
 */
export function freshHealth(health: Health, now: Date, ageS = 60): Health {
  const delta = now.getTime() - ageS * 1000 - Date.parse(health.generated_at);
  const shift = (iso: string | null) =>
    iso ? new Date(Date.parse(iso) + delta).toISOString() : iso;
  return {
    ...health,
    generated_at: shift(health.generated_at)!,
    last_success_at: shift(health.last_success_at),
    feed_timestamp: shift(health.feed_timestamp),
    recent_gaps: health.recent_gaps.map((g) => ({
      ...g,
      start: shift(g.start)!,
      end: shift(g.end)!,
    })),
  };
}

export function createDataResolver(load: (file: string) => unknown) {
  return (pathname: string, now: Date = new Date()): unknown => {
    const file = FIXTURE_FILES[decodeURIComponent(pathname)];
    if (!file) return undefined;
    const data = load(file);
    return file === "mbta-health.json" ? freshHealth(data as Health, now) : data;
  };
}

/** route_id → direction_id → stop ids, for validating commute creates like the real API. */
export type RouteStops = Record<string, Record<number, string[]>>;

export function routeStopsFrom(details: RouteDetail[]): RouteStops {
  const out: RouteStops = {};
  for (const d of details) {
    out[d.route.id] = Object.fromEntries(
      d.directions.map((dir) => [dir.direction_id, dir.stops.map((s) => s.stop_id)]),
    );
  }
  return out;
}
