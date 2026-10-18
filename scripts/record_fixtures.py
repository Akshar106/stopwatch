"""Record live GTFS-Realtime snapshots for replay tests.

Polls TripUpdates and VehiclePositions once a minute (polite), saving raw protobufs to
backend/tests/fixtures/rt_snapshots/full/ (gitignored). Then writes a trimmed copy containing only a few
routes to rt_snapshots/sample/ (small enough to commit).

    uv run python ../scripts/record_fixtures.py --minutes 15 --routes 1,39,Red,Green-B,SL1
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx
from google.transit import gtfs_realtime_pb2 as rt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "tests" / "fixtures" / "rt_snapshots"
FEEDS = {
    "tu": "https://cdn.mbta.com/realtime/TripUpdates.pb",
    "vp": "https://cdn.mbta.com/realtime/VehiclePositions.pb",
}


def record(minutes: int, out: Path) -> list[int]:
    out.mkdir(parents=True, exist_ok=True)
    stamps: list[int] = []
    with httpx.Client(timeout=15, headers={"User-Agent": "stopwatch-fixture-recorder/0.1"}) as client:
        for i in range(minutes):
            started = time.monotonic()
            tu = client.get(FEEDS["tu"]).content
            vp = client.get(FEEDS["vp"]).content
            msg = rt.FeedMessage()
            msg.ParseFromString(tu)
            ts = int(msg.header.timestamp)
            (out / f"{ts}-tu.pb").write_bytes(tu)
            (out / f"{ts}-vp.pb").write_bytes(vp)
            stamps.append(ts)
            print(f"[{i + 1}/{minutes}] saved snapshot {ts} ({len(tu) // 1024} KB)", flush=True)
            if i < minutes - 1:
                time.sleep(max(0.0, 60 - (time.monotonic() - started)))
    return stamps


def trim(full: Path, sample: Path, routes: set[str]) -> None:
    sample.mkdir(parents=True, exist_ok=True)
    for path in sorted(full.glob("*.pb")):
        msg = rt.FeedMessage()
        msg.ParseFromString(path.read_bytes())
        keep = rt.FeedMessage()
        keep.header.CopyFrom(msg.header)
        for ent in msg.entity:
            route = (ent.trip_update.trip.route_id if ent.HasField("trip_update")
                     else ent.vehicle.trip.route_id if ent.HasField("vehicle") else "")
            if route in routes:
                keep.entity.add().CopyFrom(ent)
        (sample / path.name).write_bytes(keep.SerializeToString())
    print(f"trimmed {len(list(sample.glob('*.pb')))} files into {sample}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=int, default=15)
    ap.add_argument("--routes", default="1,39,Red,Green-B,SL1")
    ap.add_argument("--trim-only", action="store_true", help="skip recording; re-trim existing captures")
    args = ap.parse_args()
    full = OUT / "full"
    if not args.trim_only:
        record(args.minutes, full)
    trim(full, OUT / "sample", {r.strip() for r in args.routes.split(",")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
