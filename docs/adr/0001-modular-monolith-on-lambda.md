# ADR-001: Modular monolith on AWS Lambda, built from one codebase

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §1, §5, §9](../04-architecture.md), [contracts §1](../contracts.md#1-runtime-entry-points-aws-lambda-python313-arm64), [ADR-002](0002-observations-in-s3-parquet-duckdb.md), [ADR-010](0010-lambdas-outside-vpc.md)

## Context

Stopwatch has one developer working about 15 hours a week, and a budget of **$0 when idle** with no recurring $10–30/month bill ([02 cost model](../02-concept-selection.md#cost-model-added-after-budget-discussion)). It still needs several kinds of compute with very different profiles:

| Workload | Profile |
|---|---|
| `ingest-tick` | Every minute, 24/7: 43,200 runs a month, ~2 s each at 512 MB (≈ 43k GB-s) |
| `schedule-import`, `daily-rollup`, `maintenance`, `lamp-validate` | Once a day or week; memory-heavy (up to 2,048 MB and 4 GB of `/tmp` for DuckDB) |
| `api` | Low, bursty, per-user traffic; latency-sensitive |
| `notify` *(should)* | Rare, triggered by `ingest-tick` |

AWS Lambda's always-free allowance (1M requests and 400,000 GB-s a month, confirmed on AWS pricing pages 2026-10-18) covers all of this. Anything billed per hour (EC2, ECS/Fargate, an always-on container) does not fit the budget.

The domain also has one hard core (arrival inference, GTFS time math, metrics) that every entry point shares.

## Decision

- **One Python codebase** (`backend/src/stopwatch`) with enforced module boundaries, deployed as **seven Lambda functions** that differ only in handler, IAM role, memory, timeout and trigger ([contracts §1](../contracts.md)).
- **One build per commit, two zip packages:** `api.zip` (project + `ask` extra, no DuckDB, to keep cold starts small) and `jobs.zip` (project + `jobs` and `alerts` extras). Both are built for `aarch64-manylinux2014` and promoted unchanged from staging to prod, verified by SHA-256.
- **Boundaries are checked in CI** by `import-linter` (`backend/.importlinter`):
  - `core-is-pure`: `stopwatch.core` may not import any application module, `platform`, or an I/O library (boto3, httpx, SQLAlchemy, psycopg, DuckDB, FastAPI).
  - `layers`: entry points (`api`, `jobs`) → application modules → `platform` → `core`.
  - Application modules call each other only through their `service.py`.
- arm64 (Graviton) for every function.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Microservices** (one repo or service per concern) | Adds network failure modes, versioned contracts between services and several deploy pipelines for one developer, with no scaling or team-ownership need to justify them. |
| **One always-on container** (ECS Fargate or a small VM) running API + scheduler | Hourly billing breaks the $0-when-idle rule. A Fargate task polling every 15 s is estimated at $5–10/month ([04 §11](../04-architecture.md#11-future-scaling-what-changes-and-when)). |
| **One Lambda function with an internal router** for every trigger | Cannot give each workload its own IAM role (the API must not reach S3; ingest must not hold database credentials, [05 §3](../05-security-reliability.md#3-authorization)), memory size, timeout or reserved concurrency. |
| **Lambda container images** | Needs ECR and a registry push in the pipeline. Zip is enough because no function needs pyarrow or anything near the 250 MB unzipped limit. |
| **x86_64** | arm64 is cheaper per GB-s and the dependencies ship aarch64 wheels, so there is nothing to gain. |

## Consequences

**Positive**

- Idle cost is $0 for compute; steady-state compute stays inside the free allowance (≈ 43k GB-s of 400k for ingest, < 20k GB-s for everything else, [04 §10.1](../04-architecture.md#101-cost-estimate-prod-steady-state-after-any-credits)).
- Shared domain types and one test suite; refactors cross module lines safely.
- Least privilege per function comes for free: a compromised `api` cannot write the data lake.
- A module can later be extracted into its own service along a boundary that CI already enforces.

**Negative**

- **Cold starts** on the API: the cold path target is p99 < 3 s (Lambda init + Neon wake) instead of the warm p95 < 300 ms. Mitigated by the lean `api.zip`, lazy imports, and documenting the number.
- Deploy granularity is coarse: one commit redeploys every function (all from the same artifact).
- Lambda limits shape the design: 15-minute maximum runtime, 512 MB–10 GB `/tmp`, and EventBridge Scheduler's 1-minute minimum interval (see [ADR-003](0003-poll-feeds-every-60-seconds.md)).
- Two zip packages built from one codebase must be kept in step; the package-size check in CI guards against DuckDB leaking into `api.zip`.

## Revisit when

- A second engineer joins and module ownership diverges, or one module needs a different release cadence.
- A workload needs sub-minute scheduling or runs longer than ~10 minutes (for example, 15-second polling, which would move ingest to a long-running container).
- API p99 cold-path latency exceeds 3 s in practice and provisioned concurrency would cost more than a small container.
