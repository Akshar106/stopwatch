"""GTFS time semantics.

GTFS stop times are seconds since *"noon minus 12 hours"* of the service day in the agency time zone. That
is midnight on most days, but not on daylight-saving transition days, when the service day is 23 or 25
hours long. Times may also exceed 24:00:00 (a trip that starts at 23:50 on Monday and ends at 00:20 on
Tuesday belongs to Monday's service and is written as 24:20:00).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

DayType = Literal["wkd", "sat", "sun"]

_TIME_RE = re.compile(r"^\s*(\d{1,3}):([0-5]\d):([0-5]\d)\s*$")


def parse_gtfs_time(value: str) -> int:
    """'25:10:00' -> 90600 seconds. Hours may exceed 23; minutes and seconds may not."""
    m = _TIME_RE.match(value)
    if not m:
        raise ValueError(f"invalid GTFS time: {value!r}")
    h, mi, s = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s


def format_gtfs_time(seconds: int) -> str:
    if seconds < 0:
        raise ValueError("GTFS times cannot be negative")
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_gtfs_date(value: str) -> date:
    """'20261018' -> date(2026, 10, 18)."""
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid GTFS date: {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def service_day_reference(service_date: date, tz: str) -> datetime:
    """The UTC instant that GTFS times on ``service_date`` are measured from (noon minus 12 h, absolute)."""
    noon_local = datetime.combine(service_date, time(12), tzinfo=ZoneInfo(tz))
    return noon_local.astimezone(UTC) - timedelta(hours=12)


def gtfs_time_to_utc(service_date: date, seconds: int, tz: str) -> datetime:
    return service_day_reference(service_date, tz) + timedelta(seconds=seconds)


def gtfs_time_to_epoch(service_date: date, seconds: int, tz: str) -> int:
    return int(gtfs_time_to_utc(service_date, seconds, tz).timestamp())


def local_hour(epoch_s: int, tz: str) -> int:
    return datetime.fromtimestamp(epoch_s, ZoneInfo(tz)).hour


def day_type(service_date: date) -> DayType:
    wd = service_date.weekday()
    if wd == 5:
        return "sat"
    if wd == 6:
        return "sun"
    return "wkd"


def service_date_for(epoch_s: int, tz: str, *, day_boundary_hour: int = 3) -> date:
    """Best-effort service date for an instant: local times before ``day_boundary_hour`` belong to yesterday."""
    local = datetime.fromtimestamp(epoch_s, ZoneInfo(tz))
    if local.hour < day_boundary_hour:
        return (local - timedelta(days=1)).date()
    return local.date()
