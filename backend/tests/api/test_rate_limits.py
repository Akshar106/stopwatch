"""Application rate limits (docs/04 §8.2) enforced through ``rate_limit_counters``."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, func, select

from stopwatch.accounts import demo as demo_accounts
from stopwatch.api import ratelimits
from stopwatch.platform.dbschema import audit_log, users

from .factories import Actor, create_google_user, new_actor, signed_in_actor

pytestmark = pytest.mark.integration


def test_fourth_demo_from_the_same_ip_prefix_is_429(app: FastAPI, app_engine: Engine) -> None:
    browser = new_actor(app, ip="10.250.1.10")
    for _ in range(3):
        assert browser.post("/api/v1/auth/demo").status_code == 201
    neighbour = new_actor(app, ip="10.250.1.99")  # same /24
    response = neighbour.post("/api/v1/auth/demo")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:stopwatch:problem:rate-limited"
    assert 1 <= int(response.headers["retry-after"]) <= 3600
    with app_engine.connect() as conn:
        blocked = conn.execute(
            select(func.count())
            .select_from(audit_log)
            .where(audit_log.c.action == "ratelimit.blocked", audit_log.c.ip_prefix == "10.250.1.0/24")
        ).scalar_one()
    assert blocked == 1

    elsewhere = new_actor(app, ip="10.250.2.10")  # a different /24 has its own budget
    assert elsewhere.post("/api/v1/auth/demo").status_code == 201


def test_rate_limited_requests_are_not_executed(app: FastAPI, app_engine: Engine) -> None:
    browser = new_actor(app, ip="10.251.1.10")
    for _ in range(4):
        browser.post("/api/v1/auth/demo")
    with app_engine.connect() as conn:
        created = conn.execute(
            select(func.count())
            .select_from(audit_log)
            .where(audit_log.c.action == "auth.demo_created", audit_log.c.ip_prefix == "10.251.1.0/24")
        ).scalar_one()
    assert created == 3


def test_demo_cap_on_active_accounts(app: FastAPI, app_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    with app_engine.connect() as conn:
        active = conn.execute(
            select(func.count()).select_from(users).where(users.c.is_demo, users.c.demo_expires_at > func.now())
        ).scalar_one()
    monkeypatch.setattr(demo_accounts, "MAX_ACTIVE_DEMO_USERS", active)
    response = new_actor(app).post("/api/v1/auth/demo")
    assert response.status_code == 429
    assert response.json()["type"] == "urn:stopwatch:problem:demo-capacity"


def test_demo_disabled_is_404(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(DEMO_ENABLED="false")
    assert new_actor(app).post("/api/v1/auth/demo").status_code == 404


def test_per_user_limits_are_keyed_by_user_not_ip(app: FastAPI, app_engine: Engine, user_a: Actor) -> None:
    """Export is limited to 5/day per user; another user on the same IP is unaffected."""
    for _ in range(ratelimits.ME_EXPORT.limit):
        assert user_a.get("/api/v1/me/export").status_code == 200
    assert user_a.get("/api/v1/me/export").status_code == 429
    same_ip = signed_in_actor(app, app_engine, create_google_user(app_engine), ip=user_a.ip)
    assert same_ip.get("/api/v1/me/export").status_code == 200
