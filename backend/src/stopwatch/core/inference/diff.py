"""Infer arrivals by diffing consecutive GTFS-Realtime snapshots.

The MBTA feed (like most) only carries *future* stops: once a vehicle serves a stop, that stop's prediction
disappears. So a stop present in the previous snapshot and absent from the current one was served
somewhere in between, and the last prediction we saw is the best available estimate of when. Vehicle
positions that show the vehicle STOPPED_AT the stop tighten the estimate.

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
            continue
        remaining = [s for s in ctrip.stops if not ctrip.stops[s].skipped] if ctrip else []
        min_remaining = min(remaining) if remaining else None
        for seq in sorted(ptrip.stops):
            pstop = ptrip.stops[seq]
            if pstop.skipped:
                continue
            if ctrip is not None:
                if ctrip.status is TripStatus.CANCELED:
                    break
                if seq in ctrip.stops:
                    continue  # not served yet (or now marked skipped; handled below)
                if min_remaining is not None and min_remaining < seq:
                    continue  # an earlier stop is still pending: out-of-order removal, don't guess
                method = Method.LAST_PREDICTION
            else:
                # Whole trip vanished: only stops that were imminent are plausibly served.
                if pstop.time is None or pstop.time > cur.feed_ts + TRIP_END_GRACE_S:
                    continue
                method = Method.TRIP_END_FLUSH
            event = _arrival(
                ptrip,
                pstop,
                prev_ts=prev.feed_ts,
                cur_ts=cur.feed_ts,
                stopped_at=stopped.get((key, seq)),
                method=method,
            )
            if event is not None:
                events.append(event)

    for key in sorted(cur.trips):
        ctrip = cur.trips[key]
        ptrip = prev.trips.get(key)
        if ctrip.status is TripStatus.CANCELED and (ptrip is None or ptrip.status is not TripStatus.CANCELED):
            events.append(
                ObservedEvent(
                    kind=EventKind.CANCELED,
                    service_date=_service_date(key.start_date),
                    trip_id=key.trip_id,
                    route_id=ctrip.route_id,
                    direction_id=ctrip.direction_id,
                    trip_status=ctrip.status,
                    observed_at=cur.feed_ts,
                    vehicle_id=ctrip.vehicle_id,
                )
            )
            continue
        for seq in sorted(ctrip.stops):
            cstop = ctrip.stops[seq]
            if not cstop.skipped:
                continue
            was_skipped = ptrip is not None and seq in ptrip.stops and ptrip.stops[seq].skipped
            if not was_skipped:
                events.append(
                    ObservedEvent(
                        kind=EventKind.SKIPPED,
                        service_date=_service_date(key.start_date),
                        trip_id=key.trip_id,
                        route_id=ctrip.route_id,
                        direction_id=ctrip.direction_id,
                        trip_status=ctrip.status,
                        observed_at=cur.feed_ts,
                        stop_id=cstop.stop_id,
                        stop_sequence=seq,
                        vehicle_id=ctrip.vehicle_id,
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
