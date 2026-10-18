"""Hand-written scenarios for arrival inference (the property tests cover invariants)."""

from __future__ import annotations

from stopwatch.core.inference import (
    Confidence,
    EventKind,
    Method,
    Snapshot,
    StopPrediction,
    TripKey,
    TripState,
    TripStatus,
    VehicleStop,
    infer_events,
    update_stopped_index,
)

K = TripKey("t1", "20261019")


def trip(stops: dict[int, int | None], *, status: TripStatus = TripStatus.SCHEDULED,
         skipped: set[int] | None = None, key: TripKey = K) -> TripState:
    skipped = skipped or set()
    return TripState(key=key, route_id="1", direction_id=0, vehicle_id="v1", status=status,
                     stops={s: StopPrediction(s, f"stop{s}", t, s in skipped) for s, t in stops.items()})


def snap(ts: int, *trips: TripState) -> Snapshot:
    return Snapshot(feed_ts=ts, trips={t.key: t for t in trips})


def test_first_snapshot_emits_nothing() -> None:
    assert infer_events(None, snap(1000, trip({1: 1100}))) == []


def test_feed_not_advanced_emits_nothing() -> None:
    s = snap(1000, trip({1: 1030, 2: 1200}))
    assert infer_events(s, snap(1000, trip({2: 1200}))) == []
    assert infer_events(s, snap(990, trip({2: 1200}))) == []


def test_served_stop_uses_last_prediction() -> None:
    prev = snap(1000, trip({1: 1030, 2: 1200}))
    cur = snap(1060, trip({2: 1210}))
    [ev] = infer_events(prev, cur)
    assert ev.kind is EventKind.ARRIVAL
    assert (ev.stop_sequence, ev.est_arrival, ev.method) == (1, 1030, Method.LAST_PREDICTION)
    assert ev.confidence is Confidence.HIGH  # predicted 30 s ahead
    assert ev.service_date == "2026-10-19"


def test_estimate_never_after_observation_time() -> None:
    prev = snap(1000, trip({1: 1500, 2: 1600}))  # prediction far in the future, yet the stop vanished
    [ev] = infer_events(prev, snap(1060, trip({2: 1600})))
    assert ev.est_arrival == 1060
    assert ev.confidence is Confidence.LOW  # lead 500 s


def test_vehicle_stopped_observation_wins() -> None:
    prev = snap(1000, trip({1: 1045, 2: 1200}))
    cur = snap(1060, trip({2: 1200}))
    [ev] = infer_events(prev, cur, {(K, 1): 1020})
    assert (ev.method, ev.est_arrival, ev.confidence) == (Method.VP_STOPPED, 1020, Confidence.HIGH)


def test_gap_downgrades_confidence() -> None:
    prev = snap(1000, trip({1: 1030, 2: 1200}))
    [ev] = infer_events(prev, snap(1400, trip({2: 1450})))
    assert ev.confidence is Confidence.LOW


def test_out_of_order_removal_is_not_guessed() -> None:
    prev = snap(1000, trip({1: 1030, 2: 1100, 3: 1200}))
    cur = snap(1060, trip({1: 1070, 3: 1200}))  # stop 2 vanished but stop 1 is still pending
    assert infer_events(prev, cur) == []


def test_vanished_trip_flushes_only_imminent_stops() -> None:
    prev = snap(1000, trip({5: 1050, 6: 1500}))
    events = infer_events(prev, snap(1060))
    assert [(e.stop_sequence, e.method) for e in events] == [(5, Method.TRIP_END_FLUSH)]
    assert events[0].confidence is Confidence.MEDIUM


def test_skipped_and_canceled_events_are_emitted_once() -> None:
    prev = snap(1000, trip({1: 1030, 2: 1100}))
    cur = snap(1060, trip({1: 1070, 2: 1100}, skipped={2}))
    [ev] = infer_events(prev, cur)
    assert (ev.kind, ev.stop_sequence) == (EventKind.SKIPPED, 2)
    # Still skipped in the next snapshot: no duplicate.
    assert infer_events(cur, snap(1120, trip({1: 1130, 2: 1100}, skipped={2}))) == []

    canceled = snap(1180, trip({1: 1190}, status=TripStatus.CANCELED))
    [cx] = infer_events(snap(1120, trip({1: 1130})), canceled)
    assert cx.kind is EventKind.CANCELED
    assert infer_events(canceled, snap(1240, trip({1: 1250}, status=TripStatus.CANCELED))) == []


def test_skipped_stop_disappearing_is_not_an_arrival() -> None:
    prev = snap(1000, trip({1: 1030, 2: 1100}, skipped={1}))
    assert infer_events(prev, snap(1060, trip({2: 1100}))) == []


def test_stopped_index_keeps_earliest_and_drops_finished_trips() -> None:
    other = TripKey("t2", "20261019")
    active = snap(1000, trip({1: 1030}))
    idx = update_stopped_index({(other, 3): 900}, [VehicleStop(K, 1, 1010), VehicleStop(K, 1, 990)], active)
    assert idx == {(K, 1): 990}


def test_stop_that_reappears_can_be_emitted_again_and_compaction_must_dedupe() -> None:
    a = snap(1000, trip({1: 1030, 2: 1200}))
    b = snap(1060, trip({2: 1200}))            # stop 1 served
    c = snap(1120, trip({1: 1090, 2: 1210}))   # feed glitch: stop 1 is back
    d = snap(1180, trip({2: 1215}))            # ... and gone again
    first, second = infer_events(a, b), infer_events(c, d)
    assert first[0].key() == second[0].key()  # same idempotency key -> one row after compaction
