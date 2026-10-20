# ADR-004: Neon (free plan) for PostgreSQL instead of Amazon RDS

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §2, §6.2](../04-architecture.md#62-postgresql-schema-mvp-and-should), [05 §10.5](../05-security-reliability.md#105-backups-and-disaster-recovery), [ADR-002](0002-observations-in-s3-parquet-duckdb.md), [ADR-010](0010-lambdas-outside-vpc.md), RB-7

## Context

Stopwatch needs a relational database for users, sessions, saved commutes, idempotency keys, rate-limit counters, the audit log, the transit catalog and `route_daily_metrics` (< 100 MB). Relational SQL is also a named skill in the market data behind the project (11 of 18 companies, 02).

Traffic is low and bursty: user requests during the day, `schedule-import` at 03:30 ET, `daily-rollup` at 04:15 ET, `maintenance` at 05:00 ET. For most of the day nothing touches the database, so a database billed per hour is paying for idle time.

Options checked against the $0-when-idle budget:

| Option | Idle cost | Notes |
|---|---|---|
| **Neon free plan** | $0 | 0.5 GB storage, 100 compute-hours/month, scales to zero, copy-on-write branches |
| Amazon RDS for PostgreSQL (smallest instance) | ≈ $12+/month | Never idle-free; needs a VPC |
| Aurora Serverless v2 | storage + I/O + capacity when awake | Needs a VPC, so Lambdas would need a VPC and, for internet egress, a NAT gateway (≈ $32/month, [ADR-010](0010-lambdas-outside-vpc.md)) |
| Self-managed Postgres on EC2 | hourly | Always on, and patching becomes the operator's job |
| DynamoDB | ≈ $0 | Not relational; joins, constraints and transactions across tables would move into code |

## Decision

- Use **PostgreSQL 17 on Neon's free plan**: one project, a `main` branch for prod and a `staging` branch.
- Two roles: `stopwatch_owner` for migrations and maintenance; `stopwatch_app` for the runtime, with DML on application tables and **only `INSERT, SELECT` on `audit_log`**.
- Connect over TLS with `sslmode=verify-full`; connection strings live in SSM SecureString parameters `database_url` and `database_owner_url`.
- Retry **connect only** with backoff (100 ms → 1.6 s, 4 tries) to absorb compute wake-up.
- Use Neon **branches** to rehearse each prod migration before applying it, and for restore drills.
- Protect data with Neon point-in-time restore plus a **nightly `pg_dump`** from GitHub Actions to `backups/postgres/{YYYY-MM-DD}.dump` (30-day lifecycle).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **RDS** | ≈ $12+/month minimum and never idle-free; also forces a VPC. |
| **Aurora Serverless v2** | VPC-only, which drags in NAT or VPC endpoints; storage and I/O billing on top. Overkill for < 100 MB. |
| **DynamoDB** | The schema is relational (users → commutes → alert rules, foreign keys to the catalog) and authorization relies on owner-scoped SQL; Postgres is also the stronger portfolio signal. |
| **Supabase / other hosted Postgres free tiers** | Comparable, but Neon's scale-to-zero compute and branching match the migration-rehearsal and restore-drill plan directly. Either would be an acceptable fallback; the code depends only on standard Postgres. |
| **SQLite on S3 / EFS** | No concurrent writers across Lambdas; EFS needs a VPC and costs per GB-month. |

## Consequences

**Positive**

- $0 at rest; the database sleeps between requests because the minute ingest path never touches it ([ADR-002](0002-observations-in-s3-parquet-duckdb.md)).
- Branching makes migration rehearsal and restore drills cheap and realistic.
- Standard Postgres: the app is portable to RDS or any other host by changing two SSM parameters.

**Negative**

- **Cold-start latency:** the first query after idle waits for Neon's compute to wake (~0.5–1 s). Together with a Lambda cold start this is why the API's cold-path target is p99 < 3 s.
- **An external vendor** outside the AWS account: separate status page, account security and terms. Free-plan limits (storage, compute-hours, PITR window, branch count) can change and are re-checked quarterly ([06 §11](../06-quality-operations.md#11-operating-cadence)).
- The database is reached over the public internet; Neon's IP allow-list cannot help because Lambda egress IPs are dynamic, so credential hygiene carries more weight ([ADR-010](0010-lambdas-outside-vpc.md)).
- The free-plan PITR window is short, so the nightly dump sets the realistic RPO at ≤ 24 h.
- Connection count per Lambda container must stay small (one connection per warm container, API reserved concurrency 10); a connection storm is handled by switching to Neon's pooled endpoint (RB-4).

## Revisit when

- Storage approaches 0.5 GB or compute approaches 100 CU-hours a month.
- Steady traffic makes the database awake most of the day anyway, or a paid plan is needed for another reason (longer PITR, private networking).
- Data sensitivity grows enough to require network-level isolation (PrivateLink or a VPC-hosted database).
