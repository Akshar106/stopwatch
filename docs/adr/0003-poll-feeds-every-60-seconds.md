# ADR-003: Poll the GTFS-Realtime feeds every 60 seconds

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §7, §9](../04-architecture.md#7-core-algorithm-arrival-inference), [methodology](../methodology.md), [feed notes](../feed-notes.md), [ADR-001](0001-modular-monolith-on-lambda.md)

## Context

The MBTA TripUpdates feed contains only **future** predictions; a stop's prediction disappears once the vehicle has served it. Stopwatch infers arrivals by diffing consecutive snapshots ([04 §7](../04-architecture.md#7-core-algorithm-arrival-inference)), so the polling interval bounds how precisely an arrival can be placed in time.

Facts measured on 2026-10-18 (16:33–16:40 ET, 8 fetches about a minute apart; details in [feed notes](../feed-notes.md)):

- TripUpdates is ~650 KB and VehiclePositions ~49 KB per snapshot; both are keyless.
- The feed header timestamp was 1–4 s older than the fetch time on every fetch, so MBTA regenerates the feed far more often than once a minute. Every minute-apart fetch had advanced.
- Roughly 210–280 predicted stops disappeared per minute from trips that stayed in the feed.
- Vehicle positions were a median 5–9 s old.

Cost of each option (prod, per month; Lambda arm64 at $0.0000133334 per GB-s after the 400k GB-s free allowance):

| Option | Invocations | Compute | S3 PUTs (state + events) | Estimated cost |
|---|---|---|---|---|
| **60 s, EventBridge Scheduler → Lambda** | 43,200 | ≈ 43k GB-s (free) | ~87k | ≈ $0.45 |
| 30 s, a Lambda that runs two ticks per invocation and sleeps between them | 43,200 | ≈ 1.3M GB-s (billed while sleeping) | ~173k | ≈ $13 |
| 15 s, long-running ECS Fargate Spot poller with checkpointing | — | always on | fewer (in-memory state) | ≈ $5–10 ([04 §11](../04-architecture.md#11-future-scaling-what-changes-and-when)) |

EventBridge Scheduler's finest interval is one minute, so anything faster needs a process that stays alive.

## Decision

- Poll TripUpdates and VehiclePositions **once a minute** with an EventBridge Scheduler `rate(1 minute)` schedule invoking `ingest-tick` (reserved concurrency 1, 50 s timeout).
- Each fetch uses a 3 s connect / 10 s read timeout, a byte cap, and at most 2 retries with full-jitter backoff that never run past the tick's own minute.
- If the header timestamp has not advanced since the previous tick, the tick is a no-op, so a stuck feed never produces false "disappearances".
- Every inferred arrival carries a `method` and a `confidence` (`high` when the last prediction was ≤ 90 s ahead or a vehicle was seen stopped at the stop; `medium` ≤ 5 min; `low` otherwise, including after missed ticks).
- The accuracy cost is **measured, not assumed**: the weekly `lamp-validate` job compares subway estimates with MBTA LAMP and publishes the error. Targets: median absolute error ≤ 45 s, p90 ≤ 120 s.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **15 s polling in a container** | Better precision, but $5–10/month for an always-on task breaks the budget, before any user has asked for sub-minute data. |
| **30 s via a sleeping Lambda** | Pays for idle seconds; about 3× the GB-s free allowance. |
| **Two schedules offset by 30 s** | Scheduler cannot offset by seconds; both would fire on the same minute boundary. |
| **Polling less often (2–5 min)** | Cheaper, but the gap between snapshots would exceed typical stop-to-stop travel time on frequent bus routes, so most estimates would fall to `medium`/`low` confidence. |
| **Streaming from the MBTA v3 API** | The GTFS-Realtime files are pull-only. The v3 API can stream predictions, but only over a long-lived connection, which needs an always-on process (the same cost problem as 15 s polling) and a different, per-request data model. |

## Consequences

**Positive**

- Ingestion stays inside the Lambda and Scheduler free tiers; S3 PUTs (~$0.45) dominate the bill.
- One request per minute per feed is polite to MBTA's CDN.
- The tick is short (target p95 < 15 s), stateless between runs apart from the S3 state object, and easy to replay from recorded snapshots.

**Negative**

- Arrival precision is roughly **±1 minute**. A stop that disappears between two snapshots was served sometime in that minute; the estimate uses the last prediction, refined by a `STOPPED_AT` vehicle position when one exists.
- Short dwell events can be missed entirely by vehicle positions, so `vp_stopped` refinement covers only part of the arrivals.
- A missed tick costs a minute of irreplaceable bus data (subway gaps can be back-filled from LAMP).
- Every rider-facing page has to say that times are estimates with about a minute of uncertainty ([methodology](../methodology.md)).

## Revisit when

- The LAMP comparison shows median error above 45 s or p90 above 120 s and the cause is the polling interval rather than the inference method.
- Riders or advocates need sub-minute data (for example dwell-time analysis), or the budget allows about $10/month.
- MBTA changes the feed's update rate, size (it is capped by `max_feed_bytes`) or terms of use.
