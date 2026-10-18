"""Public interface of the accounts module: sign-in, demo accounts, sign-out, export and deletion.

Every function runs inside the caller's transaction and writes its own audit record, so an action and its
audit trail commit (or roll back) together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from stopwatch.platform import audit
from stopwatch.platform.audit import AuditContext

from . import demo, repository, sessions
from .models import ClientInfo, GoogleIdentity, User, UserOut
from .sessions import ActiveSession, IssuedSession


@dataclass(frozen=True)
class SignedIn:
    user: User
    session: IssuedSession


def _rotate_into(
    conn: Connection, user: User, *, now: datetime, client: ClientInfo, previous_token: str | None
) -> IssuedSession:
    """Session fixation defense: whatever session the browser had is deleted before a new one is issued."""
    sessions.revoke(conn, previous_token)
    return sessions.issue(conn, user, now=now, client=client)


def sign_in_with_google(
    conn: Connection,
    identity: GoogleIdentity,
    *,
    now: datetime,
    client: ClientInfo,
    previous_token: str | None,
    ctx: AuditContext,
) -> SignedIn:
    user = repository.upsert_google_user(conn, identity, now=now)
    issued = _rotate_into(conn, user, now=now, client=client, previous_token=previous_token)
    audit.record(conn, ctx.for_user(user.id), "auth.login", target_kind="user", target_id=str(user.id))
    return SignedIn(user, issued)


def record_failed_login(conn: Connection, ctx: AuditContext, reason: str) -> None:
    audit.record(conn, ctx, "auth.login_failed", outcome="denied", details={"reason": reason})


def start_demo(
    conn: Connection, *, now: datetime, client: ClientInfo, previous_token: str | None, ctx: AuditContext
) -> SignedIn:
    """Create a demo user and sign them in. Raises :class:`demo.DemoCapacityError` at the global cap."""
    user = demo.create_demo_user(conn, now=now)
    issued = _rotate_into(conn, user, now=now, client=client, previous_token=previous_token)
    audit.record(conn, ctx.for_user(user.id), "auth.demo_created", target_kind="user", target_id=str(user.id))
    return SignedIn(user, issued)


def authenticate(conn: Connection, token: str | None, *, now: datetime) -> ActiveSession | None:
    return sessions.resolve(conn, token, now=now)


def sign_out(conn: Connection, *, user_id: UUID, token_hash: bytes, ctx: AuditContext) -> None:
    repository.delete_session(conn, token_hash)
    audit.record(conn, ctx.for_user(user_id), "auth.logout")


def sign_out_everywhere(conn: Connection, user_id: UUID, ctx: AuditContext) -> int:
    count = sessions.revoke_all(conn, user_id)
    audit.record(conn, ctx.for_user(user_id), "auth.logout_all", details={"sessions": count})
    return count


def export_profile(conn: Connection, user: User) -> dict[str, Any]:
    """The account-owned parts of a data export (profile and sessions); other modules add their own."""
    return {
        "user": UserOut.from_user(user).model_dump(mode="json"),
        "sessions": repository.list_sessions_for_owner(conn, user.id),
    }


def delete_account(conn: Connection, user_id: UUID, ctx: AuditContext) -> None:
    """Delete the user and everything they own (cascade). The audit row keeps only the pseudonymous UUID."""
    repository.delete_user(conn, user_id)
    audit.record(conn, ctx.for_user(user_id), "account.delete", target_kind="user", target_id=str(user_id))


@dataclass(frozen=True)
class PurgeResult:
    sessions: int
    demo_users: int


def purge_expired(conn: Connection, *, now: datetime) -> PurgeResult:
    """Maintenance: drop expired sessions and expired demo users (their data cascades)."""
    demo_users = repository.purge_expired_demo_users(conn, now=now)
    expired_sessions = repository.purge_expired_sessions(conn, now=now, idle_cutoff=now - sessions.IDLE_TIMEOUT)
    return PurgeResult(sessions=expired_sessions, demo_users=demo_users)
