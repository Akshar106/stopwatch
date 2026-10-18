"""Cross-cutting HTTP behaviour: problem+json errors, request IDs, health, config, local /data, Lambda."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI

from stopwatch.platform import config

from .factories import Actor, new_client

pytestmark = pytest.mark.integration


def test_request_id_is_generated_echoed_and_sanitised(anon: Actor) -> None:
    generated = anon.get("/api/v1/healthz").headers["x-request-id"]
    assert len(generated) == 32
    assert (
        anon.get("/api/v1/healthz", headers={"X-Request-Id": "load-test-0001"}).headers["x-request-id"]
        == "load-test-0001"
    )
    injected = anon.get("/api/v1/healthz", headers={"X-Request-Id": "bad id; drop table"}).headers["x-request-id"]
    assert injected != "bad id; drop table"


def test_errors_are_problem_json_with_request_id(anon: Actor) -> None:
    for response in (anon.get("/api/v1/does-not-exist"), anon.get("/api/v1/me"), anon.client.post("/api/v1/commutes")):
        assert response.headers["content-type"] == "application/problem+json"
        assert "x-request-id" in response.headers
        body = response.json()
        assert {"type", "title", "status"} <= set(body) and body["status"] == response.status_code


def test_validation_errors_list_fields_without_echoing_input(user_a: Actor) -> None:
    response = user_a.post("/api/v1/commutes", json={"label": "very private label", "days": ["mon"]})
    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation failed"
    assert {"agency_id", "route_id", "window_start"} <= {e["field"] for e in body["errors"]}
    assert all(set(e) == {"field", "message"} for e in body["errors"])
    assert "very private label" not in response.text


@pytest.mark.parametrize("env", ["test", "staging"])
def test_unhandled_errors_are_bare_500s(
    make_app: Callable[..., FastAPI], env: str, caplog: pytest.LogCaptureFixture
) -> None:
    app = make_app(STOPWATCH_ENV=env)

    def boom() -> None:
        raise RuntimeError("db said: duplicate key email=leaky@example.com")

    app.add_api_route("/api/v1/boom", boom)
    caplog.set_level(logging.INFO)
    response = new_client(app, https=True).get("/api/v1/boom")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {"type": "about:blank", "title": "Internal Server Error", "status": 500}
    assert response.headers["x-request-id"]
    if env == "staging":
        assert "leaky@example.com" not in caplog.text
        assert "RuntimeError" in caplog.text


def test_api_responses_are_not_cacheable(user_a: Actor) -> None:
    assert user_a.get("/api/v1/me").headers["cache-control"] == "no-store"


def test_healthz_never_touches_the_database(make_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    app = make_app(STOPWATCH_VERSION="abc123")
    client = new_client(app)
    assert client.get("/api/v1/healthz").json() == {"status": "ok", "version": "abc123"}
    client.cookies.set("sw_session", "x", domain="testserver.local")
    assert client.get("/api/v1/me").status_code == 500  # sanity: the DB really is unavailable


def test_config_exposes_flags_and_vapid_key(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(ALERTS_ENABLED="true", ASK_ENABLED="false", DEMO_ENABLED="true", VAPID_PUBLIC_KEY="BPubKey")
    assert new_client(app).get("/api/v1/config").json() == {
        "features": {"alerts": True, "ask": False, "google_login": True, "demo": True},
        "vapid_public_key": "BPubKey",
    }


def test_local_site_data_is_served_read_only(app: FastAPI, app_settings_env: Path) -> None:
    manifest = app_settings_env / "site" / "data" / "v1" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"schema_version": 1}')
    client = new_client(app)
    assert client.get("/data/v1/manifest.json").json() == {"schema_version": 1}
    assert client.put("/data/v1/manifest.json", content=b"{}").status_code == 405
    assert client.get("/data/../../lake/x").status_code == 404


def test_cloud_environments_do_not_serve_data_or_docs(make_app: Callable[..., FastAPI]) -> None:
    client = new_client(make_app(STOPWATCH_ENV="prod"), https=True)
    assert client.get("/data/v1/manifest.json").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 404


def test_cloud_rate_limits_use_the_first_forwarded_hop(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(STOPWATCH_ENV="staging")
    client = new_client(app, https=True)
    headers = {"X-Requested-With": "stopwatch", "X-Forwarded-For": "198.51.100.23, 10.0.0.1"}
    for _ in range(3):
        assert client.post("/api/v1/auth/demo", headers=headers).status_code == 201
        client.cookies.clear()
    other = {"X-Requested-With": "stopwatch", "X-Forwarded-For": "198.51.100.99, 10.0.0.1"}  # same /24
    assert client.post("/api/v1/auth/demo", headers=other).status_code == 429


@pytest.mark.filterwarnings("ignore:There is no current event loop:DeprecationWarning")
def test_lambda_handler_serves_api_gateway_events(app_settings_env: Path) -> None:
    config.reset_settings_cache()
    from stopwatch.api.lambda_handler import handler

    event: dict[str, Any] = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": "/api/v1/healthz",
        "rawQueryString": "",
        "headers": {"host": "dxxxx.cloudfront.net", "x-forwarded-for": "203.0.113.9"},
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "api",
            "domainName": "dxxxx.cloudfront.net",
            "requestId": "r1",
            "routeKey": "ANY /api/{proxy+}",
            "stage": "$default",
            "time": "18/Oct/2026:12:00:00 +0000",
            "timeEpoch": 1792324800000,
            "http": {
                "method": "GET",
                "path": "/api/v1/healthz",
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.9",
                "userAgent": "pytest",
            },
        },
        "isBase64Encoded": False,
    }

    class Context:
        function_name = "stopwatch-test-api"
        aws_request_id = "r1"

    result = handler(event, cast(Any, Context()))
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["status"] == "ok"
    assert "x-request-id" in {k.lower() for k in result["headers"]}
