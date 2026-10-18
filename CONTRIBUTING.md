# Contributing to Stopwatch

Thanks for helping. This guide covers local setup, the workflow for changes, and two common tasks: adding an agency and adding an ADR. Design background is in [docs/](docs/); the interfaces between components are in [docs/contracts.md](docs/contracts.md), which is **normative**.

## Local setup

**Prerequisites:** Docker (with Compose v2), GNU Make, [uv](https://docs.astral.sh/uv/) (Python 3.13 is installed by uv), Node.js 22 and npm. No AWS account is needed for local development.

```bash
git clone <repo-url> stopwatch && cd stopwatch
cp .env.example .env        # local defaults; never commit .env
make install                # uv sync (backend, all extras) + npm ci (frontend)
make dev                    # Postgres, migrations, API, ingest worker, web app
```

Open <http://localhost:5173>. The API runs on <http://localhost:8000> (OpenAPI at `/api/v1/openapi.json`), Postgres on `localhost:5433`, and local data lives in `./.localdata` (file-system blob store instead of S3). `make down` stops the local stack.

The `worker` service polls the live MBTA feed once a minute. To work offline (or for a predictable demo), run `make demo` instead: the same stack, but the worker replays recorded MBTA snapshots, so no internet connection is needed.

Useful targets (`make help` lists all):

| Target | What it does |
|---|---|
| `make demo` | The full local stack offline: the worker replays recorded snapshots instead of polling MBTA |
| `make test` | All backend tests with coverage (starts Postgres if needed) |
| `make test-unit` | Fast tests: unit, property, replay (no database) |
| `make test-integration` | Integration and API tests against local Postgres |
| `make lint` / `make fmt` | Ruff and import-linter / auto-format |
| `make typecheck` | mypy (strict on `stopwatch.core`) |
| `make seed` | Import the static GTFS schedule and catalog for configured agencies |
| `make ingest-once` | One ingest tick against the live feed |
| `make rollup DATE=YYYY-MM-DD` | Daily rollup for one service date |
| `make replay DIR=…` | Replay recorded snapshots through ingest |
| `make record-fixtures MINUTES=30` | Record live snapshots for fixtures (polls once a minute; be polite) |

Frontend unit tests use Vitest and end-to-end tests use Playwright, run from `frontend/` with the npm scripts defined in `frontend/package.json`.

## Workflow

### Branches

Work on a short-lived branch from `main`, one feature or fix per branch, named `<type>/<short-description>`, for example `feat/commute-summary`, `fix/dst-service-day`, `docs/runbook-rb3`. `main` is protected: required checks, linear history, no force-push.

### Commits: Conventional Commits

```text
<type>(<scope>): <summary in the imperative, ≤ 72 chars>

<body: what and why, wrapped at 72>

<footers: Refs #123, BREAKING CHANGE: …>
```

- **Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert`.
- **Scopes** (optional): `core`, `inference`, `gtfs`, `metrics`, `ingest`, `rollups`, `catalog`, `accounts`, `commutes`, `alerts`, `ask`, `api`, `web`, `infra`, `ops`, `deps`.
- Breaking changes to a published interface (API, published JSON, contracts) use `!` after the type/scope and a `BREAKING CHANGE:` footer.
- Release tooling builds the changelog from these messages on release tags; add a human-readable line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) for anything a user or operator would notice.

Examples: `feat(inference): refine estimates with STOPPED_AT positions`, `fix(gtfs): use noon-minus-12h on DST service days`, `docs(adr): add ADR-011 for DynamoDB state`.

### Pull requests

Keep PRs small enough to review in about 15 minutes. Every PR must pass CI (lint, types, tests, security scans, IaC checks, end-to-end tests). Checklist:

- [ ] Tests added or updated, including a failing-first test for bug fixes. Changes to `core` keep coverage ≥ 90%.
- [ ] Replay goldens changed? The diff is explained in the PR description.
- [ ] Interfaces changed? [docs/contracts.md](docs/contracts.md) updated **in the same PR**; API changes that break clients carry the `api-breaking` label; published JSON changes are additive within `/data/v1`.
- [ ] Database migration? Expand/contract style, tested `downgrade`, `lock_timeout` set, no long backfills inside the migration ([06 §5](docs/06-quality-operations.md#5-database-migrations)).
- [ ] Security and privacy impact considered: new data collected? new log fields (no emails, labels or tokens)? new endpoint added to the authorization matrix? Repository methods for user-owned data take `owner_id`.
- [ ] Cost impact considered: new AWS resources, schedules or request patterns? (Budget: ≈ $0.55/month.)
- [ ] Decision worth recording? Add an ADR (below). Operational behavior changed? Update the runbook.
- [ ] User-visible change? Line added under **Unreleased** in [CHANGELOG.md](CHANGELOG.md); methodology updated if a number's meaning changed.
- [ ] UI change: screenshots in the PR; keyboard and screen-reader checked; no new axe violations.
- [ ] No secrets, `.env` files, raw feed dumps or personal data in the diff.

## Adding an agency

Adding an agency is configuration, not code: nothing in `stopwatch.core` may know which agency it is processing.

1. **Check the feeds first.** Confirm the TripUpdates and VehiclePositions feeds and the static GTFS are reachable (keyless or with a key you are allowed to use) and that the license permits republishing derived statistics. Record a short sample (`make record-fixtures MINUTES=10` with the agency configured) and write a section in [docs/feed-notes.md](docs/feed-notes.md): header cadence, whether past stops are dropped, `delay` fields, SKIPPED/NO_DATA usage, ADDED/CANCELED counts, trip-id matching against the static schedule, time zone.
2. **Add an `AgencyConfig` entry** to `AGENCIES` in `backend/src/stopwatch/platform/agencies.py`:

   ```python
   "septa": AgencyConfig(
       id="septa",
       name="SEPTA (bus & trolley)",
       timezone="America/New_York",
       trip_updates_url="https://…/rtTripUpdates.pb",
       vehicle_positions_url="https://…/rtVehiclePosition.pb",
       static_gtfs_url="https://…/gtfs_public.zip",
       static_inner_zip="google_bus.zip",   # only if the zip contains zips
       route_types=(0, 3, 11),              # GTFS route_type values in scope
       # optional: live_api, on_time_early_s/on_time_late_s (default -60/300),
       # frequent_headway_s (default 720), max_feed_bytes (default 8 MiB)
   ),
   ```

   Keep the on-time window at −60/+300 s unless there is a documented reason; it is published with the data.
3. **Test locally:** add the id to `AGENCIES` in `.env` (comma-separated, e.g. `AGENCIES=mbta,septa`), run `make seed`, then `make ingest-once` a few times and `make rollup`. Add a trimmed replay fixture and a contract test for the agency's quirks.
4. **Deploy:** each agency gets its own ingest schedule and its own state object `state/{agency}/latest.json.gz`, so failures stay independent ([04 §11](docs/04-architecture.md#11-future-scaling-what-changes-and-when)). Add the agency to the Terraform variables for the environment, run `make up ENV=staging`, and watch a day of ticks before enabling it in prod.
5. **Document:** update the methodology's coverage note, the changelog, and the README's agency list.

## Adding an ADR

Write an Architecture Decision Record when a decision is hard to reverse, affects cost or security, or a reviewer would reasonably ask "why not X?".

1. Copy the template in [docs/adr/README.md](docs/adr/README.md#template) to `docs/adr/NNNN-short-kebab-title.md` with the next free number.
2. Fill in context (with numbers and dates), decision, alternatives with reasons, consequences (positive and negative), and concrete "revisit when" triggers.
3. Open it in the same PR as the change it explains, with status *Proposed*; set *Accepted, YYYY-MM-DD* when it merges.
4. Add it to the index in [docs/adr/README.md](docs/adr/README.md) and the decision log in [docs/04 §12](docs/04-architecture.md#12-decision-log-to-be-expanded-into-adrs).
5. Never rewrite an accepted ADR's decision; supersede it with a new ADR and link both.

## Reporting problems

- Bugs and feature requests: GitHub issues (bug, feature and data-quality templates).
- Numbers that look wrong: the data-quality issue template, with the route, stop, day and hour.
- **Security vulnerabilities: do not open a public issue.** See [SECURITY.md](SECURITY.md).

By contributing you agree that your contributions are licensed under the project's [MIT License](LICENSE).
