"""Alert rules and Web Push subscriptions: input models and owner-scoped repositories.

A rule hangs off a saved commute (one per commute), so ownership is checked through ``saved_commutes``.
Push endpoints are restricted to the browser vendors' push services: the notify job POSTs to whatever is
stored here, and an arbitrary URL would turn it into an SSRF primitive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import Connection, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from stopwatch.platform.dbschema import alert_rules, notifications, push_subscriptions, saved_commutes

MAX_SUBSCRIPTIONS_PER_USER = 10
MAX_ENDPOINT_LENGTH = 2048
# Hosts (or parent domains) of the push services used by Chrome/Edge, Firefox, Safari and legacy Edge.
PUSH_SERVICE_DOMAINS: tuple[str, ...] = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)
_B64URL = r"^[A-Za-z0-9_-]+={0,2}$"


class AlertRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_min: int = Field(ge=3, le=60)
    notify_cancellations: bool = True


class AlertRuleOut(BaseModel):
    threshold_min: int
    notify_cancellations: bool
    active: bool


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: Annotated[str, StringConstraints(min_length=16, max_length=256, pattern=_B64URL)]
    auth: Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=_B64URL)]


class PushSubscriptionIn(BaseModel):
    """The browser's ``PushSubscription.toJSON()``."""

    model_config = ConfigDict(extra="forbid")

    endpoint: Annotated[str, StringConstraints(max_length=MAX_ENDPOINT_LENGTH)]
    keys: PushKeys
    expirationTime: int | None = None

    @field_validator("endpoint")
    @classmethod
    def _known_push_service(cls, value: str) -> str:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            raise ValueError("endpoint must be an https URL")
        if not any(host == d or host.endswith("." + d) for d in PUSH_SERVICE_DOMAINS):
            raise ValueError("endpoint is not a recognised browser push service")
        return value


class SubscriptionLimitError(Exception):
    pass


# --- alert rules ----------------------------------------------------------------------------------------


def commute_agency_for_owner(conn: Connection, owner_id: UUID, commute_id: UUID) -> str | None:
    """The commute's agency if ``owner_id`` owns it, else None."""
    agency: str | None = conn.execute(
        select(saved_commutes.c.agency_id).where(
            saved_commutes.c.id == commute_id, saved_commutes.c.user_id == owner_id
        )
    ).scalar_one_or_none()
    return agency


def upsert_rule_for_owner(
    conn: Connection, owner_id: UUID, commute_id: UUID, rule: AlertRuleIn
) -> tuple[AlertRuleOut, str] | None:
    """Create or replace the commute's rule and re-activate it.

    Returns (rule, agency), or None if ``owner_id`` doesn't own the commute.
    """
    agency = commute_agency_for_owner(conn, owner_id, commute_id)
    if agency is None:
        return None
    base = insert(alert_rules).values(
        commute_id=commute_id,
        threshold_min=rule.threshold_min,
        notify_cancellations=rule.notify_cancellations,
        active=True,
    )
    stmt = base.on_conflict_do_update(
        index_elements=[alert_rules.c.commute_id],
        set_={
            "threshold_min": base.excluded.threshold_min,
            "notify_cancellations": base.excluded.notify_cancellations,
            "active": True,
        },
    ).returning(alert_rules.c.threshold_min, alert_rules.c.notify_cancellations, alert_rules.c.active)
    row = conn.execute(stmt).mappings().one()
    return AlertRuleOut(**row), agency


def delete_rule_for_owner(conn: Connection, owner_id: UUID, commute_id: UUID) -> str | None:
    """Remove the commute's rule if any. Returns the agency, or None if the commute isn't the owner's."""
    agency = commute_agency_for_owner(conn, owner_id, commute_id)
    if agency is not None:
        conn.execute(delete(alert_rules).where(alert_rules.c.commute_id == commute_id))
    return agency


def rule_agencies_for_owner(conn: Connection, owner_id: UUID) -> set[str]:
    """Agencies in which the user has alert rules (whose snapshots change when the user does)."""
    rows = conn.execute(
        select(saved_commutes.c.agency_id)
        .distinct()
        .select_from(alert_rules.join(saved_commutes, saved_commutes.c.id == alert_rules.c.commute_id))
        .where(saved_commutes.c.user_id == owner_id)
    ).scalars()
    return set(rows)


# --- push subscriptions ---------------------------------------------------------------------------------


def add_subscription(conn: Connection, owner_id: UUID, sub: PushSubscriptionIn) -> UUID:
    """Register an endpoint for the user. A browser re-subscribing under a new account moves the endpoint."""
    count = conn.execute(
        select(func.count())
        .select_from(push_subscriptions)
        .where(push_subscriptions.c.user_id == owner_id, push_subscriptions.c.endpoint != sub.endpoint)
    ).scalar_one()
    if count >= MAX_SUBSCRIPTIONS_PER_USER:
        raise SubscriptionLimitError
    base = insert(push_subscriptions).values(
        user_id=owner_id, endpoint=sub.endpoint, p256dh=sub.keys.p256dh, auth_secret=sub.keys.auth
    )
    stmt = base.on_conflict_do_update(
        index_elements=[push_subscriptions.c.endpoint],
        set_={
            "user_id": base.excluded.user_id,
            "p256dh": base.excluded.p256dh,
            "auth_secret": base.excluded.auth_secret,
            "created_at": func.now(),
            "last_success_at": None,
        },
    ).returning(push_subscriptions.c.id)
    sub_id: UUID = conn.execute(stmt).scalar_one()
    return sub_id


def delete_subscription_for_owner(conn: Connection, owner_id: UUID, subscription_id: UUID) -> bool:
    result = conn.execute(
        delete(push_subscriptions).where(
            push_subscriptions.c.id == subscription_id,
            push_subscriptions.c.user_id == owner_id,
        )
    )
    return bool(result.rowcount)


def list_subscriptions_for_owner(conn: Connection, owner_id: UUID) -> list[dict[str, Any]]:
    """Export view: ids and timestamps only (endpoints and keys are secrets of the browser)."""
    rows = conn.execute(
        select(push_subscriptions.c.id, push_subscriptions.c.created_at)
        .where(push_subscriptions.c.user_id == owner_id)
        .order_by(push_subscriptions.c.created_at)
    ).mappings()
    return [{"id": str(r["id"]), "created_at": r["created_at"].astimezone(UTC).isoformat()} for r in rows]


def purge_notifications_before(conn: Connection, cutoff: datetime) -> int:
    return conn.execute(delete(notifications).where(notifications.c.created_at < cutoff)).rowcount or 0
