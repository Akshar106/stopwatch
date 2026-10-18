"""Requests must come through CloudFront in the cloud; client IPs come from CloudFront, not X-Forwarded-For."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stopwatch.platform.security import origin_verified, parse_viewer_address


def test_origin_secret_required_in_prod(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(STOPWATCH_ENV="prod", ORIGIN_VERIFY_SECRET="cf-shared-secret")
    client = TestClient(app, base_url="https://testserver")
    denied = client.get("/api/v1/healthz")
    assert denied.status_code == 403
    assert denied.json()["type"].endswith(":origin")
    assert "x-request-id" in denied.headers
    wrong = client.get("/api/v1/healthz", headers={"X-Origin-Verify": "guess"})
    assert wrong.status_code == 403
    ok = client.get("/api/v1/healthz", headers={"X-Origin-Verify": "cf-shared-secret"})
    assert ok.status_code == 200


def test_origin_check_off_locally(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(ORIGIN_VERIFY_SECRET="cf-shared-secret")  # env=test
    assert TestClient(app).get("/api/v1/healthz").status_code == 200


def test_helpers() -> None:
    assert origin_verified(None, None) is True
    assert origin_verified("a", "a") is True and origin_verified("b", "a") is False
    assert parse_viewer_address("203.0.113.9:5000") == "203.0.113.9"
    assert parse_viewer_address(None) is None
