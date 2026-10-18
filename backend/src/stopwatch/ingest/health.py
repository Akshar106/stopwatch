"""Public data-health document (docs/contracts.md §3 `Health`)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .state import IngestState

STALE_AFTER_S = 15 * 60
FEED_AGE_DEGRADED_S = 300


def _iso(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z") if ts else None


def build_health(agency_id: str, state: IngestState, now: int) -> dict[str, Any]:
    feed_ts = state.snapshot.feed_ts if state.snapshot else None
    feed_age = (now - feed_ts) if feed_ts else None
    hour = [o for t, o in state.ticks if t > now - 3600]
    last10_failed = any(o == "failed" for t, o in state.ticks if t > now - 600)
    if state.last_success_at is None:
        status = "unknown"
    elif now - state.last_success_at > STALE_AFTER_S:
        status = "stale"
    elif (feed_age is not None and feed_age > FEED_AGE_DEGRADED_S) or last10_failed:
        status = "degraded"
    else:
        status = "ok"
    return {
        "agency_id": agency_id,
        "generated_at": _iso(now),
        "status": status,
        "last_success_at": _iso(state.last_success_at),
        "feed_timestamp": _iso(feed_ts),
        "feed_age_s": feed_age,
        "ticks_last_hour": {
            "ok": hour.count("ok"),
            "failed": hour.count("failed"),
            "not_advanced": hour.count("not_advanced"),
            "expected": 60,
        },
        "recent_gaps": [
            {"start": _iso(a), "end": _iso(b), "minutes": round((b - a) / 60)} for a, b in state.gaps
        ],
    }
