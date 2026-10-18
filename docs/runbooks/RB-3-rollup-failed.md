# RB-3: Daily rollup failed, late, low coverage, or bad data published

**Alarms / signals:** `RollupLate` (SEV-3), `RollupLowCoverage` (SEV-3), a user report of implausible numbers.
**Owner:** operator. **Related:** [04 §9](../04-architecture.md#9-background-jobs), [ADR-009](../adr/0009-static-json-with-atomic-manifest-swap.md), [contracts §2](../contracts.md#2-blob-key-layout), [methodology](../methodology.md).

Conventions are in the [runbooks README](README.md#conventions-used-in-the-runbooks).

## Symptoms

- `RollupLate`: no `RollupSuccess` in the day window ending 06:00 ET. `data/v1/manifest.json` still has yesterday's `generated_at`.
- `RollupLowCoverage`: `RollupCoveragePct` < 80 for the service date. The quality gate blocked the publish, so the previous build is still live.
- A rider or advocate reports numbers that look wrong (for example a route that is "100% on time" or a p90 of several hours).

## Impact

- **Gate failed or job late:** the site shows data one day older than intended. Nothing wrong is published. Daily publication SLO: by 06:00 ET on 29 of 30 days (1 late day of budget).
- **Bad data slipped through the gate:** wrong numbers are public and may be cited. This is the serious case.

## Severity

- SEV-3 for late or blocked builds.
- **SEV-2 if bad data is published**; postmortem required and the changelog must mention it.

## Diagnose

1. **Did the job run, and how did it end?** Logs Insights on `/aws/lambda/stopwatch-prod-daily-rollup`:

   ```text
   fields @timestamp, level, message, error_type, duration_ms
   | sort @timestamp desc
   | limit 50
   ```

   ```text
   filter @type = "REPORT"
   | fields @timestamp, @duration, @maxMemoryUsed / 1000 / 1000 as mem_mb
   | sort @timestamp desc | limit 5
   ```

   Timeouts near 600 s or memory near 2,048 MB point at data volume; errors at start point at schedule or permissions.

2. **Read the quality report** for the service date (coverage, row-count delta vs the 7-day median, null rates, delay sanity):

   ```bash
   aws s3 cp s3://stopwatch-prod-lake/reports/quality/agency=mbta/service_date=2026-10-17.json - | jq .
   ```

3. **Was ingestion healthy that service day?** A gap shows up as low coverage. Check `IngestSuccess` for the day and the gaps in `health.json`; if ingestion was down, the low coverage is real and correct ([RB-1](RB-1-ingestion-stale.md)).

4. **Was the schedule current?** A new static GTFS version (or a failed `schedule-import`) can make every trip look unmatched:

   ```bash
   aws s3 cp s3://stopwatch-prod-lake/schedule/agency=mbta/current.json - | jq .
   ```

5. **Which build is live, and which builds exist?**

   ```bash
   curl -s https://<cloudfront-domain>/data/v1/manifest.json | jq '{build_id, generated_at}'
   aws s3 ls s3://stopwatch-prod-site/data/v1/builds/ | tail -5
   ```

6. **For a "wrong numbers" report**, spot-check three routes against raw events: pick a route/stop/hour cell, pull the minute event batches for that service date (`events/agency=mbta/dt=…/`), and recompute delay for a handful of trips by hand. Typical culprits: a time-zone or after-midnight bug ([methodology § GTFS time](../methodology.md#gtfs-time-pitfalls)), SKIPPED stops counted as served ([feed notes](../feed-notes.md)), or a schedule version mismatch.

## Mitigate

| Situation | Action |
|---|---|
| **Gate failed, data really incomplete** (ingest gap, feed outage) | Leave the previous build live; re-running will not help because missed minutes cannot be recovered. The next day's build moves the window past the gap. If the gap is long, decide whether to publish anyway with the coverage shown (a manual override, recorded in the incident notes). |
| **Gate failed for a bug** (schedule, SQL) | Fix, deploy, re-run the rollup for the date (below). |
| **Job failed or timed out** | Re-run for the date; if it was memory or time, raise limits in Terraform in a reviewed change. |
| **Bad data published** | Roll back the manifest immediately, then fix: `make publish-rollback BUILD=<previous build_id> ENV=prod` (effective within the 60 s manifest cache). |

Re-running the rollup for a specific service date in the cloud (handlers accept `{"date": "YYYY-MM-DD"}`):

```bash
aws lambda invoke --function-name stopwatch-prod-daily-rollup:live \
  --payload '{"date":"2026-10-17"}' --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 660 /tmp/rollup.json && jq . /tmp/rollup.json
```

Locally against the Compose stack: `make rollup DATE=2026-10-17`.

The rollup overwrites `service_date=` partitions and writes a new `build_id`, so re-running is safe.

## Verify

- `manifest.json` points at the intended `build_id` (wait 60 s for the cache):

  ```bash
  curl -s https://<cloudfront-domain>/data/v1/manifest.json | jq '.build_id, .agencies[0].window'
  ```

- The quality report for the date passes all gates.
- Spot-check three routes (a frequent bus route, a subway line, a low-frequency route) against raw events and the previous build; numbers should move only by the expected one day of data.
- `RollupLate` / `RollupLowCoverage` return to OK on the next run.

## Follow up

- If bad data was public: postmortem, a changelog entry naming the affected dates and pages, and a new gate or test that would have caught it.
- If the gate fired on correct-but-low data (an ingest outage), consider whether the ±40% row-count rule needs a known-gap exception.
- Delete builds older than the 14 retained if pruning did not run.
