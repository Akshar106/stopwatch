# 07 — Repository Structure and Roadmap

*Phase 4 · 2026-10-18 · planned at ~15 hours/week*

## 1. Repository structure

This folder becomes the repository root. The existing `docs/` and `research/` folders stay as they are.

```text
stopwatch/
├── README.md                     # landing page: demo link, numbers, diagram, 1-command quickstart
├── CHANGELOG.md                  # generated from conventional commits on release tags
├── LICENSE                       # MIT
├── Makefile                      # dev, test, lint, seed, replay, up/down ENV=…, rollback, publish-rollback
├── compose.yaml                  # db, api, worker, web (local dev at $0)
├── .env.example                  # every config key, documented
├── .pre-commit-config.yaml       # ruff, mypy, eslint, prettier, gitleaks
├── .github/
│   ├── workflows/                # ci, codeql, deploy, nightly, weekly, teardown
│   ├── dependabot.yml
│   ├── pull_request_template.md  # includes "security / privacy impact" and "migration?" checkboxes
│   └── ISSUE_TEMPLATE/           # bug, feature, data-quality report
├── backend/
│   ├── pyproject.toml  uv.lock  .importlinter  Dockerfile.dev  alembic.ini
│   ├── migrations/versions/
│   ├── src/stopwatch/
│   │   ├── core/                 # PURE: no I/O imports allowed
│   │   │   ├── gtfs/             # service_day.py, times.py (24h+ times, DST)
│   │   │   ├── inference/        # snapshot.py, diff.py, confidence.py
│   │   │   └── metrics/          # delay.py, ontime.py, headway.py (excess wait time)
│   │   ├── ingest/               # fetch.py, index.py, state.py, tick.py
│   │   ├── rollups/              # sql/*.sql, compact.py, quality.py, publish.py
│   │   ├── catalog/              # gtfs_import.py, repository.py, service.py
│   │   ├── accounts/             # oidc.py, sessions.py, csrf.py, demo.py, repository.py, service.py
│   │   ├── commutes/             # schemas.py, repository.py, service.py
│   │   ├── alerts/               # (should) rules.py, evaluate.py, webpush.py
│   │   ├── ask/                  # (should) tools.py, agent.py, grounding.py
│   │   ├── platform/             # config, db, blobstore/{s3,local}, http, observability,
│   │   │                         # ratelimit, audit, idempotency
│   │   ├── api/                  # main.py, deps.py, errors.py, routes/{auth,me,commutes,health,…}
│   │   └── jobs/                 # ingest_tick, schedule_import, daily_rollup, maintenance,
│   │                             # notify, lamp_validate, local_scheduler
│   └── tests/
│       ├── unit/  property/  replay/  integration/  api/
│       └── fixtures/             # gtfs_mini/, rt_snapshots/ (recorded, trimmed)
├── frontend/
│   ├── package.json  package-lock.json  vite.config.ts  tsconfig.json  lighthouserc.json
│   ├── src/
│   │   ├── app/                  # routes, providers, layout
│   │   ├── features/             # search, stop, route, commutes, health, auth, (ask), (alerts)
│   │   ├── components/           # Heatmap, DelayHistogram, LivePanel, StaleBanner, …
│   │   └── lib/                  # dataClient (manifest → build), apiClient (CSRF), nearest.ts, summary.ts
│   ├── public/                   # sw.js (should: push)
│   └── tests/  e2e/              # Vitest; Playwright + axe
├── infra/
│   ├── bootstrap/                # state bucket (one-time, never destroyed by make down)
│   ├── modules/                  # storage, functions, scheduler, api, edge, observability, budget, github_oidc
│   └── envs/{staging,prod}/
├── evals/ask/                    # (should) questions.yaml, expected tools/params, runner
├── scripts/                      # package_lambda.sh, record_fixtures.py, replay.py, backup.sh
├── research/                     # market research data + scripts (already here)
└── docs/
    ├── 01–08 planning docs       # already here
    ├── methodology.md            # public: how arrivals, delay, on-time, EWT are computed + known limits
    ├── api.md  openapi.json      # public JSON + dynamic API reference
    ├── privacy.md                # plain-language privacy policy
    ├── ai-usage.md               # how AI tools were used and how output was verified
    ├── feed-notes.md             # MBTA feed quirks found (e.g., SKIPPED semantics)
    ├── adr/                      # 0001-modular-monolith-on-lambda.md … 0010-lambdas-outside-vpc.md
    ├── runbooks/                 # RB-1 … RB-7, restore-drill.md
    └── postmortems/              # YYYY-MM-DD-title.md
```

**Conventions:**

- **Work:** one PR per feature or fix, small enough to review in 15 minutes. Conventional commits (`feat:`, `fix:`, `docs:`, …). Issues and a GitHub Projects board as the backlog.
- **Visible history:** steady, incremental commits. No "initial commit" containing the whole app, because reviewers do look at history.
- **Discussion trail:** ADRs are written *when the decision is made*, not retrofitted.

## 2. Scope (MoSCoW)

| Priority | Items |
|---|---|
| **Must (MVP)** | MBTA bus + subway ingestion every minute; arrival inference; delay / on-time / p90 / excess-wait / coverage metrics; daily rollups with a quality gate and atomic publish; client-side stop search and near-me; stop and route pages with heatmaps and trends; live panel; data-health page; Google sign-in; demo accounts; saved commutes with summaries; export and delete; IaC; CI/CD; tests; security scanning; alarms; runbooks; backups; cost guardrails |
| **Should** | LAMP accuracy validation; Web Push delay alerts; "Ask Stopwatch" with evals and a $1 cap; second agency (SEPTA or NYC subway) |
| **Could** | Map view; PWA install; Parquet/CSV downloads; public API keys; weekly digest; anomaly flags; embeddable widget |
| **Excluded** | Trip planning; arrival forecasting/ML; native apps; commuter rail, ferry, paratransit; official reporting claims; precise location storage; trackers; multi-region; sub-minute freshness |

## 3. Roadmap

**Budget:** 12 weeks × 15 h = **180 h for the MVP**, plus **2 buffer weeks** (launch by week 14 at the latest), then 4 weeks × 15 h = **60 h for Should** items.

**Key sequencing choice: production ingestion starts in week 5.** Historical data can't be collected retroactively. Starting the collector early means the public demo launches with ~7 weeks of real data, and the frontend is built against real numbers instead of fixtures.

### Phase 1: Foundations and data core (weeks 1–4)

#### Week 1: Foundations and feed investigation (15 h)

| Task | Hours |
|---|---|
| Scaffold backend (uv, FastAPI hello), frontend (Vite + React + TS), Makefile, compose, pre-commit | 4 |
| CI skeleton: lint + type check + test on PR | 2 |
| Record ~2 h of minute-by-minute MBTA snapshots into fixtures; investigate the **18% SKIPPED** stop updates and other quirks; write `docs/feed-notes.md` | 6 |
| Hand-build the mini GTFS fixture (midnight-crossing trip, DST date); draft ADR-001…003 | 3 |

- **Deliverables:** `make dev` runs an empty API + web app; CI green; fixtures; feed notes.
- **Done when:** a fresh clone runs `make dev` without manual steps; the SKIPPED behavior is either explained or tracked as an issue with evidence.
- **Risk:** tooling yak-shaving. Timebox scaffolding to 6 h and accept imperfect configs.

#### Week 2: Schedule and time math (15 h)

| Task | Hours |
|---|---|
| `core.gtfs`: service days, `25:10:00` times, noon-minus-12h reference, DST, with property tests | 5 |
| `schedule-import`: conditional download (ETag), validation, `stop_times` → Parquet via DuckDB | 5 |
| First Alembic migration (agencies, feed_versions, routes, stops, route_stops); catalog upsert in one transaction | 3 |
| Tests (idempotent re-import, DST fixtures) | 2 |

- **Deliverables:** `make import-schedule` produces Parquet + catalog rows.
- **Done when:** DST and after-midnight tests pass; a second import with no feed change does nothing.
- **Risk:** large `stop_times`. Use DuckDB streaming CSV reading; don't load it into pandas.

#### Week 3: Arrival-inference engine (15 h)

| Task | Hours |
|---|---|
| Snapshot indexing, diff, confidence levels (`core.inference`) | 6 |
| Hypothesis property tests + replay goldens from week-1 fixtures | 6 |
| VehiclePositions `STOPPED_AT` refinement; skipped and canceled handling | 3 |

- **Deliverables:** an inference module with ≥ 90% coverage.
- **Done when:** replaying the recorded fixtures gives deterministic events; a manual spot check of 20 events against vehicle positions looks right.
- **Risk:** ambiguous edge cases. Ship `last_prediction` only first and add the refinement after.

#### Week 4: Ingest tick, running locally (15 h)

| Task | Hours |
|---|---|
| Blob store adapters (local FS + S3 with moto tests); state compare-and-swap with `If-Match` | 4 |
| Tick orchestration: fetch with timeouts and size caps, event writer, EMF metrics, summary log line | 6 |
| Run the local worker live for 48 h; analyze output; fix what breaks | 5 |

- **Deliverables:** a local pipeline that has run 48 h continuously.
- **Done when:** < 1% failed ticks locally; events look plausible for 3 routes compared with mbta.com predictions.

> **Checkpoint A (end of week 4): is the core sound?**
> - **Go:** plausible delays on 3 spot-checked routes; tests green.
> - **No-go actions:** if inference is unreliable, cut the VP refinement, launch with **subway only** (better feed quality, and LAMP ground truth), and add bus later.

### Phase 2: Cloud pipeline (weeks 5–6)

#### Week 5: AWS foundation and production ingestion (15 h)

| Task | Hours |
|---|---|
| Account hygiene: MFA, no root use, **budgets first** ($1/$5); Terraform bootstrap (state bucket) | 3 |
| Modules: storage, functions (ingest), scheduler, observability (SNS + `IngestStale`), budget, github_oidc | 8 |
| arm64 zip packaging; `deploy.yml` for the ingest function | 4 |

- **Deliverables:** **prod ingestion running every minute. Data collection begins.**
- **Done when:** 24 h of continuous ticks; the `IngestStale` alarm proven by pausing the schedule; Cost Explorer shows ≈ $0.

#### Week 6: Daily rollup and publishing (15 h)

| Task | Hours |
|---|---|
| DuckDB compaction (dedup by idempotency key) + schedule join + delay | 6 |
| Metrics: on-time, p50/p90, excess wait time; parity tests between the Python core and SQL | 4 |
| Build publish + data-quality gate + manifest swap + `health.json` | 4 |
| Deploy the rollup job + `RollupLate` / `RollupLowCoverage` alarms | 1 |

- **Deliverables:** daily published route JSON from real data.
- **Done when:** a bad build is blocked by the gate in a test; `make publish-rollback` works.

> **Checkpoint B (end of week 6): is the data trustworthy?**
> - **Go:** median daily coverage ≥ 90% (target 95%); no unexplained spikes.
> - **No-go actions:** spend week 7 on data quality instead of UI and push frontend work back one week, absorbed by the buffer.

### Phase 3: Public product (weeks 7–8)

#### Week 7: Frontend I, search and stop pages (15 h)

| Task | Hours |
|---|---|
| SPA shell, routing, layout, data client (manifest → build) | 4 |
| Stop index search + **client-side** near-me + tests | 4 |
| Route and stop pages: day-type × hour heatmap (Observable Plot), cell details, methodology page | 6 |
| Accessibility pass (keyboard, labels, contrast) | 1 |

#### Week 8: Frontend II, live panel, health page, edge (15 h)

| Task | Hours |
|---|---|
| Live predictions panel (MBTA v3 API from the browser; graceful failure) | 3 |
| Data-health page + site-wide stale banner | 3 |
| CloudFront module (OAC, security headers, `/data` `/api` `/` behaviors); SPA deploy in the pipeline | 5 |
| Playwright E2E (search → stop) + axe; Lighthouse CI budgets | 4 |

> **Checkpoint C (end of week 8): public read-only demo.**
> - **Go:** live URL with about 3 weeks of real data; Lighthouse mobile ≥ 90 for performance and accessibility.
> - **Action:** show it to 3 people (ideally MBTA riders) and log their feedback as issues. If accounts look too big for weeks 9–10, **ship demo accounts only** and move Google sign-in into the buffer.

### Phase 4: Accounts and commutes (weeks 9–10)

#### Week 9: Accounts (15 h)

| Task | Hours |
|---|---|
| Neon setup, roles and grants; migrations for users, sessions, audit, rate-limit tables | 3 |
| API Lambda + HTTP API + `/api` behavior; app structure; problem+json errors | 3 |
| Google OIDC (PKCE, state, nonce), server-side sessions, CSRF, logout | 6 |
| Demo accounts + rate limiting + audit log | 3 |

#### Week 10: Commutes and privacy (15 h)

| Task | Hours |
|---|---|
| Commutes CRUD + validation + idempotency keys | 4 |
| **Authorization matrix tests** + Schemathesis fuzzing | 3 |
| Frontend: sign-in, my commutes, client-side summaries | 5 |
| Export and delete account; privacy page | 3 |

### Phase 5: Hardening and launch (weeks 11–12)

#### Week 11: Hardening (15 h)

| Task | Hours |
|---|---|
| Security: Semgrep custom rules, Checkov fixes, ZAP baseline, header tests | 4 |
| Performance: k6 runs, cold-start measurement, bundle trimming | 3 |
| Reliability: remaining alarms and dashboards, nightly `pg_dump`, **first restore drill** | 4 |
| Runbooks RB-1…7; failure injection in staging (pause ingest, delete state, break a feed URL) | 4 |

#### Week 12: Launch (15 h)

| Task | Hours |
|---|---|
| README with **measured** numbers, screenshots, diagram; finalize ADR-001…010 | 5 |
| 2–3 minute demo video | 3 |
| Soft launch: r/mbta, local advocacy groups, campus channels; feedback form | 2 |
| Fix the top feedback items; tag `v1.0.0`; changelog | 5 |

> **Checkpoint D (end of week 12, or week 14 with buffer): MVP launch.**
> - **Go:** every Must item done; SLO dashboard green for 7 days; credibility checklist ([08](08-portfolio-kit.md#8-final-credibility-checklist)) ≥ 80% done.
> - **No-go:** use buffer weeks 13–14 and cut from the bottom of the Must list in this order: trends → excess wait time → demo accounts.

### Phase 6: Should items (weeks 13–16, after launch)

| Week | Focus (15 h) | Done when |
|---|---|---|
| 13 | **LAMP validation:** download LAMP Parquet, join with subway estimates, publish the error distribution on the methodology page, tune confidence thresholds | Median abs. error and p90 published; README updated with the real figure |
| 14 | **Web Push alerts:** service worker, VAPID keys, subscriptions, alert rules exported to S3 on change, evaluation in the ingest tick, `notify` + DLQ, dedupe | An alert arrives on a phone within 2 min in a staged test; duplicates impossible by constraint |
| 15 | **Ask Stopwatch:** read-only tools over published JSON, LLM call with the $1/month cap, grounding validator, 60-question eval set, guided-form fallback | Evals ≥ 90% tool accuracy, 100% grounding; cap enforced in a test |
| 16 | **Second agency** (SEPTA or NYC subway) via config + per-agency schedules; write the blog post; tag `v1.1.0` | A second agency appears in the UI with no agency-specific code paths in the core |

Weeks 17+ (**Could**, as time allows): map view → PWA → downloads → API keys.

## 4. Risk register

| Risk | Likelihood | Impact | Mitigation | Early warning |
|---|---|---|---|---|
| Arrival inference less accurate than expected | Medium | High | Confidence levels; subway-first fallback; LAMP validation; publish error honestly | Checkpoint A spot checks |
| SKIPPED / feed quirks distort coverage | Medium | Medium | Week-1 investigation; nightly drift check | `feed-notes.md` open questions |
| MBTA changes or rate-limits the feed | Low | High | 1 request/min is polite; drift check; runbook RB-2 | Parse error rate |
| DuckDB / dependencies exceed the Lambda zip limit | Low | Medium | Separate dependency groups per function; fallback to a container image | Package size check in CI |
| Free-tier terms change (AWS, Neon) | Medium | Medium | Quarterly re-check; architecture portable (Postgres anywhere, S3-compatible) | Budget alarm |
| Scope creep (maps, ML, more agencies early) | High | High | MoSCoW table; checkpoints; "could" items only after v1.0 | Week overruns > 3 h twice |
| OIDC / session work takes longer than planned | Medium | Medium | Use PyJWT + httpx (small, well-tested); demo accounts as fallback; buffer weeks | Week 9 not done by mid-week 10 |
| Few real users | Medium | Medium | Post where riders are; make one personal page genuinely useful; accept small numbers and report them honestly | < 5 signups 2 weeks after launch |
| Burnout or schedule slips | Medium | High | 15 h/week cap; buffer weeks; cut list ready | Two consecutive weeks under 8 h |
| AWS cost surprise | Low | Medium | Budgets first (week 5); concurrency caps; no NAT/ALB/RDS | Any budget alert |

## 5. Weekly working rhythm

- **Monday (30 min):** pick the week's issues from the board and check the checkpoint criteria.
- **During the week:** small PRs, each with tests; keep the ADR, runbook or docs page current in the same PR.
- **Friday (30 min):** update `CHANGELOG.md` with what's unreleased; log hours vs plan in the project board; one paragraph in a dev log, which becomes raw material for the blog post and interview stories.
