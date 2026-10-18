# Postmortem: <short title>

<!--
Copy to docs/postmortems/YYYY-MM-DD-short-title.md (date = incident start, America/New_York).
Blameless: describe what the system and the process allowed, not who made a mistake.
Every SEV-2 gets one (docs/06 §9). Link it from CHANGELOG.md when users were affected.
-->

| | |
|---|---|
| **Status** | Draft / Final |
| **Severity** | SEV-2 / SEV-3 |
| **Date** | YYYY-MM-DD |
| **Duration** | HH:MM (detection → resolution); HH:MM (start of impact → resolution) |
| **Alarm / detection** | e.g. `IngestStale`, user report, drift check |
| **Runbook used** | e.g. [RB-1](../runbooks/RB-1-ingestion-stale.md) |
| **Author** | |
| **Reviewed** | YYYY-MM-DD |

## Summary

Two or three sentences: what happened, who or what was affected, how it was fixed.

## Impact

- **Users:** what riders saw (pages, features), how many if known (sessions, demo users, alert subscribers).
- **Data:** minutes of observations lost (unrecoverable for bus), service dates with reduced coverage, published builds affected, user data affected.
- **SLOs:** error budget consumed (e.g. 47 of 432 ingest minutes this month; API 5xx minutes; late publication days).
- **Cost:** dollars, if any.

## Timeline (UTC; ET in parentheses where useful)

| Time | Event |
|---|---|
| | Trigger (change, upstream event) |
| | Impact begins |
| | Detected (alarm, report) |
| | Acknowledged |
| | Mitigation applied |
| | Impact ends |
| | Root cause confirmed |

## Root cause

Explain the mechanism. Then ask "why?" until you reach something the process can change (5 whys):

1. Why did … ?
2. Why … ?
3. Why … ?
4. Why … ?
5. Why … ?

## Contributing factors

Things that made it worse or slower to fix (missing alert, unclear runbook step, test gap, free-tier limit, upstream behavior).

## What went well

-

## What did not go well

-

## Where we got lucky

-

## Action items

| # | Action | Type (prevent / detect / mitigate / process) | Owner | Due | Issue |
|---|---|---|---|---|---|
| 1 | | | | | |

## Lessons and follow-ups to docs

- Runbooks, ADRs, [feed notes](../feed-notes.md) or [methodology](../methodology.md) updated? Link the PRs.
- Changelog entry (if users were affected):
