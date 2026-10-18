"""accounts.sessions: hashed storage, absolute/idle expiry, sliding refresh and revocation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine, select

from stopwatch.accounts import csrf, sessions
from stopwatch.accounts.models import ClientInfo
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import sessions as sessions_table
from stopwatch.platform.security import sha256
from tests.api.factories import create_demo_user, create_google_user

pytestmark = pytest.mark.integration

CLIENT = ClientInfo(ip_prefix="203.0.113.0/24", user_agent="pytest/" + "x" * 400)


def test_issue_stores_only_the_hash_and_a_truncated_user_agent(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    with app_engine.begin() as conn:
        issued = sessions.issue(conn, user, now=utc_now(), client=CLIENT)
        row = conn.execute(select(sessions_table).where(sessions_table.c.user_id == user.id)).mappings().one()
    assert len(issued.token) >= 43  # 256 bits, base64url
    assert bytes(row["token_hash"]) == sha256(issued.token) == issued.token_hash
    assert issued.token.encode() not in bytes(row["token_hash"])
    assert str(row["ip_prefix"]) == "203.0.113.0/24"
    assert len(row["user_agent"]) == 256


def test_resolve_enforces_absolute_and_idle_limits(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    t0 = utc_now()
    with app_engine.begin() as conn:
        issued = sessions.issue(conn, user, now=t0, client=CLIENT)
        assert sessions.resolve(conn, issued.token, now=t0 + timedelta(days=6)) is not None  # slides last_seen
        assert sessions.resolve(conn, issued.token, now=t0 + timedelta(days=12)) is not None  # still < 7 d idle
        assert sessions.resolve(conn, issued.token, now=t0 + timedelta(days=30, seconds=1)) is None  # absolute

    with app_engine.begin() as conn:
        idle = sessions.issue(conn, user, now=t0, client=CLIENT)
        assert sessions.resolve(conn, idle.token, now=t0 + timedelta(days=7, seconds=1)) is None


def test_touch_is_throttled(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    t0 = utc_now()
    with app_engine.begin() as conn:
        issued = sessions.issue(conn, user, now=t0, client=CLIENT)
        sessions.resolve(conn, issued.token, now=t0 + timedelta(minutes=4))

        def last_seen() -> object:
            return conn.execute(
                select(sessions_table.c.last_seen_at).where(sessions_table.c.token_hash == issued.token_hash)
            ).scalar()

        assert last_seen() == t0
        sessions.resolve(conn, issued.token, now=t0 + timedelta(minutes=6))
        assert last_seen() == t0 + timedelta(minutes=6)


def test_demo_sessions_never_outlive_the_demo_account(app_engine: Engine) -> None:
    user = create_demo_user(app_engine, expires_in=timedelta(hours=2))
    now = utc_now()
    with app_engine.begin() as conn:
        issued = sessions.issue(conn, user, now=now, client=CLIENT)
    assert user.demo_expires_at is not None
    assert issued.expires_at == user.demo_expires_at


def test_revoke_all(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    now = utc_now()
    with app_engine.begin() as conn:
        tokens = [sessions.issue(conn, user, now=now, client=CLIENT).token for _ in range(3)]
        assert sessions.revoke_all(conn, user.id) == 3
        assert all(sessions.resolve(conn, t, now=now) is None for t in tokens)


def test_csrf_token_is_bound_to_the_session_hash() -> None:
    key = b"s" * 40
    token_hash = sha256("session-token")
    token = csrf.csrf_token_for(key, token_hash)
    assert csrf.is_valid(key, token_hash, token)
    assert not csrf.is_valid(key, sha256("other-session"), token)
    assert not csrf.is_valid(b"t" * 40, token_hash, token)
    assert not csrf.is_valid(key, token_hash, None)
    assert "=" not in token
