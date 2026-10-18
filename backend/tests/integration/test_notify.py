from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Connection, Engine, insert, select, text

from stopwatch.alerts.notify import compose_message, deliver
from stopwatch.alerts.webpush import PushTarget
from stopwatch.platform import dbschema as t

pytestmark = pytest.mark.integration


@pytest.fixture
def setup(app_engine: Engine) -> dict:
    uid, commute, rule = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with app_engine.begin() as c:
        c.execute(text("insert into agencies (id, name, timezone) values ('mbta','MBTA','America/New_York') "
                       "on conflict do nothing"))
        c.execute(text("insert into routes (agency_id, route_id, short_name, route_type) values ('mbta','1','1',3) "
                       "on conflict do nothing"))
        c.execute(text("insert into stops (agency_id, stop_id, name, lat, lon) values "
                       "('mbta','64','Massachusetts Ave @ Newbury St',42.35,-71.09) on conflict do nothing"))
        c.execute(insert(t.users).values(id=uid, email=f"{uid}@x.test", oidc_issuer="https://accounts.google.com",
                                         oidc_subject=str(uid)))
        c.execute(insert(t.saved_commutes).values(id=commute, user_id=uid, agency_id="mbta", route_id="1",
                                                  direction_id=0, stop_id="64", days_mask=31,
                                                  window_start="07:30", window_end="08:30"))
        c.execute(insert(t.alert_rules).values(id=rule, commute_id=commute, threshold_min=10))
        for i in range(2):
            c.execute(insert(t.push_subscriptions).values(user_id=uid, endpoint=f"https://push.test/{uid}/{i}",
                                                          p256dh="k", auth_secret="a"))
    return {"user": uid, "rule": rule}


def _factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def tx() -> Iterator[Connection]:
        with engine.begin() as conn:
            yield conn
    return tx


def candidate(rule: uuid.UUID, kind: str = "delay") -> dict:
    return {"rule_id": str(rule), "kind": kind, "service_date": "2026-10-19", "trip_id": "trip-805", "route_id": "1",
            "stop_id": "64", "scheduled_at": "2026-10-19T12:05:00Z", "predicted_at": "2026-10-19T12:17:00Z",
            "delay_s": 720}


def test_delivers_once_and_prunes_dead_subscriptions(app_engine: Engine, setup: dict) -> None:
    sent: list[tuple[str, dict]] = []

    def send(target: PushTarget, msg: dict) -> str:
        sent.append((target.endpoint, msg))
        return "gone" if target.endpoint.endswith("/1") else "ok"

    payload = {"agency_id": "mbta", "candidates": [candidate(setup["rule"])]}
    stats = deliver(_factory(app_engine), payload, send)
    assert stats["sent"] == 1 and stats["gone"] == 1 and len(sent) == 2
    assert sent[0][1]["title"] == "Route 1 is running 12 min late"
    assert "Massachusetts Ave @ Newbury St" in sent[0][1]["body"] and "8:05 AM" in sent[0][1]["body"]
    again = deliver(_factory(app_engine), payload, send)  # retried async invoke / duplicate candidate
    assert again["duplicates"] == 1 and len(sent) == 2
    with app_engine.connect() as c:
        assert c.execute(select(t.notifications.c.status)).scalars().all() == ["sent"]
        assert len(c.execute(select(t.push_subscriptions.c.id).where(
            t.push_subscriptions.c.user_id == setup["user"])).all()) == 1


def test_failed_delivery_is_recorded(app_engine: Engine, setup: dict) -> None:
    stats = deliver(_factory(app_engine), {"agency_id": "mbta", "candidates": [candidate(setup["rule"], "canceled")]},
                    lambda target, msg: "error:500")
    assert stats["failed"] == 1
    with app_engine.connect() as c:
        row = c.execute(select(t.notifications.c.status, t.notifications.c.last_error)
                        .where(t.notifications.c.dedupe_key.like("%:canceled"))).one()
    assert row.status == "failed" and "error:500" in row.last_error


def test_cancellation_message() -> None:
    msg = compose_message(candidate(uuid.uuid4(), "canceled"), "Harvard", "1", "mbta")
    assert msg["title"] == "Route 1: trip canceled" and msg["url"] == "/s/mbta/64"
