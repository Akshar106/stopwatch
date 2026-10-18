# How AI tools were used on Stopwatch

*Started 2026-10-18. Kept up to date as the project goes on; the author adds to the last two sections over time.*

## Summary

Stopwatch is built with heavy use of an AI coding agent. The planning documents ([01](01-market-research.md)–[08](08-portfolio-kit.md)), the design, most of the code, and the engineering documentation (ADRs, runbooks, methodology, this page) were produced with **Claude Code** (Anthropic's AI coding agent), working under the author's direction: the author set the goals and constraints (a $0-when-idle budget, the target job market, one agency first), chose between options, and reviewed the output.

This page exists so a reviewer can judge the work with that in mind. The rule the project follows is simple: **AI output is a draft until something independent of the AI has checked it**: a test, a measurement against live data, a primary source, or the author's own review.

## What AI was used for

| Area | What the agent did | What the author did |
|---|---|---|
| Market research ([01](01-market-research.md)) | Collected and coded job postings, wrote the analysis scripts in `research/` | Set the scope (US early-career roles), checked the conclusions against the raw CSV |
| Concept and design ([02](02-concept-selection.md)–[07](07-repo-and-roadmap.md)) | Drafted options, scoring, architecture, schema, threat model, cost model, roadmap | Chose the concept and the budget constraint; accepted or changed each decision |
| Code (`backend/`, `frontend/`, `infra/`) | Wrote most modules and tests | Reviews every diff before merging; owns the decisions recorded in ADRs |
| Documentation | Drafted ADRs, runbooks, methodology, API reference, privacy policy, contributing guide | Reviews for accuracy; fills in measured numbers only after measuring them |
| Data investigation ([feed notes](feed-notes.md)) | Fetched and decoded live MBTA snapshots, wrote analysis scripts, summarized findings | Decides what the pipeline does about them |

## How output was verified

These checks are the project's verification gates, wired into CI as the code lands. As of 2026-10-18 the test layout exists and most suites are being written alongside the modules they cover; a row describes a check, not a claim that it already passes.

| Check | What it catches | Where |
|---|---|---|
| **Property-based tests** (Hypothesis) on the pure core: no duplicate arrivals when ticks are shuffled, `est_arrival ≤ observed_at`, replaying the same snapshots gives identical output, a missing tick yields only low-confidence events | Plausible-looking inference code that is wrong on edge cases | `backend/tests/property/` |
| **Replay ("golden") tests** on recorded MBTA snapshot sequences; changing a golden file needs a reviewed diff | Silent behavior changes | `backend/tests/replay/`, `make replay` |
| **Hand-built GTFS fixture** with a trip at `25:10:00` and a daylight-saving date | Off-by-one-hour and off-by-one-day time bugs | `backend/tests/fixtures/gtfs_mini/` |
| **Integration tests** against Postgres 17, with migrations run up/down/up and the least-privilege app role | SQL, grants and migrations that only work as a superuser | `backend/tests/integration/` |
| **Authorization matrix**: every endpoint × {anonymous, demo user, user A, user B} | Broken object-level authorization (the most likely serious bug in generated API code) | `backend/tests/api/` |
| **Static checks**: ruff, mypy (strict on `core`), import-linter module contracts, Semgrep rules (raw SQL, PII in logs, missing owner scope), gitleaks, dependency audits, Checkov | Boundary violations, injection patterns, leaked secrets, vulnerable dependencies | CI ([06 §2, §7](06-quality-operations.md#2-cicd-github-actions)) |
| **Manual review** of every diff, including tests (a generated test can assert the wrong thing) | Misunderstood requirements, over-engineering, invented APIs | PRs |
| **Live-feed checks**: claims about the MBTA feed are tested against real snapshots, not assumed | Wrong assumptions about upstream data | [feed notes](feed-notes.md), nightly drift check |
| **Primary sources** for prices, free-tier limits and API behavior (AWS pricing pages, MBTA documentation), each dated | Outdated or invented numbers | [04 §10.1](04-architecture.md#101-cost-estimate-prod-steady-state-after-any-credits) |
| **Cost checks**: AWS Budgets at $1/$5, monthly Cost Explorer review against the ≈ $0.55/month estimate | Designs that are cheap on paper only | [RB-5](runbooks/RB-5-cost-spike-abuse.md) |
| **Accuracy measurement** against MBTA LAMP for subway arrivals (planned weekly) | Inference that is self-consistent but wrong | [methodology §10](methodology.md#10-validation) |

### Examples where verification changed the result

- **The 18% SKIPPED question.** The product spec recorded that 18% of stop updates were SKIPPED and guessed "detours? flag stops?". Checking live snapshots on 2026-10-18 showed the flag-stop guess was wrong (skipped stops are ordinary pickup/drop-off stops) and that the share is dominated by placeholder trips up to a day ahead on about 20 detoured bus routes; among trips actually carrying predictions, only 1.9% of stops are skipped. It also found buses physically stopping at stops marked SKIPPED. The pipeline rules changed accordingly ([feed notes](feed-notes.md)).
- **CSV parsing of the MBTA schedule.** During the same investigation, DuckDB's automatic CSV detection failed on `trips.txt` (line 43,086 is the first quoted field), because it sniffs only the first rows. The schedule import must set CSV quoting explicitly; this was found by running the code on the real 25 MB feed, not by review.
- **OIDC library.** Early drafts of the design docs named Authlib; the implementation verifies Google ID tokens with PyJWT's `PyJWKClient` and does the code exchange with httpx, and [ADR-006](adr/0006-google-oidc-with-server-side-sessions.md) records why.

## What the author should be able to explain without AI

The project is only credible if the author can defend it unaided ([08 §8](08-portfolio-kit.md#8-final-credibility-checklist)). The author should be able to explain, from memory and in their own words:

- [ ] The architecture: the three data paths (minute ingest → S3, daily DuckDB batch → static JSON, user API → Postgres) and why each store was chosen.
- [ ] Arrival inference: diffing snapshots, the three methods, confidence levels, why a vanished trip is not proof of service, and how SKIPPED stops are handled.
- [ ] GTFS time: times past 24:00, "noon minus 12 h", what happens on the DST dates, service day vs calendar day.
- [ ] The metrics: delay, the on-time window, why p50/p90 and not the mean, the excess-wait-time formula and a worked example, coverage, minimum sample size.
- [ ] Idempotency and concurrency: reserved concurrency 1, the S3 `If-Match` compare-and-swap, deterministic keys, dedup in compaction, `Idempotency-Key`, `dedupe_key`.
- [ ] Security: the OIDC authorization-code + PKCE flow (what `state`, `nonce` and the verifier each prevent), server-side sessions vs JWTs, the CSRF layers, object-level authorization and why mismatches return 404.
- [ ] Operations: the SLOs and error-budget arithmetic (432 minutes/month), what each alarm means, and how to run each runbook's mitigation.
- [ ] The cost model, line by line, and what would change it (sub-minute polling, a NAT gateway, RDS).
- [ ] Every runtime dependency in `backend/pyproject.toml` and `frontend/package.json`: what it does and why it is there.
- [ ] How to rewrite any `core` module (inference, GTFS time, metrics) without AI help, using the tests as the specification.

## Rejected AI suggestions

AI suggestions the author rejected, and why. Filled in by the author as they happen; record the date, the suggestion, the reason, and what was done instead.

| Date | Suggestion | Why rejected | What was done instead |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

## Limits of this account

- "Most of the code" is an honest approximation, not a measured share.
- Review catches a lot but not everything; the test suite and the measurements above are the stronger evidence, and the [known limitations](methodology.md#9-known-limitations) list what is still unverified.
