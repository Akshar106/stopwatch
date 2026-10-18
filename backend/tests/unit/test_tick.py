"""Ingest tick behavior with in-memory fakes: CAS, failure handling, not-advanced feeds, health cadence."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2 as rt

from stopwatch.ingest import state as state_mod
from stopwatch.ingest.tick import TickDeps, run_tick, state_key
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import PreconditionFailedError, open_blobstore
from stopwatch.platform.http import FetchError

MBTA = get_agency("mbta")


def feed(ts: int, stops: dict[int, int], trip: str = "t1", skipped: tuple[int, ...] = ()) -> bytes:
    m = rt.FeedMessage()
    m.header.gtfs_realtime_version = "2.0"
    m.header.timestamp = ts
    e = m.entity.add()
    e.id = trip
    tu = e.trip_update
    tu.trip.trip_id = trip
    tu.trip.start_date = "20261019"
    tu.trip.route_id = "1"
    tu.trip.direction_id = 0
    for seq, t in stops.items():
        s = tu.stop_time_update.add()
        s.stop_sequence = seq
        s.stop_id = f"s{seq}"
        s.arrival.time = t
        if seq in skipped:
            s.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SKIPPED
    return m.SerializeToString()


def vehicles(ts: int) -> bytes:
    m = rt.FeedMessage()
    m.header.gtfs_realtime_version = "2.0"
    m.header.timestamp = ts
    return m.SerializeToString()


class FakeFeed:
    def __init__(self) -> None:
        self.tu: bytes | Exception = b""
        self.vp: bytes | Exception = vehicles(1)

    def __call__(self, url: str, max_bytes: int) -> bytes:
        v = self.tu if "TripUpdates" in url else self.vp
        if isinstance(v, Exception):
            raise v
        return v


@pytest.fixture
def env(tmp_path: Path) -> tuple[TickDeps, FakeFeed]:
    fake = FakeFeed()
    deps = TickDeps(lake=open_blobstore(f"file://{tmp_path}/lake"), site=open_blobstore(f"file://{tmp_path}/site"),
                    fetch=fake)
    return deps, fake


def tick(deps: TickDeps, now: int):  # type: ignore[no-untyped-def]
    deps.now = lambda: now
    return run_tick(MBTA, deps)


def test_two_ticks_emit_an_arrival_and_persist_state(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    t0 = 1_792_400_000
    fake.tu = feed(t0, {1: t0 + 30, 2: t0 + 200})
    assert tick(deps, t0 + 5).outcome == "ok"
    fake.tu = feed(t0 + 60, {2: t0 + 210})
    r = tick(deps, t0 + 65)
    assert r.outcome == "ok" and r.counts == {"arrival": 1}
    events = deps.lake.list("events/agency=mbta/")
    assert len(events) == 1 and events[0].endswith(f"{t0 + 60}.jsonl.gz")
    st = state_mod.loads(deps.lake.get(state_key("mbta")).data)  # type: ignore[union-attr]
    assert st.snapshot is not None and st.snapshot.feed_ts == t0 + 60
    assert [o for _, o in st.ticks] == ["ok", "ok"]


def test_feed_not_advanced_is_a_no_op(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    fake.tu = feed(1_792_400_000, {1: 1_792_400_030})
    tick(deps, 1_792_400_005)
    r = tick(deps, 1_792_400_065)
    assert r.outcome == "not_advanced" and deps.lake.list("events/") == []


def test_fetch_failure_records_a_failed_tick_and_keeps_snapshot(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    fake.tu = feed(1_792_400_000, {1: 1_792_400_030})
    tick(deps, 1_792_400_005)
    fake.tu = FetchError("HTTP 503")
    r = tick(deps, 1_792_400_065)
    assert r.outcome == "failed" and r.error and "fetch" in r.error
    st = state_mod.loads(deps.lake.get(state_key("mbta")).data)  # type: ignore[union-attr]
    assert st.snapshot is not None and st.snapshot.feed_ts == 1_792_400_000


def test_unparseable_feed_is_saved_for_debugging(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    fake.tu = b"\x08\x96\x01garbage"
    r = tick(deps, 1_792_400_005)
    assert r.outcome == "failed" and "parse" in (r.error or "")
    assert deps.lake.list("raw/agency=mbta/errors/")


def test_vehicle_feed_failure_does_not_fail_the_tick(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    fake.tu = feed(1_792_400_000, {1: 1_792_400_030})
    fake.vp = FetchError("timeout")
    assert tick(deps, 1_792_400_005).outcome == "ok"


def test_concurrent_writer_is_detected(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    fake.tu = feed(1_792_400_000, {1: 1_792_400_030})
    tick(deps, 1_792_400_005)
    real_get = deps.lake.get

    def stale_get(key: str):  # type: ignore[no-untyped-def]
        blob = real_get(key)
        if key == state_key("mbta"):
            deps.lake.put(key, blob.data + b"")  # another writer re-saves...
            deps.lake.put(key, state_mod.dumps(state_mod.IngestState()))  # ...and changes it
        return blob

    deps.lake.get = stale_get  # type: ignore[method-assign]
    fake.tu = feed(1_792_400_060, {1: 1_792_400_070})
    with pytest.raises(PreconditionFailedError):
        tick(deps, 1_792_400_065)


def test_health_published_at_most_every_five_minutes(env: tuple[TickDeps, FakeFeed]) -> None:
    deps, fake = env
    t0 = 1_792_400_000
    fake.tu = feed(t0, {1: t0 + 30})
    tick(deps, t0 + 5)
    first = deps.site.get("data/v1/health/mbta.json")
    fake.tu = feed(t0 + 60, {1: t0 + 70})
    tick(deps, t0 + 65)
    assert deps.site.get("data/v1/health/mbta.json") == first
    fake.tu = feed(t0 + 400, {1: t0 + 410})
    tick(deps, t0 + 405)
    assert deps.site.get("data/v1/health/mbta.json") != first
