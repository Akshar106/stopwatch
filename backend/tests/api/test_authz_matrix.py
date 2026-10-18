"""Authorization matrix (docs/05 §3, docs/06): every endpoint x {anonymous, demo user, user A, user B}.

User A owns the objects under test. User B must get 404 (never 403) on them, so object IDs from another
account can't even be confirmed to exist (BOLA / IDOR). Each case runs against a fresh world, in the order
anonymous → demo → B → A, so A's own (possibly destructive) request comes last.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from .factories import Actor, Catalog, push_subscription_body

pytestmark = pytest.mark.integration

ACTORS = ("anonymous", "demo", "user_b", "user_a")
API = "/api/v1"


@dataclass
class World:
    actors: dict[str, Actor]
    ids: dict[str, str]
    catalog: Catalog


@dataclass(frozen=True)
class Case:
    name: str
    method: str
    path: str
    expected: tuple[int, int, int, int]  # anonymous, demo, user_b, user_a
    body: Callable[[str, Catalog], Any] | None = None


def _commute(_: str, catalog: Catalog) -> dict[str, Any]:
    return catalog.commute_body(label=None)


CASES = [
    Case("healthz", "GET", "/healthz", (200, 200, 200, 200)),
    Case("config", "GET", "/config", (200, 200, 200, 200)),
    Case("login", "GET", "/auth/login?next=/routes/1", (302, 302, 302, 302)),
    Case("create demo", "POST", "/auth/demo", (201, 201, 201, 201)),
    Case("me", "GET", "/me", (401, 200, 200, 200)),
    Case("export", "GET", "/me/export", (401, 200, 200, 200)),
    Case("list commutes", "GET", "/commutes", (401, 200, 200, 200)),
    Case("create commute", "POST", "/commutes", (401, 201, 201, 201), _commute),
    Case("update A's commute", "PATCH", "/commutes/{a_commute}", (401, 404, 404, 200), lambda *_: {"label": "Renamed"}),
    Case("delete A's commute", "DELETE", "/commutes/{a_spare}", (401, 404, 404, 204)),
    Case(
        "set alert on A's commute",
        "PUT",
        "/commutes/{a_commute}/alert",
        (401, 403, 404, 200),
        lambda *_: {"threshold_min": 7, "notify_cancellations": False},
    ),
    Case("delete alert on A's commute", "DELETE", "/commutes/{a_commute}/alert", (401, 404, 404, 204)),
    Case(
        "subscribe to push",
        "POST",
        "/push-subscriptions",
        (401, 403, 201, 201),
        lambda actor, _: push_subscription_body(actor),
    ),
    Case("unsubscribe A's push", "DELETE", "/push-subscriptions/{a_subscription}", (401, 404, 404, 204)),
    Case("ask", "POST", "/ask", (401, 403, 200, 200), lambda *_: {"question": "How late is route 1?"}),
    Case("logout", "POST", "/auth/logout", (401, 204, 204, 204)),
    Case("logout everywhere", "POST", "/auth/logout-all", (401, 204, 204, 204)),
    Case("delete account", "DELETE", "/me", (401, 204, 204, 204)),
]


@pytest.fixture
def world(app: FastAPI, catalog: Catalog, anon: Actor, demo: Actor, user_a: Actor, user_b: Actor) -> World:
    a_commute = user_a.post(f"{API}/commutes", json=catalog.commute_body()).json()["id"]
    a_spare = user_a.post(f"{API}/commutes", json=catalog.commute_body(label="Spare")).json()["id"]
    assert (
        user_a.put(
            f"{API}/commutes/{a_commute}/alert", json={"threshold_min": 10, "notify_cancellations": True}
        ).status_code
        == 200
    )
    a_subscription = user_a.post(f"{API}/push-subscriptions", json=push_subscription_body("a")).json()["id"]
    return World(
        actors={"anonymous": anon, "demo": demo, "user_b": user_b, "user_a": user_a},
        ids={"a_commute": a_commute, "a_spare": a_spare, "a_subscription": a_subscription},
        catalog=catalog,
    )


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_authorization_matrix(case: Case, world: World) -> None:
    path = API + case.path.format(**world.ids)
    for actor_name, expected in zip(ACTORS, case.expected, strict=True):
        body = case.body(actor_name, world.catalog) if case.body else None
        response = world.actors[actor_name].request(case.method, path, json=body)
        assert response.status_code == expected, f"{actor_name}: {response.status_code} {response.text}"
        if expected in (401, 403, 404):
            assert response.headers["content-type"].startswith("application/problem+json")


def test_every_api_route_is_covered_by_the_matrix(app: FastAPI) -> None:
    paths: dict[str, set[str]] = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    routes = {
        (method, path.removeprefix(API))
        for path, methods in paths.items()
        if path.startswith(API) and not path.endswith(("/openapi.json", "/docs"))
        for method in methods - {"HEAD"}
    }
    covered = {
        (
            c.method,
            c.path.split("?")[0]
            .replace("{a_spare}", "{commute_id}")
            .replace("{a_commute}", "{commute_id}")
            .replace("{a_subscription}", "{subscription_id}"),
        )
        for c in CASES
    }
    assert routes - covered == set()


def test_other_users_commute_404_is_indistinguishable_from_missing(world: World) -> None:
    user_b = world.actors["user_b"]
    theirs = user_b.patch(f"{API}/commutes/{world.ids['a_commute']}", json={"label": "x"})
    missing = user_b.patch(f"{API}/commutes/00000000-0000-4000-8000-000000000000", json={"label": "x"})
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


def test_listing_and_export_never_include_other_users_commutes(world: World, app_engine: Engine) -> None:
    user_b = world.actors["user_b"]
    b_commute = user_b.post(f"{API}/commutes", json=world.catalog.commute_body(label="Bob's")).json()["id"]
    listed = {c["id"] for c in user_b.get(f"{API}/commutes").json()["commutes"]}
    assert listed == {b_commute}
    exported = user_b.get(f"{API}/me/export").json()
    assert {c["id"] for c in exported["commutes"]} == {b_commute}
    assert world.ids["a_commute"] not in str(exported)
