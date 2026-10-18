import { describe, expect, it } from "vitest";
import { fixtures } from "../test/fixtures";
import {
  cellsInWindow,
  compareTrend,
  formatPercentile,
  histogramPercentile,
  mergeHistograms,
  summarizeWindow,
} from "./summary";
import type { Cell, TrendPoint } from "./types";

const EDGES = [-60, 60, 180, 300, 600, 1200];

const cell = (over: Partial<Cell>): Cell => ({
  day: "wkd",
  hour: 8,
  n: 10,
  p50_s: 100,
  p90_s: 300,
  on_time_pct: 80,
  early_pct: 5,
  canceled: 0,
  skipped: 0,
  sched_headway_s: 600,
  ewt_s: 60,
  hist: [0, 0, 0, 0, 0, 0, 0],
  ...over,
});

describe("histogramPercentile", () => {
  it("interpolates linearly inside a closed bucket", () => {
    // 10 arrivals, all in [60, 180): the median is halfway through the bucket.
    expect(histogramPercentile([0, 0, 10, 0, 0, 0, 0], EDGES, 0.5)).toEqual({
      value_s: 120,
      bound: null,
    });
    // 4 in [-60,60), 4 in [60,180), 2 in [180,300): the 5th arrival is 1/4 into [60,180) → 90 s;
    // the 9th is halfway through [180,300) → 240 s.
    const hist = [0, 4, 4, 2, 0, 0, 0];
    expect(histogramPercentile(hist, EDGES, 0.5)).toEqual({ value_s: 90, bound: null });
    expect(histogramPercentile(hist, EDGES, 0.9)).toEqual({ value_s: 240, bound: null });
  });

  it("reports open-ended buckets as bounds instead of inventing a value", () => {
    expect(histogramPercentile([9, 1, 0, 0, 0, 0, 0], EDGES, 0.5)).toEqual({
      value_s: -60,
      bound: "lt",
    });
    expect(histogramPercentile([0, 1, 0, 0, 0, 0, 9], EDGES, 0.9)).toEqual({
      value_s: 1200,
      bound: "gt",
    });
  });

  it("returns null for empty or mismatched histograms", () => {
    expect(histogramPercentile([0, 0, 0, 0, 0, 0, 0], EDGES, 0.5)).toBeNull();
    expect(histogramPercentile([1, 2, 3], EDGES, 0.5)).toBeNull();
  });

  it("is monotonic in q", () => {
    const hist = [2, 10, 25, 14, 9, 4, 1];
    let prev = -Infinity;
    for (let q = 0.05; q < 1; q += 0.05) {
      const v = histogramPercentile(hist, EDGES, q)!.value_s;
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });
});

describe("cellsInWindow", () => {
  const cells = [
    cell({ day: "wkd", hour: 6 }),
    cell({ day: "wkd", hour: 7 }),
    cell({ day: "wkd", hour: 8 }),
    cell({ day: "wkd", hour: 9 }),
    cell({ day: "sat", hour: 8 }),
    cell({ day: "sun", hour: 8 }),
  ];

  it("keeps cells whose day type matches a selected day and whose hour overlaps the window", () => {
    const got = cellsInWindow(cells, ["mon", "wed"], "07:30", "08:30");
    expect(got.map((c) => `${c.day}-${c.hour}`)).toEqual(["wkd-7", "wkd-8"]);
  });

  it("treats the window as half-open on the hour boundary", () => {
    expect(cellsInWindow(cells, ["fri"], "07:00", "08:00").map((c) => c.hour)).toEqual([7]);
  });

  it("maps Saturday and Sunday to their own day types", () => {
    const got = cellsInWindow(cells, ["sat", "sun"], "08:00", "09:00");
    expect(got.map((c) => c.day)).toEqual(["sat", "sun"]);
  });
});

describe("summarizeWindow", () => {
  it("sums n, weights on-time % by n and approximates percentiles from the merged histogram", () => {
    const stop = {
      cells: [
        cell({ hour: 7, n: 30, on_time_pct: 90, hist: [0, 10, 17, 3, 0, 0, 0], canceled: 1 }),
        cell({ hour: 8, n: 10, on_time_pct: 50, hist: [0, 0, 2, 3, 5, 0, 0], skipped: 2 }),
      ],
    };
    const s = summarizeWindow(stop, ["mon"], "07:30", "08:30", EDGES, 8);
    expect(s.n).toBe(40);
    expect(s.on_time_pct).toBeCloseTo((90 * 30 + 50 * 10) / 40, 6);
    expect(s.hist).toEqual([0, 10, 19, 6, 5, 0, 0]);
    expect(mergeHistograms(stop.cells, 7)).toEqual(s.hist);
    // 40 arrivals: 20th falls in [60,180) after 10 → (20-10)/19 of the way → 60 + 120*10/19
    expect(s.p50).toEqual({ value_s: Math.round(60 + (120 * 10) / 19), bound: null });
    expect(s.p90?.bound).toBeNull();
    expect(s.p90!.value_s).toBeGreaterThanOrEqual(300);
    expect(s.canceled).toBe(1);
    expect(s.skipped).toBe(2);
    expect(s.enoughData).toBe(true);
  });

  it("ignores cells without an on-time % when weighting, but still counts their arrivals", () => {
    const stop = {
      cells: [
        cell({ hour: 7, n: 20, on_time_pct: 70, hist: [0, 10, 10, 0, 0, 0, 0] }),
        cell({
          hour: 8,
          n: 5,
          on_time_pct: null,
          p50_s: null,
          p90_s: null,
          hist: [0, 5, 0, 0, 0, 0, 0],
        }),
      ],
    };
    const s = summarizeWindow(stop, ["tue"], "07:00", "09:00", EDGES, 8);
    expect(s.n).toBe(25);
    expect(s.on_time_pct).toBe(70);
  });

  it("reports not enough data below min_samples", () => {
    const s = summarizeWindow(
      { cells: [cell({ n: 5, hist: [0, 5, 0, 0, 0, 0, 0] })] },
      ["mon"],
      "08:00",
      "09:00",
      EDGES,
      8,
    );
    expect(s.enoughData).toBe(false);
    expect(s.p50).toBeNull();
    expect(s.on_time_pct).toBeNull();
  });

  it("works on the published fixture for route 1 at Mass Ave @ Newbury St", () => {
    const route = fixtures.route1;
    const stop = route.directions[0]!.stops.find((s) => s.stop_id === "64")!;
    const s = summarizeWindow(
      stop,
      ["mon", "tue", "wed", "thu", "fri"],
      "07:30",
      "08:30",
      route.histogram_edges_s,
      route.min_samples,
    );
    const expected = stop.cells.filter((c) => c.day === "wkd" && (c.hour === 7 || c.hour === 8));
    expect(s.n).toBe(expected.reduce((a, c) => a + c.n, 0));
    expect(s.hist.reduce((a, b) => a + b, 0)).toBe(s.n);
    expect(s.p50!.value_s).toBeLessThanOrEqual(s.p90!.value_s);
  });
});

describe("compareTrend", () => {
  const point = (week_start: string, on_time_pct: number | null, n = 100): TrendPoint => ({
    week_start,
    n,
    on_time_pct,
    p50_s: 120,
    p90_s: 400,
  });

  it("compares the latest week with the n-weighted mean of up to 4 previous weeks", () => {
    const trend = [
      point("2026-08-31", 10), // outside the 4-week comparison
      point("2026-09-07", 60, 100),
      point("2026-09-14", 70, 300),
      point("2026-09-21", 65, 100),
      point("2026-09-28", null),
      point("2026-10-05", 72),
    ];
    const c = compareTrend(trend)!;
    expect(c.latest.week_start).toBe("2026-10-05");
    expect(c.weeks_compared).toBe(4);
    expect(c.previous_on_time_pct).toBeCloseTo((60 * 100 + 70 * 300 + 65 * 100) / 500, 6);
    expect(c.delta_pts).toBeCloseTo(72 - 67, 6);
  });

  it("handles empty and single-week trends", () => {
    expect(compareTrend([])).toBeNull();
    expect(compareTrend([point("2026-10-05", 70)])).toMatchObject({
      previous_on_time_pct: null,
      delta_pts: null,
    });
  });
});

describe("formatPercentile", () => {
  it("labels approximations and bounds", () => {
    expect(formatPercentile({ value_s: 210, bound: null })).toBe("≈ +3.5 min");
    expect(formatPercentile({ value_s: -60, bound: "lt" })).toBe("under −1.0 min");
    expect(formatPercentile({ value_s: 1200, bound: "gt" })).toBe("over +20 min");
    expect(formatPercentile(null)).toBe("—");
  });
});
