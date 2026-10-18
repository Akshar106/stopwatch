"""Server-side sessions (docs/05 §2).

The browser holds a 256-bit random token; the database holds only its SHA-256, so a database leak doesn't
leak live sessions. Lifetimes: 7 days idle (sliding), 30 days absolute (24 h for demo users).
``last_seen_at`` is written at most every five minutes to keep reads cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection

from stopwatch.platform.security import new_token, sha256

from . import repository
from .models import ClientInfo, User

IDLE_TIMEOUT = timedelta(days=7)
ABSOLUTE_LIFETIME = timedelta(days=30)
DEMO_ABSOLUTE_LIFETIME = timedelta(hours=24)
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedSession:
    """A newly created session. ``token`` goes into the cookie and is never stored."""

    token: str
    token_hash: bytes
    expires_at: datetime


@dataclass(frozen=True)
class ActiveSession:
    user: User
    token_hash: bytes
    expires_at: datetime


def hash_token(token: str) -> bytes:
    return sha256(token)


def absolute_expiry(user: User, now: datetime) -> datetime:
    if user.is_demo:
        expiry = now + DEMO_ABSOLUTE_LIFETIME
        return min(expiry, user.demo_expires_at) if user.demo_expires_at else expiry
    return now + ABSOLUTE_LIFETIME


def issue(conn: Connection, user: User, *, now: datetime, client: ClientInfo) -> IssuedSession:
    token = new_token()
    token_hash = hash_token(token)
    expires_at = absolute_expiry(user, now)
    repository.insert_session(
        conn, token_hash=token_hash, user_id=user.id, now=now, expires_at=expires_at, client=client
    )
    return IssuedSession(token=token, token_hash=token_hash, expires_at=expires_at)


def _is_live(row: repository.SessionRow, now: datetime) -> bool:
    if row.expires_at <= now or row.last_seen_at <= now - IDLE_TIMEOUT:
        return False
    demo_expiry = row.user.demo_expires_at
    return not (row.user.is_demo and demo_expiry is not None and demo_expiry <= now)


def resolve(conn: Connection, token: str | None, *, now: datetime) -> ActiveSession | None:
    """Look up a session by its cookie token; expired sessions are deleted and treated as absent."""
    if not token:
        return None
    token_hash = hash_token(token)
    row = repository.find_session(conn, token_hash)
    if row is None:
        return None
    if not _is_live(row, now):
        repository.delete_session(conn, token_hash)
        return None
    if now - row.last_seen_at >= TOUCH_INTERVAL:
        repository.touch_session(conn, token_hash, now=now)
    return ActiveSession(user=row.user, token_hash=token_hash, expires_at=row.expires_at)


def revoke(conn: Connection, token: str | None) -> None:
    if token:
        repository.delete_session(conn, hash_token(token))


def revoke_all(conn: Connection, user_id: UUID) -> int:
    return repository.delete_sessions_for_user(conn, user_id)
