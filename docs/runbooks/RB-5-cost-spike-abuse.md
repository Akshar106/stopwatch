# RB-5: Cost spike, budget alert, throttling or abuse

**Alarms:** Budget actual > $1 (SEV-3), Budget forecast > $5 (SEV-2), `ApiThrottles` (SEV-3); also demo-creation or rate-limit spikes seen on the Cost & abuse dashboard.
**Owner:** operator. **Related:** [04 §10.1](../04-architecture.md#101-cost-estimate-prod-steady-state-after-any-credits), [05 §7](../05-security-reliability.md#7-rate-limiting-and-abuse), [ADR-005](../adr/0005-api-gateway-http-api-over-function-urls.md), [RB-6](RB-6-secret-leak.md).

Conventions are in the [runbooks README](README.md#conventions-used-in-the-runbooks).

## Symptoms

- AWS Budgets email: actual month-to-date spend above $1, or forecast above $5. Expected steady state is **≈ $0.55/month** (S3 requests ≈ $0.45, S3 storage ≈ $0.07, API Gateway ≈ $0.01; everything else inside free tiers).
- `ApiThrottles`: the API function hit its reserved concurrency (10) for 5 minutes.
- Spikes in `POST /auth/demo` (limit 3/hour per IP prefix, 500 active), rate-limit blocks, or `AskCostMicroUSD` approaching the $1/month cap.

## Impact

- Money: the project's core constraint is "no recurring bill". A forecast above $5 is treated as an outage.
- Throttling: legitimate users get 429/503 from the API; public static pages are unaffected.
- Abuse can also exhaust Neon's free compute-hours, which takes the API down ([RB-4](RB-4-api-errors-latency.md)).

## Severity

- SEV-2: forecast > $5, or spend growing hour over hour.
- SEV-3: actual > $1, throttling, or contained abuse.

## Diagnose

1. **Which service is spending?** Cost Explorer, filtered by tag `project=stopwatch`, grouped by service (cost data lags by up to a day):

   ```bash
   aws ce get-cost-and-usage \
     --time-period Start=$(date -u +%Y-%m-01),End=$(date -u -v+1d +%F) \
     --granularity DAILY --metrics UnblendedCost \
     --filter '{"Tags":{"Key":"project","Values":["stopwatch"]}}' \
     --group-by Type=DIMENSION,Key=SERVICE
   ```

   Also check **untagged** spend (remove the filter): a forgotten load-test environment, a NAT gateway, or a resource created outside Terraform will not carry the tag.

2. **Which function is invoked too often?** Cost & abuse dashboard, or:

   ```bash
   for fn in api ingest-tick schedule-import daily-rollup maintenance notify lamp-validate; do
     printf '%-16s ' $fn
     aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
       --dimensions Name=FunctionName,Value=stopwatch-prod-$fn \
       --start-time $(date -u -v-24H +%FT%TZ) --end-time $(date -u +%FT%TZ) \
       --period 86400 --statistics Sum --query 'Datapoints[0].Sum' --output text
   done
   ```

   Normal daily counts: `ingest-tick` 1,440; each daily job 1; `api` in the hundreds.

3. **Who is calling the API?** API Gateway access logs:

   ```text
   fields @timestamp, routeKey, status
   | stats count(*) as requests by routeKey, status
   | sort requests desc | limit 20
   ```

   Client IPs come only from `CloudFront-Viewer-Address`; the API ignores `X-Forwarded-For`. If abusive traffic is reaching the API **without** going through CloudFront (high Lambda invocations but low CloudFront request counts, or many `403 origin` responses in the API log), the `X-Origin-Verify` secret may have leaked: rotate it ([RB-6](RB-6-secret-leak.md)).

   And the audit log (Postgres, read-only session as the owner role):

   ```sql
   select ip_prefix, action, outcome, count(*)
   from audit_log
   where at > now() - interval '1 hour'
   group by 1, 2, 3 order by 4 desc limit 20;

   select count(*) filter (where created_at > now() - interval '1 hour') as demo_last_hour,
          count(*) as demo_active
   from users where is_demo;
   ```

4. **Is S3 growing unexpectedly?** Check bucket sizes in the S3 console (Storage Lens) or CloudWatch `BucketSizeBytes`. Note that if the lake bucket is versioned, every per-minute overwrite of `state/mbta/latest.json.gz` (~170 KB) keeps a noncurrent version unless a lifecycle rule expires them: about 7 GB a month.

## Mitigate (fastest first)

1. **Turn off the costly feature.** Set `DEMO_ENABLED=false` and/or `ASK_ENABLED=false` in `infra/envs/prod/terraform.tfvars` and run `make up ENV=prod`. Feature flags are environment variables, and the `live` alias points at an immutable version, so a flag only takes effect through a deploy that publishes a new version (Terraform or the deploy workflow), not through editing `$LATEST`.
2. **Lower reserved concurrency** on the offending function (instant, CLI; record as drift):

   ```bash
   aws lambda put-function-concurrency --function-name stopwatch-prod-api --reserved-concurrent-executions 2
   ```

3. **Tighten API Gateway throttles** (instant):

   ```bash
   aws apigatewayv2 update-stage --api-id <api-id> --stage-name '$default' \
     --default-route-settings ThrottlingRateLimit=5,ThrottlingBurstLimit=10
   ```

4. **Last resort: stop the API.** Public static pages stay up.

   ```bash
   aws lambda put-function-concurrency --function-name stopwatch-prod-api --reserved-concurrent-executions 0
   ```

5. **Runaway job or loop** (for example a scheduler misconfiguration invoking a job every minute): disable that schedule (`aws scheduler update-schedule … --state DISABLED` requires re-sending the full schedule definition, so prefer fixing it in Terraform and `make up ENV=prod`), or set the function's reserved concurrency to 0.
6. **Forgotten environment:** `make down ENV=staging` (or the load-test environment). Nothing in staging holds irreplaceable data.

## Verify

- Invocation counts back to normal; throttles at 0 (unless deliberately throttling).
- Cost Explorer daily spend flat for the next 24–48 h (it lags), and the Budgets forecast below $5.
- Demo creation rate back under 3/hour per IP prefix.

## Follow up

- Adjust quotas or limits in a reviewed change; restore any temporary throttles or concurrency caps through Terraform.
- If abuse was targeted, consider AWS WAF rate-based rules on CloudFront (adds cost; write an ADR first).
- Write up the incident (postmortem for SEV-2) with the cost impact in dollars.
