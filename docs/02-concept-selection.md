# 02 — Concept Comparison and Selection

*Phase 1 output · 2026-10-18 · builds on [01-market-research.md](01-market-research.md)*

## What the research says the project has to show

These requirements come from the demand matrix in doc 01. Each one maps to a market signal, not to personal taste.

| # | Requirement for the project | Market signal behind it (company-weighted, 18 cos) |
|---|---|---|
| R1 | Real users with a real problem, plus visible product thinking | Product/user focus 17/18, cross-functional collaboration 17/18 |
| R2 | One person owns it end to end: UI → API → data → ops | Ownership/end-to-end 17/18, operating in production 17/18 |
| R3 | Correctness and reliability under real failure modes | Reliability 15/18, scalability 16/18, performance 14/18 |
| R4 | A load-bearing AI component built with judgment (evals, guardrails, cost limits), and disciplined use of AI coding tools | AI/ML/LLM 15/18, LLMs specifically 11/18, AI coding tools 11/18 |
| R5 | Python and/or TypeScript/React with a relational database | Python 16/18, TS/JS 11/18, React 10/18, SQL/relational 11/18 |
| R6 | Tests, monitoring and debuggability you can show, not just claim | Unit/integration tests 14/18, monitoring 11/18, debugging 11/18 |
| R7 | Security that actually protects something | Security 11/18 |
| R8 | Infrastructure kept modest: Docker, CI and simple IaC, not a cluster | Kubernetes 6/18, Terraform/IaC 4/18, CI/CD 4/18. Among true new-grad postings, Docker 0/9 and Kubernetes 1/9 |

## Concepts considered

Ruled out before scoring because recruiters see them constantly: todo or notes apps, e-commerce clones, chat apps, job-application trackers, AI résumé analyzers, generic uptime monitors and status pages, and weather or movie dashboards.

| # | Concept | One-line pitch |
|---|---|---|
| A | Household recall matcher | Tracks the cars, baby gear, food and medications you own and alerts you when a federal recall matches one |
| B | **Transit reliability tracker** | Ingests live GTFS-Realtime transit feeds 24/7 and shows riders how reliable *their* stop and route really are, by hour and by day, with personal alerts |
| C | Recurring-charge detector | Imports bank transactions (Plaid Sandbox or CSV), detects subscriptions and price hikes, and warns before renewals |
| D | Reliable webhook delivery service | Signed, retried, replayable outbound webhooks with delivery logs; a small open-source take on Svix/Hookdeck |
| E | Volunteer shift scheduler | Multi-tenant shift sign-ups for nonprofits with waitlists, reminders and no-show tracking |
| F | Group expense ledger | Double-entry shared-expense ledger with idempotent writes and debt simplification |
| G | Real-time collaborative editor | Multiplayer document or whiteboard built on CRDTs and WebSockets |

### Checks run before scoring (2026-10-18)

- **Recall data APIs (A):**
  - openFDA food enforcement: 29,485 records, the latest reported 2026-10-07.
  - NHTSA recalls-by-vehicle: responds; a 2020 Honda CR-V returns 7 recalls.
  - CPSC Recall API: 76 recalls since 2026-09-01.
  - USDA-FSIS API: HTTP 403 to a scripted request.

  **Existing products:** several apps already do cross-agency household recall matching. [RecallDefense](https://apps.apple.com/us/app/recalldefense/id6760236829) and RecallSentry ([ConsumerAffairs coverage](https://www.consumeraffairs.com/news/new-app-alerts-you-when-theres-a-recall-031626.html)) both do it, and hosted aggregators exist too, one even named [US Recall Radar](https://apify.com/bikram07/recall-radar). The problem is real, but it is already served.
- **Transit feeds (B):** MBTA TripUpdates (≈636 KB per snapshot), MBTA VehiclePositions, NYC MTA subway (A/C/E lines) and SEPTA TripUpdates all returned HTTP 200 with **no API key**. TriMet returned 403 (it needs an app ID).

  **Existing work:** [TransitMatters' dashboard](https://transitmatters.org/blog/2020/8/3/rolling-out-our-data-dashboard) covers Boston *subway* travel times using the MBTA performance API. There are academic and agency projects on stop-level bus reliability ([Morgan State / MTA Maryland](https://rip.trb.org/View/2343788), [UW TransitVis](https://mic.comotion.uw.edu/projects/transit-corridor-performance-study/)), and MIT's open-source [ROVE](https://rove.readthedocs.io) supports only static GTFS. Nothing dominant offers *rider-facing, stop-level, multi-agency* reliability with personal alerts. This space has precedent but isn't crowded.

### Scoring

Scale is 1–5. Weights: relevance 20%, depth 20%, impact 15%, feasibility 15%, originality 10%, demo quality 10%, interview value 10%. Relevance is scored against the broad mid-to-big-tech target, not one industry.

| Concept | Impact | Relevance | Depth | Feasibility | Originality | Demo | Interview | **Weighted** |
|---|---|---|---|---|---|---|---|---|
| **B Transit reliability** | 4 | 5 | 5 | 3 | 4 | 5 | 5 | **4.45** |
| C Recurring charges | 4 | 4 | 5 | 3 | 3 | 4 | 5 | **4.05** |
| A Recall matcher | 4 | 4 | 4 | 4 | 3 | 4 | 5 | **4.00** |
| E Volunteer scheduler | 4 | 4 | 4 | 4 | 3 | 4 | 4 | **3.90** |
| D Webhook service | 3 | 4 | 5 | 4 | 2 | 3 | 5 | **3.85** |
| F Expense ledger | 3 | 4 | 4 | 4 | 2 | 4 | 4 | **3.65** |
| G Collaborative editor | 2 | 4 | 5 | 2 | 2 | 5 | 4 | **3.50** |

The scores are judgment calls, so the reasoning below matters more than the decimals. B gets a 5 on relevance because it hits the three strongest *technical* signals in the data (production 17/18, scalability 16/18, reliability 15/18) with real traffic rather than simulated load.

### Short take on each

- **B — Transit reliability (recommended).** It's the only concept where a solo junior developer gets *genuine* production conditions for free: millions of observations a week, feeds that go stale, duplicate and out-of-order messages, clock skew, and schema quirks across agencies. That makes reliability, idempotent ingestion, data retention and rollups, SLOs and alerting *necessary* rather than decorative. The frontend is real work (maps, charts, a fast stop search), and the no-login public demo is live data. **Weaknesses and mitigations:**
  - *Authorization is thin because the data is public.* Personal commutes and alerts create sensitive data (home and work stops reveal where you live and work). A public API with keys and quotas creates a real abuse surface.
  - *No obvious LLM feature.* One natural fit is an "ask about reliability" box: the LLM picks one of a fixed set of parameterized, read-only queries, never raw SQL, and is scored against a labeled question set with a non-AI fallback. It's a *should*, not a *must*.
  - *Inferring actual arrivals from feeds is the hard part.* Start with one well-documented agency (MBTA) and a deliberately simple arrival-inference method, measure its error, and improve it iteratively.
- **C — Recurring charges.** The strongest fintech fit; 6 of the 18 sampled companies are fintech. Its security story is the best of the group (bank tokens, financial PII). **Weaknesses:** "personal finance app" is a common student genre, real users rarely hand bank access to a student project, and holding real financial data creates liability. **Best alternative if you narrow toward fintech.**
- **A — Recall matcher.** Clean entity-resolution problem, a strong AI-with-evals story, and private data that makes authorization meaningful. But commercial apps already do exactly this, and data volume is low (dozens of recalls a week), so both the impact and scale stories are weaker than they first looked.
- **E — Volunteer scheduler.** Real impact and solid multi-tenant authorization, but it depends on recruiting a partner nonprofit, and you said there isn't a community to draw on. Without one it's CRUD plus scheduling.
- **D — Webhook service.** Excellent interview material (idempotency, backoff, HMAC signing, dead-letter queues), but it's backend-only in practice, has no natural end users, and is a fairly common infra project.
- **F — Expense ledger.** Good transactional depth; Splitwise clones are common.
- **G — Collaborative editor.** CRDT edge cases can eat the whole time budget, and it signals front-end and algorithms more than full-stack production judgment.

## Recommendation: B, transit reliability tracker

*Working name: **Stopwatch**. Check name and domain availability before launch.*

**Problem.** Transit agencies report reliability as monthly, system-wide averages such as "88% on time." Riders don't experience averages. They experience *"the 8:05 at my stop is usually 6–12 minutes late on weekdays, and on Fridays it sometimes never shows."* The raw data to answer that exists in public real-time feeds, but it disappears every 30 seconds unless someone archives and analyzes it.

**Who it's for.**

1. Daily riders choosing when to leave and which route to take.
2. Transit advocates and local journalists who need evidence for specific routes.
3. Agency planners, who get a public, independent view (secondary audience).

**Why it fits the market data.**

| Signal | How Stopwatch demonstrates it |
|---|---|
| Production, ownership (17/18) | A 24/7 ingestion system you operate yourself, with real incidents and postmortems |
| Scalability, performance (16/18, 14/18) | Real volume: compact storage, partitioning, rollups, cached reads, and published p95 latencies and ingest lag |
| Reliability (15/18) | Feed outages, duplicates, out-of-order data and backfills, handled with idempotent upserts, retries with backoff, and staleness detection |
| Product/user focus (17/18) | Stop-level answers riders actually want, saved commutes, delay alerts, and feedback from real riders (local transit communities) |
| AI with judgment (15/18) | Should-tier "ask about reliability" feature using tool-calling over a fixed set of queries, with evals, a cost cap and a fallback. Plus a documented AI-assisted workflow with verification. |
| Relational SQL (11/18) | Postgres: GTFS static schema, partitioned observation tables, materialized rollups, careful indexing |
| Testing (14/18) | Recorded feed snapshots replayed as deterministic fixtures, property tests for arrival inference, contract tests per agency |
| Security (11/18) | Location-sensitive personal data, account security, API keys and quotas, rate limiting, OWASP-driven tests, audit log |
| Observability (11/18) | Freshness and lag SLOs per feed, structured logs, metrics, traces, alerts, and runbooks for "feed stale" and "ingest backlog" |
| DS&A (11/18) | Arrival inference, headway and percentile computation, nearest-stop search |

**Public demo.** No account needed for maps, route and stop reliability, or the "right now" view. A demo account shows saved commutes and alerts.

**Main risks and how to handle them.**

1. *Arrival inference is hard.* Start with one agency and a simple, explainable method. Measure it against agency-published numbers where they exist, and document the error.
2. *Storage grows forever.* Keep raw observations for N days and rollups indefinitely. Budget-driven retention is itself a design discussion.
3. *It needs to run 24/7.* This is addressed by the scale-to-zero design in [Cost model](#cost-model-added-after-budget-discussion) below, with no always-on server.

## Cost model (added after budget discussion)

**Constraint:** no ongoing $10–30/month bill. Small one-time costs are fine, and everything must be deletable.

**Design principle: $0 when idle, pay only for usage, one command to delete.**

- Develop locally with Docker Compose ($0). Real deployments are defined in infrastructure-as-code (IaC), so the whole stack can be created or destroyed with one command. That gives the IaC requirement a real job instead of being decoration.
- **No always-on servers.** Per [secondary 2026 guides](https://infratally.com/articles/aws-free-tier-2026/), AWS Lambda has a permanent monthly free allowance of 1M requests and 400,000 GB-seconds. A scheduled function that polls one agency's feed every minute is about 43,200 runs a month, roughly 45,000–90,000 GB-seconds. That fits inside the free allowance.
- **Raw observations go to object storage as compressed files** (pennies a month), with automatic expiry after N days. A daily job computes rollups.
- **Rollups, accounts and saved commutes live in a free-tier serverless Postgres.** [Neon's free plan](https://neon.com/pricing) offers 0.5 GB and 100 compute-hours a month, and scales to zero when idle. Postgres is touched only by user requests and the daily rollup job, so it sleeps most of the time.
- **Frontend on a CDN or static hosting** (free).
- **Cost guardrails:** a budget alert at $1 and $5, no NAT gateway, no load balancer, no always-on database instance, log retention limits, and a TTL tag plus a teardown command for anything temporary (for example a load-test environment).

**Rough estimate, to be validated in phase 3:**

| Phase | Cost |
|---|---|
| Building locally | $0 |
| Running in the cloud | ≈ $0–1/month after any credits |
| Optional load-test or demo days | a few dollars, one-time |
| Teardown | $0 left behind |

New AWS accounts (opened after July 15, 2025) reportedly get up to **$200 in credits on a 6-month free plan** ([Rackspace guide](https://spot.rackspace.com/blog/aws-free-tier), [InfraTally](https://infratally.com/articles/aws-free-tier-2026/)). These are secondary sources, so check the official AWS Free Tier page before relying on them.

**What this costs the transit concept:**

- Polling every minute instead of every 15–30 seconds makes arrival estimates coarser, roughly ±1 minute. That's acceptable for delays measured in minutes, and worth documenting as a deliberate tradeoff.
- The architecture is still a **modular monolith**: one codebase with a few entry points (API, ingest, rollup, alerts), not microservices.
- **Fallback if the free-tier math doesn't hold:** run collection for a 2–4 week campaign, publish the results as a static site (a permanent $0 demo), and delete the collector.

**Cost fit of the alternatives:** the recall matcher (A), recurring-charge detector (C) and volunteer scheduler (E) are naturally request-driven plus a daily job, so they are $0 at rest with less design effort. This constraint doesn't change the ranking. It makes B's design more interesting and adds a cost-engineering story for interviews.

## Decisions (resolved 2026-10-18)

1. **Concept:** B, transit reliability tracker ("Stopwatch", working name).
2. **Starting agency:** MBTA (keyless GTFS-Realtime feeds; LAMP available for validation).
3. **Stack direction:** Python (FastAPI) + TypeScript/React + PostgreSQL, justified in [04-architecture.md](04-architecture.md).
4. **Budget:** $0 when idle, one-time costs only, fully deletable. Estimated ≈ $0.55/month steady state; see [04 §10.1](04-architecture.md).
5. **Open:** AWS account (new account with free-plan credits, or existing). The design works either way.
