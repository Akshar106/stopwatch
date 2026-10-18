"""Record and deliver alert candidates. Idempotent: notifications.dedupe_key is unique."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from stopwatch.platform import dbschema as t
from stopwatch.platform.agencies import get_agency

from .webpush import PushTarget

Sender = Callable[[PushTarget, dict[str, Any]], str]


def _local_time(iso: str | None, tz: str) -> str | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
    return dt.strftime("%-I:%M %p")


def compose_message(c: dict[str, Any], stop_name: str, route_label: str, agency_id: str) -> dict[str, Any]:
    tz = get_agency(agency_id).timezone
    sched = _local_time(c["scheduled_at"], tz)
    url = f"/s/{agency_id}/{c['stop_id']}"
    if c["kind"] == "canceled":
        return {"title": f"Route {route_label}: trip canceled",
                "body": f"The {sched} trip at {stop_name} was canceled.", "url": url}
    minutes = round((c["delay_s"] or 0) / 60)
    return {"title": f"Route {route_label} is running {minutes} min late",
            "body": f"Your {sched} trip at {stop_name} is now expected at {_local_time(c['predicted_at'], tz)}.",
            "url": url}


def deliver(conn_factory: Callable[[], Any], payload: dict[str, Any], send: Sender) -> dict[str, int]:
    agency_id = payload["agency_id"]
    stats = {"candidates": 0, "duplicates": 0, "sent": 0, "failed": 0, "gone": 0}
    for c in payload.get("candidates", []):
        stats["candidates"] += 1
        key = f"{c['rule_id']}:{c['service_date']}:{c['trip_id']}:{c['kind']}"
        with conn_factory() as conn:
            conn: Connection
            notif_id = conn.execute(
                pg_insert(t.notifications).values(alert_rule_id=c["rule_id"], dedupe_key=key, status="pending")
                .on_conflict_do_nothing(index_elements=["dedupe_key"]).returning(t.notifications.c.id)
            ).scalar_one_or_none()
            if notif_id is None:
                stats["duplicates"] += 1
                continue
            targets = conn.execute(
                select(t.push_subscriptions.c.id, t.push_subscriptions.c.endpoint, t.push_subscriptions.c.p256dh,
                       t.push_subscriptions.c.auth_secret)
                .select_from(t.alert_rules.join(t.saved_commutes, t.saved_commutes.c.id == t.alert_rules.c.commute_id)
                             .join(t.push_subscriptions, t.push_subscriptions.c.user_id == t.saved_commutes.c.user_id))
                .where(t.alert_rules.c.id == c["rule_id"], t.alert_rules.c.active.is_(True))
            ).all()
            stop_name = conn.execute(select(t.stops.c.name).where(
                t.stops.c.agency_id == agency_id, t.stops.c.stop_id == c["stop_id"])).scalar_one_or_none()
            route = conn.execute(select(t.routes.c.short_name, t.routes.c.long_name).where(
                t.routes.c.agency_id == agency_id, t.routes.c.route_id == c["route_id"])).first()
        message = compose_message(c, stop_name or c["stop_id"],
                                  (route[0] or route[1]) if route else c["route_id"], agency_id)
        outcomes = []
        for sub_id, endpoint, p256dh, auth in targets:
            result = send(PushTarget(endpoint, p256dh, auth), message)
            outcomes.append((sub_id, result))
        ok = any(r == "ok" for _, r in outcomes)
        with conn_factory() as conn:
            for sub_id, result in outcomes:
                if result == "gone":
                    conn.execute(delete(t.push_subscriptions).where(t.push_subscriptions.c.id == sub_id))
                    stats["gone"] += 1
                elif result == "ok":
                    conn.execute(update(t.push_subscriptions).where(t.push_subscriptions.c.id == sub_id)
                                 .values(last_success_at=datetime.now(ZoneInfo("UTC"))))
            conn.execute(update(t.notifications).where(t.notifications.c.id == notif_id).values(
                status="sent" if ok else ("dropped" if not outcomes else "failed"),
                attempts=t.notifications.c.attempts + 1,
                sent_at=datetime.now(ZoneInfo("UTC")) if ok else None,
                last_error=None if ok else ";".join(r for _, r in outcomes)[:500] or "no subscriptions"))
        stats["sent" if ok else "failed"] += 1
    return stats
