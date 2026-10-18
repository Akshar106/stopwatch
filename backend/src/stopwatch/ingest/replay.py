"""Replay recorded snapshots through the same inference code (deterministic; used by tests and `make replay`).

A directory holds pairs ``{feed_ts}-tu.pb`` / ``{feed_ts}-vp.pb`` as written by scripts/record_fixtures.py.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections import Counter
from pathlib import Path

from stopwatch.core.inference import ObservedEvent, Snapshot, TripKey, infer_events, update_stopped_index
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.http import FetchError

from .feeds import parse_trip_updates, parse_vehicle_positions
from .tick import TickDeps, TickResult, event_to_dict, run_tick


def replay_directory(directory: Path) -> list[ObservedEvent]:
    stamps = sorted({int(p.name.split("-")[0]) for p in directory.glob("*-tu.pb")})
    prev: Snapshot | None = None
    stopped: dict[tuple[TripKey, int], int] = {}
    events: list[ObservedEvent] = []
    for ts in stamps:
        cur = parse_trip_updates((directory / f"{ts}-tu.pb").read_bytes())
        vp_path = directory / f"{ts}-vp.pb"
        if vp_path.exists():
            for obs in parse_vehicle_positions(vp_path.read_bytes()).stopped:
                k = (obs.trip, obs.stop_sequence)
                if k not in stopped or obs.ts < stopped[k]:
                    stopped[k] = obs.ts
        events.extend(infer_events(prev, cur, stopped))
        if prev is None or cur.feed_ts > prev.feed_ts:
            prev = cur
            stopped = update_stopped_index(stopped, [], cur)
    return events


def replay_into_lake(directory: Path, agency: AgencyConfig, lake: BlobStore, site: BlobStore) -> list[TickResult]:
    """Drive the *real* ingest tick with recorded snapshots (exercises state CAS, event writes, health)."""
    stamps = sorted({int(p.name.split("-")[0]) for p in directory.glob("*-tu.pb")})
    results = []
    for ts in stamps:
        payloads = {agency.trip_updates_url: (directory / f"{ts}-tu.pb").read_bytes()}
        vp = directory / f"{ts}-vp.pb"
        if vp.exists():
            payloads[agency.vehicle_positions_url] = vp.read_bytes()

        def fetch(url: str, max_bytes: int, payloads: dict[str, bytes] = payloads) -> bytes:
            if url not in payloads:
                raise FetchError(f"no recorded payload for {url}")
            return payloads[url]

        results.append(
            run_tick(agency, TickDeps(lake=lake, site=site, fetch=fetch, now=functools.partial(int, ts + 5)))
        )
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--jsonl", action="store_true", help="print every event as JSON lines")
    ap.add_argument(
        "--into-lake",
        action="store_true",
        help="run the real ingest tick against LAKE_URL/SITE_URL for each recorded snapshot",
    )
    args = ap.parse_args()
    if args.into_lake:
        from stopwatch.platform.agencies import get_agency
        from stopwatch.platform.blobstore import open_blobstore
        from stopwatch.platform.config import get_settings

        s = get_settings()
        results = replay_into_lake(
            args.directory, get_agency(s.agency_ids[0]), open_blobstore(s.lake_url), open_blobstore(s.site_url)
        )
        print(json.dumps([{"outcome": r.outcome, "feed_ts": r.feed_ts, "counts": r.counts} for r in results]))
        return 0
    events = replay_directory(args.directory)
    if args.jsonl:
        for e in events:
            print(json.dumps(event_to_dict(e), sort_keys=True))
    else:
        by_kind = Counter(e.kind.value for e in events)
        by_conf = Counter(e.confidence.value for e in events if e.confidence)
        print(json.dumps({"events": len(events), "by_kind": by_kind, "by_confidence": by_conf}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
