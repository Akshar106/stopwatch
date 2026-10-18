"""Nightly contract check of the live feed against the assumptions inference relies on (docs/06 §1).

Exit code 1 means an assumption no longer holds; CI opens an issue with the JSON report.

    python -m stopwatch.ingest.drift_check [--agency mbta]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from google.transit import gtfs_realtime_pb2 as rt

from stopwatch.platform.agencies import get_agency
from stopwatch.platform.http import fetch_bytes

CHECKS: dict[str, tuple[str, float]] = {
    # name: (comparison, threshold)
    "feed_age_s": ("max", 600),
    "trip_updates": ("min", 100),
    "past_stop_share": ("max", 0.05),  # served stops should leave the feed (inference depends on it)
    # Raw SKIPPED share is ~18% because of skip-only placeholder trips (docs/feed-notes.md); the share that
    # matters is among trips actually carrying predictions (~2% observed on 2026-10-18).
    "active_skipped_share": ("max", 0.10),
    "stop_sequence_share": ("min", 0.99),  # we key stops by stop_sequence
    "start_date_share": ("min", 0.99),  # and trips by (trip_id, start_date)
    "vehicle_stop_sequence_share": ("min", 0.5),
}


def _active_skipped_share(trips: list[Any]) -> float:
    skipped = rt.TripUpdate.StopTimeUpdate.SKIPPED
    active = [
        t
        for t in trips
        if any(s.schedule_relationship != skipped and (s.arrival.time or s.departure.time) for s in t.stop_time_update)
    ]
    stops = [s for t in active for s in t.stop_time_update]
    return sum(1 for s in stops if s.schedule_relationship == skipped) / max(len(stops), 1)


def measure(agency_id: str) -> dict[str, Any]:
    agency = get_agency(agency_id)
    tu = rt.FeedMessage()
    tu.ParseFromString(fetch_bytes(agency.trip_updates_url, max_bytes=agency.max_feed_bytes).data)
    vp = rt.FeedMessage()
    vp.ParseFromString(fetch_bytes(agency.vehicle_positions_url, max_bytes=agency.max_feed_bytes).data)
    now = int(time.time())
    ts = int(tu.header.timestamp)
    trips = [e.trip_update for e in tu.entity if e.HasField("trip_update")]
    stus = [s for t in trips for s in t.stop_time_update]
    times = [(s.arrival.time or s.departure.time) for s in stus]
    vehicles = [e.vehicle for e in vp.entity if e.HasField("vehicle")]
    n = max(len(stus), 1)
    return {
        "agency": agency_id,
        "feed_timestamp": ts,
        "feed_age_s": now - ts,
        "gtfs_realtime_version": tu.header.gtfs_realtime_version,
        "trip_updates": len(trips),
        "stop_time_updates": len(stus),
        "past_stop_share": round(sum(1 for t in times if t and t < ts - 120) / n, 4),
        "skipped_share": round(
            sum(1 for s in stus if s.schedule_relationship == rt.TripUpdate.StopTimeUpdate.SKIPPED) / n, 4
        ),
        "active_skipped_share": round(_active_skipped_share(trips), 4),
        "delay_field_share": round(sum(1 for s in stus if s.arrival.HasField("delay")) / n, 4),
        "stop_sequence_share": round(sum(1 for s in stus if s.HasField("stop_sequence")) / n, 4),
        "start_date_share": round(sum(1 for t in trips if t.trip.start_date) / max(len(trips), 1), 4),
        "vehicles": len(vehicles),
        "vehicle_stop_sequence_share": round(
            sum(1 for v in vehicles if v.HasField("current_stop_sequence")) / max(len(vehicles), 1), 4
        ),
    }


def evaluate(m: dict[str, Any]) -> list[str]:
    failures = []
    for name, (kind, limit) in CHECKS.items():
        value = m[name]
        if (kind == "max" and value > limit) or (kind == "min" and value < limit):
            failures.append(f"{name}={value} violates {kind} {limit}")
    if m["delay_field_share"] > 0:
        failures.append(
            f"delay_field_share={m['delay_field_share']}: feed now publishes delay; consider using it (informational)"
        )
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agency", default="mbta")
    m = measure(ap.parse_args().agency)
    failures = evaluate(m)
    print(json.dumps({"measurements": m, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
