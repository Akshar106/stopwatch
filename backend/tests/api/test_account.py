"""User rights: data export contains only the caller's data; deletion cascades and keeps a pseudonymous audit row."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select

from stopwatch.platform.dbschema import (
    alert_rules,
    audit_log,
    idempotency_keys,
    push_subscriptions,
    saved_commutes,
    sessions,
    users,
)

from .factories import Actor, Catalog, push_subscription_body

pytestmark = pytest.mark.integration


@pytest.fixture
def populated(user_a: Actor, user_b: Actor, catalog: Catalog) -> dict[str, str]:
    a_commute = user_a.post(
        "/api/v1/commutes",
        json=catalog.commute_body(label="Alice home"),
        headers=user_a.headers(**{"Idempotency-Key": "alice-key-0001"}),
    ).json()["id"]
    user_a.put(f"/api/v1/commutes/{a_commute}/alert", json={"threshold_min": 5, "notify_cancellations": True})
    a_sub = user_a.post("/api/v1/push-subscriptions", json=push_subscription_body("alice")).json()["id"]
    b_commute = user_b.post("/api/v1/commutes", json=catalog.commute_body(label="Bob secret place")).json()["id"]
    b_sub = user_b.post("/api/v1/push-subscriptions", json=push_subscription_body("bob")).json()["id"]
    return {"a_commute": a_commute, "a_sub": a_sub, "b_commute": b_commute, "b_sub": b_sub}


def test_export_contains_only_the_callers_data(user_a: Actor, user_b: Actor, populated: dict[str, str]) -> None:
    response = user_a.get("/api/v1/me/export")
    assert response.status_code == 200
    export = response.json()
    assert set(export) == {"exported_at", "user", "commutes", "sessions", "push_subscriptions", "audit"}
    assert export["user"]["id"] == str(user_a.user_id)
    assert [c["id"] for c in export["commutes"]] == [populated["a_commute"]]
    assert export["commutes"][0]["alert"]["threshold_min"] == 5
    assert [s["id"] for s in export["push_subscriptions"]] == [populated["a_sub"]]
    assert set(export["sessions"][0]) == {"created_at", "last_seen_at", "user_agent"}
    assert {"commute.create", "alert.configure", "push.subscribe"} <= {e["action"] for e in export["audit"]}
    assert set(export["audit"][0]) == {"at", "action", "outcome"}

    blob = json.dumps(export)
    for foreign in (
        populated["b_commute"],
        populated["b_sub"],
        str(user_b.user_id),
        str(user_b.user.email if user_b.user else None),
        "Bob secret place",
        "fcm.googleapis.com",
    ):
        assert foreign not in blob


def test_delete_account_cascades_and_keeps_pseudonymous_audit(
    user_a: Actor,
    user_b: Actor,
    populated: dict[str, str],
    app_engine: Engine,
    app_settings_env: Path,
    catalog: Catalog,
) -> None:
    user_id = user_a.user_id
    response = user_a.delete("/api/v1/me")
    assert response.status_code == 204
    assert any(h.startswith("sw_session=") and "Max-Age=0" in h for h in response.headers.get_list("set-cookie"))
    assert user_a.get("/api/v1/me").status_code == 401

    with app_engine.connect() as conn:
        for table in (sessions, saved_commutes, push_subscriptions, idempotency_keys):
            assert conn.execute(select(func.count()).select_from(table).where(table.c.user_id == user_id)).scalar() == 0
        assert conn.execute(select(users).where(users.c.id == user_id)).first() is None
        assert (
            conn.execute(select(alert_rules).where(alert_rules.c.commute_id == populated["a_commute"])).first() is None
        )
        deletion = (
            conn.execute(
                select(audit_log).where(audit_log.c.actor_user_id == user_id, audit_log.c.action == "account.delete")
            )
            .mappings()
            .one()
        )
        assert deletion["actor_kind"] == "user" and deletion["outcome"] == "success"
        assert deletion["details"] == {}
        # B is untouched.
        assert (
            conn.execute(select(saved_commutes).where(saved_commutes.c.id == populated["b_commute"])).first()
            is not None
        )

    snapshot = json.loads(
        (app_settings_env / "lake" / "config" / "alert_rules" / f"{catalog.agency_id}.json").read_text()
    )
    assert snapshot["rules"] == []  # A's rule was republished away
