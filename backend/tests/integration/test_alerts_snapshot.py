"""alerts.snapshot: the lake file ingest reads (contracts §5) has eligible rules only and no user identifiers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, update

from stopwatch.alerts import rules
from stopwatch.alerts.rules import AlertRuleIn, PushSubscriptionIn
from stopwatch.alerts.snapshot import build_rules_snapshot, publish_rules_snapshot, snapshot_key
from stopwatch.commutes.schemas import days_to_mask, parse_clock
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import alert_rules, saved_commutes
from tests.api.factories import Catalog, create_demo_user, create_google_user, push_subscription_body, seed_catalog

pytestmark = pytest.mark.integration

RULE_KEYS = {
    "rule_id",
    "route_id",
    "direction_id",
    "stop_id",
    "days_mask",
    "window_start",
    "window_end",
    "threshold_min",
    "notify_cancellations",
}


def _commute(engine: Engine, owner: UUID, agency_id: str, label: str) -> UUID:
    with engine.begin() as conn:
        commute_id: UUID = conn.execute(
            saved_commutes.insert()
            .values(
                user_id=owner,
                agency_id=agency_id,
                route_id="1",
                direction_id=0,
                stop_id="64",
                label=label,
                days_mask=days_to_mask(["mon", "tue", "wed", "thu", "fri"]),
                window_start=parse_clock("07:30"),
                window_end=parse_clock("08:30"),
            )
            .returning(saved_commutes.c.id)
        ).scalar_one()
    return commute_id


def _rule(engine: Engine, owner: UUID, commute_id: UUID, threshold: int = 10) -> str:
    with engine.begin() as conn:
        result = rules.upsert_rule_for_owner(conn, owner, commute_id, AlertRuleIn(threshold_min=threshold))
    assert result is not None
    with engine.connect() as conn:
        return str(conn.execute(alert_rules.select().where(alert_rules.c.commute_id == commute_id)).one().id)


def _subscribe(engine: Engine, owner: UUID, tag: str) -> None:
    with engine.begin() as conn:
        rules.add_subscription(conn, owner, PushSubscriptionIn.model_validate(push_subscription_body(tag)))


@pytest.fixture
def scenario(app_engine: Engine) -> dict[str, Any]:
    catalog: Catalog = seed_catalog(app_engine)
    agency = catalog.agency_id
    eligible = create_google_user(app_engine, email="eligible@example.com")
    no_subscription = create_google_user(app_engine)
    inactive = create_google_user(app_engine)
    demo = create_demo_user(app_engine)

    eligible_rule = _rule(app_engine, eligible.id, _commute(app_engine, eligible.id, agency, "Eligible home"), 12)
    _subscribe(app_engine, eligible.id, "eligible")
    _rule(app_engine, no_subscription.id, _commute(app_engine, no_subscription.id, agency, "No sub"))
    inactive_commute = _commute(app_engine, inactive.id, agency, "Inactive")
    _rule(app_engine, inactive.id, inactive_commute)
    _subscribe(app_engine, inactive.id, "inactive")
    with app_engine.begin() as conn:
        conn.execute(update(alert_rules).where(alert_rules.c.commute_id == inactive_commute).values(active=False))
    # Demo users can't create rules through the API; make sure the snapshot would exclude them anyway.
    _rule(app_engine, demo.id, _commute(app_engine, demo.id, agency, "Demo"))
    _subscribe(app_engine, demo.id, "demo")
    # A rule in another agency stays in that agency's snapshot.
    other_agency = seed_catalog(app_engine).agency_id
    _rule(app_engine, eligible.id, _commute(app_engine, eligible.id, other_agency, "Elsewhere"))
    return {"agency": agency, "eligible_rule": eligible_rule, "users": [eligible, no_subscription, inactive, demo]}


def test_snapshot_contains_only_eligible_rules(app_engine: Engine, scenario: dict[str, Any]) -> None:
    now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    with app_engine.connect() as conn:
        snapshot = build_rules_snapshot(conn, scenario["agency"], now=now)
    assert snapshot["agency_id"] == scenario["agency"]
    assert snapshot["generated_at"] == "2026-10-18T09:00:00Z"
    assert snapshot["rules"] == [
        {
            "rule_id": scenario["eligible_rule"],
            "route_id": "1",
            "direction_id": 0,
            "stop_id": "64",
            "days_mask": 31,
            "window_start": "07:30",
            "window_end": "08:30",
            "threshold_min": 12,
            "notify_cancellations": True,
        }
    ]


def test_published_snapshot_has_no_user_identifiers(
    app_engine: Engine, scenario: dict[str, Any], app_settings_env: Path
) -> None:
    lake = open_blobstore(f"file://{app_settings_env}/lake")
    with app_engine.connect() as conn:
        assert publish_rules_snapshot(conn, lake, scenario["agency"], now=utc_now()) == 1
    blob = lake.get(snapshot_key(scenario["agency"]))
    assert blob is not None
    document = json.loads(blob.data)
    assert set(document) == {"agency_id", "generated_at", "rules"}
    assert all(set(rule) == RULE_KEYS for rule in document["rules"])
    text = blob.data.decode()
    for user in scenario["users"]:
        assert str(user.id) not in text
    for forbidden in ("eligible@example.com", "Eligible home", "fcm.googleapis.com", "user", "label", "email"):
        assert forbidden not in text


def test_empty_agency_still_gets_a_snapshot(app_engine: Engine, app_settings_env: Path) -> None:
    lake = open_blobstore(f"file://{app_settings_env}/lake")
    with app_engine.connect() as conn:
        assert publish_rules_snapshot(conn, lake, "no-rules-agency") == 0
    blob = lake.get(snapshot_key("no-rules-agency"))
    assert blob is not None and json.loads(blob.data)["rules"] == []


def test_rule_repository_is_owner_scoped(app_engine: Engine, scenario: dict[str, Any]) -> None:
    eligible, mallory = scenario["users"][0], create_google_user(app_engine)
    commute = _commute(app_engine, eligible.id, scenario["agency"], "Mine")
    with app_engine.begin() as conn:
        assert rules.upsert_rule_for_owner(conn, mallory.id, commute, AlertRuleIn(threshold_min=5)) is None
        assert rules.delete_rule_for_owner(conn, mallory.id, commute) is None
        assert rules.rule_agencies_for_owner(conn, mallory.id) == set()
        assert rules.list_subscriptions_for_owner(conn, mallory.id) == []
