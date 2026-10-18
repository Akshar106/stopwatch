"""Parse GTFS-Realtime protobufs into domain snapshots, treating the feed as untrusted input."""

from __future__ import annotations

from dataclasses import dataclass

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as rt

from stopwatch.core.inference import Snapshot, StopPrediction, TripKey, TripState, TripStatus, VehicleStop

MAX_ENTITIES = 50_000
MAX_STOPS_PER_TRIP = 500
# Accept stop times within this window around the feed timestamp; anything else is garbage.
TIME_SANITY_S = 36 * 3600

_TRIP_STATUS = {
    rt.TripDescriptor.SCHEDULED: TripStatus.SCHEDULED,
    rt.TripDescriptor.ADDED: TripStatus.ADDED,
    rt.TripDescriptor.CANCELED: TripStatus.CANCELED,
}


class FeedParseError(Exception):
    pass


@dataclass(frozen=True)
class ParsedVehicles:
    feed_ts: int
    stopped: list[VehicleStop]
    count: int


def _message(data: bytes) -> rt.FeedMessage:
    msg = rt.FeedMessage()
    try:
        msg.ParseFromString(data)
    except DecodeError as exc:
        raise FeedParseError(f"protobuf decode failed: {exc}") from exc
    if not msg.header.timestamp:
        raise FeedParseError("feed header has no timestamp")
    if len(msg.entity) > MAX_ENTITIES:
        raise FeedParseError(f"too many entities: {len(msg.entity)}")
    return msg


def parse_trip_updates(data: bytes, *, now: int | None = None) -> Snapshot:
    msg = _message(data)
    feed_ts = int(msg.header.timestamp)
    if now is not None and abs(feed_ts - now) > TIME_SANITY_S:
        raise FeedParseError(f"feed timestamp {feed_ts} is implausible relative to now {now}")
    trips: dict[TripKey, TripState] = {}
    for ent in msg.entity:
        if not ent.HasField("trip_update"):
            continue
        tu = ent.trip_update
        trip = tu.trip
        if not trip.trip_id or not trip.start_date or len(trip.start_date) != 8 or not trip.start_date.isdigit():
            continue  # unusable without a trip id and service date
        status = _TRIP_STATUS.get(trip.schedule_relationship)
        if status is None:
            continue  # UNSCHEDULED/DUPLICATED/etc. are out of scope
        key = TripKey(trip.trip_id, trip.start_date)
        stops: dict[int, StopPrediction] = {}
        for stu in list(tu.stop_time_update)[:MAX_STOPS_PER_TRIP]:
            if not stu.HasField("stop_sequence") or not stu.stop_id:
                continue
            t = stu.arrival.time if stu.HasField("arrival") and stu.arrival.time else None
            if t is None and stu.HasField("departure") and stu.departure.time:
                t = stu.departure.time
            if t is not None and abs(int(t) - feed_ts) > TIME_SANITY_S:
                t = None
            skipped = stu.schedule_relationship == rt.TripUpdate.StopTimeUpdate.SKIPPED
            stops[int(stu.stop_sequence)] = StopPrediction(
                stop_sequence=int(stu.stop_sequence), stop_id=stu.stop_id,
                time=int(t) if t is not None else None, skipped=skipped,
            )
        trips[key] = TripState(
            key=key,
            route_id=trip.route_id,
            direction_id=int(trip.direction_id) if trip.HasField("direction_id") else 0,
            vehicle_id=tu.vehicle.id if tu.HasField("vehicle") and tu.vehicle.id else None,
            status=status,
            stops=stops,
        )
    return Snapshot(feed_ts=feed_ts, trips=trips)


def parse_vehicle_positions(data: bytes) -> ParsedVehicles:
    msg = _message(data)
    stopped: list[VehicleStop] = []
    count = 0
    for ent in msg.entity:
        if not ent.HasField("vehicle"):
            continue
        count += 1
        v = ent.vehicle
        if (
            v.current_status == rt.VehiclePosition.STOPPED_AT
            and v.HasField("current_stop_sequence")
            and v.trip.trip_id
            and v.trip.start_date
            and v.timestamp
        ):
            stopped.append(VehicleStop(
                trip=TripKey(v.trip.trip_id, v.trip.start_date),
                stop_sequence=int(v.current_stop_sequence),
                ts=int(v.timestamp),
            ))
    return ParsedVehicles(feed_ts=int(msg.header.timestamp), stopped=stopped, count=count)
