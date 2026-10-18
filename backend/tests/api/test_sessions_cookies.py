"""Session cookies: flags per environment, hashed storage, logout, expiry and sliding refresh."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select, update

from stopwatch.accounts.sessions import hash_token
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import sessions, users

from .factories import Actor, create_google_user, issue_session, new_client, set_cookie, signed_in_actor

pytestmark = pytest.mark.integration

ME = "/api/v1/me"


def _session_cookie_header(response_headers: list[str], name: str) -> str:
    return next(h for h in response_headers if h.startswith(f"{name}="))


def test_local_cookie_is_httponly_lax_and_not_secure(anon: Actor) -> None:
    response = anon.post("/api/v1/auth/demo")
    assert response.status_code == 201
    header = _session_cookie_header(response.headers.get_list("set-cookie"), "sw_session")
    attrs = [a.strip().lower() for a in header.split(";")]
    assert "httponly" in attrs and "samesite=lax" in attrs and "path=/" in attrs
    assert "secure" not in attrs
    assert "max-age=86400" in attrs  # demo sessions live at most 24 h


def test_cloud_cookie_uses_host_prefix_and_secure(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(STOPWATCH_ENV="staging")
    client = new_client(app, https=True)
    response = client.post("/api/v1/auth/demo", headers={"X-Requested-With": "stopwatch"})
    assert response.status_code == 201, response.text
    header = _session_cookie_header(response.headers.get_list("set-cookie"), "__Host-sw_session")
    attrs = [a.strip().lower() for a in header.split(";")]
    assert {"secure", "httponly", "samesite=lax", "path=/"} <= set(attrs)
    assert not any(a.startswith("domain=") for a in attrs)
    # The secure cookie works on the next request and the CSRF token matches it.
    me = client.get(ME)
    assert me.status_code == 200
    assert me.json()["csrf_token"] == response.json()["csrf_token"]


def test_only_the_token_hash_is_stored(anon: Actor, app_engine: Engine) -> None:
    anon.post("/api/v1/auth/demo")
    token = anon.client.cookies["sw_session"]
    with app_engine.connect() as conn:
        stored = conn.execute(select(sessions.c.token_hash).where(sessions.c.token_hash == hash_token(token)))
        assert stored.scalar_one() == hash_token(token)
        raw = conn.execute(select(sessions.c.token_hash).where(sessions.c.token_hash == token.encode()))
        assert raw.first() is None


def test_logout_deletes_the_session_server_side(user_a: Actor, app: FastAPI, app_engine: Engine) -> None:
    token = user_a.client.cookies["sw_session"]
    response = user_a.post("/api/v1/auth/logout")
    assert response.status_code == 204
    cleared = _session_cookie_header(response.headers.get_list("set-cookie"), "sw_session")
    assert "Max-Age=0" in cleared
    replay = new_client(app)  # an attacker who copied the cookie before logout
    set_cookie(replay, "sw_session", token)
    assert replay.get(ME).status_code == 401
    with app_engine.connect() as conn:
        assert conn.execute(select(sessions).where(sessions.c.token_hash == hash_token(token))).first() is None


def test_logout_all_ends_every_session_of_the_user(app: FastAPI, app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    laptop = signed_in_actor(app, app_engine, user)
    phone = signed_in_actor(app, app_engine, user)
    other = signed_in_actor(app, app_engine, create_google_user(app_engine))
    assert laptop.post("/api/v1/auth/logout-all").status_code == 204
    assert laptop.get(ME).status_code == 401
    assert phone.get(ME).status_code == 401
    assert other.get(ME).status_code == 200


def _set_session(engine: Engine, token: str, **values: object) -> None:
    with engine.begin() as conn:
        conn.execute(update(sessions).where(sessions.c.token_hash == hash_token(token)).values(**values))


def test_absolute_expiry(user_a: Actor, app_engine: Engine) -> None:
    token = user_a.client.cookies["sw_session"]
    _set_session(app_engine, token, expires_at=utc_now() - timedelta(seconds=1))
    response = user_a.get(ME)
    assert response.status_code == 401
    assert response.json()["type"] == "urn:stopwatch:problem:unauthenticated"
    with app_engine.connect() as conn:  # expired rows are removed on sight
        assert conn.execute(select(sessions).where(sessions.c.token_hash == hash_token(token))).first() is None


def test_idle_timeout(user_a: Actor, app_engine: Engine) -> None:
    _set_session(app_engine, user_a.client.cookies["sw_session"], last_seen_at=utc_now() - timedelta(days=7, minutes=1))
    assert user_a.get(ME).status_code == 401


def test_demo_session_ends_with_the_demo_account(demo: Actor, app_engine: Engine) -> None:
    with app_engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == demo.user_id).values(demo_expires_at=utc_now()))
    assert demo.get(ME).status_code == 401


def test_last_seen_slides_at_most_every_five_minutes(user_a: Actor, app_engine: Engine) -> None:
    token = user_a.client.cookies["sw_session"]

    def last_seen() -> datetime:
        with app_engine.connect() as conn:
            seen: datetime = conn.execute(
                select(sessions.c.last_seen_at).where(sessions.c.token_hash == hash_token(token))
            ).scalar_one()
        return seen

    recent = utc_now() - timedelta(minutes=1)
    _set_session(app_engine, token, last_seen_at=recent)
    user_a.get(ME)
    assert last_seen() == recent  # no write for a fresh session

    stale = utc_now() - timedelta(minutes=10)
    _set_session(app_engine, token, last_seen_at=stale)
    user_a.get(ME)
    assert last_seen() > stale


def test_session_absolute_lifetime_is_30_days_for_google_users(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    issued = issue_session(app_engine, user)
    lifetime = issued.expires_at - utc_now()
    assert timedelta(days=29, hours=23) < lifetime <= timedelta(days=30)


def test_garbage_cookie_is_simply_unauthenticated(anon: Actor) -> None:
    set_cookie(anon.client, "sw_session", "not-a-real-token")
    assert anon.get(ME).status_code == 401


def test_demo_creation_rotates_an_existing_session(user_a: Actor, app: FastAPI) -> None:
    old_token = user_a.client.cookies["sw_session"]
    response = user_a.post("/api/v1/auth/demo")
    assert response.status_code == 201
    assert user_a.client.cookies["sw_session"] != old_token
    stale = new_client(app)
    set_cookie(stale, "sw_session", old_token)
    assert stale.get(ME).status_code == 401
