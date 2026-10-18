"""Agency definitions. Adding an agency is configuration, not code."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgencyConfig:
    id: str
    name: str
    timezone: str
    trip_updates_url: str
    vehicle_positions_url: str
    static_gtfs_url: str
    # Some agencies ship a zip of zips (e.g. SEPTA: google_bus.zip inside gtfs_public.zip).
    static_inner_zip: str | None = None
    # GTFS route_type values in scope: 0 light rail/tram, 1 subway, 3 bus.
    route_types: tuple[int, ...] = (0, 1, 3)
    # Live predictions API the browser may call directly (None = no live panel).
    live_api: str | None = None
    on_time_early_s: int = -60
    on_time_late_s: int = 300
    # Scheduled headway at or below which a route-stop-hour is treated as "frequent" (excess wait time applies).
    frequent_headway_s: int = 720
    max_feed_bytes: int = 8 * 1024 * 1024
    extra: dict[str, str] = field(default_factory=dict)


AGENCIES: dict[str, AgencyConfig] = {
    "mbta": AgencyConfig(
        id="mbta",
        name="MBTA",
        timezone="America/New_York",
        trip_updates_url="https://cdn.mbta.com/realtime/TripUpdates.pb",
        vehicle_positions_url="https://cdn.mbta.com/realtime/VehiclePositions.pb",
        static_gtfs_url="https://cdn.mbta.com/MBTA_GTFS.zip",
        live_api="mbta-v3",
    ),
    "septa": AgencyConfig(
        id="septa",
        name="SEPTA (bus & trolley)",
        timezone="America/New_York",
        trip_updates_url="https://www3.septa.org/gtfsrt/septa-pa-us/Trip/rtTripUpdates.pb",
        vehicle_positions_url="https://www3.septa.org/gtfsrt/septa-pa-us/Vehicle/rtVehiclePosition.pb",
        static_gtfs_url="https://github.com/septadev/GTFS/releases/latest/download/gtfs_public.zip",
        static_inner_zip="google_bus.zip",
        route_types=(0, 3, 11),
    ),
}


def get_agency(agency_id: str) -> AgencyConfig:
    try:
        return AGENCIES[agency_id]
    except KeyError as exc:
        raise ValueError(f"unknown agency {agency_id!r}; known: {sorted(AGENCIES)}") from exc
