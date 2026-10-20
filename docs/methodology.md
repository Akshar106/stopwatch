# Methodology: how Stopwatch measures reliability

*Last updated 2026-10-18. Applies to MBTA bus, subway and light rail.*

> **Stopwatch publishes independent, unofficial estimates.** They are computed from the MBTA's public real-time feeds, not from the MBTA's own performance records, and they can differ from official figures. Where official data exists (subway), we compare against it and publish the error.

This page explains where every number on a stop or route page comes from, what it means, and where it can go wrong. The engineering detail behind it is in [04 §7](04-architecture.md#7-core-algorithm-arrival-inference) and [feed notes](feed-notes.md).

## 1. What the feed gives us, and what it doesn't

The MBTA publishes a live feed of **predictions**: for each bus or train trip in progress (and some about to start), the times it is expected to reach its upcoming stops. Three facts shape everything below:

- **Predictions vanish once a stop is served.** The feed only looks forward. When a bus leaves a stop, that stop drops off the trip's list. The feed keeps no record of what the last prediction was or when the stop disappeared; that history exists only if someone captures the feed every minute.
- **There is no "how late" field.** The feed's `delay` fields were absent in every snapshot we checked. Lateness has to be computed by comparing our estimate with the published schedule.
- **Vehicle positions are a separate feed.** Each bus or train reports where it is and whether it is stopped at a stop, typically 5–10 seconds old.

Stopwatch reads both feeds **once a minute**, all day, every day ([ADR-003](adr/0003-poll-feeds-every-60-seconds.md)).

## 2. Inferring arrivals from disappearing predictions

Each minute we compare the new snapshot with the previous one. If a stop that was listed for a trip a minute ago is gone, and the trip itself is still in the feed, the vehicle has served that stop in the last minute. We estimate *when* from the information we had just before it disappeared:

1. **Last prediction** (`last_prediction`): the predicted arrival time from the last snapshot that still listed the stop. A prediction made 30 seconds before arrival is usually very close.
2. **Vehicle seen stopped** (`vp_stopped`): if the vehicle-position feed shows the vehicle *stopped at that stop*, we use that report's timestamp instead.
3. **End of trip** (`trip_end_flush`): when a whole trip leaves the feed (normally just after its last stop), its remaining stops are recorded from their last predictions, but only if those predictions were no more than 2 minutes in the future. A stop whose last prediction was further ahead is **not** counted as served: the trip may have been cut short or the data may have stopped, and we don't invent arrivals.

### Worked example

Route 1 toward Harvard, stop *Massachusetts Ave @ Newbury St*, a weekday trip **scheduled at 8:05:00 am**:

| Feed snapshot (ET) | Stop still listed? | Predicted arrival | How far ahead the prediction was |
|---|---|---|---|
| 8:03:04 | yes | 8:06:50 | 3 min 46 s |
| 8:04:05 | yes | 8:07:20 | 3 min 15 s |
| 8:05:03 | yes | 8:07:35 | 2 min 32 s |
| 8:06:04 | yes | 8:07:30 | 1 min 26 s |
| 8:07:05 | yes | 8:07:40 | 35 s |
| 8:08:04 | **no** (later stops still listed) | — | — |

At 8:08:04 the stop has disappeared while the trip continues, so the bus served it between 8:07:05 and 8:08:04.

- **Estimate:** 8:07:40, the last prediction. It was made only 35 seconds ahead, so confidence is **high**.
- **Delay:** 8:07:40 − 8:05:00 = **+2 min 40 s**, which is **on time** (within −1 to +5 minutes).
- **With a vehicle position:** if the 8:08:04 vehicle snapshot reported the bus *stopped at* this stop as of 8:07:52, the estimate becomes 8:07:52 (method `vp_stopped`, high confidence) and the delay +2 min 52 s.
- **With a gap:** if our 8:07 snapshot had been missed, the last thing we knew would be the 8:06:04 prediction (8:07:30). The estimate would still be recorded, but marked **low** confidence because a minute of data is missing.

### Confidence levels

| Confidence | When |
|---|---|
| **High** | The last prediction was made ≤ 90 s before the predicted time, or the vehicle was seen stopped at the stop |
| **Medium** | The last prediction was made 90 s – 5 min ahead, or its time had already passed by more than 90 s while the stop was still listed (the vehicle was waiting there) |
| **Low** | The last prediction was made more than 5 min ahead, or one or more of our minute snapshots around that time are missing |

Predictions that the MBTA marks as schedule-based rather than live (bus trips with no vehicle assigned yet, about 15% of bus predictions on 2026-10-18) never produce high-confidence estimates on their own ([feed notes](feed-notes.md)).

### Skipped stops and canceled trips

- The feed can mark a stop **SKIPPED** for a trip, usually because of a detour or a closed stop. A skipped stop that disappears is **not** treated as served, and it is never counted as on time or late; it is counted separately as `skipped`. If the vehicle-position feed shows the vehicle actually stopped there, we record the arrival (method `vp_stopped`), because on 2026-10-18 we saw buses stop at stops the feed had marked skipped ([feed notes](feed-notes.md)).
- A skip is recorded once per trip when the trip finishes, not when it first appears: the MBTA lists skips for trips up to about a day in advance, and those plans can change.
- **Canceled** trips are counted as `canceled`, never as on time.
- **Added** trips (not in the published schedule) have no scheduled time, so they have no delay. They are excluded from delay and on-time figures; on frequent routes they still count toward observed headways.

## 3. Delay

**Delay = estimated arrival − scheduled arrival**, where the scheduled time comes from the MBTA schedule (GTFS) that was valid on that service date. Schedules change several times a year; each day is compared with its own schedule version, so a schedule change does not show up as a sudden "improvement" or "decline".

A negative delay means early.

### GTFS time pitfalls

Schedule times look like clock times but are not. Getting these wrong produces errors of exactly one hour or one day, so they are tested explicitly.

- **Times past midnight belong to the previous service day.** A trip at `25:10:00` on Friday's schedule runs at 1:10 am on Saturday. It is a Friday trip: it appears under *weekday* (Friday's service), in the *1 am* hour. Day type follows the service that ran, so a holiday Monday operated on a Sunday schedule counts as a Sunday.
- **Times are measured from "noon minus 12 hours", not from midnight.** On most days these are the same. On the two daylight-saving days they differ by an hour:
  - On **Sunday 1 November 2026** (clocks fall back at 2:00 am), "noon minus 12 h" is 1:00 am EDT. A scheduled `00:30:00` therefore means 1:30 am EDT, not 12:30 am.
  - On **Sunday 14 March 2027** (clocks spring forward), "noon minus 12 h" is 11:00 pm EST the previous evening, so `00:30:00` means 11:30 pm on Saturday 13 March by the wall clock.
  - Daytime times are unaffected on both days.
- **The service day is not the calendar day.** All metrics are grouped by service date (the date the schedule belongs to), in the agency's time zone (America/New_York).

## 4. On time

A stop arrival is **on time** if it is between **1 minute early and 5 minutes late** (−60 s ≤ delay ≤ +300 s). This window is a common convention among US transit agencies, it is configurable per agency, and it is stated on every page (`on_time_definition_s` in the [published data](api.md#manifest)). Earlier than 1 minute counts as **early** (shown separately, because an early bus can be as bad as a late one for someone arriving on time); later than 5 minutes counts as **late**.

## 5. Typical and worst-case delay: why median and p90, not the average

Delays are lopsided: most trips are a little late, and a few are very late. An average mixes the two and describes neither.

Ten trips at one stop, delays in minutes: −0.5, 0.5, 1, 1.5, 2, 2, 3, 4, 12, 22.

| Statistic | Value | What it tells a rider |
|---|---|---|
| Mean | 4.75 min | Nothing useful: no trip was actually about 5 minutes late |
| **Median (p50), "typical"** | **2.0 min** | Half the trips were at most 2 minutes late |
| **90th percentile (p90), "worst case"** | **13 min** | 9 in 10 trips were at most about 13 minutes late; plan for this if you can't be late |
| On time (−1 to +5 min) | 80% | 8 of 10 trips |

Percentiles use linear interpolation between neighbouring observations (the default in most statistics tools). Every cell also shows a histogram of delays so you can see the shape directly.

## 6. Excess wait time (frequent routes)

On routes where a bus or train comes every few minutes, riders don't look at a timetable; they turn up and wait. What matters is **even spacing**, not schedule adherence. Excess wait time (EWT) measures how much longer the average rider waits than the schedule promises.

For a rider arriving at a random moment, the average wait with headways (gaps between vehicles) *h₁, h₂, …* is:

> **average wait = Σh² / (2 · Σh)**

Long gaps count more than short ones because more riders arrive during them. **EWT = average actual wait − average scheduled wait.**

**Example**, one hour at one stop, scheduled every 10 minutes (six buses):

- Scheduled headways: 10, 10, 10, 10, 10, 10. Average scheduled wait = 600 / (2 × 60) = **5.0 min**.
- Actual headways (same six buses, bunched in pairs): 4, 16, 6, 14, 2, 18. Σh = 60, Σh² = 16 + 256 + 36 + 196 + 4 + 324 = 832. Average actual wait = 832 / 120 = **6.9 min**.
- **EWT = 6.9 − 5.0 ≈ 1.9 min.** Every bus "ran", yet the average rider waited almost 2 minutes longer than promised.

Stopwatch shows EWT only for stop-hours whose median scheduled headway is **12 minutes or less**. Headways come from consecutive estimated arrivals of the same route and direction at the stop; a canceled trip lengthens the actual headway, which EWT correctly counts against the service.

## 7. Coverage

**Coverage = observed trips ÷ scheduled trips** for a service day. A trip is *observed* if we inferred at least one served-stop arrival for it. Trips that appear in the feed only as a list of skipped stops, or only as canceled, do not count as observed.

- Coverage is shown wherever metrics are shown. Below **80%**, metrics for that day are labelled *low confidence*, and the daily publish is held back for a manual check (RB-3).
- Canceled trips are reported separately on the coverage page, so a day with many cancellations can be told apart from a day when our collector was down.
- Coverage can be low for reasons on our side (a collector outage) or the MBTA's (a feed outage, trips running without predictions). The [data-health page](api.md#health) lists gaps.

## 8. Minimum sample size

A heatmap cell (route, stop, day type, hour) shows statistics only if it has at least **8 observed arrivals** in the window (`min_samples`, normally the last 4 weeks). Below that it shows *not enough data*. With fewer than 8 values a "90th percentile" is essentially the single worst trip, and one odd day dominates the result.

## 9. Known limitations

- **One-minute polling** means estimates are good to about **±1 minute**, sometimes better when a vehicle is seen stopped. Delays of a few seconds are not meaningful ([ADR-003](adr/0003-poll-feeds-every-60-seconds.md)).
- **Unofficial estimates.** They are not the MBTA's on-time performance figures and use a different method; the MBTA's official reliability reporting may use different definitions, stops and periods.
- **Skipped stops** depend on the MBTA's own marking. Not every detour is marked, and some marked skips are not real (the bus stopped anyway). See §2 and [feed notes](feed-notes.md).
- **Added trips are excluded from delay** because they have no schedule. On subway lines, a noticeable share of trips are added trips (about 14 of ~125 rapid-transit trips in each snapshot on 2026-10-18), so subway delay figures rest on fewer trips than headway figures.
- **First and last stops.** The first stop has a departure time but no meaningful arrival; layovers at terminals make "arrival" there ambiguous. Treat terminal figures with care.
- **Gaps cannot be filled.** Minutes when our collector or the MBTA feed was down are lost for bus. They lower coverage; they are never filled with guesses.
- **Data is up to a day old.** Pages are rebuilt each morning for the previous service day. The *right now* panel shows live MBTA predictions directly.
- **Commuter rail, ferry and paratransit are not covered.**

## 10. Validation

**Subway and light rail:** the MBTA publishes its own record of when trains actually arrived and departed (the [LAMP performance data](https://www.mbta.com/developers/mbta-performance-data)). Every Monday a job downloads LAMP's daily subway files (`https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/{date}-subway-on-time-performance-v1.parquet`) and compares them with our estimates for the previous week. LAMP and the real-time feed often use different trip IDs for the same train, so each of our arrivals is matched to LAMP by **train (vehicle ID) and stop, taking LAMP's nearest recorded arrival within 15 minutes**; a train rarely serves the same stop twice within that window (terminal turnarounds are the exception to watch), and estimates with no match are left out. The error distribution, overall, by line and by inference method, is published at `/data/v1/validation/mbta.json` and on this page.

| Measure | Target | Result |
|---|---|---|
| Median absolute error | ≤ 45 s | *Pending: the first report will appear here once the validation job has run* |
| 90th percentile absolute error | ≤ 120 s | *Pending* |

**Bus:** there is no official per-stop record to compare with in real time. As a partial check, we compare `last_prediction` estimates with the subset of arrivals where the vehicle was also seen stopped at the stop, and report coverage alongside every metric.

If the error turns out larger than the target, we will say so here and adjust the confidence rules, rather than hide it.

## Questions and corrections

If a number looks wrong, open a GitHub issue with the route, stop, day and hour.
