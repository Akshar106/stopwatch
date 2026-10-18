# RB-2: Feed parse errors and schema/semantics drift

**Alarms / signals:** `IngestErrorRate` (SEV-3) with `error_type=ParseError`; the nightly feed-drift check opening a GitHub issue.
**Owner:** operator. **Related:** [05 §4 (unsafe consumption of APIs)](../05-security-reliability.md#4-owasp-risk-coverage), [06 §1 (feed-drift check)](../06-quality-operations.md#1-testing-strategy), [feed notes](../feed-notes.md), [RB-1](RB-1-ingestion-stale.md).

Conventions are in the [runbooks README](README.md#conventions-used-in-the-runbooks).

## Symptoms

- Ticks fail with protobuf decode errors, value-sanity failures (timestamps outside ±1 day, impossible stop sequences) or byte-cap errors.
- Payloads that failed to parse appear under `s3://stopwatch-prod-lake/raw/agency=mbta/errors/`.
- Or nothing fails, but the nightly drift check reports that an assumption no longer holds. The assumptions and their 2026-10-18 baselines are in [feed notes](../feed-notes.md):

| Assumption | Baseline (2026-10-18) |
|---|---|
| Feed advances every minute; header ≤ a few seconds old at fetch | 1–4 s |
| No `delay` fields; delay must be computed from the schedule | 0 delay fields in 8 snapshots |
| Past stops are dropped (except the vehicle's current stop, briefly) | ~0.8% of non-skipped stop updates have a past time; median 29 s |
| SKIPPED share of all stop updates | 17.6–17.8%, almost all bus |
| SKIPPED share among trips that carry predictions | 1.9% |
| Trips dated tomorrow appear only as SKIPPED placeholders | 365 of 365 |
| Every SKIPPED stop matches the static `stop_times` (trip, sequence, stop) | 4,073 of 4,073 |

## Impact

- Hard parse failures stop ingestion for the agency: same impact as [RB-1](RB-1-ingestion-stale.md) (lost minutes are unrecoverable for bus).
- Silent semantic drift is worse: inference keeps running but may emit **wrong arrivals** (for example, if SKIPPED stops start disappearing like served stops, or past stops stop being dropped). Published numbers could be wrong until caught.

## Severity

- SEV-2 if every tick is failing (ingestion stopped).
- SEV-3 for intermittent parse errors or drift reports; treat drift that affects inference as SEV-2 if numbers are already published from it.

## Diagnose

1. **Find failing payloads and the error:**

   ```bash
   aws s3 ls s3://stopwatch-prod-lake/raw/agency=mbta/errors/ | tail -5
   ```

   ```text
   # /aws/lambda/stopwatch-prod-ingest-tick
   fields @timestamp, error_type, message
   | filter level = "ERROR" and error_type like /Parse|Decode|Sanity/
   | stats count(*) as n, earliest(@timestamp) as first_seen, latest(@timestamp) as last_seen by error_type, message
   ```

2. **Copy one payload into a new, empty local directory and replay it** (feed payloads are untrusted input; keep them out of the repo and out of directories containing code):

   ```bash
   mkdir -p ~/stopwatch-incident/$(date +%F)/payloads
   aws s3 cp s3://stopwatch-prod-lake/raw/agency=mbta/errors/<timestamp>-tu.pb ~/stopwatch-incident/$(date +%F)/payloads/
   make replay DIR=$HOME/stopwatch-incident/$(date +%F)/payloads
   ```

3. **Compare with the source of truth:** the [MBTA GTFS-Realtime documentation](https://github.com/mbta/gtfs-documentation/blob/master/reference/gtfs-realtime.md) and its commit history, the [GTFS-Realtime reference](https://gtfs.org/realtime/reference/), and MBTA developer announcements. Note the date of any change.

4. **For drift reports**, re-run the feed investigation against a few fresh snapshots (`make record-fixtures MINUTES=10`) and compare each baseline in the table above. Decide whether the change is a new *format* (parser fix) or new *semantics* (inference change).

## Mitigate

1. **Patch the parser behind a test that uses the captured payload** (trimmed, with no secrets or personal data; feed data is public). Deploy through the normal pipeline.
2. **If the new behavior is ambiguous**, ship a guard that skips and logs the unknown entities instead of failing the whole tick. A tick that ingests 99% of trips is better than none, and the skipped entities are counted in the logs.
3. **Semantic drift that affects inference** (for example SKIPPED or past-stop behavior): pause publishing rather than ingestion. Ingestion keeps collecting irreplaceable raw events; the rollup's quality gate or a manual hold keeps the previous build live ([RB-3](RB-3-rollup-failed.md)). Fix inference, then re-run the rollup for affected dates.
4. **Bad deploy** of parser changes: `make rollback FN=ingest-tick ENV=prod`.

## Verify

- `IngestErrorRate` back below 20% and falling to ~0; no new objects under `raw/agency=mbta/errors/`.
- The replay of the captured payload passes locally and in CI.
- The drift check passes on the next nightly run, or the issue is updated with the new, documented baseline.

## Follow up

- Add the payload (trimmed) to the replay fixtures in `backend/tests/fixtures/rt_snapshots/`.
- Update [feed notes](../feed-notes.md) with the new behavior, the date first seen, and the evidence.
- If inference rules changed, update the [methodology](../methodology.md) and note it in the [changelog](../../CHANGELOG.md).
- If published numbers were affected, write a postmortem and link it from the changelog.
