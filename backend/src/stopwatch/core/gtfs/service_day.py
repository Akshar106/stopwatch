"""Which GTFS service_ids run on a given date (calendar.txt + calendar_dates.txt)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CalendarRow:
    service_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]  # Monday .. Sunday
    start_date: date
    end_date: date


@dataclass(frozen=True)
class CalendarException:
    service_id: str
    date: date
    exception_type: int  # 1 = service added, 2 = service removed


def active_service_ids(
    service_date: date, calendar: Iterable[CalendarRow], exceptions: Iterable[CalendarException]
) -> set[str]:
    active = {
        row.service_id
        for row in calendar
        if row.start_date <= service_date <= row.end_date and row.weekdays[service_date.weekday()]
    }
    for exc in exceptions:
        if exc.date != service_date:
            continue
        if exc.exception_type == 1:
            active.add(exc.service_id)
        elif exc.exception_type == 2:
            active.discard(exc.service_id)
    return active
