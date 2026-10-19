# Changelog

All notable changes to Stopwatch are documented here, for riders, developers using the published data, and the operator.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries under **Unreleased** are added by hand in each pull request ([CONTRIBUTING.md](CONTRIBUTING.md#commits-conventional-commits)); on a release tag they move under the version number, cross-checked against the Conventional Commit history. Changes to published data definitions, corrections to published numbers, and incidents that affected users are always listed, with a link to the postmortem where there is one.

## [Unreleased]

Initial feature set for `v1.0.0` (MBTA bus, subway and light rail). Items are listed as they land.

### Added

- **Ingestion:** MBTA GTFS-Realtime TripUpdates and VehiclePositions polled every minute by a scheduled Lambda (reserved concurrency 1), with fetch timeouts, byte caps, bounded retries, a no-op tick when the feed has not advanced, and S3 compare-and-swap state.
- **Arrival inference:** arrivals inferred from disappearing predictions (`last_prediction`, `vp_stopped`, `trip_end_flush`) with `high` / `medium` / `low` confidence; SKIPPED stops and CANCELED trips recorded separately, never as on time.
- **Schedule import:** daily conditional download of the MBTA static GTFS, `stop_times` to Parquet with DuckDB, catalog upsert in one transaction; service-day and daylight-saving time math in `core.gtfs`.
- **Daily rollup and publishing:** compaction to Parquet, schedule join, delay, on-time share (−1 to +5 min), median and 90th-percentile delay, delay histograms, excess wait time on frequent stop-hours, coverage; a data-quality gate and an atomic manifest swap; immutable builds under `/data/v1/builds/{build_id}/`.
- **Public pages:** client-side stop search and "near me" (location never leaves the device), route and stop pages with day-type × hour heatmaps and 8-week trends, a live "right now" panel from the MBTA v3 API, and a data-health page with a site-wide stale-data banner.
- **Accounts:** Google sign-in (OIDC authorization code + PKCE; ID tokens verified with PyJWT), server-side sessions, CSRF protection, temporary demo accounts (24 h).
- **Saved commutes:** create, edit and delete up to 20 commutes (3 for demo accounts) with idempotent creation and personal reliability summaries computed in the browser.
- **Privacy controls:** account export (`GET /api/v1/me/export`) and immediate deletion (`DELETE /api/v1/me`); sign out everywhere.
- **Operations:** structured logs, 10 custom metrics, 10 CloudWatch alarms and 2 AWS Budgets routed to email, 3 dashboards, runbooks RB-1 to RB-7, nightly `pg_dump` backups, and a quarterly restore drill.
- **Edge trust:** CloudFront adds an `X-Origin-Verify` secret to API requests and the API rejects requests without it in staging and prod; the client IP for rate limits comes only from `CloudFront-Viewer-Address`.
- **Offline demo:** `make demo` runs the full local stack with the worker replaying recorded MBTA snapshots, no internet needed.
- **Infrastructure and delivery:** Terraform for staging and prod (`make up` / `make down`), GitHub Actions CI with security and IaC scanning, keyless OIDC deploys, build-once-promote releases with alias rollback.
- **Documentation:** [methodology](docs/methodology.md), [API and data reference](docs/api.md), [privacy policy](docs/privacy.md), [feed notes](docs/feed-notes.md), [ADR-001 to ADR-010](docs/adr/README.md), [runbooks](docs/runbooks/README.md), [AI usage note](docs/ai-usage.md), [contributing guide](CONTRIBUTING.md) and [security policy](SECURITY.md).

### Planned after v1.0.0 (*should*)

- Web Push delay and cancellation alerts for saved commutes.
- "Ask Stopwatch" plain-English questions over published data with evals; Groq model `openai/gpt-oss-120b` by default (`ASK_MODEL` to change) and a hard $1/month cost cap with a guided-form fallback.
- Weekly accuracy validation against MBTA LAMP subway files, matching on (vehicle, stop) with the nearest arrival within 15 minutes, published on the methodology page.
- A second agency (SEPTA or NYC subway).

[Unreleased]: https://github.com/OWNER/stopwatch/commits/main
