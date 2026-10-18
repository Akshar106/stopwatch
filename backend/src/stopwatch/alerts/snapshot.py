"""The alert-rules snapshot that ``ingest-tick`` reads every minute (docs/contracts.md §5).

Ingest has no database credentials, so the API writes ``config/alert_rules/{agency}.json`` to the lake on
every rule or subscription change, and ``maintenance`` reconciles it nightly. It contains only active rules
of non-demo users who have at least one push subscription, and **no user identifiers**: the notify job maps
``rule_id`` back to subscriptions itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, exists, select

from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import alert_rules, push_subscriptions, saved_commutes, users

SNAPSHOT_KEY = "config/alert_rules/{agency}.json"


def snapshot_key(agency_id: str) -> str:
    return SNAPSHOT_KEY.format(agency=agency_id)


def build_rules_snapshot(conn: Connection, agency_id: str, *, now: datetime) -> dict[str, Any]:
    c = saved_commutes.c
    has_subscription = exists().where(push_subscriptions.c.user_id == users.c.id)
    rows = conn.execute(
        select(
            alert_rules.c.id,
            c.route_id,
            c.direction_id,
            c.stop_id,
            c.days_mask,
            c.window_start,
            c.window_end,
            alert_rules.c.threshold_min,
            alert_rules.c.notify_cancellations,
        )
        .select_from(
            alert_rules.join(saved_commutes, c.id == alert_rules.c.commute_id).join(users, users.c.id == c.user_id)
        )
        .where(alert_rules.c.active, c.agency_id == agency_id, users.c.is_demo.is_(False), has_subscription)
        .order_by(alert_rules.c.id)
    ).mappings()
    rules = [
        {
            "rule_id": str(r["id"]),
            "route_id": r["route_id"],
            "direction_id": int(r["direction_id"]),
            "stop_id": r["stop_id"],
            "days_mask": int(r["days_mask"]),
            "window_start": r["window_start"].strftime("%H:%M"),
            "window_end": r["window_end"].strftime("%H:%M"),
            "threshold_min": int(r["threshold_min"]),
            "notify_cancellations": bool(r["notify_cancellations"]),
        }
        for r in rows
    ]
    generated_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {"agency_id": agency_id, "generated_at": generated_at, "rules": rules}


def publish_rules_snapshot(conn: Connection, lake: BlobStore, agency_id: str, *, now: datetime | None = None) -> int:
    """Write the agency's snapshot to the lake. Returns the number of rules published."""
    snapshot = build_rules_snapshot(conn, agency_id, now=now or utc_now())
    lake.put(
        snapshot_key(agency_id),
        json.dumps(snapshot, separators=(",", ":")).encode(),
        content_type="application/json",
        cache_control="no-store",
    )
    return len(snapshot["rules"])
