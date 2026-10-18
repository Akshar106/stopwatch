"""Commute request/response models (docs/contracts.md §4) and the day/time conversions they rely on.

Input models forbid unknown fields, so a client can't mass-assign ``user_id`` or timestamps.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

CatalogId = Annotated[str, StringConstraints(min_length=1, max_length=100)]
ClockTime = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
MAX_LABEL_LENGTH = 60


def days_to_mask(days: Iterable[Weekday]) -> int:
    """Encode weekdays as a bit mask, bit 0 = Monday (so Mon-Fri = 31)."""
    mask = 0
    for day in days:
        mask |= 1 << WEEKDAYS.index(day)
    return mask


def mask_to_days(mask: int) -> list[Weekday]:
    return [day for bit, day in enumerate(WEEKDAYS) if mask & (1 << bit)]


def parse_clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def format_clock(value: time) -> str:
    return value.strftime("%H:%M")


def _clean_label(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("label must not contain control characters")
    return value or None


class CommuteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agency_id: CatalogId
    route_id: CatalogId
    direction_id: Literal[0, 1]
    stop_id: CatalogId
    label: Annotated[str, StringConstraints(max_length=MAX_LABEL_LENGTH)] | None = None
    days: list[Weekday] = Field(min_length=1, max_length=7)
    window_start: ClockTime
    window_end: ClockTime

    _label = field_validator("label")(_clean_label)

    @model_validator(mode="after")
    def _window_order(self) -> CommuteCreate:
        if parse_clock(self.window_end) <= parse_clock(self.window_start):
            raise ValueError("window_end must be later than window_start")
        return self


class CommutePatch(BaseModel):
    """Any subset of the create fields. Only ``label`` may be set to null (to clear it)."""

    model_config = ConfigDict(extra="forbid")

    agency_id: CatalogId | None = None
    route_id: CatalogId | None = None
    direction_id: Literal[0, 1] | None = None
    stop_id: CatalogId | None = None
    label: Annotated[str, StringConstraints(max_length=MAX_LABEL_LENGTH)] | None = None
    days: list[Weekday] | None = Field(default=None, min_length=1, max_length=7)
    window_start: ClockTime | None = None
    window_end: ClockTime | None = None

    _label = field_validator("label")(_clean_label)

    @model_validator(mode="after")
    def _no_null_required_fields(self) -> CommutePatch:
        for name in self.model_fields_set - {"label"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class CommuteAlert(BaseModel):
    threshold_min: int
    notify_cancellations: bool
    active: bool


class CommuteOut(BaseModel):
    id: str
    agency_id: str
    route_id: str
    direction_id: int
    stop_id: str
    label: str | None
    days: list[Weekday]
    window_start: str
    window_end: str
    created_at: datetime
    updated_at: datetime
    alert: CommuteAlert | None


class CommuteList(BaseModel):
    commutes: list[CommuteOut]
