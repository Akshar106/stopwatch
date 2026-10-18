# ADR-009: Publish analytics as immutable static JSON builds behind an atomically swapped manifest

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §6.3, §8.1](../04-architecture.md#63-analytics-schemas-parquet), [contracts §2–3](../contracts.md#3-published-data-typescript-notation-all-times-iso-8601-utc-unless-noted), [api.md](../api.md), [RB-3](../runbooks/RB-3-rollup-failed.md), [ADR-002](0002-observations-in-s3-parquet-duckdb.md)

## Context

The rider-facing pages (stop search, route and stop heatmaps, trends, coverage, data health) are read-heavy, identical for every visitor, and only change when a new service day has been processed. The underlying data is daily Parquet in S3 ([ADR-002](0002-observations-in-s3-parquet-duckdb.md)). People may cite the numbers, so a bad rollup must never replace good data silently, and a bad publish must be reversible in minutes.

Performance targets: public page TTFB p95 < 200 ms from the CDN and mobile LCP < 2.5 s ([05 §11](../05-security-reliability.md#11-performance-goals-measurable)). Budget: no per-request compute for public pages.

## Decision

- `daily-rollup` (04:15 ET, for service date D−1) writes a complete **build** to the site bucket under `data/v1/builds/{build_id}/{agency}/…`: `stops.json`, `routes.json`, `routes/{route_id}.json`, `coverage.json` ([contracts §2–3](../contracts.md#2-blob-key-layout)).
- Build files are **immutable** (`Cache-Control: max-age=31536000, immutable`). A build is never edited after upload.
- A **data-quality gate** checks the build before publishing: coverage ≥ 80%, row-count delta within ±40% of the 7-day median, null rates, delay sanity (−30 … +120 min). The report goes to `reports/quality/agency={agency}/service_date={date}.json` in the lake.
- Only if the gate passes is **`data/v1/manifest.json`** (max-age 60 s) overwritten to point at the new `build_id`. This single small write is the publish. On failure the previous build stays live and `RollupLowCoverage`/`RollupLate` alert.
- **Rollback** is a manifest swap back to an earlier build: `make publish-rollback BUILD=<build_id> ENV=prod`, effective within the 60-second manifest cache. The last 14 builds are retained.
- The browser reads the manifest, then the build. Personal commute summaries are computed **in the browser** from the public route file, so the API never reads analytics data.
- "Right now" information does not come from builds: the live panel calls the MBTA v3 API directly from the browser, and `data/v1/health/{agency}.json` is rewritten every 5 minutes by `ingest-tick`.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Query API per request** (Lambda + DuckDB over Parquet) | Cold starts of a DuckDB-sized package on every popular page, per-request compute cost, and an availability dependency for pages that change once a day. |
| **Serve metrics from Postgres** | Keeps Neon awake for public traffic and puts every visitor on the database's free-tier compute. |
| **Overwrite files in place** (`data/v1/mbta/routes/1.json`) | Visitors could see a mix of old and new files mid-upload; CDN invalidation costs and delays; no clean rollback. |
| **CloudFront invalidation per publish** | Works but is slower and less precise than an immutable path plus a 60-second manifest. |
| **Intraday rebuilds** (hourly) | 24× the rollup work and S3 writes for little rider value; the live panel already covers "now". |

## Consequences

**Positive**

- Public pages are CDN-cached files: fast, cheap and still available when the API or Neon is down.
- Publishing is atomic from the reader's point of view, and rollback is one command.
- Immutable builds are easy to diff, audit and reproduce; the `build_id` doubles as a cache key (for example for Ask responses).
- A failed or suspicious rollup has no user impact beyond data being a day older.

**Negative**

- **Data is up to ~24 h old** (D−1, published by 06:00 ET). Intraday stats ("today so far") are not available.
- Readers must handle the manifest indirection and a window of up to 60 s where different clients see different builds.
- Storage grows with retained builds (~15 MB each, 14 kept) and old builds must be pruned.
- Schema changes to published files need versioning discipline: additive changes within `/data/v1`, breaking changes in `/data/v2`.

## Revisit when

- Users need intraday statistics, or the advocate audience needs ad-hoc queries the static files cannot answer (consider a cached query API or downloadable Parquet).
- Build size or route count grows enough that publishing a full build daily becomes slow (> 5 minutes) or costly; switch to incremental builds that reuse unchanged files.
