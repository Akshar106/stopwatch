from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stopwatch.core.gtfs import (
    CalendarException,
    CalendarRow,
    active_service_ids,
    day_type,
    format_gtfs_time,
    gtfs_time_to_utc,
    local_hour,
    parse_gtfs_date,
    parse_gtfs_time,
    service_date_for,
    service_day_reference,
)

TZ = "America/New_York"


@pytest.mark.parametrize(("raw", "secs"), [("00:00:00", 0), ("08:05:30", 29130), ("23:59:59", 86399),
                                            ("24:00:00", 86400), ("25:10:00", 90600), ("7:05:00", 25500)])
def test_parse_gtfs_time(raw: str, secs: int) -> None:
    assert parse_gtfs_time(raw) == secs


@pytest.mark.parametrize("bad", ["", "8:5:00", "08:60:00", "08:00:61", "abc", "-1:00:00"])
def test_parse_gtfs_time_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_gtfs_time(bad)


@given(st.integers(min_value=0, max_value=48 * 3600 - 1))
def test_time_round_trip(secs: int) -> None:
    assert parse_gtfs_time(format_gtfs_time(secs)) == secs


def test_reference_is_midnight_on_normal_days() -> None:
    ref = service_day_reference(date(2026, 10, 19), TZ)
    assert ref == datetime(2026, 10, 19, 4, 0, tzinfo=UTC)  # midnight EDT


def test_after_midnight_trip_belongs_to_previous_service_day() -> None:
    # 25:10:00 on Monday's service = 01:10 local on Tuesday
    t = gtfs_time_to_utc(date(2026, 10, 19), parse_gtfs_time("25:10:00"), TZ)
    assert t == datetime(2026, 10, 20, 5, 10, tzinfo=UTC)
    assert local_hour(int(t.timestamp()), TZ) == 1


def test_spring_forward_day_uses_noon_minus_12h_not_midnight() -> None:
    # 2026-03-08: clocks jump 02:00 EST -> 03:00 EDT. Noon EDT is 16:00 UTC; minus 12 h = 04:00 UTC,
    # which is 23:00 EST on the previous calendar day. A trip at "08:00:00" is therefore 08:00 EDT.
    d = date(2026, 3, 8)
    assert service_day_reference(d, TZ) == datetime(2026, 3, 8, 4, 0, tzinfo=UTC)
    t = gtfs_time_to_utc(d, parse_gtfs_time("08:00:00"), TZ)
    assert t == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    assert local_hour(int(t.timestamp()), TZ) == 8


def test_fall_back_day_reference() -> None:
    # 2026-11-01: clocks fall back 02:00 EDT -> 01:00 EST. Noon EST = 17:00 UTC; minus 12 h = 05:00 UTC
    # = 01:00 EDT. A trip at "08:00:00" is 08:00 EST.
    d = date(2026, 11, 1)
    t = gtfs_time_to_utc(d, parse_gtfs_time("08:00:00"), TZ)
    assert t == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
    assert local_hour(int(t.timestamp()), TZ) == 8


def test_day_type() -> None:
    assert day_type(date(2026, 10, 19)) == "wkd"  # Monday
    assert day_type(date(2026, 10, 24)) == "sat"
    assert day_type(date(2026, 10, 25)) == "sun"


def test_service_date_for_early_morning_belongs_to_yesterday() -> None:
    late = int(datetime(2026, 10, 20, 6, 30, tzinfo=UTC).timestamp())  # 02:30 EDT Tuesday
    assert service_date_for(late, TZ) == date(2026, 10, 19)


def test_parse_gtfs_date() -> None:
    assert parse_gtfs_date("20261018") == date(2026, 10, 18)
    with pytest.raises(ValueError):
        parse_gtfs_date("2026-10-18")


def test_active_service_ids_with_exceptions() -> None:
    weekday = (True, True, True, True, True, False, False)
    cal = [CalendarRow("WKD", weekday, date(2026, 9, 1), date(2026, 12, 31)),
           CalendarRow("SAT", (False,) * 5 + (True, False), date(2026, 9, 1), date(2026, 12, 31))]
    holiday = date(2026, 11, 26)  # Thursday: weekday service removed, Sunday-like service added
    exc = [CalendarException("WKD", holiday, 2), CalendarException("HOLIDAY", holiday, 1)]
    assert active_service_ids(date(2026, 11, 25), cal, exc) == {"WKD"}
    assert active_service_ids(holiday, cal, exc) == {"HOLIDAY"}
    assert active_service_ids(date(2026, 11, 28), cal, exc) == {"SAT"}
    assert active_service_ids(date(2027, 1, 4), cal, exc) == set()
