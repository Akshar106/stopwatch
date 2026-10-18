"""Fixed-window rate limiting backed by Postgres (docs/05 §7).

One atomic statement per check: ``INSERT … ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count``.
There is no Redis in this architecture; at our volume a single indexed upsert is cheap and survives
Lambda container churn. Buckets look like ``demo:ip:203.0.113.0/24`` or ``me:user:<uuid>``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, delete
from sqlalchemy.dialects.postgresql import insert

from .dbschema import rate_limit_counters

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RateLimit:
    """``limit`` requests per ``window`` for one named route group."""

    name: str
    limit: int
    window: timedelta


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    count: int
    limit: int
    retry_after_s: int

    @property
    def first_rejection(self) -> bool:
        """True exactly once per window: lets callers sample audit records instead of logging every hit."""
        return self.count == self.limit + 1


class RateLimitExceededError(Exception):
    def __init__(self, decision: RateLimitDecision, rule: RateLimit) -> None:
        super().__init__(f"rate limit {rule.name} exceeded")
        self.decision = decision
        self.rule = rule


def window_start(now: datetime, window: timedelta) -> datetime:
    """Align ``now`` down to the start of its fixed window (windows are aligned to the Unix epoch)."""
    size = window.total_seconds()
    elapsed = (now - _EPOCH).total_seconds()
    return _EPOCH + timedelta(seconds=math.floor(elapsed / size) * size)


def hit(conn: Connection, rule: RateLimit, key: str, *, now: datetime) -> RateLimitDecision:
    """Count one request for ``key`` under ``rule`` and say whether it is within the limit."""
    start = window_start(now, rule.window)
    bucket = f"{rule.name}:{key}"
    stmt = (
        insert(rate_limit_counters)
        .values(bucket=bucket, window_start=start, count=1)
        .on_conflict_do_update(
            index_elements=[rate_limit_counters.c.bucket, rate_limit_counters.c.window_start],
            set_={"count": rate_limit_counters.c.count + 1},
        )
        .returning(rate_limit_counters.c.count)
    )
    count = int(conn.execute(stmt).scalar_one())
    retry_after = max(1, math.ceil((start + rule.window - now).total_seconds()))
    return RateLimitDecision(allowed=count <= rule.limit, count=count, limit=rule.limit, retry_after_s=retry_after)


def enforce(conn: Connection, rule: RateLimit, key: str, *, now: datetime) -> RateLimitDecision:
    """Like :func:`hit`, but raises :class:`RateLimitExceededError` when over the limit."""
    decision = hit(conn, rule, key, now=now)
    if not decision.allowed:
        raise RateLimitExceededError(decision, rule)
    return decision


def purge_before(conn: Connection, cutoff: datetime) -> int:
    """Delete counters whose window started before ``cutoff``. Returns the number of rows removed."""
    result = conn.execute(delete(rate_limit_counters).where(rate_limit_counters.c.window_start < cutoff))
    return result.rowcount or 0
