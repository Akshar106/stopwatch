# ADR-008: Deliver delay alerts by asynchronous Lambda invoke with a dead-letter queue, not an SQS-polled worker

- **Status:** Accepted, 2026-10-18 (applies to the *should*-tier Web Push alerts)
- **Deciders:** project author
- **Related:** [04 §9](../04-architecture.md#9-background-jobs), [contracts §5](../contracts.md#5-alerts-should), [06 §9](../06-quality-operations.md#9-alerts), RB-1

## Context

Signed-in, non-demo riders can opt in to a push notification when the next bus in a saved commute window is predicted to be N+ minutes late (3–60) or is canceled. Alert rules are evaluated inside `ingest-tick` every minute against the fresh snapshot, using a snapshot of active rules at `config/alert_rules/{agency}.json` that contains no user identifiers. Matching candidates then need to be delivered through browser push services, which can be slow or fail.

Expected volume is tiny: zero most minutes, a handful at commute peaks. The target is 95% of alerts delivered within 2 minutes of the trigger ([05 §10.1](../05-security-reliability.md#101-slos-and-error-budgets)).

The obvious design is a queue between evaluation and delivery: SQS with a Lambda event source mapping. But a Lambda reading from SQS **long-polls continuously**, even when the queue is empty. With up to five pollers, idle polling alone can consume most of SQS's 1M-requests/month free tier.

## Decision

- `ingest-tick` **asynchronously invokes** `notify` (`InvocationType=Event`) with the candidate list ([contracts §5](../contracts.md#5-alerts-should)) only when at least one candidate exists.
- `notify` (256 MB, 30 s timeout, reserved concurrency 2) sends Web Push messages and records each in `notifications`.
- **Idempotency:** `notifications.dedupe_key = {rule_id}:{service_date}:{trip_id}:{kind}` is `UNIQUE`, so a retried invoke or a candidate that reappears on the next tick never notifies twice.
- **Retries and dead letters:** Lambda's async retry policy (2 retries) with an **on-failure destination SQS queue (DLQ)**. The `NotifyDLQ` alarm fires when the DLQ has any visible message.
- A push endpoint answering 404/410 is deleted.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **SQS queue + Lambda event source mapping** | Idle long-polling costs requests every minute of every day; at five pollers it uses a large share of the free tier for nothing. |
| **Send push messages inline in `ingest-tick`** | A slow push service would eat into the 50 s tick budget and delay ingestion, which is the system's most important SLO. Failures would be mixed into ingest error rates. |
| **EventBridge bus between ingest and notify** | Works, but adds a bus, a rule and another failure mode for one producer and one consumer. |
| **Step Functions** | Per-state-transition billing and much more machinery than "retry twice, then park". |
| **SNS mobile push / a third-party push vendor** | Web Push with VAPID needs no vendor; SNS adds cost and platform registrations aimed at native apps. |

## Consequences

**Positive**

- **Zero idle cost:** nothing runs and nothing polls when no rule matches.
- Ingest stays fast and isolated; the async invoke returns immediately.
- At-least-once delivery from Lambda's async queue plus a unique dedupe key gives effectively-once notifications without claiming exactly-once.
- Failures are visible (DLQ depth alarm) and replayable from the DLQ.

**Negative**

- **Less buffering under burst:** Lambda's internal async queue, `notify` reserved concurrency 2 and the 2-retry policy are the only smoothing. Fine at today's scale, not for thousands of simultaneous matches.
- Async invoke payloads are size-limited, so a very large candidate list must be split into several invokes.
- Events can sit in Lambda's async queue during throttling; the 2-minute delivery target can be missed without any error.
- `NotifyDLQ` currently routes to RB-1 (the producer side), which covers the first checks; a dedicated alerts runbook is needed once the feature ships.

## Revisit when

- More than ~1,000 active alert rules, or bursts that make `notify` throttle: index rules by (route, stop) in memory, batch sends, and put SQS between evaluation and delivery ([04 §11](../04-architecture.md#11-future-scaling-what-changes-and-when)).
- Delivery SLO misses show up in `notifications.sent_at − created_at`.
