"""One ingest tick: fetch → parse → diff against previous snapshot → write events → save state (CAS).

At-least-once with idempotent keys: events are written under a key derived from the feed timestamp, and
the daily compaction de-duplicates by (kind, service date, trip, stop sequence). The state object is
written with If-Match so two overlapping ticks can never silently corrupt each other.
"""

from __future__ import annotations

import gzip
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from stopwatch.core.inference import Confidence, EventKind, ObservedEvent, Snapshot, infer_events, update_stopped_index
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.http import FetchError

from . import state as state_mod
from .feeds import FeedParseError, ParsedVehicles, parse_trip_updates, parse_vehicle_positions
from .health import build_health
from .state import IngestState

HEALTH_EVERY_S = 300

Fetch = Callable[[str, int], bytes]
SnapshotHook = Callable[[Snapshot, IngestState, int], None]


def state_key(agency_id: str) -> str:
    return f"state/{agency_id}/latest.json.gz"


def events_key(agency_id: str, feed_ts: int) -> str:
    day = datetime.fromtimestamp(feed_ts, UTC).strftime("%Y-%m-%d")
    return f"events/agency={agency_id}/dt={day}/{feed_ts}.jsonl.gz"


def health_key(agency_id: str) -> str:
    return f"data/v1/health/{agency_id}.json"


def event_to_dict(e: ObservedEvent) -> dict[str, Any]:
    d = asdict(e)
    for k in ("kind", "trip_status", "method", "confidence"):
        if d[k] is not None:
            d[k] = str(d[k])
    return d


def encode_events(events: list[ObservedEvent]) -> bytes:
    lines = "\n".join(json.dumps(event_to_dict(e), separators=(",", ":"), sort_keys=True) for e in events)
    return gzip.compress((lines + "\n").encode(), mtime=0)


@dataclass
class TickResult:
    agency_id: str
    outcome: str  # ok | not_advanced | failed
    feed_ts: int | None = None
    feed_age_s: int | None = None
    counts: dict[str, int] = field(default_factory=dict)
    low_confidence_ratio: float | None = None
    duration_ms: int = 0
    error: str | None = None


@dataclass
class TickDeps:
    lake: BlobStore
    site: BlobStore
    fetch: Fetch
    now: Callable[[], int] = lambda: int(time.time())
    on_snapshot: SnapshotHook | None = None  # e.g. alert evaluation


def _persist(deps: TickDeps, agency: AgencyConfig, st: IngestState, etag: str | None) -> None:
    data = state_mod.dumps(st)
    if etag is None:
        deps.lake.put(state_key(agency.id), data, content_type="application/gzip", if_none_match=True)
    else:
        deps.lake.put(state_key(agency.id), data, content_type="application/gzip", if_match=etag)


def _maybe_publish_health(deps: TickDeps, agency: AgencyConfig, st: IngestState, now: int) -> None:
    if st.last_health_publish_at is not None and now - st.last_health_publish_at < HEALTH_EVERY_S:
        return
    body = json.dumps(build_health(agency.id, st, now), separators=(",", ":")).encode()
    deps.site.put(health_key(agency.id), body, content_type="application/json", cache_control="public, max-age=60")
    st.last_health_publish_at = now


def _maybe_sample_raw(
    deps: TickDeps, agency: AgencyConfig, st: IngestState, feed_ts: int, tu: bytes, vp: bytes | None
) -> None:
    hour = datetime.fromtimestamp(feed_ts, UTC).strftime("%Y-%m-%d/%H")
    if st.last_raw_sample_hour == hour:
        return
    day, hh = hour.split("/")
    deps.lake.put(f"raw/agency={agency.id}/dt={day}/{hh}-tu.pb", tu, content_type="application/x-protobuf")
    if vp:
        deps.lake.put(f"raw/agency={agency.id}/dt={day}/{hh}-vp.pb", vp, content_type="application/x-protobuf")
    st.last_raw_sample_hour = hour


def run_tick(agency: AgencyConfig, deps: TickDeps) -> TickResult:
    started = time.monotonic()
    now = deps.now()
    blob = deps.lake.get(state_key(agency.id))
    st = state_mod.loads(blob.data) if blob else IngestState()
    etag = blob.etag if blob else None
    result = TickResult(agency_id=agency.id, outcome="failed")

    try:
        tu = deps.fetch(agency.trip_updates_url, agency.max_feed_bytes)
        cur = parse_trip_updates(tu, now=now)
    except FeedParseError as exc:
        deps.lake.put(f"raw/agency={agency.id}/errors/{now}-tu.pb", tu, content_type="application/x-protobuf")
        result.error = f"parse: {exc}"
    except FetchError as exc:
        result.error = f"fetch: {exc}"
    else:
        try:
            vp: bytes | None = deps.fetch(agency.vehicle_positions_url, agency.max_feed_bytes)
            vehicles = parse_vehicle_positions(vp)
        except (FetchError, FeedParseError):
            vp, vehicles = None, ParsedVehicles(feed_ts=cur.feed_ts, stopped=[], count=0)
        result.feed_ts = cur.feed_ts
        result.feed_age_s = now - cur.feed_ts
        prev = st.snapshot
        if prev is not None and cur.feed_ts <= prev.feed_ts:
            result.outcome = "not_advanced"
        else:
            merged = dict(st.stopped)
            for obs in vehicles.stopped:
                k = (obs.trip, obs.stop_sequence)
                if k not in merged or obs.ts < merged[k]:
                    merged[k] = obs.ts
            events = infer_events(prev, cur, merged)
            if events:
                deps.lake.put(
                    events_key(agency.id, cur.feed_ts), encode_events(events), content_type="application/gzip"
                )
            counts = Counter(e.kind.value for e in events)
            arrivals = [e for e in events if e.kind is EventKind.ARRIVAL]
            result.counts = dict(counts)
            if arrivals:
                low = sum(1 for e in arrivals if e.confidence is Confidence.LOW)
                result.low_confidence_ratio = round(100.0 * low / len(arrivals), 2)
            if deps.on_snapshot is not None:
                deps.on_snapshot(cur, st, now)
            st.snapshot = cur
            st.stopped = update_stopped_index(merged, [], cur)
            _maybe_sample_raw(deps, agency, st, cur.feed_ts, tu, vp)
            result.outcome = "ok"

    st.record_tick(now, result.outcome)
    _maybe_publish_health(deps, agency, st, now)
    _persist(deps, agency, st, etag)  # raises PreconditionFailedError on a concurrent writer
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
