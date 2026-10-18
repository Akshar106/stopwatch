"""Owner-scoped SQL for saved commutes.

Every function that touches a user's rows takes ``owner_id`` and filters on it, so object-level
authorization can't be forgotten in a handler (docs/05 §3). A row owned by someone else is
indistinguishable from a missing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Select, delete, exists, func, select, update

from stopwatch.platform.dbschema import alert_rules, route_stops, saved_commutes


@dataclass(frozen=True)
class AlertRecord:
    threshold_min: int
    notify_cancellations: bool
    active: bool


@dataclass(frozen=True)
class CommuteRecord:
    id: UUID
    agency_id: str
    route_id: str
    direction_id: int
    stop_id: str
    label: str | None
    days_mask: int
    window_start: time
    window_end: time
    created_at: datetime
    updated_at: datetime
    alert: AlertRecord | None

    @classmethod
    def from_row(cls, row: Any) -> CommuteRecord:
        alert = None
        if row["threshold_min"] is not None:
            alert = AlertRecord(int(row["threshold_min"]), bool(row["notify_cancellations"]), bool(row["active"]))
        return cls(
            id=row["id"],
            agency_id=row["agency_id"],
            route_id=row["route_id"],
            direction_id=int(row["direction_id"]),
            stop_id=row["stop_id"],
            label=row["label"],
            days_mask=int(row["days_mask"]),
            window_start=row["window_start"],
            window_end=row["window_end"],
            created_at=row["created_at"].astimezone(UTC),
            updated_at=row["updated_at"].astimezone(UTC),
            alert=alert,
        )


def _select_for_owner(owner_id: UUID) -> Select[Any]:
    c = saved_commutes.c
    return (
        select(
            c.id,
            c.agency_id,
            c.route_id,
            c.direction_id,
            c.stop_id,
            c.label,
            c.days_mask,
            c.window_start,
            c.window_end,
            c.created_at,
            c.updated_at,
            alert_rules.c.threshold_min,
            alert_rules.c.notify_cancellations,
            alert_rules.c.active,
        )
        .select_from(saved_commutes.outerjoin(alert_rules, alert_rules.c.commute_id == c.id))
        .where(c.user_id == owner_id)
    )


def list_for_owner(conn: Connection, owner_id: UUID) -> list[CommuteRecord]:
    query = _select_for_owner(owner_id).order_by(saved_commutes.c.created_at, saved_commutes.c.id)
    return [CommuteRecord.from_row(r) for r in conn.execute(query).mappings()]


def get_for_owner(conn: Connection, owner_id: UUID, commute_id: UUID) -> CommuteRecord | None:
    row = conn.execute(_select_for_owner(owner_id).where(saved_commutes.c.id == commute_id)).mappings().first()
    return CommuteRecord.from_row(row) if row else None


def lock_owner(conn: Connection, owner_id: UUID) -> None:
    """Serialize this owner's creates for the rest of the transaction so the per-user cap can't be raced."""
    conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"commutes:{owner_id}", 0))))


def count_for_owner(conn: Connection, owner_id: UUID) -> int:
    return int(
        conn.execute(
            select(func.count()).select_from(saved_commutes).where(saved_commutes.c.user_id == owner_id)
        ).scalar_one()
    )


def insert_for_owner(conn: Connection, owner_id: UUID, values: dict[str, Any], *, now: datetime) -> UUID:
    stmt = (
        saved_commutes.insert()
        .values(**values, user_id=owner_id, created_at=now, updated_at=now)
        .returning(saved_commutes.c.id)
    )
    commute_id: UUID = conn.execute(stmt).scalar_one()
    return commute_id


def update_for_owner(
    conn: Connection, owner_id: UUID, commute_id: UUID, values: dict[str, Any], *, now: datetime
) -> bool:
    stmt = (
        update(saved_commutes)
        .where(saved_commutes.c.id == commute_id, saved_commutes.c.user_id == owner_id)
        .values(**values, updated_at=now)
    )
    return bool(conn.execute(stmt).rowcount)


def delete_for_owner(conn: Connection, owner_id: UUID, commute_id: UUID) -> bool:
    stmt = delete(saved_commutes).where(saved_commutes.c.id == commute_id, saved_commutes.c.user_id == owner_id)
    return bool(conn.execute(stmt).rowcount)


def route_serves_stop(conn: Connection, *, agency_id: str, route_id: str, direction_id: int, stop_id: str) -> bool:
    """True if the catalog says ``route_id`` stops at ``stop_id`` in ``direction_id``."""
    rs = route_stops.c
    return bool(
        conn.execute(
            select(
                exists().where(
                    rs.agency_id == agency_id,
                    rs.route_id == route_id,
                    rs.direction_id == direction_id,
                    rs.stop_id == stop_id,
                )
            )
        ).scalar()
    )
