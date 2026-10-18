"""Cross-site request defenses: X-Requested-With on every state change, X-CSRF-Token when signed in."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from stopwatch.api import middleware

from .factories import Actor, Catalog, create_google_user, signed_in_actor

pytestmark = pytest.mark.integration

COMMUTES = "/api/v1/commutes"


@pytest.fixture
def metrics(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []
    monkeypatch.setattr(middleware, "put_metric", lambda name, value: recorded.append(name))
    return recorded


def test_state_change_without_requested_with_is_rejected(user_a: Actor, catalog: Catalog, metrics: list[str]) -> None:
    headers = {"X-CSRF-Token": user_a.csrf or ""}
    response = user_a.post(COMMUTES, json=catalog.commute_body(), headers=headers)
    assert response.status_code == 403
    assert response.json()["type"] == "urn:stopwatch:problem:missing-requested-with"
    assert metrics == ["AuthFailures"]


def test_wrong_requested_with_value_is_rejected(user_a: Actor, catalog: Catalog) -> None:
    response = user_a.post(
        COMMUTES, json=catalog.commute_body(), headers=user_a.headers(**{"X-Requested-With": "XMLHttpRequest"})
    )
    assert response.status_code == 403


@pytest.mark.parametrize("token", [None, "", "forged-token", "A" * 43])
def test_missing_or_wrong_csrf_token_is_rejected(
    user_a: Actor, catalog: Catalog, metrics: list[str], token: str | None
) -> None:
    headers = {"X-Requested-With": "stopwatch"}
    if token is not None:
        headers["X-CSRF-Token"] = token
    response = user_a.post(COMMUTES, json=catalog.commute_body(), headers=headers)
    assert response.status_code == 403
    assert response.json()["type"] == "urn:stopwatch:problem:csrf"
    assert metrics == ["AuthFailures"]


def test_csrf_token_of_another_session_is_rejected(
    user_a: Actor, app: FastAPI, app_engine: Engine, catalog: Catalog
) -> None:
    other = signed_in_actor(app, app_engine, create_google_user(app_engine))
    response = user_a.post(
        COMMUTES, json=catalog.commute_body(), headers=user_a.headers(**{"X-CSRF-Token": other.csrf or ""})
    )
    assert response.status_code == 403


def test_valid_tokens_pass(user_a: Actor, catalog: Catalog) -> None:
    assert user_a.post(COMMUTES, json=catalog.commute_body()).status_code == 201


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", f"{COMMUTES}/x"),
        ("DELETE", f"{COMMUTES}/x"),
        ("PUT", f"{COMMUTES}/x/alert"),
        ("POST", "/api/v1/auth/logout"),
        ("DELETE", "/api/v1/me"),
    ],
)
def test_every_unsafe_method_is_covered(user_a: Actor, method: str, path: str) -> None:
    response = user_a.request(method, path, headers={"X-Requested-With": "stopwatch"})
    assert response.status_code == 403
    assert response.json()["type"] == "urn:stopwatch:problem:csrf"


def test_safe_methods_need_neither_header(user_a: Actor) -> None:
    assert user_a.client.get("/api/v1/me").status_code == 200
    assert user_a.client.get(COMMUTES).status_code == 200


def test_anonymous_state_change_gets_401_not_403(anon: Actor, catalog: Catalog) -> None:
    response = anon.post(COMMUTES, json=catalog.commute_body())
    assert response.status_code == 401


def test_demo_creation_needs_requested_with_but_no_csrf_token(anon: Actor) -> None:
    assert anon.client.post("/api/v1/auth/demo").status_code == 403
    assert anon.post("/api/v1/auth/demo").status_code == 201


def test_csrf_token_rotates_with_the_session(anon: Actor) -> None:
    first = anon.post("/api/v1/auth/demo").json()["csrf_token"]
    anon.csrf = first
    second = anon.post("/api/v1/auth/demo").json()["csrf_token"]
    assert first != second
    anon.csrf = first
    assert anon.post("/api/v1/auth/logout").status_code == 403  # old token is useless
    anon.csrf = second
    assert anon.post("/api/v1/auth/logout").status_code == 204
