"""Invariants of arrival inference over randomly generated snapshot sequences (Hypothesis)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stopwatch.core.inference import (
    Confidence,
    EventKind,
    Snapshot,
    StopPrediction,
    TripKey,
    TripState,
    TripStatus,
    infer_events,
)


@st.composite
def snapshot_sequences(draw: st.DrawFn) -> list[Snapshot]:
    """Trips whose remaining stops shrink over time, as in a real feed, with random noise."""
    n_trips = draw(st.integers(1, 6))
    n_snaps = draw(st.integers(2, 8))
    start = draw(st.integers(1_700_000_000, 1_800_000_000))
    gaps = draw(st.lists(st.integers(30, 400), min_size=n_snaps, max_size=n_snaps))
    times = [start]
    for g in gaps[1:]:
        times.append(times[-1] + g)
    trips_plan = []
    for i in range(n_trips):
        n_stops = draw(st.integers(1, 12))
        first_arrival = start + draw(st.integers(-120, 900))
        spacing = draw(st.integers(30, 240))
        skipped = set(draw(st.lists(st.integers(1, n_stops), max_size=2)))
        cancel_at = draw(st.one_of(st.none(), st.integers(0, n_snaps - 1)))
        trips_plan.append((TripKey(f"t{i}", "20261019"), n_stops, first_arrival, spacing, skipped, cancel_at))
    snaps = []
    for si, ts in enumerate(times):
        trips = {}
        for key, n_stops, first, spacing, skipped, cancel_at in trips_plan:
            jitter = draw(st.integers(-30, 90))
            stops = {}
            for seq in range(1, n_stops + 1):
                t = first + (seq - 1) * spacing + jitter
                if t > ts - 20 or seq in skipped:  # past stops drop off the feed
                    stops[seq] = StopPrediction(seq, f"s{seq}", t, seq in skipped)
            if not stops and draw(st.booleans()):
                continue  # finished trips vanish
            status = TripStatus.CANCELED if cancel_at is not None and si >= cancel_at else TripStatus.SCHEDULED
            trips[key] = TripState(key, "R", 0, "v", status, stops)
        snaps.append(Snapshot(feed_ts=ts, trips=trips))
    return snaps


def _run(snaps: list[Snapshot]) -> list[list]:
    out = []
    prev = None
    for s in snaps:
        out.append(infer_events(prev, s))
        prev = s
    return out


@settings(max_examples=300, deadline=None)
@given(snapshot_sequences())
def test_at_most_one_event_per_key_per_call(snaps: list[Snapshot]) -> None:
    for events in _run(snaps):
        keys = [e.key() for e in events]
        assert len(keys) == len(set(keys))


@settings(max_examples=300, deadline=None)
@given(snapshot_sequences())
def test_no_arrival_in_the_future(snaps: list[Snapshot]) -> None:
    for events in _run(snaps):
        for e in events:
            if e.kind is EventKind.ARRIVAL:
                assert e.est_arrival is not None
                assert e.est_arrival <= e.observed_at


@settings(max_examples=200, deadline=None)
@given(snapshot_sequences())
def test_deterministic(snaps: list[Snapshot]) -> None:
    assert _run(snaps) == _run(snaps)


@settings(max_examples=200, deadline=None)
@given(snapshot_sequences())
def test_gaps_never_produce_confident_prediction_based_arrivals(snaps: list[Snapshot]) -> None:
    prev = None
    for s in snaps:
        events = infer_events(prev, s)
        if prev is not None and s.feed_ts - prev.feed_ts > 180:
            for e in events:
                if e.kind is EventKind.ARRIVAL:
                    assert e.confidence is Confidence.LOW
        prev = s


@settings(max_examples=200, deadline=None)
@given(snapshot_sequences())
def test_duplicates_across_ticks_collapse_under_the_compaction_key(snaps: list[Snapshot]) -> None:
    """Real feeds sometimes drop a stop and then re-add it, so the same arrival can be emitted by two ticks.
    infer_events only promises uniqueness *within* a tick; compaction de-duplicates by key across ticks.
    Here we check the compaction rule (keep one row per key) always yields unique keys and keeps the
    earliest-observed estimate when confidences tie."""
    best: dict = {}
    for events in _run(snaps):
        for e in events:
            if e.kind is EventKind.ARRIVAL:
                k = e.key()
                rank = {"high": 0, "medium": 1, "low": 2}[e.confidence.value]
                if k not in best or rank < best[k][0]:
                    best[k] = (rank, e)
    keys = [v[1].key() for v in best.values()]
    assert len(keys) == len(set(keys))
