"""Value types for arrival inference. Pure data: no parsing, no I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple


class TripKey(NamedTuple):
    trip_id: str
    start_date: str  # GTFS service date, YYYYMMDD


class TripStatus(StrEnum):
    SCHEDULED = "scheduled"
    ADDED = "added"
    CANCELED = "canceled"


class Method(StrEnum):
    VP_STOPPED = "vp_stopped"  # vehicle observed STOPPED_AT the stop
    LAST_PREDICTION = "last_prediction"  # last predicted time before the stop left the feed
    TRIP_END_FLUSH = "trip_end_flush"  # trip vanished; remaining near-term stops assumed served


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EventKind(StrEnum):
    ARRIVAL = "arrival"
    SKIPPED = "skipped"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class StopPrediction:
    stop_sequence: int
    stop_id: str
    time: int | None  # predicted arrival (or departure) epoch seconds
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class TripState:
    key: TripKey
    route_id: str
    direction_id: int
    vehicle_id: str | None
    status: TripStatus
    stops: Mapping[int, StopPrediction]  # by stop_sequence


@dataclass(frozen=True, slots=True)
class Snapshot:
    feed_ts: int  # feed header timestamp (epoch seconds)
    trips: Mapping[TripKey, TripState] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VehicleStop:
    """A vehicle observed STOPPED_AT a stop, from VehiclePositions."""

    trip: TripKey
    stop_sequence: int
    ts: int


@dataclass(frozen=True, slots=True)
class ObservedEvent:
    kind: EventKind
    service_date: str  # YYYY-MM-DD
    trip_id: str
    route_id: str
    direction_id: int
    trip_status: TripStatus
    observed_at: int  # feed timestamp of the snapshot that revealed the event
    stop_id: str | None = None
    stop_sequence: int | None = None
    vehicle_id: str | None = None
    est_arrival: int | None = None
    method: Method | None = None
    confidence: Confidence | None = None
    lead_s: int | None = None  # how far ahead of the previous snapshot the last prediction pointed

    def key(self) -> tuple[str, str, str, int | None]:
        """Idempotency key: one event per (kind, service date, trip, stop sequence)."""
        return (self.kind.value, self.service_date, self.trip_id, self.stop_sequence)
