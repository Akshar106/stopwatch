"""Ingest state persisted between ticks (one gzip JSON object per agency, written with compare-and-swap)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from typing import Any

from stopwatch.core.inference import Snapshot, StopPrediction, TripKey, TripState, TripStatus

STATE_VERSION = 1
TICK_HISTORY = 120  # minutes of tick outcomes kept for health reporting
GAP_HISTORY_DAYS = 7
GAP_MIN_S = 180


@dataclass
class IngestState:
    snapshot: Snapshot | None = None
    stopped: dict[tuple[TripKey, int], int] = field(default_factory=dict)
    # [epoch_s, outcome] with outcome in {"ok", "failed", "not_advanced"}, newest last
    ticks: list[tuple[int, str]] = field(default_factory=list)
    last_success_at: int | None = None
    gaps: list[tuple[int, int]] = field(default_factory=list)  # [start, end] epoch seconds
    last_health_publish_at: int | None = None
    last_raw_sample_hour: str | None = None
    alerts_sent: list[str] = field(default_factory=list)  # dedupe keys already handed to notify today

    def record_tick(self, at: int, outcome: str) -> None:
        if outcome == "ok":
            if self.last_success_at is not None and at - self.last_success_at >= GAP_MIN_S:
                self.gaps.append((self.last_success_at, at))
            self.last_success_at = at
        self.ticks.append((at, outcome))
        self.ticks = self.ticks[-TICK_HISTORY:]
        cutoff = at - GAP_HISTORY_DAYS * 86400
        self.gaps = [g for g in self.gaps if g[1] >= cutoff]


def _snapshot_to_json(s: Snapshot) -> dict[str, Any]:
    return {
        "feed_ts": s.feed_ts,
        "trips": [
            [
                k.trip_id,
                k.start_date,
                t.route_id,
                t.direction_id,
                t.vehicle_id,
                t.status.value,
                [[p.stop_sequence, p.stop_id, p.time, 1 if p.skipped else 0] for p in t.stops.values()],
            ]
            for k, t in s.trips.items()
        ],
    }


def _snapshot_from_json(d: dict[str, Any]) -> Snapshot:
    trips: dict[TripKey, TripState] = {}
    for trip_id, start_date, route_id, direction_id, vehicle_id, status, stops in d["trips"]:
        key = TripKey(trip_id, start_date)
        trips[key] = TripState(
            key=key,
            route_id=route_id,
            direction_id=direction_id,
            vehicle_id=vehicle_id,
            status=TripStatus(status),
            stops={seq: StopPrediction(seq, stop_id, t, bool(sk)) for seq, stop_id, t, sk in stops},
        )
    return Snapshot(feed_ts=d["feed_ts"], trips=trips)


def dumps(state: IngestState) -> bytes:
    payload = {
        "v": STATE_VERSION,
        "snapshot": _snapshot_to_json(state.snapshot) if state.snapshot else None,
        "stopped": [[k[0].trip_id, k[0].start_date, k[1], ts] for k, ts in state.stopped.items()],
        "ticks": state.ticks,
        "last_success_at": state.last_success_at,
        "gaps": state.gaps,
        "last_health_publish_at": state.last_health_publish_at,
        "last_raw_sample_hour": state.last_raw_sample_hour,
        "alerts_sent": state.alerts_sent[-5000:],
    }
    return gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)


def loads(data: bytes) -> IngestState:
    d = json.loads(gzip.decompress(data))
    if d.get("v") != STATE_VERSION:
        return IngestState()  # unknown format: cold start rather than misinterpret
    return IngestState(
        snapshot=_snapshot_from_json(d["snapshot"]) if d.get("snapshot") else None,
        stopped={(TripKey(t, sd), seq): ts for t, sd, seq, ts in d.get("stopped", [])},
        ticks=[(int(a), str(b)) for a, b in d.get("ticks", [])],
        last_success_at=d.get("last_success_at"),
        gaps=[(int(a), int(b)) for a, b in d.get("gaps", [])],
        last_health_publish_at=d.get("last_health_publish_at"),
        last_raw_sample_hour=d.get("last_raw_sample_hour"),
        alerts_sent=list(d.get("alerts_sent", [])),
    )
