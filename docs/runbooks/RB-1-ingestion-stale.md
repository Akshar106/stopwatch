# RB-1: Ingestion stale or failing

**Alarms:** `IngestStale` (SEV-2), `IngestErrorRate` (SEV-3), `FeedStale` (SEV-3), `NotifyDLQ` (SEV-3, [last section](#alert-delivery-dlq-notifydlq)).
**Owner:** operator. **Related:** [04 §7, §9](../04-architecture.md#7-core-algorithm-arrival-inference), [05 §10.2](../05-security-reliability.md#102-failure-handling), [feed notes](../feed-notes.md), [RB-2](RB-2-feed-parse-errors.md).

Conventions (names, log fields, `make` targets) are in the [runbooks README](README.md#conventions-used-in-the-runbooks). Commands show `prod`; substitute the environment.

## Symptoms

- `IngestStale`: `IngestSuccess` < 1 for 5 consecutive minutes (missing data counts as breaching).
- `IngestErrorRate`: more than 20% of `ingest-tick` invocations errored over 15 minutes.
- `FeedStale`: `FeedAgeSeconds` (now − feed header timestamp) above 300 s for 10 minutes. Ticks may be "succeeding" as no-ops because the feed is not advancing.
- The site banner "data delayed" appears when the last success is more than 15 minutes old; `data/v1/health/mbta.json` shows `status: "stale"` or `"degraded"`.

## Impact

- **Bus observations missed during the outage are gone for good.** The feed holds only future predictions; there is nothing to back-fill. Each minute down costs about a minute of data (≈ 210–280 stop arrivals, [feed notes](../feed-notes.md)). Subway gaps can be partly back-filled from LAMP.
- Stops served during the gap get `low`-confidence estimates or none; the next day's coverage drops and `RollupLowCoverage` may follow.
- Ingestion freshness SLO: 99% of minutes per 30 days, an error budget of **432 minutes a month** ([05 §10.1](../05-security-reliability.md#101-slos-and-error-budgets)).
- Published pages keep working (static files); they just stop getting fresher.

## Severity

| Situation | Severity |
|---|---|
| `IngestStale` (our side not completing ticks) | **SEV-2** — respond the same day; postmortem if > 30 min |
| `FeedStale` with healthy ticks (MBTA not advancing) | SEV-3 — record the gap; nothing to fix on our side |
| `IngestErrorRate` with some ticks succeeding | SEV-3 — escalate to SEV-2 if it becomes `IngestStale` |

## Diagnose

Work top to bottom; stop when you find the cause.

**1. Is the scheduler invoking the function?**

```bash
aws scheduler list-schedules --name-prefix stopwatch-prod --query 'Schedules[].[Name,State]' --output table
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=stopwatch-prod-ingest-tick \
  --start-time $(date -u -v-30M +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 60 --statistics Sum
```

No invocations → the schedule is disabled (check `INGEST_ENABLED` in `infra/envs/prod/terraform.tfvars`), deleted, or its role lost `lambda:InvokeFunction`. Check the schedule's DLQ for failed deliveries.

**2. What do the last errors say?** Logs Insights on `/aws/lambda/stopwatch-prod-ingest-tick`:

```text
fields @timestamp, level, message, error_type, http_status, tick_id
| filter level = "ERROR"
| sort @timestamp desc
| limit 20
```

Error mix over the incident window:

```text
filter level = "ERROR"
| stats count(*) as errors by error_type, http_status
| sort errors desc
```

| `error_type` | Likely cause | Go to |
|---|---|---|
| `FetchError` with `http_status` 5xx / 429, or timeouts | MBTA CDN trouble | step 3 |
| `ResponseTooLargeError` | Feed grew past `max_feed_bytes` | step 3, then raise the cap in `platform/agencies.py` if the growth is legitimate |
| `ParseError` / protobuf `DecodeError` | Malformed or changed feed | [RB-2](RB-2-feed-parse-errors.md) |
| `PreconditionFailed` (S3 412 on the state write) | Two writers raced on the state object | step 5 |
| `AccessDenied` | IAM or bucket policy change | Compare the role with [contracts §1 IAM](../contracts.md#iam-least-privilege); `make up ENV=prod` to restore |
| Timeout (`Task timed out after 50.00 seconds`) | Slow upstream or oversized state | step 4 |

**3. Is it upstream?**

```bash
curl -sI https://cdn.mbta.com/realtime/TripUpdates.pb | grep -iE '^(HTTP|last-modified|content-length|date)'
```

Compare `last-modified` with `date`: a healthy feed is a few seconds old (on 2026-10-18 the header timestamp trailed the fetch by 1–4 s). Also check `FeedAgeSeconds` on the Pipeline dashboard and MBTA's developer channels. One request is enough; do not poll the CDN in a loop.

**4. Throttled, out of memory, or timing out?**

```text
filter @type = "REPORT"
| stats count(*) as runs, pct(@duration, 95) as p95_ms, max(@duration) as max_ms,
        max(@maxMemoryUsed / 1000 / 1000) as max_mem_mb by bin(5m)
```

```bash
aws lambda get-function-concurrency --function-name stopwatch-prod-ingest-tick   # expect ReservedConcurrentExecutions = 1
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles \
  --dimensions Name=FunctionName,Value=stopwatch-prod-ingest-tick \
  --start-time $(date -u -v-30M +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 60 --statistics Sum
```

Throttles mean a previous tick is still running (concurrency 1): look for durations near the 50 s timeout. Memory near 512 MB or p95 > 20 s suggests the state object has grown ([04 §11](../04-architecture.md#11-future-scaling-what-changes-and-when)):

```bash
aws s3api head-object --bucket stopwatch-prod-lake --key state/mbta/latest.json.gz --query '[ContentLength,LastModified]'
```

Normal size is ~170 KB.

**5. Is it our code?** Check whether a deploy happened just before the first failure:

```bash
aws lambda get-alias --function-name stopwatch-prod-ingest-tick --name live --query FunctionVersion
aws lambda list-versions-by-function --function-name stopwatch-prod-ingest-tick \
  --query 'Versions[-3:].[Version,LastModified,Description]' --output table
```

## Mitigate

| Cause | Action |
|---|---|
| **Upstream outage** | Nothing to fix. Confirm the banner shows and `health.json` lists the gap. Do not retry harder; ticks already retry twice within their minute. |
| **Bad deploy** | `make rollback FN=ingest-tick ENV=prod` (moves `live` to the previous version). |
| **Schedule disabled or broken** | Restore it from Terraform: `make up ENV=prod`. |
| **Corrupt or oversized state** | Delete the state object; the next tick cold-starts by indexing the current snapshot and emits nothing for that minute (marked low-confidence): `aws s3 rm s3://stopwatch-prod-lake/state/mbta/latest.json.gz` |
| **Timeouts from slow upstream** | Let the per-fetch timeouts (3 s connect / 10 s read) do their job; if ticks still exceed 50 s, roll back any change to fetch or retry settings. |
| **Feed grew past the byte cap** | Raise `max_feed_bytes` for the agency in `platform/agencies.py` in a reviewed PR, deploy. Do not disable the cap. |
| **Parse errors** | Follow [RB-2](RB-2-feed-parse-errors.md). |

To test one tick by hand after a fix (reserved concurrency 1 means it may throttle if the scheduled tick is running; retry a few seconds later):

```bash
aws lambda invoke --function-name stopwatch-prod-ingest-tick:live --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/tick.json && cat /tmp/tick.json
```

## Verify

- `IngestSuccess` is 1 per minute again for at least 5 consecutive minutes and the alarm returns to OK.
- `FeedAgeSeconds` is back under ~60 s.
- `data/v1/health/mbta.json` shows `status: "ok"` and a recent `last_success_at` within about 6 minutes (it is rewritten every 5 minutes and cached for 60 s):

```bash
curl -s https://<cloudfront-domain>/data/v1/health/mbta.json | jq '{status, last_success_at, feed_age_s, ticks_last_hour}'
```

- The site banner disappears.

## Follow up

- Record the gap (start, end, minutes) in the incident notes; `health.json` lists gaps ≥ 3 minutes for 7 days only.
- Postmortem ([template](../postmortems/TEMPLATE.md)) if ingestion was down more than 30 minutes or the cause was ours.
- Update error-budget tracking (432 min/month). If the budget is exhausted, feature work pauses until a reliability fix ships ([05 §10.1](../05-security-reliability.md#101-slos-and-error-budgets)).
- If the state was deleted, expect one low-confidence minute in the next rollup.
- Copy any CLI changes back into Terraform.

## Alert delivery DLQ (`NotifyDLQ`)

*Should-tier; applies once Web Push alerts ship ([ADR-008](../adr/0008-async-invoke-and-dlq-for-alerts.md)).*

- **Symptom:** the `notify` on-failure SQS queue has visible messages: an async invoke failed three times (1 attempt + 2 retries).
- **Impact:** some riders did not get a delay or cancellation alert. Ingestion itself is unaffected.
- **Diagnose:**

  ```text
  # /aws/lambda/stopwatch-prod-notify
  fields @timestamp, level, message, error_type, http_status
  | filter level = "ERROR" | sort @timestamp desc | limit 20
  ```

  ```bash
  aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names ApproximateNumberOfMessages
  aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 1   # payload: candidates, no user identifiers
  ```

  Typical causes: VAPID key missing or wrong in SSM, the push service rejecting requests, Neon unavailable ([RB-4](RB-4-api-errors-latency.md)), or a bad deploy.
- **Mitigate:** fix the cause (`make rollback FN=notify ENV=prod` for a bad deploy). Stale alerts are worthless, so **purge messages older than ~10 minutes rather than replaying them**; the dedupe key prevents duplicates if you do replay.
- **Verify:** DLQ empty; `NotificationsSent` increments on the next matching tick.
