"""Commute CRUD behaviour: validation, catalog checks, caps, Idempotency-Key replay, alert snapshot updates."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, func, select

from stopwatch.commutes import service as commutes_service
from stopwatch.platform.dbschema import saved_commutes

from .factories import Actor, Catalog, push_subscription_body

pytestmark = pytest.mark.integration

COMMUTES = "/api/v1/commutes"


def test_create_returns_the_contract_shape(user_a: Actor, catalog: Catalog) -> None:
    body = user_a.post(COMMUTES, json=catalog.commute_body(days=["fri", "mon", "mon"])).json()
    assert set(body) == {
        "id",
        "agency_id",
        "route_id",
        "direction_id",
        "stop_id",
        "label",
        "days",
        "window_start",
        "window_end",
        "created_at",
        "updated_at",
        "alert",
    }
    assert body["days"] == ["mon", "fri"]
    assert (body["window_start"], body["window_end"], body["alert"]) == ("07:30", "08:30", None)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"window_start": "09:00", "window_end": "08:00"}, "body"),
        ({"window_start": "7:30"}, "window_start"),
        ({"window_end": "24:00"}, "window_end"),
        ({"days": []}, "days"),
        ({"days": ["someday"]}, "days.0"),
        ({"direction_id": 2}, "direction_id"),
        ({"label": "x" * 61}, "label"),
        ({"user_id": "00000000-0000-4000-8000-000000000000"}, "user_id"),
    ],
)
def test_schema_validation_errors(user_a: Actor, catalog: Catalog, overrides: dict[str, object], field: str) -> None:
    response = user_a.post(COMMUTES, json=catalog.commute_body(**overrides))
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:stopwatch:problem:validation"
    assert field in {e["field"] for e in problem["errors"]}


@pytest.mark.parametrize(
    "overrides",
    [{"stop_id": "99"}, {"direction_id": 1}, {"route_id": "nope"}, {"agency_id": "unknown-agency"}],
)
def test_route_must_serve_the_stop_in_that_direction(
    user_a: Actor, catalog: Catalog, overrides: dict[str, object]
) -> None:
    response = user_a.post(COMMUTES, json=catalog.commute_body(**overrides))
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "stop_id"


def test_patch_updates_and_revalidates(user_a: Actor, catalog: Catalog) -> None:
    created = user_a.post(COMMUTES, json=catalog.commute_body()).json()
    url = f"{COMMUTES}/{created['id']}"
    patched = user_a.patch(url, json={"label": None, "days": ["sat", "sun"], "window_end": "09:00"})
    assert patched.status_code == 200
    assert (patched.json()["label"], patched.json()["days"], patched.json()["window_end"]) == (
        None,
        ["sat", "sun"],
        "09:00",
    )
    assert user_a.patch(url, json={"direction_id": 1}).status_code == 422  # stop 64 isn't served in direction 1
    assert user_a.patch(url, json={"direction_id": 1, "stop_id": "65"}).status_code == 200
    assert user_a.patch(url, json={"window_start": "09:30"}).status_code == 422  # would end before it starts
    assert user_a.patch(url, json={"route_id": None}).status_code == 422
    assert user_a.patch(url, json={"id": "00000000-0000-4000-8000-000000000000"}).status_code == 422


def test_commute_limits(user_a: Actor, demo: Actor, catalog: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in range(commutes_service.MAX_DEMO_COMMUTES):
        assert demo.post(COMMUTES, json=catalog.commute_body()).status_code == 201
    response = demo.post(COMMUTES, json=catalog.commute_body())
    assert response.status_code == 409
    assert response.json()["type"] == "urn:stopwatch:problem:commute-limit"

    monkeypatch.setattr(commutes_service, "MAX_COMMUTES", 2)
    assert user_a.post(COMMUTES, json=catalog.commute_body()).status_code == 201
    assert user_a.post(COMMUTES, json=catalog.commute_body()).status_code == 201
    assert user_a.post(COMMUTES, json=catalog.commute_body()).status_code == 409


def test_idempotency_key_replays_the_original_response(user_a: Actor, catalog: Catalog, app_engine: Engine) -> None:
    headers = user_a.headers(**{"Idempotency-Key": "retry-key-0001"})
    first = user_a.post(COMMUTES, json=catalog.commute_body(), headers=headers)
    second = user_a.post(COMMUTES, json=catalog.commute_body(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers.get("idempotent-replayed") == "true"
    assert "idempotent-replayed" not in first.headers
    with app_engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(saved_commutes).where(saved_commutes.c.user_id == user_a.user_id)
        ).scalar()
    assert count == 1


def test_idempotency_key_reused_with_a_different_body_is_422(user_a: Actor, catalog: Catalog) -> None:
    headers = user_a.headers(**{"Idempotency-Key": "retry-key-0002"})
    assert user_a.post(COMMUTES, json=catalog.commute_body(), headers=headers).status_code == 201
    response = user_a.post(COMMUTES, json=catalog.commute_body(label="Different"), headers=headers)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "Idempotency-Key"


def test_idempotency_keys_are_per_user(user_a: Actor, user_b: Actor, catalog: Catalog) -> None:
    a = user_a.post(
        COMMUTES, json=catalog.commute_body(), headers=user_a.headers(**{"Idempotency-Key": "shared-key-01"})
    )
    b = user_b.post(
        COMMUTES, json=catalog.commute_body(), headers=user_b.headers(**{"Idempotency-Key": "shared-key-01"})
    )
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.parametrize("key", ["short", "x" * 7, "x" * 65])
def test_malformed_idempotency_key(user_a: Actor, catalog: Catalog, key: str) -> None:
    headers = user_a.headers()
    headers["Idempotency-Key"] = key
    response = user_a.client.post(COMMUTES, json=catalog.commute_body(), headers=headers)
    assert response.status_code == 422


def _snapshot(root: Path, agency_id: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = json.loads((root / "lake" / "config" / "alert_rules" / f"{agency_id}.json").read_text())
    return snapshot


def test_alert_changes_republish_the_snapshot(user_a: Actor, catalog: Catalog, app_settings_env: Path) -> None:
    commute = user_a.post(COMMUTES, json=catalog.commute_body()).json()
    alert_url = f"{COMMUTES}/{commute['id']}/alert"
    rule = user_a.put(alert_url, json={"threshold_min": 12, "notify_cancellations": False})
    assert rule.json() == {"threshold_min": 12, "notify_cancellations": False, "active": True}
    assert _snapshot(app_settings_env, catalog.agency_id)["rules"] == []  # no push subscription yet

    sub = user_a.post("/api/v1/push-subscriptions", json=push_subscription_body("a")).json()["id"]
    rules = _snapshot(app_settings_env, catalog.agency_id)["rules"]
    assert [r["threshold_min"] for r in rules] == [12]

    assert user_a.patch(f"{COMMUTES}/{commute['id']}", json={"window_end": "09:15"}).status_code == 200
    assert _snapshot(app_settings_env, catalog.agency_id)["rules"][0]["window_end"] == "09:15"
    assert user_a.get(COMMUTES).json()["commutes"][0]["alert"]["threshold_min"] == 12

    assert user_a.delete(f"/api/v1/push-subscriptions/{sub}").status_code == 204
    assert _snapshot(app_settings_env, catalog.agency_id)["rules"] == []

    user_a.post("/api/v1/push-subscriptions", json=push_subscription_body("a2"))
    assert user_a.delete(alert_url).status_code == 204
    assert _snapshot(app_settings_env, catalog.agency_id)["rules"] == []
    assert user_a.delete(alert_url).status_code == 204  # idempotent


@pytest.mark.parametrize("threshold", [2, 61])
def test_alert_threshold_bounds(user_a: Actor, catalog: Catalog, threshold: int) -> None:
    commute = user_a.post(COMMUTES, json=catalog.commute_body()).json()
    response = user_a.put(f"{COMMUTES}/{commute['id']}/alert", json={"threshold_min": threshold})
    assert response.status_code == 422


def test_alerts_feature_flag(make_app: Callable[..., FastAPI], app_engine: Engine, catalog: Catalog) -> None:
    from .factories import create_google_user, signed_in_actor

    app = make_app(ALERTS_ENABLED="false")
    actor = signed_in_actor(app, app_engine, create_google_user(app_engine))
    commute = actor.post(COMMUTES, json=catalog.commute_body()).json()
    assert actor.put(f"{COMMUTES}/{commute['id']}/alert", json={"threshold_min": 5}).status_code == 404
    assert actor.post("/api/v1/push-subscriptions", json=push_subscription_body("x")).status_code == 404
    assert actor.get("/api/v1/me").json()["features"]["alerts"] is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example.com/push",
        "https://fcm.googleapis.com.evil.example.com/x",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com:8443/x",
    ],
)
def test_push_endpoint_must_be_a_known_push_service(user_a: Actor, endpoint: str) -> None:
    body = push_subscription_body("a")
    body["endpoint"] = endpoint
    response = user_a.post("/api/v1/push-subscriptions", json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "endpoint"


def test_push_endpoint_moves_to_the_account_that_resubscribes(user_a: Actor, user_b: Actor) -> None:
    body = push_subscription_body("shared-browser")
    first = user_a.post("/api/v1/push-subscriptions", json=body).json()["id"]
    second = user_b.post("/api/v1/push-subscriptions", json=body).json()["id"]
    assert first == second
    assert user_a.delete(f"/api/v1/push-subscriptions/{first}").status_code == 404
    assert user_b.delete(f"/api/v1/push-subscriptions/{second}").status_code == 204


def test_ask_validates_question_length(user_a: Actor) -> None:
    assert user_a.post("/api/v1/ask", json={"question": "x" * 301}).status_code == 422
    assert user_a.post("/api/v1/ask", json={"question": "   "}).status_code == 422
    assert user_a.post("/api/v1/ask", json={"question": "x" * 300}).status_code == 200
