"""Logs carry user IDs, never emails, commute labels or tokens (docs/05 §5, docs/06)."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from stopwatch.platform.observability import get_logger, scrub

from .conftest import FakeGoogle
from .factories import Actor, Catalog

pytestmark = pytest.mark.integration


def test_scrub_redacts_sensitive_keys_recursively() -> None:
    payload = {
        "user_id": "3f2b",
        "email": "rider@example.com",
        "nested": {"label": "Home to work", "session_token": "abc", "count": 3},
        "items": [{"endpoint": "https://fcm.googleapis.com/x", "p256dh": "B..."}, {"route_id": "1"}],
        "Authorization": "Bearer x",
    }
    clean = scrub(payload)
    assert clean["user_id"] == "3f2b"
    assert clean["email"] == "[redacted]"
    assert clean["nested"] == {"label": "[redacted]", "session_token": "[redacted]", "count": 3}
    assert clean["items"] == [{"endpoint": "[redacted]", "p256dh": "[redacted]"}, {"route_id": "1"}]
    assert clean["Authorization"] == "[redacted]"


def test_logger_never_emits_scrubbed_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    get_logger("test").info("signed_in", user_id="u-1", email="rider@example.com", csrf_token="t0k3n")
    assert "u-1" in caplog.text
    assert "rider@example.com" not in caplog.text and "t0k3n" not in caplog.text


def test_a_full_sign_in_and_commute_flow_leaks_nothing(
    anon: Actor, google: FakeGoogle, catalog: Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    login = anon.get("/api/v1/auth/login?next=/")
    params = {k: v[0] for k, v in parse_qs(urlsplit(login.headers["location"]).query).items()}
    google.will_return(google.id_token(nonce=params["nonce"], email="private.person@example.com"))
    anon.client.get("/api/v1/auth/callback", params={"code": "the-auth-code", "state": params["state"]})
    me = anon.client.get("/api/v1/me").json()
    anon.csrf = me["csrf_token"]
    anon.post("/api/v1/commutes", json=catalog.commute_body(label="Secret clinic visit"))

    # Everything the server process logged. The test client's own request lines ("HTTP Request: GET
    # http://testserver/...") are not ours; the server's outbound httpx calls (e.g. to Google) still count.
    def from_test_client(r: logging.LogRecord) -> bool:
        return r.name.split(".")[0] in ("httpx", "httpx2") and "http://testserver" in r.getMessage()

    server_logs = "\n".join(r.getMessage() for r in caplog.records if not from_test_client(r))
    secrets = [
        "private.person@example.com",
        "Secret clinic visit",
        anon.client.cookies["sw_session"],
        me["csrf_token"],
        params["state"],
        params["nonce"],
        "the-auth-code",
    ]
    for secret in secrets:
        assert secret not in server_logs
    assert me["user"]["id"] in server_logs  # the pseudonymous ID is what we do log
