"""Infer arrivals by diffing consecutive GTFS-Realtime snapshots.

The MBTA feed (like most) only carries *future* stops: once a vehicle serves a stop, that stop's prediction
disappears. So a stop present in the previous snapshot and absent from the current one was served
somewhere in between, and the last prediction we saw is the best available estimate of when. Vehicle
positions that show the vehicle STOPPED_AT the stop tighten the estimate.

SKIPPED stops (see docs/feed-notes.md): MBTA marks ~18% of stop updates SKIPPED, mostly on placeholder trips
published up to a day ahead. A skip is therefore only recorded once it is confirmed (the stop leaves the feed
while the trip continues, or the trip ends having run), never when it first appears; a vehicle observed
STOPPED_AT a "skipped" stop wins and yields an arrival.

Properties (property-tested in tests/property/test_inference_properties.py):
  * at most one event per (kind, trip, stop_sequence) per call;
  * est_arrival <= observed_at (no arrivals in the future);
  * deterministic: the same inputs always produce the same outputs, in the same order;
  * a gap between snapshots never produces higher-than-low confidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .model import (
    Confidence,
    EventKind,
    Method,
    ObservedEvent,
    Snapshot,
    StopPrediction,
    TripKey,
    TripState,
    TripStatus,
    VehicleStop,
)

# A gap longer than this between snapshots means we may have missed when stops were served.
GAP_THRESHOLD_S = 180
# When a whole trip vanishes, only stops predicted within this window after the snapshot count as served.
TRIP_END_GRACE_S = 120
# Predictions this stale (relative to the previous snapshot) are not trusted for timing.
STALE_PREDICTION_S = 600

StoppedIndex = Mapping[tuple[TripKey, int], int]


def _service_date(start_date: str) -> str:
    return f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"


def confidence_for(lead_s: int, method: Method, gap_s: int) -> Confidence:
    if method is Method.VP_STOPPED:
        return Confidence.HIGH
    if gap_s > GAP_THRESHOLD_S or lead_s < -STALE_PREDICTION_S:
        return Confidence.LOW
    if lead_s <= 90:
        return Confidence.HIGH
    if lead_s <= 300:
        return Confidence.MEDIUM
    return Confidence.LOW


def _arrival(
    trip: TripState,
    stop: StopPrediction,
    *,
    prev_ts: int,
    cur_ts: int,
    stopped_at: int | None,
    method: Method,
) -> ObservedEvent | None:
    gap_s = cur_ts - prev_ts
    if stopped_at is not None:
        est = min(stopped_at, stop.time) if stop.time is not None else stopped_at
        used = Method.VP_STOPPED
    elif stop.time is not None:
        est = stop.time
        used = method
    else:
        return None
    est = min(est, cur_ts)
    lead = (stop.time - prev_ts) if stop.time is not None else 0
    conf = confidence_for(lead, used, gap_s)
    if method is Method.TRIP_END_FLUSH and conf is Confidence.HIGH and used is not Method.VP_STOPPED:
        conf = Confidence.MEDIUM  # trip disappearance is weaker evidence than a stop dropping off
    return ObservedEvent(
        kind=EventKind.ARRIVAL,
        service_date=_service_date(trip.key.start_date),
        trip_id=trip.key.trip_id,
        route_id=trip.route_id,
        direction_id=trip.direction_id,
        trip_status=trip.status,
        observed_at=cur_ts,
        stop_id=stop.stop_id,
        stop_sequence=stop.stop_sequence,
        vehicle_id=trip.vehicle_id,
        est_arrival=est,
        method=used,
        confidence=conf,
        lead_s=lead,
    )


def _skipped(trip: TripState, stop: StopPrediction, cur_ts: int) -> ObservedEvent:
    return ObservedEvent(
        kind=EventKind.SKIPPED,
        service_date=_service_date(trip.key.start_date),
        trip_id=trip.key.trip_id,
        route_id=trip.route_id,
        direction_id=trip.direction_id,
        trip_status=trip.status,
        observed_at=cur_ts,
        stop_id=stop.stop_id,
        stop_sequence=stop.stop_sequence,
        vehicle_id=trip.vehicle_id,
    )


def infer_events(prev: Snapshot | None, cur: Snapshot, stopped: StoppedIndex | None = None) -> list[ObservedEvent]:
    """Events revealed by moving from ``prev`` to ``cur``.

    ``stopped`` maps (trip, stop_sequence) to the earliest time the vehicle was seen STOPPED_AT that stop.
    Returns events sorted deterministically. Returns [] if there is no previous snapshot or the feed did
    not advance.
    """
    if prev is None or cur.feed_ts <= prev.feed_ts:
        return []
    stopped = stopped or {}
    events: list[ObservedEvent] = []

    for key in sorted(prev.trips):
        ptrip = prev.trips[key]
        ctrip = cur.trips.get(key)
        if ptrip.status is TripStatus.CANCELED:
            continue  # cancellations are reported once (below); their stops are neither served nor "skipped"
        remaining = [s for s in ctrip.stops if not ctrip.stops[s].skipped] if ctrip else []
        min_remaining = min(remaining) if remaining else None
        # A trip that never carried a single timed, non-skipped prediction is a placeholder (MBTA publishes
        # skip-only trips up to a day ahead); when one vanishes we learn nothing about its stops.
        trip_ran = any(not p.skipped and p.time is not None for p in ptrip.stops.values())
        for seq in sorted(ptrip.stops):
            pstop = ptrip.stops[seq]
            if ctrip is not None:
                if ctrip.status is TripStatus.CANCELED:
                    break
                if seq in ctrip.stops:
                    continue  # not served yet
                if min_remaining is not None and min_remaining < seq:
                    continue  # an earlier stop is still pending: out-of-order removal, don't guess
            stopped_at = stopped.get((key, seq))
            if pstop.skipped:
                if stopped_at is not None:
                    # Marked SKIPPED, but the vehicle was observed stopped there: trust the vehicle.
                    event = _arrival(
                        ptrip,
                        pstop,
                        prev_ts=prev.feed_ts,
                        cur_ts=cur.feed_ts,
                        stopped_at=stopped_at,
                        method=Method.LAST_PREDICTION,
                    )
                elif ctrip is not None or trip_ran:
                    # Confirmed skip: it left the feed as the trip moved past it, or the trip ended.
                    event = _skipped(ptrip, pstop, cur.feed_ts)
                else:
                    event = None
            else:
                if ctrip is None and (pstop.time is None or pstop.time > cur.feed_ts + TRIP_END_GRACE_S):
                    continue  # whole trip vanished: only stops that were imminent are plausibly served
                method = Method.LAST_PREDICTION if ctrip is not None else Method.TRIP_END_FLUSH
                event = _arrival(
                    ptrip, pstop, prev_ts=prev.feed_ts, cur_ts=cur.feed_ts, stopped_at=stopped_at, method=method
                )
            if event is not None:
                events.append(event)

    for key in sorted(cur.trips):
        now_trip = cur.trips[key]
        before = prev.trips.get(key)
        if now_trip.status is TripStatus.CANCELED and (before is None or before.status is not TripStatus.CANCELED):
            events.append(
                ObservedEvent(
                    kind=EventKind.CANCELED,
                    service_date=_service_date(key.start_date),
                    trip_id=key.trip_id,
                    route_id=now_trip.route_id,
                    direction_id=now_trip.direction_id,
                    trip_status=now_trip.status,
                    observed_at=cur.feed_ts,
                    vehicle_id=now_trip.vehicle_id,
                )
            )
    return events


def update_stopped_index(
    previous: StoppedIndex, observations: Iterable[VehicleStop], active: Snapshot
) -> dict[tuple[TripKey, int], int]:
    """Keep the earliest STOPPED_AT time per (trip, stop) for trips still in the feed."""
    merged: dict[tuple[TripKey, int], int] = {k: v for k, v in previous.items() if k[0] in active.trips}
    for obs in observations:
        key = (obs.trip, obs.stop_sequence)
        if obs.trip in active.trips and (key not in merged or obs.ts < merged[key]):
            merged[key] = obs.ts
    return merged
