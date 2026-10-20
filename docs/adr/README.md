# Architecture Decision Records

Each record captures one significant decision: the context at the time, what was decided, the alternatives and why they lost, the consequences we accept, and the signal that should make us look again. They expand the decision log in [04 §12](../04-architecture.md#12-decision-log-to-be-expanded-into-adrs).

| # | Decision | Status | Key tradeoff |
|---|---|---|---|
| [ADR-001](0001-modular-monolith-on-lambda.md) | Modular monolith on Lambda, one codebase, two zip packages | Accepted, 2026-10-18 | Simplicity and $0 idle vs cold starts and coarse deploys |
| [ADR-002](0002-observations-in-s3-parquet-duckdb.md) | Observations in S3/Parquet + DuckDB; OLTP in Postgres | Accepted, 2026-10-18 | Two storage systems vs fitting the free tier and using the right engine for each workload |
| [ADR-003](0003-poll-feeds-every-60-seconds.md) | Poll the feeds every 60 s | Accepted, 2026-10-18 | ±~1 min precision vs staying inside free tiers; validated against LAMP |
| [ADR-004](0004-neon-free-postgres-over-rds.md) | Neon free plan over RDS | Accepted, 2026-10-18 | Scale-to-zero and $0 vs an external vendor and ~0.5–1 s wake-up |
| [ADR-005](0005-api-gateway-http-api-over-function-urls.md) | API Gateway HTTP API over Function URLs | Accepted, 2026-10-18 | ~$0.01/month vs built-in throttling and simple same-origin routing |
| [ADR-006](0006-google-oidc-with-server-side-sessions.md) | Google OIDC + server-side sessions (PyJWT + httpx, not Authlib) | Accepted, 2026-10-18 | No password liability, revocable sessions vs a dependency on Google |
| [ADR-007](0007-terraform-over-cdk.md) | Terraform over CDK | Accepted, 2026-10-18 | Portability and recognition vs HCL instead of Python |
| [ADR-008](0008-async-invoke-and-dlq-for-alerts.md) | Async invoke + DLQ over SQS polling for alerts | Accepted, 2026-10-18 | Zero idle cost vs less buffering under burst |
| [ADR-009](0009-static-json-with-atomic-manifest-swap.md) | Static JSON builds with an atomic manifest swap | Accepted, 2026-10-18 | Instant, cacheable reads and one-command rollback vs data up to 24 h old |
| [ADR-010](0010-lambdas-outside-vpc.md) | Lambdas outside a VPC | Accepted, 2026-10-18 | Saves ≈ $32/month NAT vs no network isolation for database access |

## Statuses

- **Proposed:** under discussion in a pull request.
- **Accepted:** in effect.
- **Superseded by ADR-NNN:** replaced; kept for history. Never delete or rewrite an accepted ADR. Write a new one and link both ways.
- **Deprecated:** no longer relevant (for example, the feature was removed).

Small corrections (typos, broken links, updated numbers that do not change the decision) can be edited in place. An amendment that changes a detail but not the decision is noted in the Status line, as in ADR-006.

## Adding an ADR

1. Copy the template below to `docs/adr/NNNN-short-kebab-title.md`, using the next free number.
2. Write it **when the decision is made**, in the same pull request as the change it explains, with status *Proposed*.
3. Use numbers from the docs or from measurements (cost, limits, latency, feed facts), and date any number that can change.
4. Set the status to *Accepted* with the date when the PR merges. Add a row to the table above and to the decision log in [04 §12](../04-architecture.md#12-decision-log-to-be-expanded-into-adrs).
5. If it replaces an earlier ADR, mark that one *Superseded by ADR-NNNN* in the same PR.

## Template

```markdown
# ADR-NNN: <decision as a short imperative sentence>

- **Status:** Proposed | Accepted, YYYY-MM-DD | Superseded by ADR-NNN
- **Deciders:** <names>
- **Related:** <links to design docs, contracts, other ADRs, runbooks>

## Context
What forces are at play: requirements, constraints (budget, free-tier limits), measured facts. No solution yet.

## Decision
What we will do, specifically enough that a reviewer can check the code against it.

## Alternatives considered
| Alternative | Why rejected |
|---|---|

## Consequences
**Positive** — what gets easier.
**Negative** — what gets harder, what we now have to watch, and the mitigations.

## Revisit when
Concrete, observable triggers (a metric, a cost, a user need), not "if things change".
```
