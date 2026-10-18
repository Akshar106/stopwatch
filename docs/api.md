# API and data reference

*Last updated 2026-10-18. Normative source: [contracts.md](contracts.md) §2–4. If this page and `contracts.md` disagree, `contracts.md` wins; please open an issue.*

Stopwatch has two interfaces:

1. **Published data** (`/data/v1/…`): static JSON files rebuilt once a day and served from the CDN. No key, no account. This is the interface for developers, researchers and journalists.
2. **Dynamic API** (`/api/v1/…`): sign-in, saved commutes, account export and deletion. It exists for the Stopwatch web app (same origin, cookie sessions) and is documented here for transparency and contributors; it is not a general-purpose public API.

All times are ISO-8601 in UTC unless noted. Service dates (`YYYY-MM-DD`) and clock hours are in the agency's local time zone (`America/New_York` for MBTA). How the numbers are computed is explained in the [methodology](methodology.md).

## 1. Published data

### How to read it

1. Fetch **`/data/v1/manifest.json`** (cached 60 s). It names the current `build_id` and the paths of every file in that build.
2. Fetch the files listed under `paths`. Build files are **immutable**: a given URL never changes content and is cached for a year. A new day means a new `build_id`.
3. Never hard-code a `build_id`. Old builds are deleted after 14 days.

| Path | Cache | Content |
|---|---|---|
| `/data/v1/manifest.json` | 60 s | Current build, per-agency settings and paths |
| `/data/v1/health/{agency}.json` | 60 s (rewritten every 5 min) | Ingestion freshness and recent gaps |
| `/data/v1/builds/{build_id}/{agency}/stops.json` | 1 year, immutable | Every in-scope stop, with the routes serving it |
| `/data/v1/builds/{build_id}/{agency}/routes.json` | 1 year, immutable | Every in-scope route with headline numbers |
| `/data/v1/builds/{build_id}/{agency}/routes/{route_id}.json` | 1 year, immutable | Per stop × day type × hour statistics for one route |
| `/data/v1/builds/{build_id}/{agency}/coverage.json` | 1 year, immutable | Scheduled vs observed trips per service day |
| `/data/v1/validation/{agency}.json` | 1 hour | Inference accuracy vs MBTA LAMP (subway); `null` path until the first report |

`{route_id}` is URL-encoded with `encodeURIComponent` (MBTA ids such as `Green-B` or `34E` need no escaping, but don't rely on that).

**Stability.** Files carry `schema_version: 1` in the manifest. Within `/data/v1`, fields may be **added** but not removed or changed in meaning. A breaking change gets a new prefix (`/data/v2`) and both are published in parallel for a transition period announced in the [changelog](../CHANGELOG.md).

**Terms.** The underlying feed data comes from the MBTA under the [MBTA Developers License Agreement](https://www.mbta.com/developers). Stopwatch figures are independent, unofficial estimates. If you republish them, say so and link to the methodology. Please cache files rather than polling: they change once a day.

**Shared types**

```ts
type DayType = "wkd" | "sat" | "sun";            // day type of the service that ran (holiday schedules follow their type)

interface Stats {
  n: number;                    // observed arrivals
  on_time_pct: number | null;   // share with -60 s <= delay <= +300 s (see on_time_definition_s)
  p50_s: number | null;         // median delay, seconds (negative = early)
  p90_s: number | null;         // 90th-percentile delay, seconds
}
```

Statistics are `null` when `n < min_samples` (8 by default).

### Manifest

`GET /data/v1/manifest.json`

```json
{
  "schema_version": 1,
  "build_id": "20261019T081502Z",
  "generated_at": "2026-10-19T08:15:02Z",
  "agencies": [{
    "id": "mbta",
    "name": "MBTA",
    "timezone": "America/New_York",
    "live_api": "mbta-v3",
    "window": {"from": "2026-09-21", "to": "2026-10-18", "days": 28},
    "on_time_definition_s": [-60, 300],
    "histogram_edges_s": [-60, 60, 180, 300, 600, 1200],
    "min_samples": 8,
    "paths": {
      "stops": "/data/v1/builds/20261019T081502Z/mbta/stops.json",
      "routes": "/data/v1/builds/20261019T081502Z/mbta/routes.json",
      "route_template": "/data/v1/builds/20261019T081502Z/mbta/routes/{route_id}.json",
      "coverage": "/data/v1/builds/20261019T081502Z/mbta/coverage.json",
      "health": "/data/v1/health/mbta.json",
      "validation": null
    }
  }]
}
```

- `live_api: "mbta-v3"` means a browser may call `https://api-v3.mbta.com` directly for live predictions (that is what the Stopwatch "right now" panel does).
- `histogram_edges_s` has 6 edges, so every `hist` array has 7 buckets: `< -60`, `-60…60`, `60…180`, `180…300`, `300…600`, `600…1200`, `≥ 1200` seconds.

### Stops

`GET {paths.stops}` — powers client-side search and "near me" (about 8,000 stops).

```json
{
  "agency_id": "mbta",
  "stops": [
    {"id": "64", "name": "Massachusetts Ave @ Newbury St", "lat": 42.348777, "lon": -71.087691,
     "parent": null, "routes": ["1"]},
    {"id": "70075", "name": "Park Street", "lat": 42.35639, "lon": -71.0624,
     "parent": "place-pktrm", "routes": ["Red"]}
  ]
}
```

`routes` lists only in-scope route types (bus, subway, light rail). Coordinates in this example are illustrative.

### Routes

`GET {paths.routes}`

```json
{
  "agency_id": "mbta",
  "routes": [
    {"id": "1", "short_name": "1", "long_name": "Harvard Square - Nubian Station", "type": 3,
     "color": "FFC72C", "text_color": "000000", "sort_order": 50010,
     "summary": {"n": 7811, "on_time_pct": 63.4, "p50_s": 190, "p90_s": 610, "coverage_pct": 97.2}}
  ]
}
```

`type` is the GTFS `route_type` (0 light rail, 1 subway, 3 bus). Numbers in examples are illustrative, not measurements.

### Route detail

`GET {paths.route_template}` with `{route_id}` substituted.

```json
{
  "agency_id": "mbta",
  "route": {"id": "1", "short_name": "1", "long_name": "Harvard Square - Nubian Station", "type": 3,
            "color": "FFC72C", "text_color": "000000", "sort_order": 50010},
  "window": {"from": "2026-09-21", "to": "2026-10-18", "days": 28},
  "on_time_definition_s": [-60, 300],
  "histogram_edges_s": [-60, 60, 180, 300, 600, 1200],
  "min_samples": 8,
  "directions": [{
    "direction_id": 0,
    "headsign": "Harvard",
    "stops": [{
      "stop_id": "64", "name": "Massachusetts Ave @ Newbury St", "order": 12,
      "summary": {"n": 512, "on_time_pct": 61.2, "p50_s": 210, "p90_s": 640},
      "cells": [
        {"day": "wkd", "hour": 8, "n": 74, "p50_s": 210, "p90_s": 640,
         "on_time_pct": 61.2, "early_pct": 4.1, "canceled": 2, "skipped": 0,
         "sched_headway_s": 600, "ewt_s": 95, "hist": [3, 18, 22, 9, 12, 7, 3]},
        {"day": "sun", "hour": 6, "n": 5, "p50_s": null, "p90_s": null,
         "on_time_pct": null, "early_pct": null, "canceled": 0, "skipped": 0,
         "sched_headway_s": 1800, "ewt_s": null, "hist": [0, 2, 2, 1, 0, 0, 0]}
      ]
    }]
  }],
  "trend": [
    {"week_start": "2026-09-21", "n": 1890, "on_time_pct": 63.0, "p50_s": 200, "p90_s": 610}
  ],
  "coverage": {"observed_trips": 7811, "scheduled_trips": 8034, "coverage_pct": 97.2}
}
```

Field notes:

- `cells` contains only (day, hour) combinations with scheduled service. `hour` is the local clock hour (0–23) of the **scheduled** arrival; a `25:10:00` trip on Friday's schedule is `day: "wkd", hour: 1`.
- `canceled` and `skipped` count trips that were canceled, or that skipped this stop; they are never part of `n` or the on-time share.
- `sched_headway_s` is the median scheduled gap between trips at this stop and hour. `ewt_s` (excess wait time) is present only when that headway is ≤ 720 s (12 minutes).
- `trend` is weekly, route-level, oldest first, up to 8 weeks.

### Coverage

`GET {paths.coverage}`

```json
{"agency_id": "mbta", "days": [
  {"service_date": "2026-10-17", "scheduled_trips": 10432, "observed_trips": 10012,
   "canceled_trips": 41, "coverage_pct": 96.0}
]}
```

### Health

`GET /data/v1/health/{agency}.json` — rewritten by the ingest job every 5 minutes.

```json
{
  "agency_id": "mbta",
  "generated_at": "2026-10-18T20:40:05Z",
  "status": "ok",
  "last_success_at": "2026-10-18T20:40:03Z",
  "feed_timestamp": "2026-10-18T20:40:01Z",
  "feed_age_s": 4,
  "ticks_last_hour": {"ok": 59, "failed": 0, "not_advanced": 1, "expected": 60},
  "recent_gaps": [{"start": "2026-10-16T09:12:00Z", "end": "2026-10-16T09:19:00Z", "minutes": 7}]
}
```

| `status` | Rule |
|---|---|
| `stale` | Last successful ingest more than 15 minutes ago |
| `degraded` | Feed age over 300 s, or any failed ticks in the last 10 minutes |
| `ok` | Otherwise |
| `unknown` | No data yet |

`recent_gaps` lists gaps of 3 minutes or more in the last 7 days.

### Validation

`GET /data/v1/validation/{agency}.json` — weekly comparison of subway estimates with MBTA LAMP.

The `lamp-validate` job (Mondays 06:00 ET) downloads LAMP's daily subway file, `https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/{date}-subway-on-time-performance-v1.parquet`, for each day of the week. Trip IDs differ between LAMP and the real-time feed for many subway trips, so each of our arrivals is matched to LAMP on **(`vehicle_id`, `stop_id`) with the nearest LAMP arrival timestamp within 15 minutes**; unmatched estimates are left out of the sample.

```json
{"agency_id": "mbta", "generated_at": "<ISO time>", "week": "<YYYY-MM-DD, week start>", "days": "<days with both files>",
 "sample": "<matched arrivals>",
 "median_abs_error_s": "<seconds or null>", "p90_abs_error_s": "<seconds or null>",
 "by_route": {"Red": {"n": "<matched arrivals>", "median_abs_error_s": "<seconds>"}},
 "by_method": {"last_prediction": {"n": "<matched arrivals>", "median_abs_error_s": "<seconds>"},
               "vp_stopped": {"n": "<matched arrivals>", "median_abs_error_s": "<seconds>"}}}
```

*(Shape only, with placeholders instead of numbers: no validation report has been produced yet. Numeric fields are numbers in the real file.)*

## 2. Dynamic API (`/api/v1`)

Served on the same origin as the web app (CloudFront → API Gateway → Lambda). The machine-readable **OpenAPI spec is served by the API at `/api/v1/openapi.json` in non-production environments** (local: `http://localhost:8000/api/v1/openapi.json`); CI diffs it against `main` and requires the `api-breaking` label for breaking changes.

### Conventions

| Header / rule | Direction | Notes |
|---|---|---|
| `Content-Type: application/json` | both | JSON bodies only |
| `X-Requested-With: stopwatch` | request | Sent by the web app on **every** API request. State-changing requests without it are rejected with `403`; it forces a CORS preflight for cross-site attackers |
| `X-CSRF-Token: <token>` | request | Required on every state-changing request while signed in. The token comes from `GET /me` or the login/demo response (`csrf_token`) |
| `Idempotency-Key: <8–64 chars>` | request | Optional on `POST /commutes`. A retry with the same key and body returns the original response instead of creating a duplicate |
| `X-Request-Id` | response | Echoed on every response; quote it when reporting a problem |
| `X-Origin-Verify` | added by CloudFront | Staging and prod only. CloudFront adds a shared secret to every `/api/*` origin request and the API rejects requests without it (`403`, problem type `origin`: "Requests must come through the site."). Calling the API Gateway URL directly therefore does not work; use the site's own origin |
| Client IP | — | Taken only from `CloudFront-Viewer-Address`, which CloudFront sets from the TCP connection. `X-Forwarded-For` is ignored, because clients can forge it. Per-IP limits use the /24 (IPv4) or /48 (IPv6) prefix |

**Session cookie:** `__Host-sw_session` (Secure; HttpOnly; SameSite=Lax; Path=/) in staging and prod, `sw_session` without `Secure` locally. **OIDC transaction cookie:** `sw_oidc`, HMAC-signed (state, nonce, PKCE verifier, `next`), 10-minute TTL, `Path=/api/v1/auth`. There is no CORS configuration; cross-origin browser calls are not supported.

### Errors

Errors use RFC 9457 `application/problem+json`:

```json
{"type": "about:blank", "title": "Unprocessable Entity", "status": 422,
 "detail": "Request validation failed",
 "errors": [{"field": "window_end", "message": "must be after window_start"}]}
```

`errors` appears only on `422`. Other common statuses: `401` not signed in; `403` missing `X-Requested-With` or CSRF token; `404` not found **or not yours** (the API never confirms that another user's object exists); `409` commute limit reached (20, or 3 for demo accounts); `429` rate limit; `503` feature disabled.

### Endpoints

| Method & path | Auth | Request | Success | Rate limit |
|---|---|---|---|---|
| `GET /healthz` | — | — | `200 {"status":"ok","version":"…"}` | gateway only |
| `GET /config` | — | — | `200 {"features":{"alerts","ask","google_login","demo"},"vapid_public_key"}` | gateway only |
| `GET /auth/login?next=/path` | — | `next` must be a same-site relative path | `302` → Google | 10/min/IP |
| `GET /auth/callback` | — | Google redirect | `302` → `next` (or `/signin?error=<code>`) + session cookie | 10/min/IP |
| `POST /auth/demo` | — (needs `X-Requested-With`) | — | `201 MeResponse` + session cookie; `404` if demo disabled | 3/hour/IP, 500 active |
| `POST /auth/logout` | session | — | `204`, cookie cleared | — |
| `POST /auth/logout-all` | session | — | `204`, all your sessions deleted | — |
| `GET /me` | session | — | `200 MeResponse` | 60/min/user |
| `GET /me/export` | session | — | `200` export JSON (below) | 5/day/user |
| `DELETE /me` | session | — | `204`; everything deleted, pseudonymous audit record kept | 3/day/user |
| `GET /commutes` | session | — | `200 {"commutes": Commute[]}` | 60/min/user |
| `POST /commutes` | session | `CommuteInput` + optional `Idempotency-Key` | `201 Commute` | 30/min/user |
| `PATCH /commutes/{id}` | owner | any subset of `CommuteInput` | `200 Commute` | 30/min/user |
| `DELETE /commutes/{id}` | owner | — | `204` | 30/min/user |
| `PUT /commutes/{id}/alert` *(should)* | owner, non-demo | `{"threshold_min": 3-60, "notify_cancellations": bool}` | `200 AlertRule` | 10/min/user |
| `DELETE /commutes/{id}/alert` *(should)* | owner | — | `204` | 10/min/user |
| `POST /push-subscriptions` *(should)* | session, non-demo | browser `PushSubscription` JSON `{endpoint, keys:{p256dh, auth}}` | `201 {"id"}` | 10/min/user |
| `DELETE /push-subscriptions/{id}` *(should)* | owner | — | `204` | 10/min/user |
| `POST /ask` *(should)* | session, non-demo | `{"question": "≤ 300 chars"}` | `200 AskResponse` | 20/day/user + hard $1/month global cap |

Paths are relative to `/api/v1`. Rate limits are enforced per user or per IP prefix in the application ([04 §8.2](04-architecture.md#8-interfaces)); API Gateway additionally throttles the whole stage at 20 requests/s (burst 40) and `/auth/*` at 5 requests/s.

### Shapes

```ts
interface User { id: string; display_name: string | null; email: string | null; is_demo: boolean;
                 demo_expires_at: string | null; created_at: string }
interface MeResponse { user: User; csrf_token: string;
                       features: { alerts: boolean; ask: boolean; google_login: boolean } }

type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
interface CommuteInput {
  agency_id: string; route_id: string; direction_id: 0 | 1; stop_id: string;
  label?: string | null;              // ≤ 60 chars
  days: Weekday[];                    // at least one
  window_start: string; window_end: string;   // "HH:MM", local agency time, end > start
}
interface Commute extends CommuteInput {
  id: string; label: string | null; created_at: string; updated_at: string;
  alert: AlertRule | null;
}
interface AlertRule { threshold_min: number; notify_cancellations: boolean; active: boolean }
interface AskResponse {
  answer: string | null; fallback: boolean;
  reason: "disabled" | "cap_reached" | "ungrounded" | "error" | null;
  facts: { label: string; value: string; source: string }[];
  links: { label: string; href: string }[];
}
```

`POST /commutes` validates that the route serves that stop in that direction; otherwise `422`.

**Ask Stopwatch** *(should)* answers only from published data, through a fixed set of read-only tools ([05 §6](05-security-reliability.md#6-the-ask-feature-should-llm-specific-controls)). It calls Anthropic's Claude API; the model defaults to `claude-opus-5-5` and is configurable with `ASK_MODEL`. Spending is capped at **$1 per month** across all users (tracked in `ask_usage`); at the cap, or when the answer cannot be grounded in tool results, the response has `answer: null`, `fallback: true` and a `reason`, and the app shows a guided form instead.

### Example: save a commute

```http
POST /api/v1/commutes HTTP/1.1
Content-Type: application/json
X-Requested-With: stopwatch
X-CSRF-Token: 3q2-7w…
Idempotency-Key: 6f1c0e9a-commute-1
Cookie: __Host-sw_session=…

{"agency_id": "mbta", "route_id": "1", "direction_id": 0, "stop_id": "64",
 "label": "Morning", "days": ["mon","tue","wed","thu","fri"],
 "window_start": "07:45", "window_end": "08:30"}
```

```http
HTTP/1.1 201 Created
Content-Type: application/json
X-Request-Id: 1c9e…

{"id": "0b7c4d1e-…", "agency_id": "mbta", "route_id": "1", "direction_id": 0, "stop_id": "64",
 "label": "Morning", "days": ["mon","tue","wed","thu","fri"],
 "window_start": "07:45", "window_end": "08:30",
 "created_at": "2026-10-18T20:41:00Z", "updated_at": "2026-10-18T20:41:00Z", "alert": null}
```

### Export format

`GET /me/export` returns everything stored about the signed-in user:

```json
{"exported_at": "…", "user": {"id": "…", "email": "…", "display_name": "…", "is_demo": false,
  "demo_expires_at": null, "created_at": "…"},
 "commutes": [],
 "sessions": [{"created_at": "…", "last_seen_at": "…", "user_agent": "…"}],
 "push_subscriptions": [{"id": "…", "created_at": "…"}],
 "audit": [{"at": "…", "action": "auth.login", "outcome": "success"}]}
```

See the [privacy policy](privacy.md) for what each item is and how long it is kept.
