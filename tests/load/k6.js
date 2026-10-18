// Weekly load test against staging (docs/05 §11, docs/06 §1), run by .github/workflows/weekly.yml.
//
//   k6 run --env BASE_URL=https://dxxxx.cloudfront.net tests/load/k6.js
//
// Two open-model scenarios at 20 requests/second each, for 2 minutes:
//   api   GET /api/v1/healthz and /api/v1/config through CloudFront -> API Gateway -> Lambda.
//         No database work, so this measures the edge + API path. 20 rps is the stage throttle,
//         so it also confirms legitimate traffic at the limit is not rejected.
//   data  GET /data/v1/manifest.json from the CDN (60 s cache): the path every page load takes.
//
// Thresholds (the test fails if any is crossed):
//   API  p95 < 300 ms (warm SLO, docs/05 §10.1)
//   data p95 < 200 ms (cached TTFB goal, docs/05 §11)
//   < 1% failed requests, > 99% of checks passing.
//
// REQUIRE_MANIFEST=0 accepts 404 for the manifest (staging with ingest off has nothing published).
import http from "k6/http";
import { check } from "k6";

const BASE_URL = (__ENV.BASE_URL || "").replace(/\/$/, "");
const REQUIRE_MANIFEST = (__ENV.REQUIRE_MANIFEST || "1") === "1";
const RATE = Number(__ENV.RATE || 20);
const DURATION = __ENV.DURATION || "2m";

if (!BASE_URL) {
  throw new Error("Set BASE_URL, e.g. --env BASE_URL=https://dxxxx.cloudfront.net");
}

export const options = {
  scenarios: {
    api: {
      executor: "constant-arrival-rate",
      exec: "api",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
    data: {
      executor: "constant-arrival-rate",
      exec: "data",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 10,
      maxVUs: 40,
    },
  },
  thresholds: {
    "http_req_duration{endpoint:api}": ["p(95)<300"],
    "http_req_duration{endpoint:data}": ["p(95)<200"],
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
  },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
};

const apiPaths = ["/api/v1/healthz", "/api/v1/config"];
const browserHeaders = { "X-Requested-With": "stopwatch", Accept: "application/json" };

export function api() {
  const path = apiPaths[__ITER % apiPaths.length];
  const res = http.get(`${BASE_URL}${path}`, {
    headers: browserHeaders,
    tags: { endpoint: "api", name: path },
  });
  check(res, {
    "api: status 200": (r) => r.status === 200,
    "api: JSON body": (r) => (r.headers["Content-Type"] || "").includes("json"),
  });
}

const manifestStatuses = REQUIRE_MANIFEST ? [200] : [200, 404];

export function data() {
  const res = http.get(`${BASE_URL}/data/v1/manifest.json`, {
    tags: { endpoint: "data", name: "/data/v1/manifest.json" },
    responseCallback: http.expectedStatuses(...manifestStatuses),
  });
  check(res, {
    "data: expected status": (r) => manifestStatuses.includes(r.status),
  });
}
