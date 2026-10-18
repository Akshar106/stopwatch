"""Append-only security audit log (docs/05 §9).

The runtime database role can only INSERT and SELECT ``audit_log``; purging old rows needs the owner role.
Records are pseudonymous: an actor UUID and an IP *prefix*, never emails, labels or tokens. ``details`` is
passed through the same scrubber as the logs as a second line of defense.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, delete, insert, select

from .dbschema import audit_log
from .observability import scrub

ActorKind = Literal["user", "system", "anonymous"]
Outcome = Literal["success", "denied", "error"]

ACTIONS: frozenset[str] = frozenset(
    {
        "auth.login",
        "auth.login_failed",
        "auth.logout",
        "auth.logout_all",
        "auth.demo_created",
        "commute.create",
        "commute.update",
        "commute.delete",
        "account.export",
        "account.delete",
        "alert.configure",
        "push.subscribe",
        "push.unsubscribe",
        "ask.cap_reached",
        "ratelimit.blocked",
        "system.demo_purge",
        "system.publish",
        "system.publish_rollback",
    }
)


@dataclass(frozen=True)
class AuditContext:
    """Who is acting and from where; built once per request (or job run)."""

    actor_kind: ActorKind
    actor_user_id: UUID | None = None
    request_id: str | None = None
    ip_prefix: str | None = None

    def for_user(self, user_id: UUID) -> AuditContext:
        return AuditContext("user", user_id, self.request_id, self.ip_prefix)


SYSTEM = AuditContext("system")


def record(
    conn: Connection,
    ctx: AuditContext,
    action: str,
    *,
    outcome: Outcome = "success",
    target_kind: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one audit record. Unknown actions are a programming error and fail loudly."""
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    conn.execute(
        insert(audit_log).values(
            actor_kind=ctx.actor_kind,
            actor_user_id=ctx.actor_user_id,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            outcome=outcome,
            request_id=ctx.request_id,
            ip_prefix=ctx.ip_prefix,
            details=scrub(details or {}),
        )
    )


def list_for_actor(conn: Connection, owner_id: UUID, *, limit: int = 500) -> list[dict[str, Any]]:
    """The user's own recent security activity, newest first (for data export)."""
    rows = conn.execute(
        select(audit_log.c.at, audit_log.c.action, audit_log.c.outcome)
        .where(audit_log.c.actor_user_id == owner_id)
        .order_by(audit_log.c.at.desc(), audit_log.c.id.desc())
        .limit(limit)
    ).mappings()
    return [{"at": r["at"].isoformat(), "action": r["action"], "outcome": r["outcome"]} for r in rows]


def purge_before(owner_conn: Connection, cutoff: datetime) -> int:
    """Delete audit rows older than ``cutoff``. Requires the owner role (the app role cannot delete)."""
    result = owner_conn.execute(delete(audit_log).where(audit_log.c.at < cutoff))
    return result.rowcount or 0
