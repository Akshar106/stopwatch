"""jobs.maintenance: retention purges, demo cleanup, snapshot reconciliation and the backup check."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import time, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from stopwatch.jobs import maintenance
from stopwatch.platform import config
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import (
    alert_rules,
    audit_log,
    idempotency_keys,
    notifications,
    rate_limit_counters,
    saved_commutes,
    sessions,
    users,
)
from tests.api.factories import create_demo_user, create_google_user, issue_session, seed_catalog

pytestmark = pytest.mark.integration

SEVEN, EIGHT = time(7, 0), time(8, 0)


@pytest.fixture
def seeded(
    app_engine: Engine, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch, app_settings_env: Path
) -> dict[str, Any]:
    now = utc_now()
    catalog = seed_catalog(app_engine)
    monkeypatch.setenv("AGENCIES", catalog.agency_id)
    config.reset_settings_cache()

    user = create_google_user(app_engine)
    live, expired, idle = (issue_session(app_engine, user) for _ in range(3))
    expired_demo = create_demo_user(app_engine, expires_in=timedelta(hours=-1))
    active_demo = create_demo_user(app_engine)
    bucket = f"maint:{uuid.uuid4().hex}"
    with app_engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.token_hash == expired.token_hash)
            .values(expires_at=now - timedelta(minutes=1))
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.token_hash == idle.token_hash)
            .values(last_seen_at=now - timedelta(days=8))
        )
        demo_commute = conn.execute(
            saved_commutes.insert()
            .values(
                user_id=expired_demo.id,
                agency_id=catalog.agency_id,
                route_id="1",
                direction_id=0,
                stop_id="64",
                days_mask=1,
                window_start=SEVEN,
                window_end=EIGHT,
            )
            .returning(saved_commutes.c.id)
        ).scalar_one()
        conn.execute(
            insert(rate_limit_counters),
            [
                {"bucket": bucket, "window_start": now - timedelta(days=2), "count": 9},
                {"bucket": bucket, "window_start": now, "count": 1},
            ],
        )
        conn.execute(
            insert(idempotency_keys),
            [
                {
                    "user_id": user.id,
                    "key": "old-key-0001",
                    "request_hash": b"x",
                    "status_code": 201,
                    "response": {},
                    "created_at": now - timedelta(hours=25),
                },
                {
                    "user_id": user.id,
                    "key": "new-key-0001",
                    "request_hash": b"x",
                    "status_code": 201,
                    "response": {},
                    "created_at": now,
                },
            ],
        )
        commute = conn.execute(
            saved_commutes.insert()
            .values(
                user_id=user.id,
                agency_id=catalog.agency_id,
                route_id="1",
                direction_id=0,
                stop_id="64",
                days_mask=31,
                window_start=SEVEN,
                window_end=EIGHT,
            )
            .returning(saved_commutes.c.id)
        ).scalar_one()
        rule = conn.execute(
            alert_rules.insert().values(commute_id=commute, threshold_min=10).returning(alert_rules.c.id)
        ).scalar_one()
        conn.execute(
            insert(notifications),
            [
                {
                    "alert_rule_id": rule,
                    "dedupe_key": f"old-{uuid.uuid4()}",
                    "status": "sent",
                    "created_at": now - timedelta(days=91),
                },
                {"alert_rule_id": rule, "dedupe_key": f"new-{uuid.uuid4()}", "status": "sent", "created_at": now},
            ],
        )
        conn.execute(
            insert(audit_log),
            [
                {
                    "actor_kind": "system",
                    "action": "system.publish",
                    "outcome": "success",
                    "request_id": bucket,
                    "at": now - timedelta(days=366),
                },
                {
                    "actor_kind": "system",
                    "action": "system.publish",
                    "outcome": "success",
                    "request_id": bucket,
                    "at": now,
                },
            ],
        )
    return {
        "now": now,
        "catalog": catalog,
        "user": user,
        "live": live,
        "expired": expired,
        "idle": idle,
        "expired_demo": expired_demo,
        "active_demo": active_demo,
        "demo_commute": demo_commute,
        "bucket": bucket,
        "root": app_settings_env,
    }


def test_run_purges_only_what_has_aged_out(seeded: dict[str, Any], app_engine: Engine) -> None:
    lake = open_blobstore(f"file://{seeded['root']}/lake")
    yesterday = (seeded["now"] - timedelta(days=1)).date().isoformat()
    lake.put(f"backups/postgres/{yesterday}.dump", b"PGDMP")

    summary = maintenance.run(now=seeded["now"])

    purged = summary["purged"]
    assert purged["sessions"] >= 2 and purged["demo_users"] >= 1
    assert (
        min(purged["rate_limit_counters"], purged["idempotency_keys"], purged["notifications"], purged["audit_log"])
        >= 1
    )
    assert summary["backup_ok"] is True and summary["backup_key"].endswith(f"{yesterday}.dump")
    assert summary["alert_snapshots"] == {seeded["catalog"].agency_id: 0}  # the rule has no subscription

    with app_engine.connect() as conn:
        hashes = set(
            conn.execute(select(sessions.c.token_hash).where(sessions.c.user_id == seeded["user"].id)).scalars()
        )
        assert {bytes(h) for h in hashes} == {seeded["live"].token_hash}
        demo_ids = set(
            conn.execute(
                select(users.c.id).where(users.c.id.in_([seeded["expired_demo"].id, seeded["active_demo"].id]))
            ).scalars()
        )
        assert demo_ids == {seeded["active_demo"].id}
        assert conn.execute(select(saved_commutes).where(saved_commutes.c.id == seeded["demo_commute"])).first() is None
        assert conn.execute(
            select(rate_limit_counters.c.count).where(rate_limit_counters.c.bucket == seeded["bucket"])
        ).scalars().all() == [1]
        assert conn.execute(
            select(idempotency_keys.c.key).where(idempotency_keys.c.user_id == seeded["user"].id)
        ).scalars().all() == ["new-key-0001"]
        assert [
            k.split("-")[0]
            for k in conn.execute(
                select(notifications.c.dedupe_key)
                .join(alert_rules, alert_rules.c.id == notifications.c.alert_rule_id)
                .join(saved_commutes, saved_commutes.c.id == alert_rules.c.commute_id)
                .where(saved_commutes.c.user_id == seeded["user"].id)
            ).scalars()
        ] == ["new"]
        assert len(conn.execute(select(audit_log).where(audit_log.c.request_id == seeded["bucket"])).all()) == 1
        purge_row = conn.execute(
            select(audit_log.c.actor_kind, audit_log.c.details)
            .where(audit_log.c.action == "system.demo_purge")
            .order_by(audit_log.c.id.desc())
        ).first()
    assert purge_row is not None and purge_row.actor_kind == "system" and purge_row.details["count"] >= 1

    snapshot = json.loads(lake.get(f"config/alert_rules/{seeded['catalog'].agency_id}.json").data)  # type: ignore[union-attr]
    assert snapshot["rules"] == []


def test_missing_backup_is_reported(seeded: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    summary = maintenance.run(now=seeded["now"])
    assert summary["backup_ok"] is False and summary["backup_key"] is None
    assert "backup_missing" in caplog.text


def test_handler_and_cli_return_a_summary(seeded: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    result = maintenance.handler({}, None)
    assert set(result) == {"ran_at", "purged", "alert_snapshots", "backup_ok", "backup_key"}
    assert maintenance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["purged"]["demo_users"] == 0  # already purged by the handler
