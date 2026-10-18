"""Plain helpers (not fixtures) for API and integration tests: users, sessions, catalog rows, clients.

The test database is shared by the whole session, so every helper creates uniquely named rows (agency ids,
Google subjects, client IPs) instead of truncating tables.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from stopwatch.accounts import repository, sessions
from stopwatch.accounts.csrf import csrf_token_for
from stopwatch.accounts.models import ClientInfo, GoogleIdentity, User
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import agencies, route_stops, routes, stops

TEST_SESSION_SECRET = "test-secret-" + "x" * 40  # matches tests/conftest.py::app_settings_env
_ip_counter = itertools.count(1)


def unique_ip() -> str:
    """A client address in its own /24, so per-IP rate-limit buckets never collide between tests."""
    n = next(_ip_counter) + uuid.uuid4().int % 50_000
    return f"10.{(n // 256) % 256}.{n % 256}.7"


# --- catalog --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Catalog:
    """route 1 serves stops 64 → 65 in direction 0 and 65 in direction 1; route 2 serves stop 99."""

    agency_id: str
    route_id: str = "1"
    stop_id: str = "64"
    other_stop_id: str = "65"
    other_route_id: str = "2"
    other_route_stop_id: str = "99"

    def commute_body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "agency_id": self.agency_id,
            "route_id": self.route_id,
            "direction_id": 0,
            "stop_id": self.stop_id,
            "label": "Home to work",
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "window_start": "07:30",
            "window_end": "08:30",
        }
        body.update(overrides)
        return body


def seed_catalog(engine: Engine) -> Catalog:
    catalog = Catalog(agency_id=f"t{uuid.uuid4().hex[:10]}")
    a = catalog.agency_id
    with engine.begin() as conn:
        conn.execute(insert(agencies).values(id=a, name="Test Transit", timezone="America/New_York"))
        conn.execute(
            insert(routes),
            [
                {"agency_id": a, "route_id": "1", "route_type": 3, "short_name": "1"},
                {"agency_id": a, "route_id": "2", "route_type": 3, "short_name": "2"},
            ],
        )
        conn.execute(
            insert(stops),
            [
                {"agency_id": a, "stop_id": s, "name": f"Stop {s}", "lat": 42.35, "lon": -71.06}
                for s in ("64", "65", "99")
            ],
        )
        conn.execute(
            insert(route_stops),
            [
                {"agency_id": a, "route_id": "1", "direction_id": 0, "stop_id": "64", "stop_order": 1},
                {"agency_id": a, "route_id": "1", "direction_id": 0, "stop_id": "65", "stop_order": 2},
                {"agency_id": a, "route_id": "1", "direction_id": 1, "stop_id": "65", "stop_order": 1},
                {"agency_id": a, "route_id": "2", "direction_id": 0, "stop_id": "99", "stop_order": 1},
            ],
        )
    return catalog


# --- users and sessions ---------------------------------------------------------------------------------


def create_google_user(engine: Engine, *, email: str | None = None, name: str = "Test Rider") -> User:
    identity = GoogleIdentity(
        issuer="https://accounts.google.com",
        subject=uuid.uuid4().hex,
        email=email or f"rider-{uuid.uuid4().hex[:10]}@example.com",
        display_name=name,
    )
    with engine.begin() as conn:
        return repository.upsert_google_user(conn, identity, now=utc_now())


def create_demo_user(engine: Engine, *, expires_in: timedelta = timedelta(hours=24)) -> User:
    with engine.begin() as conn:
        return repository.insert_demo_user(conn, display_name="Demo rider", expires_at=utc_now() + expires_in)


def issue_session(engine: Engine, user: User) -> sessions.IssuedSession:
    with engine.begin() as conn:
        return sessions.issue(conn, user, now=utc_now(), client=ClientInfo(ip_prefix=None, user_agent="pytest"))


def csrf_for_token(token: str) -> str:
    return csrf_token_for(TEST_SESSION_SECRET.encode(), sessions.hash_token(token))


# --- HTTP actors ----------------------------------------------------------------------------------------


@dataclass
class Actor:
    """A browser: its own cookie jar and IP, and the headers our SPA sends on every API call."""

    client: TestClient
    ip: str
    user: User | None = None
    csrf: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def user_id(self) -> UUID:
        assert self.user is not None, "anonymous actor"
        return self.user.id

    def headers(self, **overrides: str) -> dict[str, str]:
        h = {"X-Requested-With": "stopwatch", **self.extra_headers}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        h.update(overrides)
        return h

    def request(self, method: str, path: str, *, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.client.request(method, path, json=json, headers=headers if headers is not None else self.headers())

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)


def new_client(app: FastAPI, *, https: bool = False, ip: str | None = None) -> TestClient:
    ip = ip or unique_ip()
    return TestClient(
        app,
        base_url="https://testserver" if https else "http://testserver",
        client=(ip, 50000),
        # In staging/prod the API trusts CloudFront's viewer header, not the socket peer: send what CloudFront would.
        headers={"CloudFront-Viewer-Address": f"{ip}:50000"},
        follow_redirects=False,
    )


def new_actor(app: FastAPI, *, https: bool = False, ip: str | None = None) -> Actor:
    """An anonymous browser with its own IP (so per-IP rate limits never interfere between tests)."""
    ip = ip or unique_ip()
    return Actor(client=new_client(app, https=https, ip=ip), ip=ip)


def signed_in_actor(
    app: FastAPI, engine: Engine, user: User, *, cookie_name: str = "sw_session", ip: str | None = None
) -> Actor:
    issued = issue_session(engine, user)
    actor = new_actor(app, ip=ip)
    set_cookie(actor.client, cookie_name, issued.token)
    actor.user, actor.csrf = user, csrf_for_token(issued.token)
    return actor


def set_cookie(client: TestClient, name: str, value: str, *, path: str = "/") -> None:
    """Plant a cookie exactly as if the server had set it (same jar key, so later Set-Cookies replace it)."""
    client.cookies.set(name, value, domain="testserver.local", path=path)


def push_subscription_body(tag: str) -> dict[str, Any]:
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/{tag}-{uuid.uuid4().hex}",
        "expirationTime": None,
        "keys": {"p256dh": "B" + "A" * 86, "auth": "c2VjcmV0LWF1dGgtMTY"},
    }
