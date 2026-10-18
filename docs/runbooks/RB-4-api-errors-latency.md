# RB-4: API errors or high latency

**Alarms:** `Api5xx` (SEV-2), `ApiLatencyP95` (SEV-3).
**Owner:** operator. **Related:** [05 §10](../05-security-reliability.md#10-reliability), [ADR-004](../adr/0004-neon-free-postgres-over-rds.md), [ADR-005](../adr/0005-api-gateway-http-api-over-function-urls.md), [RB-5](RB-5-cost-spike-abuse.md).

Conventions are in the [runbooks README](README.md#conventions-used-in-the-runbooks).

## Symptoms

- `Api5xx`: more than 5% of at least 20 requests returned 5xx over 5 minutes.
- `ApiLatencyP95`: API Gateway p95 latency above 1 s for 15 minutes (target: p95 < 300 ms warm).
- Users cannot sign in, save commutes, or see "your commutes". Public pages (stop search, heatmaps, health) still load because they are static files.

## Impact

- Signed-in features fail or are slow. Public data is unaffected.
- API availability SLO: 99.5% non-5xx over 30 days (~3.6 h of budget).

## Severity

- SEV-2 for `Api5xx` (user-visible outage). SEV-3 for latency alone.

## Diagnose

1. **Which routes are failing?** API Gateway access logs (stage log group from the `api` Terraform module):

   ```text
   fields @timestamp, routeKey, status, responseLatency, integrationErrorMessage
   | filter status >= 500
   | stats count(*) as errors by routeKey, status
   | sort errors desc
   ```

   One route failing → a code path. Every route failing → the function, its configuration, or the database.

   Every request answered `403` with problem type `origin` ("Requests must come through the site") is not a 5xx, but it is the same outage from a user's point of view: CloudFront's `X-Origin-Verify` header and the API's `origin_verify_secret` disagree, typically after a partial `terraform apply` or a rotation without restarting the API. Fix with `make up ENV=prod`, then force new containers (below).

2. **What does the API log say?** `/aws/lambda/stopwatch-prod-api`:

   ```text
   fields @timestamp, level, message, error_type, request_id
   | filter level = "ERROR"
   | stats count(*) as n by error_type
   | sort n desc
   ```

   | `error_type` | Likely cause |
   |---|---|
   | `OperationalError`, connection timeout | Neon unavailable, waking slowly, or connection limit hit |
   | `ValidationError` at startup | Missing or invalid config/secret (pydantic-settings fails fast on cold start) |
   | Task timed out after 15 s | Slow query or Neon wake + retries exceeding the budget |
   | Any new exception type right after a deploy | Bad deploy |

3. **Cold starts vs warm latency:**

   ```text
   filter @type = "REPORT"
   | stats count(*) as invocations, count(@initDuration) as cold_starts,
           pct(@duration, 95) as p95_ms, avg(@initDuration) as avg_init_ms by bin(5m)
   ```

   A high cold-start ratio after idle periods is expected (cold path target p99 < 3 s). Sustained high warm p95 is not.

4. **Is Neon healthy?** Check [neonstatus.com](https://neonstatus.com) and the Neon console (compute state, connection count, storage vs the 0.5 GB limit, compute-hours vs 100/month). On the free plan, exhausting the monthly compute-hours can suspend the compute until the next billing period (check the current plan terms).

5. **Recent deploy?**

   ```bash
   aws lambda get-alias --function-name stopwatch-prod-api --name live --query FunctionVersion
   ```

6. **Throttling at the gateway or function?** `ApiThrottles` or many 429s point at [RB-5](RB-5-cost-spike-abuse.md).

## Mitigate

| Cause | Action |
|---|---|
| **Bad deploy** | `make rollback FN=api ENV=prod`. Migrations are expand/contract, so the previous version is compatible with the current schema. |
| **Neon incident** | Nothing to fix on our side. Public pages keep working. Post a status note (data-health page or repository README) that sign-in and saved commutes are temporarily unavailable. |
| **Neon free-plan compute-hours exhausted** | Find what kept the database awake (a job looping, a bot hitting `/me`); stop it ([RB-5](RB-5-cost-spike-abuse.md)). Upgrading the plan is a cost decision, not an incident fix. |
| **Connection storm** (many cold containers each opening a connection) | Lower API reserved concurrency, then switch `database_url` to Neon's pooled endpoint (`-pooler` host) and force new containers (see below). |
| **Missing or bad secret** | Fix the SSM parameter ([RB-6](RB-6-secret-leak.md) has the commands), then force new containers. |

Lower concurrency (CLI change = drift; copy it into Terraform afterwards):

```bash
aws lambda put-function-concurrency --function-name stopwatch-prod-api --reserved-concurrent-executions 4
```

**Forcing new containers:** secrets and config are read once per cold start, and the `live` alias points at an immutable published version, so changing an environment variable on `$LATEST` does nothing for live traffic. Re-run the deploy workflow for the current commit (it publishes a new version and moves `live`), or `make up ENV=prod` after the change is in `terraform.tfvars`.

## Verify

- `Api5xx` and `ApiLatencyP95` back to OK; 5xx rate near 0 in the access logs for 15 minutes.
- Smoke test from a browser: demo sign-in, list commutes, sign out. Or:

  ```bash
  curl -s https://<cloudfront-domain>/api/v1/healthz
  ```

## Follow up

- Postmortem for any SEV-2.
- If cold starts caused the latency alarm, record the measured cold-path p99 next to the 3 s target and decide whether the alarm threshold or the package needs work.
- Copy any CLI concurrency change into Terraform, or revert it.
