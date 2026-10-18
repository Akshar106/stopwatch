"""Google OIDC sign-in against a mocked Google (respx) with a locally generated RSA key and JWKS."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import Engine, select

from stopwatch.accounts import oidc
from stopwatch.platform.dbschema import audit_log, sessions, users
from stopwatch.platform.security import pkce_challenge

from .conftest import GOOGLE_CLIENT_ID, FakeGoogle
from .factories import Actor, csrf_for_token, new_actor, new_client, set_cookie

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"
CALLBACK = "/api/v1/auth/callback"


def _start(actor: Actor, next_path: str = "/routes/1") -> dict[str, str]:
    response = actor.get(f"{LOGIN}?next={next_path}")
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(oidc.AUTHORIZATION_ENDPOINT + "?")
    params = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    assert "sw_oidc" in actor.client.cookies
    return params


def _callback(actor: Actor, params: dict[str, str], **query: str) -> Any:
    q = {"code": "auth-code-123", "state": params["state"], **query}
    return actor.client.get(CALLBACK, params=q)


def _failure_reason(engine: Engine, request_id: str) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            select(audit_log.c.action, audit_log.c.outcome, audit_log.c.details).where(
                audit_log.c.request_id == request_id
            )
        ).one()
    assert (row.action, row.outcome) == ("auth.login_failed", "denied")
    return str(row.details["reason"])


def test_login_redirect_requests_pkce_state_nonce_and_minimal_scopes(anon: Actor) -> None:
    params = _start(anon)
    assert params["response_type"] == "code"
    assert params["client_id"] == GOOGLE_CLIENT_ID
    assert params["redirect_uri"] == "http://localhost:5173/api/v1/auth/callback"
    assert params["scope"] == "openid email profile"
    assert params["code_challenge_method"] == "S256"
    assert len(params["state"]) >= 43 and len(params["nonce"]) >= 43
    set_cookie = next(
        h for h in anon.client.get(f"{LOGIN}?next=/").headers.get_list("set-cookie") if h.startswith("sw_oidc=")
    )
    assert "HttpOnly" in set_cookie and "Path=/api/v1/auth" in set_cookie and "Max-Age=600" in set_cookie


def test_happy_path_creates_user_and_session(anon: Actor, google: FakeGoogle, app_engine: Engine) -> None:
    params = _start(anon, "/routes/1?day=sat")
    google.will_return(
        google.id_token(nonce=params["nonce"], sub="google-123", email="Rider@Example.com", name="Rider Example")
    )
    response = _callback(anon, params)
    assert response.status_code == 302
    assert response.headers["location"] == "/routes/1?day=sat"

    # The code exchange carried the PKCE verifier that matches the challenge we sent to Google.
    form = parse_qs(google.token_route.calls.last.request.content.decode())
    assert pkce_challenge(form["code_verifier"][0]) == params["code_challenge"]
    assert form["redirect_uri"] == ["http://localhost:5173/api/v1/auth/callback"]
    assert form["grant_type"] == ["authorization_code"]

    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("sw_session=") for c in cookies)
    assert any(c.startswith("sw_oidc=") and "Max-Age=0" in c for c in cookies)  # transaction consumed

    token = anon.client.cookies["sw_session"]
    me = anon.client.get("/api/v1/me").json()
    assert me["user"]["email"].lower() == "rider@example.com"
    assert me["user"]["is_demo"] is False
    assert me["csrf_token"] == csrf_for_token(token)
    with app_engine.connect() as conn:
        row = conn.execute(
            select(users.c.oidc_issuer, users.c.oidc_subject).where(users.c.oidc_subject == "google-123")
        )
        assert row.one() == ("https://accounts.google.com", "google-123")


def test_second_login_updates_the_same_user_and_rotates_the_session(
    app: FastAPI, google: FakeGoogle, app_engine: Engine
) -> None:
    browser = new_actor(app)
    params = _start(browser)
    google.will_return(
        google.id_token(nonce=params["nonce"], sub="google-rotate", email="old@example.com", iss="accounts.google.com")
    )
    _callback(browser, params)
    first_token = browser.client.cookies["sw_session"]
    first_user = browser.client.get("/api/v1/me").json()["user"]["id"]

    params = _start(browser)
    google.will_return(google.id_token(nonce=params["nonce"], sub="google-rotate", email="new@example.com"))
    assert _callback(browser, params).status_code == 302
    second_token = browser.client.cookies["sw_session"]
    me = browser.client.get("/api/v1/me").json()["user"]
    assert me["id"] == first_user and me["email"] == "new@example.com"
    assert second_token != first_token

    stale = new_client(app)
    set_cookie(stale, "sw_session", first_token)
    assert stale.get("/api/v1/me").status_code == 401  # the pre-login session was deleted


def test_unverified_email_is_not_stored(anon: Actor, google: FakeGoogle) -> None:
    params = _start(anon)
    google.will_return(google.id_token(nonce=params["nonce"], email="unverified@example.com", email_verified=False))
    _callback(anon, params)
    assert anon.client.get("/api/v1/me").json()["user"]["email"] is None


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": "someone-else.apps.googleusercontent.com"}, "invalid_audience"),
        ({"iss": "https://evil.example.com"}, "invalid_issuer"),
        ({"exp": 1_000_000_000, "iat": 999_999_000}, "token_expired"),
        ({"nonce": "not-the-nonce"}, "invalid_nonce"),
        ({"azp": "another-client"}, "invalid_azp"),
    ],
)
def test_rejects_invalid_id_tokens(
    anon: Actor, google: FakeGoogle, app_engine: Engine, claims: dict[str, Any], reason: str
) -> None:
    params = _start(anon)
    overrides = {"nonce": params["nonce"], **claims}
    google.will_return(google.id_token(**overrides))
    response = _callback(anon, params)
    assert response.status_code == 302
    assert response.headers["location"] == "/signin?error=login_failed"
    assert "sw_session" not in anon.client.cookies
    assert _failure_reason(app_engine, response.headers["x-request-id"]) == reason


def test_rejects_token_signed_by_another_key(anon: Actor, google: FakeGoogle, app_engine: Engine) -> None:
    params = _start(anon)
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    google.will_return(google.id_token(nonce=params["nonce"], key=forged_key))
    response = _callback(anon, params)
    assert response.headers["location"] == "/signin?error=login_failed"
    assert _failure_reason(app_engine, response.headers["x-request-id"]) == "invalid_token"


def test_bad_state_is_rejected_before_contacting_google(anon: Actor, google: FakeGoogle, app_engine: Engine) -> None:
    params = _start(anon)
    response = _callback(anon, params, state="attacker-chosen-state")
    assert response.headers["location"] == "/signin?error=invalid_state"
    assert not google.token_route.called
    assert _failure_reason(app_engine, response.headers["x-request-id"]) == "state_mismatch"


def test_missing_or_tampered_transaction_cookie_is_rejected(app: FastAPI, anon: Actor, google: FakeGoogle) -> None:
    params = _start(anon)
    body, tag = anon.client.cookies["sw_oidc"].split(".")
    set_cookie(anon.client, "sw_oidc", body[:-2] + "AA." + tag, path="/api/v1/auth")
    assert _callback(anon, params).headers["location"] == "/signin?error=invalid_state"

    fresh = new_actor(app)
    assert _callback(fresh, params).headers["location"] == "/signin?error=invalid_state"
    assert not google.token_route.called


def test_user_cancelling_at_google(anon: Actor, google: FakeGoogle) -> None:
    params = _start(anon)
    response = anon.client.get(CALLBACK, params={"state": params["state"], "error": "access_denied"})
    assert response.headers["location"] == "/signin?error=access_denied"
    assert not google.token_route.called


def test_token_endpoint_failure(anon: Actor, google: FakeGoogle) -> None:
    import httpx

    params = _start(anon)
    google.token_route.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    assert _callback(anon, params).headers["location"] == "/signin?error=login_failed"


def test_failed_logins_emit_auth_failure_metric(
    anon: Actor, google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stopwatch.api.routes import auth as auth_routes

    metrics: list[str] = []
    monkeypatch.setattr(auth_routes, "put_metric", lambda name, value: metrics.append(name))
    params = _start(anon)
    _callback(anon, params, state="wrong")
    assert metrics == ["AuthFailures"]


@pytest.mark.parametrize(
    "next_path",
    [
        "https://evil.example.com/",
        "//evil.example.com",
        "/\\evil.example.com",
        "javascript:alert(1)",
        "evil.example.com",
        "/\r\nLocation: https://evil.example.com",
        "http:/evil.example.com",
        "\\\\evil.example.com",
        "/\t/evil.example.com",
    ],
)
def test_open_redirect_next_is_rejected(anon: Actor, next_path: str) -> None:
    response = anon.client.get(LOGIN, params={"next": next_path})
    if response.status_code == 302:  # only acceptable if it was normalised into a same-site path
        pytest.fail(f"accepted {next_path!r}")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "next"
    assert "sw_oidc" not in anon.client.cookies


def test_login_is_404_when_google_is_not_configured(make_app: Any) -> None:
    app = make_app(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    client = new_client(app)
    assert client.get(LOGIN).status_code == 404
    assert client.get("/api/v1/config").json()["features"]["google_login"] is False


def test_session_row_is_bound_to_ip_prefix_not_address(anon: Actor, google: FakeGoogle, app_engine: Engine) -> None:
    params = _start(anon)
    google.will_return(google.id_token(nonce=params["nonce"], sub="google-ip-prefix"))
    _callback(anon, params)
    with app_engine.connect() as conn:
        prefix = conn.execute(
            select(sessions.c.ip_prefix)
            .join(users, users.c.id == sessions.c.user_id)
            .where(users.c.oidc_subject == "google-ip-prefix")
        ).scalar_one()
    assert str(prefix) == ".".join(anon.ip.split(".")[:3]) + ".0/24"
