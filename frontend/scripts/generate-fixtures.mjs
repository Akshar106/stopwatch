#!/usr/bin/env node
/**
 * Generates the deterministic fixture JSON in src/test/fixtures/ (docs/contracts.md §3 shapes).
 *
 * The numbers are synthetic but internally consistent: every cell's histogram, p50/p90,
 * on-time % and early % are computed from the same simulated delay samples, cells with
 * n < min_samples carry null stats, and excess wait time is only present at frequent hours.
 *
 *   npm run fixtures
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "test", "fixtures");
const BUILD_ID = "20261019T081502Z";
const EDGES = [-60, 60, 180, 300, 600, 1200];
const ON_TIME = [-60, 300];
const MIN_SAMPLES = 8;
const FREQUENT_HEADWAY_S = 720;
const WINDOW = { from: "2026-09-21", to: "2026-10-18", days: 28 };
const DAY_COUNT = { wkd: 20, sat: 4, sun: 4 };

// ---------------------------------------------------------------------------
// Deterministic randomness
// ---------------------------------------------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(20261019);
const normal = () => {
  const u = 1 - rand();
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};
const round1 = (x) => Math.round(x * 10) / 10;

// ---------------------------------------------------------------------------
// Stats helpers (mirror the rollup definitions in docs/03 §5)
// ---------------------------------------------------------------------------
function quantile(sorted, q) {
  if (sorted.length === 0) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return Math.round(sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo));
}
function histogram(samples) {
  const hist = new Array(EDGES.length + 1).fill(0);
  for (const d of samples) {
    let i = 0;
    while (i < EDGES.length && d >= EDGES[i]) i++;
    hist[i]++;
  }
  return hist;
}
function stats(samples) {
  const n = samples.length;
  if (n < MIN_SAMPLES) return { n, on_time_pct: null, p50_s: null, p90_s: null };
  const sorted = [...samples].sort((a, b) => a - b);
  const onTime = samples.filter((d) => d >= ON_TIME[0] && d <= ON_TIME[1]).length;
  return {
    n,
    on_time_pct: round1((100 * onTime) / n),
    p50_s: quantile(sorted, 0.5),
    p90_s: quantile(sorted, 0.9),
  };
}

// ---------------------------------------------------------------------------
// Service patterns: trips per hour by day type
// ---------------------------------------------------------------------------
const BUS_TRIPS = {
  wkd: {
    5: 2,
    6: 4,
    7: 7,
    8: 7,
    9: 7,
    10: 5,
    11: 5,
    12: 5,
    13: 5,
    14: 5,
    15: 5,
    16: 7,
    17: 7,
    18: 7,
    19: 5,
    20: 3,
    21: 3,
    22: 3,
    23: 2,
    0: 1,
  },
  sat: {
    6: 2,
    7: 3,
    8: 3,
    9: 3,
    10: 4,
    11: 4,
    12: 4,
    13: 4,
    14: 4,
    15: 4,
    16: 4,
    17: 4,
    18: 4,
    19: 3,
    20: 3,
    21: 3,
    22: 2,
    23: 2,
    0: 1,
  },
  sun: {
    7: 1,
    8: 2,
    9: 2,
    10: 3,
    11: 3,
    12: 3,
    13: 3,
    14: 3,
    15: 3,
    16: 3,
    17: 3,
    18: 3,
    19: 2,
    20: 2,
    21: 2,
    22: 1,
    23: 1,
  },
};
const RAIL_TRIPS = {
  wkd: {
    5: 4,
    6: 8,
    7: 10,
    8: 10,
    9: 10,
    10: 7,
    11: 7,
    12: 7,
    13: 7,
    14: 7,
    15: 7,
    16: 10,
    17: 10,
    18: 10,
    19: 7,
    20: 7,
    21: 5,
    22: 5,
    23: 5,
    0: 3,
  },
  sat: {
    5: 3,
    6: 5,
    7: 5,
    8: 5,
    9: 7,
    10: 7,
    11: 7,
    12: 7,
    13: 7,
    14: 7,
    15: 7,
    16: 7,
    17: 7,
    18: 7,
    19: 7,
    20: 7,
    21: 5,
    22: 5,
    23: 5,
    0: 3,
  },
  sun: {
    6: 3,
    7: 5,
    8: 5,
    9: 5,
    10: 6,
    11: 6,
    12: 6,
    13: 6,
    14: 6,
    15: 6,
    16: 6,
    17: 6,
    18: 6,
    19: 6,
    20: 6,
    21: 4,
    22: 4,
    23: 4,
    0: 2,
  },
};

const PEAK = new Set([7, 8, 9, 16, 17, 18]);
const SHOULDER = new Set([6, 10, 15, 19]);

function delayModel(kind, day, hour, stopIdx) {
  const peak = day === "wkd" && PEAK.has(hour);
  const shoulder = day === "wkd" && SHOULDER.has(hour);
  if (kind === "bus") {
    const mean = 30 + 28 * stopIdx + (peak ? 110 : shoulder ? 45 : 0) - (day === "wkd" ? 0 : 25);
    const sd = 80 + 14 * stopIdx + (peak ? 70 : 0);
    return {
      mean,
      sd,
      tailP: peak ? 0.12 : 0.06,
      tailMean: 360,
      cancelRate: 0.015,
      skipRate: 0.006,
    };
  }
  const mean = 15 + 6 * stopIdx + (peak ? 40 : 0);
  return {
    mean,
    sd: 55 + (peak ? 25 : 0),
    tailP: 0.04,
    tailMean: 240,
    cancelRate: 0.006,
    skipRate: 0.001,
  };
}

function simulateCell(kind, day, hour, tripsPerHour, stopIdx) {
  const scheduled = tripsPerHour * DAY_COUNT[day];
  const m = delayModel(kind, day, hour, stopIdx);
  const canceled = Math.round(scheduled * m.cancelRate * (0.5 + rand()));
  const coverage = 0.93 + rand() * 0.05;
  const n = Math.max(0, Math.round((scheduled - canceled) * coverage));
  const samples = [];
  for (let i = 0; i < n; i++) {
    let d = m.mean + m.sd * normal();
    if (rand() < m.tailP) d += -Math.log(1 - rand()) * m.tailMean;
    samples.push(Math.round(d));
  }
  const s = stats(samples);
  const headway = Math.round(3600 / tripsPerHour);
  const enough = n >= MIN_SAMPLES;
  const early = samples.filter((d) => d < ON_TIME[0]).length;
  const cell = {
    day,
    hour,
    n,
    p50_s: s.p50_s,
    p90_s: s.p90_s,
    on_time_pct: s.on_time_pct,
    early_pct: enough ? round1((100 * early) / n) : null,
    canceled,
    skipped: Math.round(scheduled * m.skipRate * rand() * 2),
    sched_headway_s: headway,
    ewt_s: enough && headway <= FREQUENT_HEADWAY_S ? Math.round(m.sd * 0.55 + rand() * 40) : null,
    hist: histogram(samples),
  };
  return { cell, samples, scheduled };
}

function buildStop(kind, trips, stop, order, stopIdx) {
  const cells = [];
  const all = [];
  let scheduled = 0;
  for (const day of ["wkd", "sat", "sun"]) {
    const hours = Object.keys(trips[day])
      .map(Number)
      .sort((a, b) => a - b);
    for (const hour of hours) {
      const r = simulateCell(kind, day, hour, trips[day][hour], stopIdx);
      cells.push(r.cell);
      all.push(...r.samples);
      scheduled += r.scheduled;
    }
  }
  return {
    stopCells: { stop_id: stop.id, name: stop.name, order, summary: stats(all), cells },
    samples: all,
    scheduled,
  };
}

function buildRoute(route, kind, trips, directions, coveragePct, trendDrift) {
  const allSamples = [];
  let scheduledStopVisits = 0;
  const dirs = directions.map((dir) => ({
    direction_id: dir.direction_id,
    headsign: dir.headsign,
    stops: dir.stops.map((stop, i) => {
      const built = buildStop(kind, trips, stop, i + 1, i);
      allSamples.push(...built.samples);
      scheduledStopVisits += built.scheduled;
      return built.stopCells;
    }),
  }));
  const summary = stats(allSamples);
  const scheduledTrips = Math.round(scheduledStopVisits / directions[0].stops.length);
  const observedTrips = Math.round((scheduledTrips * coveragePct) / 100);

  const weeks = [
    "2026-08-24",
    "2026-08-31",
    "2026-09-07",
    "2026-09-14",
    "2026-09-21",
    "2026-09-28",
    "2026-10-05",
    "2026-10-12",
  ];
  const trend = weeks.map((week_start, i) => {
    const k = weeks.length - 1 - i; // weeks before the latest
    const wobble = normal() * 1.2;
    return {
      week_start,
      n: Math.round((summary.n / 4) * (0.94 + rand() * 0.08)),
      on_time_pct: round1(summary.on_time_pct + trendDrift * k + wobble),
      p50_s: Math.round(summary.p50_s - trendDrift * 4 * k + normal() * 6),
      p90_s: Math.round(summary.p90_s - trendDrift * 12 * k + normal() * 15),
    };
  });

  return {
    detail: {
      agency_id: "mbta",
      route,
      window: WINDOW,
      on_time_definition_s: ON_TIME,
      histogram_edges_s: EDGES,
      min_samples: MIN_SAMPLES,
      directions: dirs,
      trend,
      coverage: {
        observed_trips: observedTrips,
        scheduled_trips: scheduledTrips,
        coverage_pct: round1(coveragePct),
      },
    },
    summary: { ...summary, coverage_pct: round1(coveragePct) },
  };
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------
const BUS_STOPS = {
  64000: { name: "Nubian Station", lat: 42.32941, lon: -71.08395 },
  1: { name: "Washington St @ Melnea Cass Blvd", lat: 42.33184, lon: -71.08118 },
  2: { name: "Massachusetts Ave @ Washington St", lat: 42.33647, lon: -71.07724 },
  6: { name: "Massachusetts Ave @ Tremont St", lat: 42.33945, lon: -71.08113 },
  10: { name: "Massachusetts Ave @ Columbus Ave", lat: 42.34118, lon: -71.08317 },
  64: { name: "Massachusetts Ave @ Newbury St", lat: 42.34862, lon: -71.08771 },
  97: { name: "Massachusetts Ave @ Vassar St (MIT)", lat: 42.35921, lon: -71.09352 },
  102: { name: "Massachusetts Ave @ Prospect St (Central Sq)", lat: 42.36531, lon: -71.10292 },
  110: { name: "Harvard Upper Busway", lat: 42.37331, lon: -71.11892 },
  75: { name: "Massachusetts Ave opp Prospect St (Central Sq)", lat: 42.36502, lon: -71.10268 },
  77: { name: "77 Massachusetts Ave (MIT)", lat: 42.35937, lon: -71.09401 },
  79: { name: "Massachusetts Ave @ Beacon St", lat: 42.35021, lon: -71.08968 },
  80: { name: "Massachusetts Ave @ Boylston St", lat: 42.34763, lon: -71.08741 },
  187: { name: "Massachusetts Ave opp Columbus Ave", lat: 42.34097, lon: -71.08352 },
  188: { name: "Massachusetts Ave opp Tremont St", lat: 42.33928, lon: -71.08142 },
  190: { name: "Massachusetts Ave @ Harrison Ave", lat: 42.33672, lon: -71.07658 },
};
const BUS_DIRS = [
  {
    direction_id: 0,
    headsign: "Harvard Square",
    ids: ["64000", "1", "2", "6", "10", "64", "97", "102", "110"],
  },
  {
    direction_id: 1,
    headsign: "Nubian Station",
    ids: ["110", "75", "77", "79", "80", "187", "188", "190", "64000"],
  },
];
const EXTRA_ROUTES = { 102: ["47"], 75: ["47"], 97: ["CT1"], 77: ["CT1"] };

const STATIONS = [
  ["place-alfcl", "Alewife", 42.39583, -71.14193, "70061", "70061"],
  ["place-davis", "Davis", 42.39674, -71.12188, "70063", "70064"],
  ["place-portr", "Porter", 42.3884, -71.11915, "70065", "70066"],
  ["place-harsq", "Harvard", 42.37336, -71.11895, "70067", "70068"],
  ["place-cntsq", "Central", 42.36549, -71.10361, "70069", "70070"],
  ["place-knncl", "Kendall/MIT", 42.36249, -71.08617, "70071", "70072"],
  ["place-chmnl", "Charles/MGH", 42.36116, -71.07051, "70073", "70074"],
  ["place-pktrm", "Park Street", 42.35639, -71.06242, "70075", "70076"],
  ["place-dwnxg", "Downtown Crossing", 42.35554, -71.06033, "70077", "70078"],
  ["place-sstat", "South Station", 42.35227, -71.05524, "70079", "70080"],
];

const ROUTE_INFO = {
  1: {
    id: "1",
    short_name: "1",
    long_name: "Harvard Square - Nubian Station",
    type: 3,
    color: "FFC72C",
    text_color: "000000",
    sort_order: 50010,
  },
  47: {
    id: "47",
    short_name: "47",
    long_name: "Central Square - Broadway Station",
    type: 3,
    color: "FFC72C",
    text_color: "000000",
    sort_order: 50470,
  },
  CT1: {
    id: "CT1",
    short_name: "CT1",
    long_name: "Central Square - BU Medical Center",
    type: 3,
    color: "FFC72C",
    text_color: "000000",
    sort_order: 50015,
  },
  Red: {
    id: "Red",
    short_name: "",
    long_name: "Red Line",
    type: 1,
    color: "DA291C",
    text_color: "FFFFFF",
    sort_order: 10010,
  },
};

// ---------------------------------------------------------------------------
// Build everything
// ---------------------------------------------------------------------------
const bus = buildRoute(
  ROUTE_INFO[1],
  "bus",
  BUS_TRIPS,
  BUS_DIRS.map((d) => ({ ...d, stops: d.ids.map((id) => ({ id, name: BUS_STOPS[id].name })) })),
  96.2,
  0.6,
);
const red = buildRoute(
  ROUTE_INFO.Red,
  "rail",
  RAIL_TRIPS,
  [
    {
      direction_id: 0,
      headsign: "Ashmont/Braintree",
      stops: STATIONS.map(([, name, , , s]) => ({ id: s, name })),
    },
    {
      direction_id: 1,
      headsign: "Alewife",
      stops: [...STATIONS].reverse().map(([, name, , , , n]) => ({ id: n, name })),
    },
  ],
  97.8,
  -0.3,
);

const stops = [];
for (const [id, s] of Object.entries(BUS_STOPS)) {
  stops.push({
    id,
    name: s.name,
    lat: s.lat,
    lon: s.lon,
    parent: null,
    routes: ["1", ...(EXTRA_ROUTES[id] ?? [])],
  });
}
for (const [parent, name, lat, lon, south, north] of STATIONS) {
  for (const id of new Set([south, north])) {
    const offset = id === north && south !== north ? 0.00008 : 0;
    stops.push({
      id,
      name,
      lat: round6(lat + offset),
      lon: round6(lon - offset),
      parent,
      routes: ["Red"],
    });
  }
}
function round6(x) {
  return Math.round(x * 1e6) / 1e6;
}

const routes = {
  agency_id: "mbta",
  routes: [
    { ...ROUTE_INFO.Red, summary: red.summary },
    { ...ROUTE_INFO[1], summary: bus.summary },
    {
      ...ROUTE_INFO.CT1,
      summary: { n: 2210, on_time_pct: 58.3, p50_s: 194, p90_s: 612, coverage_pct: 74.5 },
    },
    {
      ...ROUTE_INFO[47],
      summary: { n: 18342, on_time_pct: 64.0, p50_s: 155, p90_s: 520, coverage_pct: 94.1 },
    },
  ],
};

const coverageDays = [];
const start = Date.UTC(2026, 8, 19);
for (let i = 0; i < 30; i++) {
  const date = new Date(start + i * 86400000);
  const dow = date.getUTCDay();
  const scheduled = dow === 0 ? 8120 : dow === 6 ? 9810 : 12940;
  const iso = date.toISOString().slice(0, 10);
  const pct = iso === "2026-10-03" ? 76.4 : iso === "2026-10-16" ? 91.2 : 95 + rand() * 3.4;
  const canceled = Math.round(scheduled * (0.003 + rand() * 0.004));
  coverageDays.push({
    service_date: iso,
    scheduled_trips: scheduled,
    observed_trips: Math.round((scheduled * pct) / 100),
    canceled_trips: canceled,
    coverage_pct: round1(pct),
  });
}

const base = `/data/v1/builds/${BUILD_ID}/mbta`;
const files = {
  "manifest.json": {
    schema_version: 1,
    build_id: BUILD_ID,
    generated_at: "2026-10-19T08:15:02Z",
    agencies: [
      {
        id: "mbta",
        name: "MBTA",
        timezone: "America/New_York",
        live_api: "mbta-v3",
        window: WINDOW,
        on_time_definition_s: ON_TIME,
        histogram_edges_s: EDGES,
        min_samples: MIN_SAMPLES,
        paths: {
          stops: `${base}/stops.json`,
          routes: `${base}/routes.json`,
          route_template: `${base}/routes/{route_id}.json`,
          coverage: `${base}/coverage.json`,
          health: "/data/v1/health/mbta.json",
          validation: "/data/v1/validation/mbta.json",
        },
      },
    ],
  },
  "mbta-stops.json": { agency_id: "mbta", stops },
  "mbta-routes.json": routes,
  "mbta-route-1.json": bus.detail,
  "mbta-route-Red.json": red.detail,
  "mbta-coverage.json": { agency_id: "mbta", days: coverageDays },
  "mbta-health.json": {
    agency_id: "mbta",
    generated_at: "2026-10-19T12:00:05Z",
    status: "ok",
    last_success_at: "2026-10-19T12:00:02Z",
    feed_timestamp: "2026-10-19T11:59:51Z",
    feed_age_s: 14,
    ticks_last_hour: { ok: 59, failed: 0, not_advanced: 1, expected: 60 },
    recent_gaps: [
      { start: "2026-10-16T06:11:00Z", end: "2026-10-16T06:19:00Z", minutes: 8 },
      { start: "2026-10-13T18:02:00Z", end: "2026-10-13T18:05:00Z", minutes: 3 },
    ],
  },
  "mbta-validation.json": {
    agency_id: "mbta",
    generated_at: "2026-10-19T10:04:11Z",
    week: "2026-10-12",
    sample: 18234,
    median_abs_error_s: 31,
    p90_abs_error_s: 98,
    by_route: {
      Red: { n: 9120, median_abs_error_s: 29 },
      Orange: { n: 5402, median_abs_error_s: 33 },
      Blue: { n: 3712, median_abs_error_s: 34 },
    },
  },
};

// Compact, diff-friendly JSON: flat objects (cells, stops) stay on one line.
function fmt(value, indent = "") {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  const next = indent + "  ";
  if (Array.isArray(value)) {
    if (value.every((v) => v === null || typeof v !== "object"))
      return `[${value.map((v) => JSON.stringify(v)).join(", ")}]`;
    return `[\n${value.map((v) => next + fmt(v, next)).join(",\n")}\n${indent}]`;
  }
  const entries = Object.entries(value);
  const flat = entries.every(
    ([, v]) =>
      v === null ||
      typeof v !== "object" ||
      (Array.isArray(v) && v.every((x) => typeof x !== "object")),
  );
  const inline = `{${entries.map(([k, v]) => `"${k}": ${fmt(v)}`).join(", ")}}`;
  if (flat && inline.length <= 220) return inline;
  return `{\n${entries.map(([k, v]) => `${next}"${k}": ${fmt(v, next)}`).join(",\n")}\n${indent}}`;
}

mkdirSync(OUT, { recursive: true });
for (const [name, data] of Object.entries(files)) {
  writeFileSync(join(OUT, name), fmt(data) + "\n");
}
console.log(`Wrote ${Object.keys(files).length} fixtures to ${OUT} (${stops.length} stops)`);
