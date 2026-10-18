"""Public interface of the commutes module: owner-scoped CRUD with catalog validation and per-user caps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from stopwatch.platform import audit, idempotency
from stopwatch.platform.audit import AuditContext

from . import repository
from .repository import CommuteRecord
from .schemas import (
    CommuteAlert,
    CommuteCreate,
    CommuteOut,
    CommutePatch,
    days_to_mask,
    format_clock,
    mask_to_days,
    parse_clock,
)

MAX_COMMUTES = 20
MAX_DEMO_COMMUTES = 3
_IDEMPOTENCY_SCOPE = "POST /commutes"


class CommuteNotFoundError(Exception):
    """No such commute for this owner (also raised for other users' commutes: never confirm their IDs)."""


class CommuteLimitError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"commute limit of {limit} reached")
        self.limit = limit


class CommuteValidationError(Exception):
    """Semantically invalid input that passed schema validation, e.g. a route that doesn't serve the stop."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        super().__init__("; ".join(f"{f}: {m}" for f, m in errors))
        self.errors = errors


@dataclass(frozen=True)
class CreateResult:
    body: dict[str, Any]
    replayed: bool


def to_out(record: CommuteRecord) -> CommuteOut:
    alert = None
    if record.alert is not None:
        alert = CommuteAlert(
            threshold_min=record.alert.threshold_min,
            notify_cancellations=record.alert.notify_cancellations,
            active=record.alert.active,
        )
    return CommuteOut(
        id=str(record.id),
        agency_id=record.agency_id,
        route_id=record.route_id,
        direction_id=record.direction_id,
        stop_id=record.stop_id,
        label=record.label,
        days=mask_to_days(record.days_mask),
        window_start=format_clock(record.window_start),
        window_end=format_clock(record.window_end),
        created_at=record.created_at,
        updated_at=record.updated_at,
        alert=alert,
    )


def _require_served(conn: Connection, *, agency_id: str, route_id: str, direction_id: int, stop_id: str) -> None:
    if not repository.route_serves_stop(
        conn, agency_id=agency_id, route_id=route_id, direction_id=direction_id, stop_id=stop_id
    ):
        raise CommuteValidationError([("stop_id", "this route does not serve this stop in that direction")])


def list_commutes(conn: Connection, owner_id: UUID) -> list[CommuteOut]:
    return [to_out(r) for r in repository.list_for_owner(conn, owner_id)]


def get_commute(conn: Connection, owner_id: UUID, commute_id: UUID) -> CommuteRecord:
    record = repository.get_for_owner(conn, owner_id, commute_id)
    if record is None:
        raise CommuteNotFoundError
    return record


def _insert(conn: Connection, owner_id: UUID, is_demo: bool, data: CommuteCreate, now: datetime) -> CommuteOut:
    repository.lock_owner(conn, owner_id)
    limit = MAX_DEMO_COMMUTES if is_demo else MAX_COMMUTES
    if repository.count_for_owner(conn, owner_id) >= limit:
        raise CommuteLimitError(limit)
    _require_served(
        conn,
        agency_id=data.agency_id,
        route_id=data.route_id,
        direction_id=data.direction_id,
        stop_id=data.stop_id,
    )
    commute_id = repository.insert_for_owner(
        conn,
        owner_id,
        {
            "agency_id": data.agency_id,
            "route_id": data.route_id,
            "direction_id": data.direction_id,
            "stop_id": data.stop_id,
            "label": data.label,
            "days_mask": days_to_mask(data.days),
            "window_start": parse_clock(data.window_start),
            "window_end": parse_clock(data.window_end),
        },
        now=now,
    )
    return to_out(get_commute(conn, owner_id, commute_id))


def create_commute(
    conn: Connection,
    *,
    owner_id: UUID,
    is_demo: bool,
    data: CommuteCreate,
    now: datetime,
    ctx: AuditContext,
    idempotency_key: str | None = None,
) -> CreateResult:
    """Create a commute. With an ``Idempotency-Key``, a retried request replays the original response.

    Raises CommuteLimitError (409), CommuteValidationError (422) or IdempotencyConflictError (422).
    """
    fingerprint = idempotency.request_fingerprint({"scope": _IDEMPOTENCY_SCOPE, "body": data.model_dump(mode="json")})
    if idempotency_key is not None:
        stored = idempotency.begin(conn, owner_id, idempotency_key, fingerprint, now=now)
        if stored is not None:
            return CreateResult(body=stored.body, replayed=True)
    created = _insert(conn, owner_id, is_demo, data, now)
    body = created.model_dump(mode="json")
    if idempotency_key is not None:
        idempotency.save(conn, owner_id, idempotency_key, fingerprint, idempotency.StoredResponse(201, body), now=now)
    audit.record(conn, ctx, "commute.create", target_kind="commute", target_id=created.id)
    return CreateResult(body=body, replayed=False)


@dataclass(frozen=True)
class UpdateResult:
    commute: CommuteOut
    previous_agency_id: str


def update_commute(
    conn: Connection,
    *,
    owner_id: UUID,
    commute_id: UUID,
    patch: CommutePatch,
    now: datetime,
    ctx: AuditContext,
) -> UpdateResult:
    current = get_commute(conn, owner_id, commute_id)
    changes = patch.changes()
    merged = {
        "agency_id": changes.get("agency_id", current.agency_id),
        "route_id": changes.get("route_id", current.route_id),
        "direction_id": changes.get("direction_id", current.direction_id),
        "stop_id": changes.get("stop_id", current.stop_id),
        "window_start": parse_clock(changes["window_start"]) if "window_start" in changes else current.window_start,
        "window_end": parse_clock(changes["window_end"]) if "window_end" in changes else current.window_end,
    }
    if merged["window_end"] <= merged["window_start"]:
        raise CommuteValidationError([("window_end", "window_end must be later than window_start")])
    if changes.keys() & {"agency_id", "route_id", "direction_id", "stop_id"}:
        _require_served(
            conn,
            agency_id=merged["agency_id"],
            route_id=merged["route_id"],
            direction_id=merged["direction_id"],
            stop_id=merged["stop_id"],
        )
    values: dict[str, Any] = {k: v for k, v in merged.items() if k in changes}
    if "label" in changes:
        values["label"] = changes["label"]
    if "days" in changes:
        values["days_mask"] = days_to_mask(changes["days"])
    if not repository.update_for_owner(conn, owner_id, commute_id, values, now=now):
        raise CommuteNotFoundError
    audit.record(
        conn,
        ctx,
        "commute.update",
        target_kind="commute",
        target_id=str(commute_id),
        details={"fields": sorted(changes)},
    )
    return UpdateResult(to_out(get_commute(conn, owner_id, commute_id)), previous_agency_id=current.agency_id)


def delete_commute(conn: Connection, *, owner_id: UUID, commute_id: UUID, ctx: AuditContext) -> CommuteRecord:
    """Delete and return the deleted record (callers republish the alert snapshot if it had a rule)."""
    current = get_commute(conn, owner_id, commute_id)
    if not repository.delete_for_owner(conn, owner_id, commute_id):
        raise CommuteNotFoundError
    audit.record(conn, ctx, "commute.delete", target_kind="commute", target_id=str(commute_id))
    return current
