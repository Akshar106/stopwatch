# MBTA feed notes

*Investigation run 2026-10-18 (a Sunday) against the live MBTA feeds. Answers the open question in [03 §8](03-product-spec.md#8-assumptions-and-open-questions): what are the ~18% of stop updates marked SKIPPED, and how should the pipeline treat them? Also records the feed behaviors that inference relies on, as baselines for the nightly drift check ([06 §1](06-quality-operations.md#1-testing-strategy), [RB-2](runbooks/RB-2-feed-parse-errors.md)).*

Sections 1–2 are **observations** (numbers and dates). Section 3 is **interpretation**. Section 4 is **what the pipeline should do**.

## 1. Method

**Data collected** (raw files and analysis scripts kept outside the repository, per the "no raw data in the repo" rule):

| Source | When (UTC; ET = UTC−4) | Count |
|---|---|---|
| `https://cdn.mbta.com/realtime/TripUpdates.pb` + `VehiclePositions.pb` | 20:33:05–20:40:25 (16:33–16:40 ET), about every 62 s | 8 pairs |
| Same, sparse follow-up | 20:47–21:37 (16:47–17:37 ET), every 10 min | 6 pairs |
| `https://cdn.mbta.com/realtime/Alerts.pb` | 20:35:03 and 21:37:06 | 2 |
| `https://cdn.mbta.com/MBTA_GTFS.zip` (24.5 MB) | 20:33, once | `feed_version` "Fall 2026, 2026-10-16T20:25:58+00:00, version D", valid 2026-10-09 → 2026-12-12 |

No feed was requested more than once a minute.

**Tools:** `gtfs-realtime-bindings` to decode protobuf; DuckDB to read `routes.txt`, `trips.txt`, `route_patterns.txt`, `stops.txt` and the `stop_times.txt` rows for every trip seen in the real-time feed (1,422 of 1,446 trip IDs had schedule rows; the other 24 were ADDED trips).

**Definitions used below**

- *STU*: one `stop_time_update` (one stop of one trip in one snapshot).
- *Mode* comes from `route_type` in `routes.txt` (0 light rail, 1 subway, 2 commuter rail, 3 bus, 4 ferry), not from the shape of the route ID: bus IDs include `34E`, Silver Line routes are `741`–`751` (SL1 = `741`), and CT3 is `708`.
- Trips are keyed by `(trip_id, start_date)`; stops within a trip by `stop_sequence`.
- *Skip-only trip*: a trip whose every STU is SKIPPED (no predicted times at all).
- *Behind the vehicle*: `stop_sequence` < the vehicle's `current_stop_sequence` in the VehiclePositions snapshot fetched at the same time.

**MBTA documentation consulted**

- [MBTA GTFS-Realtime reference](https://github.com/mbta/gtfs-documentation/blob/master/reference/gtfs-realtime.md): documents `uncertainty` codes (bus 300 = schedule-based prediction when no vehicle is assigned; 301 = stalled bus; rail 60/120/360) and enhanced-feed fields. **It does not mention SKIPPED.**
- MBTA v3 API schema (`api-v3.mbta.com/docs/swagger/swagger.json`), Prediction `schedule_relationship`: SKIPPED means the stop "was originally scheduled, but was skipped".
- [MBTA real-time display guidelines](https://www.mbta.com/developers/real-time-display-guidelines): for CANCELED or SKIPPED, show a crossed-out scheduled time or hide the trip.
- [MBTA static GTFS reference](https://github.com/mbta/gtfs-documentation/blob/master/reference/gtfs.md): `route_pattern_typicality` 4 = diversions (planned detours, shuttles, snow routes); `pickup_type`/`drop_off_type` 3 = flag stop (commuter rail) or continuous pickup/drop-off (some bus routes).

## 2. Findings

### 2.1 Feed shape (8 snapshots, 16:33–16:40 ET)

| Fact | Value |
|---|---|
| Trip updates per snapshot | 1,348–1,374: bus 1,188–1,200, subway 67, light rail 57–59, commuter rail 20–22, ferry 14 |
| STUs per snapshot | 22,901–23,361 |
| STUs per trip | median 14 (p10 2, p90 35–36) |
| Trip `schedule_relationship` | SCHEDULED 1,325–1,355; **ADDED 13–17**; **CANCELED 6** |
| STU `schedule_relationship` | SCHEDULED and SKIPPED only (no NO_DATA, no UNSCHEDULED) |
| `delay` fields (trip-level or stop-level) | **0** in every snapshot |
| Header timestamp vs our fetch time | 1–4 s old (median 2 s) on all 8 fetches |
| Header timestamp step between our fetches | 61–66 s (equal to our fetch spacing; every fetch had advanced) |
| `trip_update.timestamp` age vs header | median 10 s, p90 35 s |
| Non-skipped STUs with a predicted time before the header ("past stops") | ~190 per snapshot (0.8%): median 29 s in the past, p90 214 s, max 1,097 s; 72% are the first STU listed for the trip (the stop the vehicle is at) |
| Non-skipped STUs behind the vehicle | 525 across 8 snapshots (~66 per snapshot, ~0.3%) |
| Non-skipped STUs that disappeared between consecutive snapshots while their trip stayed | 213–275 per interval |
| STUs that left together with their trip | ~75 per interval |
| `uncertainty` on non-skipped STUs | bus with a vehicle: absent (76% of all non-skipped STUs); **bus without a vehicle: 300, schedule-based (13.8% of all; 15% of bus)**; bus 301: 0.2%; rail with a vehicle: 360 / 60 / 120 (4.4% / 3.7% / 0.9%) |
| ADDED trips | none present in static `trips.txt`; mostly rapid transit (summed over 8 snapshots: Blue 38, Red 31, Green-C 16, Green-B 15, Orange 13) plus bus route 66 (8) |
| CANCELED trips | 6, all on routes 215 and 225; every STU of each is SKIPPED (27–50 per trip); 4 of the 6 have an empty `start_time` |

**VehiclePositions** (same 8 fetches): 421–431 vehicles, all with a trip descriptor. `current_status`: STOPPED_AT 208–234 (49–54%), IN_TRANSIT_TO 162–191, INCOMING_AT 24–33. Position age vs header: median 5–9 s, p90 47–56 s. For buses reported STOPPED_AT, the distance from the reported stop was a median 36 m but p90 971 m (probably vehicles laying over away from the terminal stop they are reported at).

### 2.2 SKIPPED: what and where

First snapshot (16:33:03 ET): **4,073 of 23,149 STUs (17.6%) were SKIPPED.** All 8 snapshots: 4,072–4,124 (17.6–17.8%).

**By mode.** Bus 4,070–4,123 (19.2–19.4% of bus STUs). Light rail 0–2 (one Green-E STU at Symphony, closed since June per an active NO_SERVICE alert; one Green-B STU at Government Center). Subway, commuter rail, ferry: 0.

**By route** (first snapshot). 21 of 128 routes in the feed had any SKIPPED STU, and a handful account for nearly all of them:

| Route(s) | SKIPPED STUs | Share | Trips with skips / trips in feed | Skipped stops |
|---|---|---|---|---|
| 57 | 2,586 | 63.5% | 224 / 224 | 14 consecutive stops between Brighton and Watertown (Washington St @ Market St → Oak Square → Newton Corner → Galen St @ Maple St), and the reverse direction's equivalent |
| 30, 34, 34E, 35, 36, 40, 50 (Forest Hills routes) | 1,072 | 26.3% | 232 / 255 | Roslindale Square: Poplar St @ South St, Washington St @ Albano St … Walworth St, Belgrade Ave stops, Cummins Hwy @ Washington St |
| 215, 225 | 216 | 5.3% | 6 / 17 | All stops of the 6 CANCELED trips (Quincy Center routes) |
| 220 | 73 | 1.8% | 73 / 73 | Hingham Shipyard @ Ferry Terminal (one or two stops per trip) |
| 66, 86 | 62 | 1.5% | 22 / 29 | N Harvard St / Eliot St / JFK St stops near the Charles |
| 450, 87, 112, 426, 88, 455 | 62 | 1.5% | — | Event detours and closed stops (below) |
| Green-B, Green-E | 2 | 0.05% | 2 / 27 | One station each |

**By kind of trip** (first snapshot):

| Trip kind | Trips | SKIPPED STUs | Share of SKIPPED |
|---|---|---|---|
| **Skip-only trips** (not canceled, no predicted times) | 495 | 3,493 | **85.8%** |
| CANCELED trips (all stops SKIPPED) | 6 | 216 | 5.3% |
| Trips with predictions, no vehicle position yet | — | 203 | 5.0% |
| Trips with predictions, skipped stop at or ahead of the vehicle | — | 128 | 3.1% |
| Trips with predictions, skipped stop behind the vehicle | — | 33 | 0.8% |

Among the **856 trips that carry predictions** (the trips inference actually uses), 364 of 19,440 STUs were SKIPPED: **1.9%**, steady at 1.9% in all 8 snapshots.

**Skip-only trips are tomorrow's and tonight's detoured trips.** Their start times were up to 24 h ahead (median 15.8 h after the snapshot; only 0.4% had already started). **All 365 trips dated 2026-10-19 in the feed were skip-only**: the feed lists next-day trips only to carry their SKIPPED stops. The other 130 skip-only trips were later on 2026-10-18 (start times 16:xx to 26:xx). Skip-only trips were 36% of all trip updates in the snapshot (495 of 1,357).

**Position in the trip.** 4,060 of 4,073 SKIPPED stops were intermediate stops of the scheduled trip; 6 were the first stop and 7 the last. Running trips with skips showed a skipped block in the middle (71 trips), at the head (8; a skipped block already behind the vehicle) or at the tail (1). On a detoured route the same stops are skipped on every trip in a direction (for example, 114 route-57 trips skip the same 14 stops).

**No times.** 0 of 4,073 SKIPPED STUs had an arrival or departure time, and none had an `uncertainty`.

**Static schedule.** All 4,073 matched a row in `stop_times.txt` with the same `trip_id`, `stop_sequence` and `stop_id`. Their pickup/drop-off types were ordinary: 0/0 for 4,059, and 0/1 or 1/0 (pickup-only first stop, drop-off-only last stop) for the other 14. **None were flag or continuous stops** (type 3, which do occur on 103 non-skipped bus STUs). The trips used typical route patterns (typicality 1: 525 trips; 2: 42; 3: 14); **none were on a typicality-4 "diversion" pattern**, so the static schedule does not model these detours.

**Alerts** (Alerts.pb at 16:35 ET). Only **198 of 4,073 (4.9%)** SKIPPED STUs were at a stop named in an active DETOUR or NO_SERVICE alert:

- Route 220 detour for construction (active since 15 July).
- Route 87 detour for the Monster Mash, 10:00–19:00 that day.
- Routes 66 and 86 detours for the Head of the Charles Regatta, 16 October 08:00 to 19 October 03:00.
- Route 450 detours for Salem Haunted Happenings (Fridays–Sundays in October) and a parade (until 18:34).
- Routes 112/121 detour for Day Square construction (since 13 October).
- Closed stops: American Legion Hwy @ Revere St (426, 450, 455), Broadway @ Weston Ave (87, 88), Symphony (Green-E).

**No alert mentioned route 57 or the Roslindale Square stops**, which together hold 90% of all SKIPPED STUs (3,658) (the only alerts on routes 34E, 36 and 40 were "delays of about 20–25 minutes due to traffic").

### 2.3 SKIPPED over time

**Minute to minute** (8 snapshots, 7 intervals):

- 28,672 SKIPPED → SKIPPED; **0 SKIPPED → SCHEDULED**; **0 SCHEDULED → SKIPPED**.
- 12 SKIPPED STUs dropped out while their trip stayed in the feed; 8 left with their trip.
- 4,053 of the 4,073 SKIPPED STUs in the first snapshot were still SKIPPED in all 8; the other 20 left the feed (alone or with their trip) without ever changing status.

**Over one hour** (16:33 → 17:37 ET, 14 snapshots, 13 intervals): *see [§2.5](#25-one-hour-follow-up).*

**SKIPPED stops behind the vehicle linger.** 31–64 SKIPPED STUs per snapshot were behind their vehicle (411 across 8 snapshots), whereas served non-skipped stops disappear within about a minute.

### 2.4 Can a SKIPPED stop be served?

**Yes.** 7 times in the 8 one-minute snapshots (and 7 more in the hour that followed, §2.5), a vehicle was reported **STOPPED_AT** a stop that the previous TripUpdates snapshot had marked SKIPPED for that same trip, and the vehicle's position was **3–79 m** from the stop (median 14 m):

| Route | Stop | Distance |
|---|---|---|
| 66 | N Harvard St @ Gate 2 Harvard Stadium, then N Harvard St @ S Campus Dr (same trip, consecutive minutes) | 3 m, 6 m |
| 86 | the same two stops, consecutive minutes | 18 m, 9 m |
| 66 | N Harvard St @ Western Ave | 14 m |
| 86 | N Harvard St opp Harvard Stadium Gate 2 | 43 m |
| 88 | Broadway @ Weston Ave (closed stop) | 79 m |

In every case the stop then disappeared from the trip, exactly as a served stop does. No vehicle was STOPPED_AT a stop marked SKIPPED in the *same* snapshot.

### 2.5 One-hour follow-up

Six more snapshot pairs at 10-minute intervals (16:47–17:37 ET), analysed together with the first eight:

| Time (ET) | Trip updates | SKIPPED STUs (share) | Skip-only trips | SKIPPED share on trips with predictions |
|---|---|---|---|---|
| 16:33 | 1,357 | 4,073 (17.6%) | 495 | 1.9% |
| 16:47 | 1,361 | 4,130 (18.0%) | 500 | 1.9% |
| 16:57 | 1,366 | 4,147 (18.0%) | 504 | 1.9% |
| 17:07 | 1,369 | 4,178 (18.2%) | 509 | 2.0% |
| 17:17 | 1,367 | 4,217 (18.2%) | 515 | 2.0% |
| 17:27 | 1,454 | 4,507 (19.2%) | 595 | 1.9% |
| 17:37 | 1,464 | 4,512 (19.1%) | 591 | 1.9% |

- **Skips are added in blocks, as new placeholder trips.** Between 17:17 and 17:27, route 87's SKIPPED STUs went from 19 to 323: **77 new skip-only trips** appeared at once, running from that evening through the next morning (start dates 2026-10-18 and 2026-10-19), all skipping the same 8 Somerville Ave / Union Square stops. The only route-87 detour alert (Monster Mash) was scheduled to end at 19:00 that day, so the markers extend well past the published end of the detour. This one change moved the raw SKIPPED share from 18.2% to 19.2%; the share on trips with predictions did not move.
- **Statuses still never flip.** Across all 13 intervals: 53,609 SKIPPED → SKIPPED, 0 SKIPPED → SCHEDULED, 0 SCHEDULED → SKIPPED. 134 SKIPPED STUs dropped out while their trip stayed in the feed, 252 left with their trip, and 6 SKIPPED STUs were added to trips already in the feed.
- **Skip sets are stable.** 477 skip-only trips were present at both 16:33 and 17:37; none had a different set of skipped stops. Only one of them started running (gained predictions) within the hour, and its skipped stops stayed SKIPPED.
- **More SKIPPED stops served.** Over all 14 vehicle snapshots, 14 of 3,110 STOPPED_AT reports (0.45%) were at a stop SKIPPED for that trip in the preceding TripUpdates snapshot (1 or 10 minutes earlier): 12 on routes 66/86 along N Harvard St, Eliot St and JFK St (3–108 m from the stop), 1 on route 88 (79 m) and 1 on route 426 at the closed American Legion Hwy @ Revere St stop (165 m, probably not a stop for passengers). The 66/86 regatta detour alerts were still active at 17:36 ET.
- **Alerts at 17:36 ET** (139 alerts): still nothing for route 57 or the Roslindale Square stops beyond traffic-delay notices on 34, 34E and 40.

## 3. Interpretation

*Separate from the findings above: these are the most likely explanations, not facts.*

1. **SKIPPED means "this scheduled stop will not be served by this trip"**, as in the GTFS-Realtime spec and the MBTA v3 API definition. On 2026-10-18 the MBTA used it for three things:
   - **bus detours**, both long-running (construction) and one-day events (regatta, festival, parade), including detours that had **no** published alert (route 57, the Roslindale Square routes). Those are most likely detours entered in the bus prediction system that are not mirrored in Alerts; the data cannot confirm why;
   - **closed stops** (NO_SERVICE alerts);
   - **canceled trips**, which list every stop as SKIPPED in addition to the trip-level CANCELED.
2. **The 18% is mostly a denominator effect.** About 500 not-yet-started trips (36% of trip updates), up to a day ahead, appear *only* to announce their skipped stops. They have no predictions, so they inflate the SKIPPED share without affecting any arrival inference. For trips that carry predictions the share is 1.9%. The raw share will swing with how many trips the detoured routes run in the next 24 hours, not with feed quality.
3. **SKIPPED is a forecast, not an observation.** It can be wrong: buses on 66 and 86 kept stopping at N Harvard St stops that were still marked SKIPPED throughout the hour (most likely the regatta detour was lifted on the street before the feed's detour, which the alert scheduled to end at 03:00, was removed). Markers are also applied in bulk to every upcoming trip in the 24-hour horizon (the route-87 block at 17:27 covered trips after the detour's published 19:00 end), so the skip list for a trip that runs tomorrow is a plan made today. The 88 at Broadway @ Weston Ave is probably a stop for traffic near a closed stop, not a passenger stop; a 79 m distance cannot tell the two apart.
4. **It is not flag stops.** The early guess in [03](03-product-spec.md#1-problem) is ruled out: skipped stops have ordinary pickup/drop-off types.
5. Commuter rail and ferry trips appear in the same feed and must be filtered by route type; ADDED trips are mostly rapid-transit trains that do not match a scheduled trip ID.

## 4. Implications for the pipeline

Each item names where it lands. Items 1–5 change behavior described in [04 §7](04-architecture.md#7-core-algorithm-arrival-inference); the [methodology](methodology.md) already describes the resulting rules.

*Status in `core/inference/diff.py` when this was written:* items 1 and 4 are already implemented (stops last seen as SKIPPED never become arrivals, and canceled trips emit one CANCELED event without per-stop skips; skipped stops also don't block the out-of-order guard). Item 2 (vehicle override) is not, and SKIPPED events are still emitted the first time a stop is seen skipped, which item 3 changes. The nightly drift check (`ingest/drift_check.py`) still uses the raw SKIPPED share (limit 40%); item 11 replaces it.

1. **Index the STU status and never infer an arrival from a SKIPPED stop disappearing.** `index(tu)` keeps `rel` (it already does in 04 §7); the diff must branch on it. A SKIPPED STU has no time, so `last_prediction` is impossible anyway; code that assumes `t_pred` exists would crash or emit garbage. (`core.inference`)
2. **A SKIPPED stop can still be served: let vehicle evidence override.** If VehiclePositions shows the trip's vehicle `STOPPED_AT` that `stop_sequence` (same tick or the tick after the stop was last listed as SKIPPED) within about 100 m of the stop, emit an arrival with `method=vp_stopped`, `stop_status=served`. Count these as `skipped_but_served` in the tick summary so the rate is visible. (`core.inference`, `ingest`)
3. **Record skips when the trip ends, not when they first appear.** 04 §7 says "emit Skipped … the first time they appear". With this feed that would emit ~3,500 skip events for trips that have not started, 365 of them for the next service date, and any change to a detour before the trip runs would leave stale records. Instead, carry the latest status in state and emit `stop_status=skipped` only when the trip leaves the feed (or its service day closes), for stops that were still SKIPPED at last sight and never served. Attribute them to the trip's `start_date` service date. (`core.inference`, state)
4. **Canceled trips are counted once, as canceled.** Do not also count each of their stops as skipped (216 STUs here). In published cells, `canceled` counts canceled trips and `skipped` counts trips that ran but skipped this stop. (`rollups`)
5. **Exclude skipped stops from every delay statistic, keep them visible.** SKIPPED stops are excluded from `n`, on-time share, p50/p90 and the histogram, counted in `Cell.skipped`, and treated as **no service at that stop** for observed headways and excess wait time (like a cancellation, they lengthen the real gap). (`rollups`, `core.metrics`)
6. **Coverage counts a trip as observed only if at least one stop was inferred served.** Skip-only placeholder trips and canceled trips appear in the feed but are not observations; counting "trips seen in the feed" would have overstated coverage by up to ~500 trips at this hour. ADDED trips are excluded from both numerator and denominator (they have no scheduled counterpart). (`rollups`)
7. **Use the schedule-based flag.** STUs with `uncertainty` 300 (bus, no vehicle assigned) are schedule-based, not live; an estimate taken from one must not be `high` confidence, and a trip with no vehicle that vanishes yields no arrivals (the existing "trip vanished" rule). (`core.inference`)
8. **Stops whose predicted time has passed are not yet served.** Up to 0.8% of non-skipped STUs carry a time in the past (mostly the vehicle's current stop, up to 18 minutes for layovers). Keep using disappearance as the signal. When the last prediction was already in the past by more than 90 s, prefer a `vp_stopped` time and cap confidence at `medium`. (`core.inference`)
9. **Filter by route type at index time.** Commuter rail (20–22 trips) and ferry (14 trips) are in the same feed; `AgencyConfig.route_types` = (0, 1, 3) for MBTA should drop them before diffing. (`ingest`)
10. **Rapid-transit ADDED trips.** ~14 of ~125 rapid-transit trips per snapshot were ADDED and have no schedule row, so they produce no delay. Subway pages should lean on headway metrics. The LAMP comparison cannot rely on `trip_id` either; `lamp-validate` matches on `(vehicle_id, stop_id)` with the nearest LAMP timestamp within 15 minutes, which also covers ADDED trains. (`rollups`, `lamp-validate`)
11. **Drift-check baselines.** Track (a) SKIPPED share among trips with predictions (baseline 1.9%), (b) skip-only trip count (~500 on a Sunday afternoon), (c) `skipped_but_served` per day, (d) SKIPPED STUs carrying a time (baseline 0), (e) `delay` fields present (baseline 0), (f) past-time share of non-skipped STUs (baseline ~0.8% for any time before the header; ~0.2% for more than 120 s before it, which is the measure `drift_check.py` uses with a 5% limit). Do **not** alert on the raw 18%: it follows detour volume (one detour added a full percentage point within ten minutes, §2.5). ([RB-2](runbooks/RB-2-feed-parse-errors.md))
12. **Static GTFS import: set CSV quoting explicitly.** DuckDB's CSV sniffer reads the first 20,480 rows; in `trips.txt` the first quoted field (a headsign containing commas) is on line 43,086, so auto-detection chose "no quote character" and the read failed. `schedule-import` must pass `quote='"'` (and `escape='"'`) rather than rely on detection; a fixture row with a quoted comma belongs in the mini GTFS. (`catalog`)

## 5. Open questions

- **Weekday behavior.** This is one Sunday afternoon. Repeat the investigation on a weekday morning peak (more trips, different detours) before treating the baselines as normal ranges.
- **Route 57 and Roslindale.** Confirm with the MBTA developer community whether these unannounced skips are operator detours, and whether they are reliable.
- **Lifted detours.** How long do SKIPPED markers survive after a detour ends on the street (the 66/86 case, still marked at 17:37 ET), and are bulk-added markers (route 87) removed when the alert ends? Track `skipped_but_served` by route for a few days once ingestion runs.
- **Skipped stops behind the vehicle.** Do they only leave the feed when the trip ends? Affects state size, not correctness.
