"""accounts: user upserts, demo accounts, OIDC helpers and the signed envelope used for the sw_oidc cookie."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine, select

from stopwatch.accounts import demo, oidc, repository
from stopwatch.accounts.models import GoogleIdentity
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import users
from stopwatch.platform.security import open_envelope, sign_envelope
from tests.api.factories import create_google_user

pytestmark = pytest.mark.integration

KEY = b"k" * 40


def _identity(subject: str, email: str | None) -> GoogleIdentity:
    return GoogleIdentity(issuer=oidc.CANONICAL_ISSUER, subject=subject, email=email, display_name="Rider")


def test_upsert_is_keyed_by_issuer_and_subject(app_engine: Engine) -> None:
    with app_engine.begin() as conn:
        first = repository.upsert_google_user(conn, _identity("sub-upsert", "one@example.com"), now=utc_now())
        second = repository.upsert_google_user(conn, _identity("sub-upsert", "two@example.com"), now=utc_now())
    assert first.id == second.id
    assert second.email == "two@example.com"


def test_email_held_by_another_account_does_not_block_sign_in(app_engine: Engine) -> None:
    holder = create_google_user(app_engine, email="taken@example.com")
    with app_engine.begin() as conn:
        user = repository.upsert_google_user(conn, _identity("sub-collide", "TAKEN@example.com"), now=utc_now())
    assert user.id != holder.id
    assert user.email is None


def test_demo_users_get_a_24h_expiry_and_respect_the_cap(app_engine: Engine) -> None:
    now = utc_now()
    with app_engine.begin() as conn:
        user = demo.create_demo_user(conn, now=now)
        active = repository.count_active_demo_users(conn, now=now)
    assert user.is_demo and user.email is None
    assert user.demo_expires_at is not None and user.demo_expires_at - now == timedelta(hours=24)
    with pytest.raises(demo.DemoCapacityError), app_engine.begin() as conn:
        demo.create_demo_user(conn, now=now, max_active=active)


def test_database_rejects_non_demo_users_without_identity(app_engine: Engine) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), app_engine.begin() as conn:
        conn.execute(users.insert().values(is_demo=False, display_name="nobody"))


def test_identity_from_claims_only_trusts_verified_email() -> None:
    claims = {"sub": "123", "email": "a@example.com", "email_verified": True, "name": "A" * 300}
    identity = oidc.identity_from_claims(claims)
    assert identity.email == "a@example.com"
    assert identity.display_name is not None and len(identity.display_name) == oidc.MAX_DISPLAY_NAME_LENGTH
    assert oidc.identity_from_claims({**claims, "email_verified": "true"}).email is None
    assert identity.issuer == "https://accounts.google.com"


@pytest.mark.parametrize("value", [None, "", "/", "/routes/1", "/routes/Green-B?day=sat#map", "/a%2F%2Fb"])
def test_safe_next_accepts_relative_paths(value: str | None) -> None:
    assert oidc.safe_next_path(value) == (value or "/")


@pytest.mark.parametrize(
    "value",
    ["//evil.com", "/\\evil.com", "https://evil.com", "evil.com", "/x\ny", "javascript:alert(1)", "/" + "a" * 600],
)
def test_safe_next_rejects_everything_else(value: str) -> None:
    with pytest.raises(oidc.InvalidNextPathError):
        oidc.safe_next_path(value)


def test_envelope_round_trip_tamper_expiry_and_purpose() -> None:
    now = utc_now()
    sealed = sign_envelope(KEY, "sw_oidc", {"state": "s", "next": "/"}, expires_at=now + timedelta(minutes=10))
    opened = open_envelope(KEY, "sw_oidc", sealed, now=now)
    assert opened is not None and opened["state"] == "s"
    assert open_envelope(KEY, "other-purpose", sealed, now=now) is None
    assert open_envelope(b"x" * 40, "sw_oidc", sealed, now=now) is None
    assert open_envelope(KEY, "sw_oidc", sealed, now=now + timedelta(minutes=11)) is None
    body, tag = sealed.split(".")
    assert open_envelope(KEY, "sw_oidc", body + "x." + tag, now=now) is None
    assert open_envelope(KEY, "sw_oidc", "garbage", now=now) is None


def test_start_login_builds_a_pkce_s256_request() -> None:
    from urllib.parse import parse_qs, urlsplit

    from stopwatch.platform.security import pkce_challenge

    config = oidc.GoogleClientConfig.build(client_id="cid", client_secret="sec", public_base_url="https://x.test/")
    start = oidc.start_login(config, KEY, "/next", now=utc_now())
    query = {k: v[0] for k, v in parse_qs(urlsplit(start.authorization_url).query).items()}
    txn = open_envelope(KEY, oidc.TRANSACTION_PURPOSE, start.transaction_cookie, now=utc_now())
    assert txn is not None
    assert query["redirect_uri"] == "https://x.test/api/v1/auth/callback"
    assert query["code_challenge"] == pkce_challenge(txn["verifier"])
    assert 43 <= len(txn["verifier"]) <= 128
    assert (query["state"], query["nonce"], txn["next"]) == (txn["state"], txn["nonce"], "/next")


def test_user_rows_store_no_secrets(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    with app_engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.id == user.id)).mappings().one()
    assert set(row) == {
        "id",
        "email",
        "display_name",
        "oidc_issuer",
        "oidc_subject",
        "is_demo",
        "demo_expires_at",
        "created_at",
        "last_login_at",
    }
