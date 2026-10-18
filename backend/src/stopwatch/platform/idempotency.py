"""``Idempotency-Key`` support for POST creates (docs/05 §10.3).

Within the caller's transaction:

1. :func:`begin` takes a transaction-scoped advisory lock on (user, key), so two concurrent retries of the
   same request serialize instead of racing, then looks up a stored response.
2. Same key + same body → the stored response is replayed. Same key + different body → conflict (422).
3. Otherwise the caller performs the work and calls :func:`save` before committing.

Keys expire after 24 hours; the maintenance job purges them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from .dbschema import idempotency_keys
from .security import sha256

KEY_TTL = timedelta(hours=24)
MIN_KEY_LENGTH, MAX_KEY_LENGTH = 8, 64


class InvalidIdempotencyKeyError(ValueError):
    pass


class IdempotencyConflictError(Exception):
    """The key was already used with a different request body."""


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: Any


def request_fingerprint(body: Any) -> bytes:
    """SHA-256 of the canonical JSON form of a request body (key order and whitespace don't matter)."""
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str))


def validate_key(key: str) -> str:
    if not (MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH) or not key.isascii() or not key.isprintable():
        raise InvalidIdempotencyKeyError(
            f"Idempotency-Key must be {MIN_KEY_LENGTH}-{MAX_KEY_LENGTH} printable ASCII characters"
        )
    return key


def begin(conn: Connection, user_id: UUID, key: str, fingerprint: bytes, *, now: datetime) -> StoredResponse | None:
    """Lock the key and return a replayable response, or None if the request should run.

    Raises :class:`IdempotencyConflictError` when the key was used with a different body.
    """
    conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"idem:{user_id}:{key}", 0))))
    row = conn.execute(
        select(idempotency_keys.c.request_hash, idempotency_keys.c.status_code, idempotency_keys.c.response).where(
            idempotency_keys.c.user_id == user_id,
            idempotency_keys.c.key == key,
            idempotency_keys.c.created_at > now - KEY_TTL,
        )
    ).first()
    if row is None:
        return None
    if bytes(row.request_hash) != fingerprint:
        raise IdempotencyConflictError(key)
    return StoredResponse(status_code=int(row.status_code), body=row.response)


def save(
    conn: Connection, user_id: UUID, key: str, fingerprint: bytes, response: StoredResponse, *, now: datetime
) -> None:
    """Store the response for replay. Overwrites an expired row with the same key."""
    values = {
        "user_id": user_id,
        "key": key,
        "request_hash": fingerprint,
        "status_code": response.status_code,
        "response": response.body,
        "created_at": now,
    }
    stmt = insert(idempotency_keys).values(**values)
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[idempotency_keys.c.user_id, idempotency_keys.c.key],
            set_={k: stmt.excluded[k] for k in ("request_hash", "status_code", "response", "created_at")},
        )
    )


def purge_before(conn: Connection, cutoff: datetime) -> int:
    result = conn.execute(delete(idempotency_keys).where(idempotency_keys.c.created_at < cutoff))
    return result.rowcount or 0
