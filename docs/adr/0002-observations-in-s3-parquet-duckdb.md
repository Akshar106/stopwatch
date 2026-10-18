# ADR-002: Observations in S3 (JSON lines → Parquet) analysed with DuckDB; OLTP data in Postgres

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §6](../04-architecture.md#6-data-architecture), [contracts §2](../contracts.md#2-blob-key-layout), [ADR-004](0004-neon-free-postgres-over-rds.md), [ADR-009](0009-static-json-with-atomic-manifest-swap.md)

## Context

Stopwatch stores two very different kinds of data.

**Observations** come from the MBTA feed every minute. One TripUpdates snapshot decoded on 2026-10-18 held 1,357 trip updates and 23,149 stop-level predictions, and roughly 300–350 predicted stops dropped out of the feed per minute on that Sunday afternoon, each a candidate arrival event: on the order of 500k a day ([03 §1](../03-product-spec.md#1-problem), [feed notes](../feed-notes.md)). They are append-only, written every minute, read in bulk once a day, and scanned column-wise (group by route, stop, hour). Planned volumes:

| Data | Format | Size |
|---|---|---|
| Minute event batches | gzip JSON lines | ~10 MB/day, kept 14 days |
| Hourly raw samples | protobuf | ~15 MB/day, kept 7 days |
| Curated arrivals | Parquet (zstd) | ~5 MB/day ≈ 1.8 GB/year, kept indefinitely |

**User data** (users, sessions, saved commutes, idempotency keys, audit log, rate-limit counters) is small (< 100 MB), relational and transactional, with foreign keys and per-user authorization.

The database budget is Neon's free plan: **0.5 GB storage and 100 compute-hours a month**, scaling to zero when idle. A 0.25 CU compute that never sleeps uses ~180 CU-hours a month.

## Decision

- Observations live in **S3** (`LAKE_URL`): minute batches under `events/`, raw samples under `raw/`, compacted daily **Parquet** under `curated/arrivals/…/service_date=…/part-0.parquet`. Lifecycle rules expire `events/` after 14 days and `raw/` after 7 days.
- Batch analytics run in **DuckDB embedded in the `daily-rollup` and `schedule-import` Lambdas** (`jobs.zip` only), reading and writing Parquet in S3 directly.
- **Postgres holds only relational data** plus the small `route_daily_metrics` table that powers trends and Ask.
- The per-minute ingest path never touches Postgres; `ingest-tick` has no database credentials at all.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Everything in Postgres** (observations in a partitioned table) | Hundreds of thousands of stop events a day would pass the 0.5 GB free limit within weeks. Writing every minute keeps the compute awake 24/7 (~180 CU-hours/month against a 100-hour quota). |
| **TimescaleDB** or another time-series database | Same always-on problem, plus a second vendor or self-hosting. |
| **Amazon Athena** over the same Parquet | Billed per TB scanned, slower edit-run loop, harder to test locally. Kept as the growth path (Iceberg + Athena), not the starting point. |
| **Spark / EMR / Glue** | Absurd at a few MB per day; hourly or per-DPU billing. |
| **DynamoDB** for observations | Poor fit for column scans and percentile aggregation; analytics would need an export step anyway. |
| **pandas** in the rollup | Loads whole tables into memory; MBTA `stop_times.txt` alone is ~146 MB of CSV. DuckDB streams it. |

## Consequences

**Positive**

- Storage costs pennies (≈ $0.07/month for < 3 GB) and Neon sleeps most of the day.
- The engine matches the workload: columnar scans for analytics, transactions and constraints for user data.
- Local development uses the same code with the file-system blob store (`file://.localdata/lake`); DuckDB runs the same SQL against local files, so rollup SQL is testable on fixture Parquet in CI.
- Raw data has explicit, budget-driven retention; curated data is small enough to keep forever.

**Negative**

- Two storage systems to understand, secure and back up (Postgres via `pg_dump`, S3 via versioning).
- No ad-hoc SQL over observations from the API; anything a user sees must be precomputed by the rollup (see [ADR-009](0009-static-json-with-atomic-manifest-swap.md)).
- DuckDB pins the `jobs.zip` size and memory (rollup at 2,048 MB, 4 GB `/tmp`); the CI package-size check must catch growth.
- Idempotency moves into application code: deterministic object keys and dedup by `(service_date, trip_id, stop_sequence)` during compaction, instead of database constraints.
- S3 request charges (~87k PUTs/month, ≈ $0.45) become the largest line item.

## Revisit when

- Ad-hoc analytical queries are needed by users or the operator on more than a few years of data → Iceberg tables queried by Athena, keeping DuckDB for jobs.
- Per-trip ingest state outgrows one object (> 5 MB, or tick p95 > 20 s) → move state to DynamoDB with conditional writes ([04 §11](../04-architecture.md#11-future-scaling-what-changes-and-when)).
- The Postgres side outgrows the free plan for its own reasons (users, not observations).
