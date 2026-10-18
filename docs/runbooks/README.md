# Runbooks

Operator procedures for Stopwatch incidents. Every CloudWatch alarm and AWS Budget alert has a runbook, and every alarm description contains its severity and a link to the runbook ([06 §9](../06-quality-operations.md#9-alerts)). Each runbook follows the same shape: **symptoms → impact → severity → diagnose → mitigate → verify → follow up**.

## Index

| Runbook | Covers |
|---|---|
| [RB-1](RB-1-ingestion-stale.md) | Ingestion stale or failing; upstream feed stale; alert-delivery DLQ |
| [RB-2](RB-2-feed-parse-errors.md) | Feed parse errors and schema/semantics drift |
| [RB-3](RB-3-rollup-failed.md) | Daily rollup failed, late, low coverage, or bad data published |
| [RB-4](RB-4-api-errors-latency.md) | API 5xx errors or high latency (including Neon problems) |
| [RB-5](RB-5-cost-spike-abuse.md) | Cost spike, budget alert, throttling, abuse |
| [RB-6](RB-6-secret-leak.md) | Suspected secret leak or account compromise |
| [RB-7](RB-7-restore-database.md) | Restore the Postgres database (incident or drill) |
| [Restore drill log](restore-drill.md) | Quarterly restore drill procedure and timings |
| [Postmortem template](../postmortems/TEMPLATE.md) | Blameless write-up after every SEV-2 |

## Alarm → runbook map

Ten CloudWatch alarms (the free-tier limit) and two AWS Budgets, all routed to the SNS topic `stopwatch-alerts` → operator email.

| Alarm | Condition | Severity | Runbook |
|---|---|---|---|
| `IngestStale` | `IngestSuccess` < 1 for 5 consecutive 1-min periods (missing data = breaching) | SEV-2 | [RB-1](RB-1-ingestion-stale.md) |
| `IngestErrorRate` | ingest Lambda errors / invocations > 20% over 15 min | SEV-3 | [RB-1](RB-1-ingestion-stale.md), then [RB-2](RB-2-feed-parse-errors.md) if `error_type=ParseError` |
| `FeedStale` | `FeedAgeSeconds` max > 300 for 10 min (upstream problem) | SEV-3 | [RB-1](RB-1-ingestion-stale.md) |
| `RollupLate` | `RollupSuccess` < 1 in the day window ending 06:00 ET | SEV-3 | [RB-3](RB-3-rollup-failed.md) |
| `RollupLowCoverage` | `RollupCoveragePct` < 80 | SEV-3 | [RB-3](RB-3-rollup-failed.md) |
| `Api5xx` | 5xx > 5% of ≥ 20 requests over 5 min | SEV-2 | [RB-4](RB-4-api-errors-latency.md) |
| `ApiLatencyP95` | p95 > 1 s for 15 min | SEV-3 | [RB-4](RB-4-api-errors-latency.md) |
| `ApiThrottles` | API function throttles > 0 for 5 min | SEV-3 | [RB-5](RB-5-cost-spike-abuse.md) |
| `AuthFailureSpike` | `AuthFailures` > 50 in 10 min | SEV-3 | [RB-6](RB-6-secret-leak.md) (and [RB-5](RB-5-cost-spike-abuse.md) if it is volume abuse) |
| `NotifyDLQ` *(should)* | DLQ visible messages > 0 | SEV-3 | [RB-1 § Alert DLQ](RB-1-ingestion-stale.md#alert-delivery-dlq-notifydlq) |
| Budget: actual > $1 | AWS Budgets | SEV-3 | [RB-5](RB-5-cost-spike-abuse.md) |
| Budget: forecast > $5 | AWS Budgets | SEV-2 | [RB-5](RB-5-cost-spike-abuse.md) |

Other signals without a dedicated alarm (the free tier allows ten): the nightly **feed-drift** issue ([RB-2](RB-2-feed-parse-errors.md)), a **missing nightly backup** detected by `maintenance` ([RB-7](RB-7-restore-database.md)), and a **user report** of implausible numbers ([RB-3](RB-3-rollup-failed.md)).

## Severity

| Level | Meaning | Response |
|---|---|---|
| **SEV-2** | User-visible outage or data loss in progress (ingestion stopped, API failing, forecast spend > $5) | Same day. Postmortem required. |
| **SEV-3** | Degradation (slow, partial, late, or upstream) | Within 48 h. Postmortem if it breaches an SLO or recurs. |

There is no SEV-1 tier: Stopwatch is a single-region, single-operator project with no paging rota ([03 §7](../03-product-spec.md#wont-non-goals)).

## Conventions used in the runbooks

Names follow the patterns in [contracts.md](../contracts.md); confirm them against `terraform output` if a module changes.

| Thing | Pattern (prod shown) |
|---|---|
| Lambda function | `stopwatch-prod-<function>`, e.g. `stopwatch-prod-ingest-tick`; traffic goes to the alias `live` |
| Log group | `/aws/lambda/stopwatch-prod-<function>` (14-day retention) |
| Data lake bucket | `stopwatch-prod-lake` (`LAKE_URL`) |
| Site bucket | `stopwatch-prod-site` (`SITE_URL`; served by CloudFront at `/`) |
| Custom metrics | namespace `Stopwatch`, dimension `env=prod` |
| SSM parameters | `/stopwatch/prod/<name>` (SecureString) |
| Region | `us-east-1` |

Logs are Powertools JSON lines with `level`, `message`, `function`, `env`, `version`, `request_id` or `tick_id`, `duration_ms`, and, on errors, `error_type` (and `http_status` for fetches). Lambda's own `REPORT` lines provide `@duration`, `@initDuration` and `@maxMemoryUsed`.

Run Logs Insights queries in the console, or from the CLI:

```bash
QID=$(aws logs start-query \
  --log-group-name /aws/lambda/stopwatch-prod-ingest-tick \
  --start-time $(date -u -v-30M +%s) --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, level, message, error_type | filter level = "ERROR" | sort @timestamp desc | limit 20' \
  --query queryId --output text)
sleep 5; aws logs get-query-results --query-id "$QID"
```

(`date -v-30M` is BSD/macOS syntax; on Linux use `date -u -d '30 min ago' +%s`.)

`make` targets used in the runbooks (`make help` lists them):

| Target | What it does |
|---|---|
| `make rollback FN=<function> ENV=<env>` | Move the function's `live` alias back to the previous published version |
| `make publish-rollback BUILD=<build_id> ENV=<env>` | Point `data/v1/manifest.json` at an earlier build (manifest swap) |
| `make up ENV=<env>` / `make down ENV=<env>` | Terraform apply / destroy for an environment (`make down ENV=prod` also needs `ALLOW_DATA_DESTROY=1`) |
| `make rollup DATE=YYYY-MM-DD` | Run the daily rollup locally against the local stack |
| `make replay DIR=<dir>` | Replay recorded snapshots locally through the ingest pipeline |
| `make ingest-once` | Run one ingest tick locally against the live feed |

> **Status of the deploy targets (2026-10-18):** `rollback`, `publish-rollback`, `up ENV=…` and `down ENV=…` are specified in [06 §4, §10](../06-quality-operations.md#4-infrastructure-as-code-terraform) and [07 §1](../07-repo-and-roadmap.md#1-repository-structure) but are not in the Makefile yet. Today `make down` with no `ENV` stops the local Compose stack; when the deploy targets land, keep that distinction explicit (a bare `make down` must never reach Terraform).

**Every change made from the CLI during an incident (concurrency, throttles, flags) is drift.** Copy it into `infra/envs/<env>/terraform.tfvars` before closing the incident, or the next `make up` reverts it.
