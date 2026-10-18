# 08 — Portfolio Kit

*Phase 4 · 2026-10-18 · fill every `[bracket]` with a **measured** value before using it. If a number isn't measured yet, leave the claim out.*

## 1. Documentation deliverables

| Deliverable | Audience | Contents | Ready by |
|---|---|---|---|
| `README.md` | Recruiter (30 s), engineer (5 min) | One-line pitch; live demo + demo-account link; GIF/screenshot; **numbers table** (coverage, inference error, freshness SLO, p95 latency, monthly cost, tests); architecture diagram; `make dev` quickstart; stack with links to ADRs; "known limitations"; roadmap | Week 12 |
| `docs/methodology.md` | Riders, advocates, interviewers | How arrivals are inferred; delay, on-time and excess-wait definitions; confidence levels; validation results; known biases | Week 7, updated week 13 |
| `docs/adr/0001…0010` | Engineers | Context → decision → alternatives → consequences, one page each | As decisions are made |
| `docs/runbooks/RB-1…7` + `restore-drill.md` | Operator, interviewers | Template from [06 §10](06-quality-operations.md); drill log with real timings | Week 11 |
| `docs/postmortems/` | Interviewers | At least one real incident write-up (blameless). An honest failure is more credible than none | When it happens (it will) |
| `docs/api.md` + `openapi.json` | Developers | Public JSON layout + dynamic API reference | Week 10 |
| `docs/privacy.md` | Users | Plain-language data inventory, retention, rights | Week 10 |
| `docs/ai-usage.md` | Interviewers | Which AI tools were used and for what, how output was reviewed and tested, examples of AI suggestions that were rejected and why | Ongoing |
| Demo video (2–3 min) | Recruiters | Problem (15 s) → stop page → saved commute → ops dashboard + an alarm → cost screenshot | Week 12 |
| Blog post: *"Running a 24/7 transit data pipeline for about fifty cents a month"* | Everyone | Story, architecture, hardest bug, numbers, lessons | Week 16 |

## 2. Résumé bullets

Three bullets: **impact → engineering → practices**. Each starts with a strong verb and carries real numbers.

1. **Built and launched Stopwatch, a transit-reliability web app** (Python/FastAPI, React/TypeScript, PostgreSQL) that ingests MBTA real-time feeds every minute (~[500K] stop events/day) and publishes stop-level delay analytics used by [N] riders.
2. **Designed a scale-to-zero AWS data pipeline** (Lambda, S3/Parquet, DuckDB, EventBridge, Terraform) sustaining [99.x]% ingestion freshness at ≈$[0.55]/month; validated inferred arrivals at [X] s median error against MBTA's official data.
3. **Shipped production practices end to end:** Google OIDC with server-side sessions, object-level authorization tests, CI/CD with keyless OIDC deploys and security scanning, SLO-based alerting with runbooks; [N] automated tests, [X]% core coverage, p95 API latency [X] ms.

*Tailoring:*

- **Backend/infra roles:** lead with bullet 2.
- **Full-stack roles:** swap bullet 3 for "Built an accessible React/TypeScript frontend with client-side stop search over 8K stops (< 100 ms), live predictions, and Lighthouse-gated performance (LCP [X] s on mobile)."

## 3. Repository description (GitHub "About")

> Stop-level transit reliability for riders. Ingests MBTA GTFS-Realtime every minute, infers arrivals, and publishes delay & headway analytics. Python · FastAPI · React · Postgres · DuckDB · AWS Lambda · Terraform. Runs 24/7 for under $1/month.

Topics: `gtfs-realtime`, `transit`, `fastapi`, `react`, `typescript`, `postgresql`, `duckdb`, `aws-lambda`, `terraform`, `serverless`, `data-pipeline`.

## 4. Elevator pitch (~30 seconds)

> "Transit apps tell you when the bus is *predicted* to come, but the prediction disappears once the bus passes, so nobody can tell you how reliable *your* stop is at *your* time. I built Stopwatch, which captures Boston's real-time transit feed every minute, works out when each bus actually arrived, and shows riders a reliability heatmap for their stop by hour and day. It runs 24/7 on a serverless pipeline for about fifty cents a month, and I validated its arrival estimates against the MBTA's official data, within [X] seconds median. [N] riders use it to plan their commutes."

## 5. Technical explanation (~2 minutes, for "tell me about a project")

1. **Problem (15 s).** The real-time feed only contains future predictions. Served stops vanish, so the history riders need is never recorded.
2. **Architecture (40 s).**
   - A modular monolith in Python, deployed as several Lambda entry points from one codebase.
   - Every minute a scheduled function fetches the feed, diffs it against the previous snapshot stored in S3, and emits arrival events. It runs with concurrency 1 and saves its state with an S3 compare-and-swap write.
   - A daily DuckDB job compacts events to Parquet, joins the schedule, computes delay and headway metrics, and publishes immutable JSON behind CloudFront with an atomic manifest swap.
   - User features (sign-in, saved commutes) are a FastAPI app on Postgres (Neon).
3. **Hardest problem (30 s).** Inferring arrival times from disappearing predictions, plus GTFS time semantics (times past 24:00, daylight-saving days). I made inference a pure function, property-tested it with Hypothesis, replay-tested it against recorded snapshots, and measured it against MBTA's official subway data.
4. **Results (20 s).** [Coverage]% of scheduled trips observed, [99.x]% freshness, [X] s median error, p95 API [X] ms, ≈$0.55/month, [N] users.
5. **Next (15 s).** Sub-minute freshness would need a long-running container (≈$5–10/month), which is a deliberate product/cost tradeoff. More agencies are config, not code.

## 6. Interview questions with answer outlines

### Architecture and design

1. **"Walk me through the architecture."** Draw context → containers ([04 §3–4](04-architecture.md)). Emphasize three data paths: minute ingest (S3), daily batch (DuckDB → static JSON), user API (Postgres). Mention $0 when idle as the organizing constraint.
2. **"Why a monolith and not microservices?"**
   - One developer, one deploy pipeline, shared domain types.
   - Boundaries are still enforced (import-linter) and functions are separated by IAM role and scaling profile.
   - I'd extract a service only when release cadence or scaling diverges.
   - Microservices would add network failure modes and cost with no benefit at this scale.
3. **"Why not keep everything in Postgres?"** Observations are append-only and columnar-scanned; Parquet + DuckDB fits that workload and costs pennies. Putting minute writes in Postgres would exceed the free 0.5 GB within weeks and keep the database awake 24/7, burning the compute quota. Postgres holds what's relational and transactional.
4. **"How would you scale to 50 agencies, or to 15-second freshness?"**
   - **Agencies:** one schedule per agency → independent state and failure domains; per-trip state in DynamoDB if it outgrows one object.
   - **Freshness:** a long-running Fargate Spot poller with checkpointing; cost goes from ≈$0 to roughly $5–10/month. I'd want to see user demand first.
   - **Reads:** already CDN-served.
5. **"Design the delay-alert system for 1M users."** (System-design extension)
   - Index rules by (route, stop, time window).
   - Evaluation is per tick in memory; it emits candidates to a queue.
   - Workers batch push sends; delivery is idempotent via a dedupe key.
   - Use per-user rate caps, DLQ, and backpressure.
   - Contrast with the current async-invoke design and why it's right at the current scale.

### Data and algorithms

6. **"How do you infer arrival times?"**
   - Diff consecutive snapshots: a stop disappearing means it was served.
   - The estimate is the last predicted time, refined by vehicle `STOPPED_AT` positions.
   - Confidence comes from prediction lead time.
   - Gaps produce low-confidence events, never silent guesses.
7. **"How accurate is it, and how do you know?"** Weekly comparison against MBTA LAMP official subway arrivals: median [X] s, p90 [Y] s. Bus has no official per-event ground truth in real time, so I use vehicle-position stops as a partial check and report coverage alongside every metric.
8. **"What's tricky about GTFS time?"**
   - Times can exceed 24:00 (service day ≠ calendar day).
   - Times are relative to noon minus 12 h, so daylight-saving days have 23 or 25 hours.
   - Added trips have no schedule.
   - Schedule versions change mid-season, so each service date joins against its valid version.
   - All of it is tested with a hand-built fixture.
9. **"Why median and p90 instead of average delay?"** Delay distributions are skewed. The mean hides the bad tail riders actually remember; p90 is "how bad does it get." For frequent routes, excess wait time matters more than schedule adherence.

### Reliability and operations

10. **"What happens if two ingest runs overlap?"** Reserved concurrency 1 prevents it in normal operation. If it ever happens, the state write uses `If-Match` (compare-and-swap) so the second writer fails instead of corrupting state. Event keys are deterministic and compaction dedups. At-least-once with idempotency; exactly-once isn't claimed.
11. **"The feed goes down for 20 minutes. What happens?"**
    - Ticks retry within their minute, then skip.
    - The `FeedStale` alarm fires and the site banner appears.
    - The gap is recorded in `health.json`.
    - Stops passed during the gap get low-confidence estimates or are excluded.
    - The rollup's coverage reflects it. No fabricated data.
12. **"What are your SLOs and how do you alert?"** 99% minute freshness (432 min/month error budget), daily publish by 06:00, API 99.5% non-5xx. Ten alarms with severities and runbooks. Then tell the real incident from `docs/postmortems/`.
13. **"How do you make sure published numbers are trustworthy?"**
    - The data-quality gate (coverage, row deltas, null rates) blocks the manifest swap.
    - Builds are immutable and rollback is one command.
    - The methodology is public, and coverage is shown next to every metric.

### Security and privacy

14. **"How do you stop one user from reading another's commutes?"** Repositories require `owner_id` and return 404 on mismatch. An authorization matrix test runs every endpoint as anonymous, demo user, user A and user B in CI. Schemathesis fuzzes the API. There is no admin surface in the app.
15. **"Why server-side sessions instead of JWTs?"** Instant revocation (logout, "sign out everywhere", incident response); tokens are stored hashed; an HttpOnly `__Host-` cookie is out of reach of JavaScript; same-origin API means no CORS. JWTs would add key management and make revocation harder, with no benefit for a single backend.
16. **"What's sensitive here?"** Saved commutes reveal home and work patterns. Minimized, never logged, deleted on request; "near me" runs entirely in the browser. Cost is also a security property: concurrency caps, quotas and budgets limit abuse.

### Testing, cost and AI

17. **"How do you test something driven by live, non-deterministic data?"** Separate the pure core from I/O. Property-based tests (invariants), replay tests against recorded snapshots (determinism), a hand-built GTFS fixture for edge cases, and a nightly drift check against the live feed to catch upstream changes.
18. **"How did you keep it under a dollar a month, and what's the biggest cost?"**
    - Scale-to-zero everything; no NAT, ALB or RDS.
    - Async invoke instead of an SQS poller.
    - Budgets and concurrency caps.
    - The biggest line is S3 PUTs from minute writes (~$0.45). In-memory state with checkpoints would halve it, but I chose simplicity.
19. **"How did you use AI tools?"** Point to `docs/ai-usage.md`: where AI helped (scaffolding, test generation, docs), how output was verified (tests first, review every diff, property tests caught [example]), and something AI suggested that I rejected and why. Be specific and honest. This was explicitly asked about in several postings.

### Behavioral

20. **"Tell me about a time data changed your mind."**
    - I first picked a household recall-alert app, then found three existing apps doing it and switched.
    - Later I had to choose 60-second polling for cost, and validated the accuracy rather than assuming it.
    - (Also the market research itself: requirements counted from 91 postings.)

## 7. Defensible tradeoffs

| Decision | Alternative | Why this choice | What it costs | Revisit when |
|---|---|---|---|---|
| Lambda + scheduler, 60 s polling | Always-on container polling every 15 s | ≈$0 when idle; within free tiers | ±~1 min precision; cold starts | Users need sub-minute data, or budget allows ~$10/month |
| S3/Parquet + DuckDB for observations | Postgres / TimescaleDB | Columnar fit; pennies; keeps the DB asleep | Two storage systems to understand | Ad-hoc analytics demand → Athena/Iceberg |
| Static JSON published daily | Query API per request | CDN-fast, cacheable, atomic rollback, no compute | Data up to 24 h old (the live panel covers "now") | Users need intraday stats |
| Neon free Postgres | RDS | Scale to zero, $0, branching | External vendor; ~0.5–1 s wake | Steady traffic or paid plan anyway |
| Google OIDC + sessions | Passwords / Cognito | No password liability; revocable sessions | Requires a Google account (demo accounts cover the rest) | Add GitHub as a second provider |
| API Gateway HTTP API | Lambda Function URLs | Throttling; same-origin routing simplicity | ~$0.01/month | Never at this scale |
| Async invoke + DLQ for alerts | SQS + Lambda poller | No idle polling cost | Less buffering under burst | > 1k active rules |
| Lambdas outside a VPC | VPC + NAT | Saves ~$32/month | No network isolation for DB access; relies on TLS and credentials | Handling more sensitive data |
| Monolith with enforced modules | Microservices | One developer; shared types; one pipeline | Coarser deploy granularity | Team or scaling profiles diverge |
| Terraform | CDK | Recognition, portability | HCL instead of Python | Team standard differs |

## 8. Final credibility checklist

**Proof it works**
- [ ] Live URL loads without login on a phone; demo account works in one click.
- [ ] README numbers are **measured and dated** (coverage, error, freshness, latency, cost, test count).
- [ ] Screenshots and video match the current UI.
- [ ] Cost Explorer screenshot for a full month included.

**Proof it's engineered**
- [ ] CI badge green; `make dev` works on a fresh clone (verified in a clean environment, e.g. a Codespace).
- [ ] ADRs exist for the major decisions and are dated.
- [ ] Runbooks exercised at least once (failure injection in staging); restore drill logged with timings.
- [ ] At least one real postmortem.
- [ ] OpenAPI spec committed; methodology page public.
- [ ] Known limitations listed in the README (60 s granularity, unofficial estimates, single region).

**Proof it's safe**
- [ ] gitleaks run on the **full history**: no secrets ever committed.
- [ ] Authorization matrix tests present and passing.
- [ ] Privacy page and "delete my account" work end to end.
- [ ] Budgets and alarms active (screenshot in docs).

**Proof it's yours**
- [ ] Commit history shows incremental progress over weeks, not a single dump.
- [ ] `docs/ai-usage.md` is honest and specific.
- [ ] You can draw the architecture and explain every dependency from memory, and rewrite any core module without AI help.
- [ ] You can answer every question in §6 out loud in under 2 minutes each (practice with a timer).

**Proof people use it**
- [ ] Real user count reported honestly, even if small.
- [ ] Two or three quotes or feedback items (with permission), and the changes they led to in the changelog.

**Presentation**
- [ ] Repo pinned on your GitHub profile; About text and topics set.
- [ ] Résumé links work; LinkedIn or portfolio post with the demo video.
- [ ] License file; clean issue tracker with a visible roadmap.
