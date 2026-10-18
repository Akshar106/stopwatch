import { describe, expect, it } from "vitest";
import { agency, fixtures } from "./fixtures";

/** Guards the fixtures against drifting from docs/contracts.md §3. */
describe("fixtures follow the published-data contract", () => {
  const edges = agency.histogram_edges_s;

  it("manifest", () => {
    expect(fixtures.manifest.schema_version).toBe(1);
    expect(agency.paths.route_template).toContain("{route_id}");
    expect(agency.on_time_definition_s).toEqual([-60, 300]);
  });

  it("stops index", () => {
    expect(fixtures.stops.stops.length).toBeGreaterThanOrEqual(30);
    for (const s of fixtures.stops.stops) {
      expect(Number.isFinite(s.lat) && Number.isFinite(s.lon)).toBe(true);
      expect(s.routes.length).toBeGreaterThan(0);
    }
  });

  for (const route of [fixtures.route1, fixtures.routeRed]) {
    it(`route ${route.route.id} cells are internally consistent`, () => {
      expect(route.histogram_edges_s).toEqual(edges);
      expect(route.trend.length).toBeLessThanOrEqual(8);
      for (const dir of route.directions) {
        for (const stop of dir.stops) {
          for (const c of stop.cells) {
            expect(c.hour).toBeGreaterThanOrEqual(0);
            expect(c.hour).toBeLessThanOrEqual(23);
            expect(c.hist).toHaveLength(edges.length + 1);
            expect(c.hist.reduce((a, b) => a + b, 0)).toBe(c.n);
            if (c.n < route.min_samples) {
              expect([c.p50_s, c.p90_s, c.on_time_pct, c.early_pct, c.ewt_s]).toEqual([
                null,
                null,
                null,
                null,
                null,
              ]);
            } else {
              expect(c.p50_s!).toBeLessThanOrEqual(c.p90_s!);
            }
            if (c.ewt_s != null) expect(c.sched_headway_s!).toBeLessThanOrEqual(720);
          }
        }
      }
    });
  }

  it("health and coverage", () => {
    expect(fixtures.health.ticks_last_hour.expected).toBe(60);
    expect(fixtures.coverage.days).toHaveLength(30);
    expect(fixtures.coverage.days.some((d) => (d.coverage_pct ?? 100) < 80)).toBe(true);
  });
});
