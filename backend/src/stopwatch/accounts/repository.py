"""SQL for users and sessions. Composed with SQLAlchemy Core: bound parameters only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from stopwatch.platform.dbschema import sessions, users

from .models import ClientInfo, GoogleIdentity, User, as_utc

_USER_COLUMNS = (
    users.c.id,
    users.c.email,
    users.c.display_name,
    users.c.is_demo,
    users.c.demo_expires_at,
    users.c.created_at,
)
MAX_USER_AGENT_LENGTH = 256


# --- users ----------------------------------------------------------------------------------------------


def get_user(conn: Connection, user_id: UUID) -> User | None:
    row = conn.execute(select(*_USER_COLUMNS).where(users.c.id == user_id)).mappings().first()
    return User.from_row(row) if row else None


def lock_user(conn: Connection, user_id: UUID) -> None:
    """Row-lock the user for the rest of the transaction (serializes per-user limit checks)."""
    conn.execute(select(users.c.id).where(users.c.id == user_id).with_for_update())


def _upsert_google_user(conn: Connection, identity: GoogleIdentity, email: str | None, now: datetime) -> User:
    base = insert(users).values(
        oidc_issuer=identity.issuer,
        oidc_subject=identity.subject,
        email=email,
        display_name=identity.display_name,
        is_demo=False,
        last_login_at=now,
    )
    stmt = base.on_conflict_do_update(
        index_elements=[users.c.oidc_issuer, users.c.oidc_subject],
        set_={
            "email": base.excluded.email,
            "display_name": base.excluded.display_name,
            "last_login_at": base.excluded.last_login_at,
        },
    ).returning(*_USER_COLUMNS)
    return User.from_row(conn.execute(stmt).mappings().one())


def upsert_google_user(conn: Connection, identity: GoogleIdentity, *, now: datetime) -> User:
    """Create or refresh the user keyed by (issuer, subject); email and display name follow Google."""
    try:
        with conn.begin_nested():
            return _upsert_google_user(conn, identity, identity.email, now)
    except IntegrityError:
        # The email is held by another account (e.g. an address reassigned at Google). Identity is the
        # (issuer, subject) pair, so sign in without storing the duplicate email.
        return _upsert_google_user(conn, identity, None, now)


def insert_demo_user(conn: Connection, *, display_name: str, expires_at: datetime) -> User:
    row = (
        conn.execute(
            users.insert()
            .values(is_demo=True, display_name=display_name, demo_expires_at=expires_at)
            .returning(*_USER_COLUMNS)
        )
        .mappings()
        .one()
    )
    return User.from_row(row)


def count_active_demo_users(conn: Connection, *, now: datetime) -> int:
    return int(
        conn.execute(
            select(func.count()).select_from(users).where(users.c.is_demo, users.c.demo_expires_at > now)
        ).scalar_one()
    )


def delete_user(conn: Connection, user_id: UUID) -> bool:
    """Delete the user; sessions, commutes, rules, subscriptions etc. go with it (ON DELETE CASCADE)."""
    return bool(conn.execute(delete(users).where(users.c.id == user_id)).rowcount)


def purge_expired_demo_users(conn: Connection, *, now: datetime) -> int:
    result = conn.execute(delete(users).where(users.c.is_demo, users.c.demo_expires_at <= now))
    return result.rowcount or 0


# --- sessions -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionRow:
    token_hash: bytes
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user: User


def insert_session(
    conn: Connection,
    *,
    token_hash: bytes,
    user_id: UUID,
    now: datetime,
    expires_at: datetime,
    client: ClientInfo,
) -> None:
    user_agent = client.user_agent[:MAX_USER_AGENT_LENGTH] if client.user_agent else None
    conn.execute(
        sessions.insert().values(
            token_hash=token_hash,
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            ip_prefix=client.ip_prefix,
            user_agent=user_agent,
        )
    )


def find_session(conn: Connection, token_hash: bytes) -> SessionRow | None:
    row = (
        conn.execute(
            select(
                sessions.c.token_hash,
                sessions.c.created_at,
                sessions.c.last_seen_at,
                sessions.c.expires_at,
                *_USER_COLUMNS,
            )
            .join(users, users.c.id == sessions.c.user_id)
            .where(sessions.c.token_hash == token_hash)
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return SessionRow(
        token_hash=bytes(row["token_hash"]),
        created_at=as_utc(row["created_at"]),
        last_seen_at=as_utc(row["last_seen_at"]),
        expires_at=as_utc(row["expires_at"]),
        user=User.from_row(row),
    )


def touch_session(conn: Connection, token_hash: bytes, *, now: datetime) -> None:
    conn.execute(update(sessions).where(sessions.c.token_hash == token_hash).values(last_seen_at=now))


def delete_session(conn: Connection, token_hash: bytes) -> bool:
    return bool(conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash)).rowcount)


def delete_sessions_for_user(conn: Connection, user_id: UUID) -> int:
    return conn.execute(delete(sessions).where(sessions.c.user_id == user_id)).rowcount or 0


def list_sessions_for_owner(conn: Connection, owner_id: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(sessions.c.created_at, sessions.c.last_seen_at, sessions.c.user_agent)
        .where(sessions.c.user_id == owner_id)
        .order_by(sessions.c.created_at)
    ).mappings()
    return [
        {
            "created_at": as_utc(r["created_at"]).isoformat(),
            "last_seen_at": as_utc(r["last_seen_at"]).isoformat(),
            "user_agent": r["user_agent"],
        }
        for r in rows
    ]


def purge_expired_sessions(conn: Connection, *, now: datetime, idle_cutoff: datetime) -> int:
    result = conn.execute(
        delete(sessions).where((sessions.c.expires_at <= now) | (sessions.c.last_seen_at <= idle_cutoff))
    )
    return result.rowcount or 0
