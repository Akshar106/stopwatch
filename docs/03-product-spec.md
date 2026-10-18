# 03 — Product Spec: Stopwatch

*Phase 3 (design) · 2026-10-18 · "Stopwatch" is a working name*

## 1. Problem

Transit agencies publish real-time predictions, but **those predictions disappear the moment a bus passes the stop.** Nobody keeps the history at the level riders care about, and agencies report reliability as monthly, system-wide averages. A rider deciding when to leave home needs different answers:

- *"How late is the 1 bus at Mass Ave & Newbury on weekday mornings, really?"*
- *"Is the 8:05 worse than the 8:15?"*
- *"Did reliability on my route get worse after the schedule change?"*

**What the live MBTA feed looks like** (decoded 2026-10-18, Sunday mid-afternoon):

| Fact | Value |
|---|---|
| Trip updates in one snapshot | 1,329 (1,173 of them bus) |
| Stop-level predictions in one snapshot | 22,687 (median 14 per trip) |
| Vehicles reporting positions | 431; positions a median 7 s old |
| Stop visits that drop out of the feed per minute | about 360, i.e. served stops whose prediction vanishes |
| Trips marked canceled / added | 9 / 11 |
| Stop updates marked SKIPPED | 4,066 (18%). Needs investigation (detours? flag stops?) and is an early data-quality task |
| Schedule-delay field | absent. Delay must be computed by joining against the published schedule |
| Past stops | dropped from the feed. A stop's prediction disappears once the vehicle has served it |

So the data a rider needs exists, but it is gone within about a minute unless someone captures it.

**Existing work.** [TransitMatters](https://transitmatters.org/blog/2020/8/3/rolling-out-our-data-dashboard) covers Boston subway travel times. MBTA publishes official rapid-transit arrival data ([LAMP](https://www.mbta.com/developers/mbta-performance-data)) and monthly datasets. Neither gives riders a stop-level, hour-by-hour view of *bus* reliability with personal tracking. Stopwatch uses the official data as **ground truth to validate its own estimates**, not as a competitor.

## 2. Users

| Persona | Who | Job to be done | Must have |
|---|---|---|---|
| **Daily rider** (primary) | Commutes by bus or subway at roughly fixed times | "Tell me how reliable *my* stop is at *my* time, so I can plan." | Fast stop search, hour-by-day reliability, saved commute, mobile-friendly |
| **Advocate / reporter** (secondary) | Transit advocacy groups, local journalists, students | "Give me trustworthy evidence about a specific route." | Clear methodology, trends, data quality shown, shareable links, downloadable data |
| **Developer** (tertiary) | Builds transit tools | "Let me reuse the cleaned data." | Stable public JSON with documentation |
| **Operator** (you) | Runs the system | "Know when it breaks, fix it fast, keep cost near $0." | Alerts, dashboards, runbooks, one-command deploy and teardown |

## 3. Core workflows

1. **Check a stop (no login).** Search by stop name or "near me" → pick a route and direction → see a weekday/Saturday/Sunday × hour heatmap of typical delay, % on time, a worst-case (90th percentile) delay, and how much data backs each cell. A "right now" panel shows live predictions, fetched by the browser directly from the MBTA API.
2. **Compare.** On a route page, compare stops along the route or hours of the day, and see the 8-week trend.
3. **Save a commute (login).** Sign in with Google or use a temporary demo account → save route + direction + stop + days + time window → the home screen shows "your commutes" with personal reliability summaries.
4. **Get alerted** *(should)*. Opt in to a push notification when the next bus in your window is predicted to be N+ minutes late or is canceled.
5. **Ask in plain English** *(should)*. "Which is more reliable at 8 am, the 1 or the CT1?" → an answer built only from computed data, shown with its source numbers and a chart.
6. **Check data quality.** A public page shows feed freshness, % of scheduled trips observed per day, known gaps and incidents, and the methodology.
7. **Operate** (operator). Receive an alert → follow the runbook → fix → write a postmortem.

## 4. User stories (MVP) with acceptance criteria

| ID | Story | Acceptance criteria |
|---|---|---|
| US-1 | As a rider, I can find a stop by name so I can see its reliability. | Typing 2+ characters returns matching stops in < 100 ms (client-side index); results show the routes serving each stop; works with keyboard and screen reader. |
| US-2 | As a rider, I can find stops near me without my location leaving my phone. | The "near me" button uses browser geolocation; nearest stops are computed **in the browser** from the static stop index; no coordinates are sent to any server (verified by a test of network requests). |
| US-3 | As a rider, I can see how late a route runs at my stop by day type and hour. | The heatmap shows median delay, % on time (−1 to +5 min, configurable) and 90th-percentile delay; cells with fewer than 8 observations show "not enough data"; methodology is one click away. |
| US-4 | As a rider, I can see live predictions for my stop. | The browser fetches the MBTA v3 API directly (CORS allowed, 20 requests/min per IP unkeyed); this degrades gracefully to "live data unavailable"; Stopwatch servers are not called. |
| US-5 | As a rider on a frequent route, I can see how long I *actually* wait compared with the schedule. | For hours where scheduled headway is ≤ 12 min, show excess wait time; a tooltip explains it. |
| US-6 | As a rider, I can sign in with Google. | OIDC authorization code + PKCE; the session cookie is HttpOnly, Secure, SameSite; no passwords are stored. |
| US-7 | As a visitor, I can try a temporary demo account without Google. | One click creates an isolated demo user that expires in 24 h; limited to 3 commutes; rate-limited per IP; never shares data with other visitors. |
| US-8 | As a signed-in rider, I can save, edit and delete commutes. | Up to 20 commutes; validation (route serves that stop in that direction, time window valid); a retried create does not duplicate (Idempotency-Key); other users cannot read or modify them (tested). |
| US-9 | As a signed-in rider, I see a personal summary per commute. | Shows typical delay and worst case for the saved window and the trend vs the previous 4 weeks; computed from public data in the browser. |
| US-10 | As a user, I can export or delete my account. | Export returns JSON of everything stored about me; deletion removes my personal data immediately (cascade) and leaves only a pseudonymous audit record. |
| US-11 | As anyone, I can see whether the data is fresh and complete. | The health page shows last successful ingest time, today's coverage % and the last 30 days of gaps; a banner appears site-wide if data is > 15 min stale. |
| US-12 | As the operator, I am alerted when ingestion stops. | An alarm fires within 5 min of the last successful tick; the email links to the runbook. |

*Should-tier stories (alerts, Ask, a second agency, API keys) are specified in [04-architecture.md](04-architecture.md) and will be scheduled in the roadmap.*

## 5. Metric definitions (domain)

These are written down up front because they're where a transit analysis can quietly go wrong.

| Metric | Definition | Notes |
|---|---|---|
| **Estimated arrival** | Time a vehicle served a stop, inferred from the feed (see the inference section in 04) | Each estimate carries a `method` and a `confidence` |
| **Delay** | Estimated arrival − scheduled arrival (from the schedule valid for that service date) | GTFS times can exceed 24:00 and use "noon minus 12 h" as the reference, which matters on daylight-saving days |
| **On time** | −1 min ≤ delay ≤ +5 min | A common US convention; configurable per agency and stated on every page |
| **Typical / worst-case delay** | Median (p50) / 90th percentile (p90) of delay | Never reported as a mean alone; means hide bad tails |
| **Excess wait time (EWT)** | Average actual wait − average scheduled wait, where average wait = Σh² / (2·Σh) over headways h | Standard for high-frequency service, where riders don't use timetables |
| **Coverage** | Observed trips ÷ scheduled trips per service day | Shown wherever metrics are shown; below 80% → "low confidence" |
| **Canceled / skipped** | Trips marked CANCELED; stop updates marked SKIPPED | Counted separately, never as "on time" |

## 6. Success metrics

| Area | Metric | Target |
|---|---|---|
| Product | Riders who saved a commute | ≥ 15 real (non-demo) users within 8 weeks of launch |
| Product | Qualitative feedback | ≥ 5 riders interviewed or surveyed; changes logged in the changelog |
| Data quality | Daily coverage of scheduled trips (bus + subway) | ≥ 95% median |
| Data quality | Arrival-inference error vs MBTA LAMP (subway) | median absolute error ≤ 45 s, p90 ≤ 120 s, published |
| Reliability | Ingestion freshness SLO | ≥ 99% of minutes per 30 days have a successful ingest |
| Performance | Public pages | p95 time-to-first-byte < 200 ms (CDN); mobile LCP < 2.5 s |
| Performance | Authenticated API | p95 < 300 ms warm; cold path < 3 s (documented tradeoff) |
| Engineering | Test coverage | ≥ 90% on inference and metrics core; ≥ 75% overall |
| Engineering | Security | 0 open high or critical findings from dependency, code and IaC scanners |
| Cost | AWS bill | ≤ $1 a month steady state; budget alarms at $1 and $5 |

## 7. Scope

### Must (MVP)
- MBTA bus + subway; minute-by-minute ingestion; arrival inference; delay, on-time, p90, excess-wait and coverage metrics.
- Daily rollups published as static JSON; stop search (client-side); stop and route pages with heatmaps and trends; live "right now" panel.
- Google sign-in, temporary demo accounts, saved commutes with personal summaries, account export and deletion.
- Public data-health page; operator alarms, dashboards and runbooks.
- Infrastructure as code, CI/CD, test suite, security scanning, cost guardrails.

### Should
- Web Push delay and cancellation alerts for saved commutes.
- "Ask Stopwatch" plain-English questions, with evals and a hard monthly cost cap.
- A second agency (SEPTA or NYC subway, both confirmed keyless) to prove the multi-agency abstraction.
- Inference validation job against MBTA LAMP, with the error published on the methodology page.

### Could
- Map view (MapLibre + free vector tiles).
- Installable PWA.
- Downloadable daily Parquet/CSV.
- Public API keys with quotas.
- Weekly email digest.
- Anomaly flags ("unusually bad today").
- Embeddable stop widget.

### Won't (non-goals)
- **Trip planning or routing.** Google Maps and the Transit app already do this well.
- **Better arrival predictions than the agency** (ML forecasting). Stopwatch measures; it doesn't predict.
- **Native mobile apps.** A responsive web app plus a PWA is enough.
- **Commuter rail, ferry or paratransit** in the MVP. Different schedule semantics, low value per hour of effort.
- **Official performance reporting.** Every page carries an "independent, unofficial estimate" note and links to the methodology.
- **Storing precise user location**, behavioral analytics or third-party trackers.
- **Multi-region high availability or sub-minute freshness.** Ruled out by the $0-when-idle constraint; documented as a tradeoff.

## 8. Assumptions and open questions

- **Assumption:** AWS (new or existing account) plus the Neon free plan. Free-tier terms should be re-verified at implementation time (see the cost model in 02).
- **Assumption:** a 1-minute poll is accurate enough. *Validation:* the LAMP comparison (Should) produces the real error figure, and the README reports it either way.
- **Open:** what the 18% SKIPPED stop updates mean in MBTA's feed. Investigate in week 1 of implementation; it affects coverage math.
- **Open:** how to recruit real riders. Candidates: r/mbta, local transit advocacy groups, campus transit groups. Decide before launch.
