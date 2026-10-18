"""Fixtures for API tests: an app wired to the throwaway test database, browser-like actors, a fake Google."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import Engine

from stopwatch.accounts import oidc
from stopwatch.api.main import create_app
from stopwatch.platform import config

from .factories import Actor, Catalog, create_demo_user, create_google_user, new_actor, seed_catalog, signed_in_actor

GOOGLE_CLIENT_ID = "stopwatch-test.apps.googleusercontent.com"


@pytest.fixture
def make_app(app_settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., FastAPI]:
    """Build an app with test settings; keyword arguments override environment variables."""

    def factory(**env: str) -> FastAPI:
        defaults = {
            "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
            "GOOGLE_CLIENT_SECRET": "google-client-secret-for-tests",
            "PUBLIC_BASE_URL": "http://localhost:5173",
            "ALERTS_ENABLED": "true",
            "ASK_ENABLED": "true",
            "DEMO_ENABLED": "true",
            "VAPID_PUBLIC_KEY": "BTestVapidPublicKey",
        }
        for key, value in {**defaults, **env}.items():
            monkeypatch.setenv(key, value)
        config.reset_settings_cache()
        return create_app()

    return factory


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture
def catalog(app_engine: Engine) -> Catalog:
    return seed_catalog(app_engine)


@pytest.fixture
def anon(app: FastAPI) -> Actor:
    return new_actor(app)


@pytest.fixture
def user_a(app: FastAPI, app_engine: Engine) -> Actor:
    return signed_in_actor(app, app_engine, create_google_user(app_engine, name="Alice"))


@pytest.fixture
def user_b(app: FastAPI, app_engine: Engine) -> Actor:
    return signed_in_actor(app, app_engine, create_google_user(app_engine, name="Bob"))


@pytest.fixture
def demo(app: FastAPI, app_engine: Engine) -> Actor:
    return signed_in_actor(app, app_engine, create_demo_user(app_engine))


# --- a fake Google ----------------------------------------------------------------------------------------


@dataclass
class FakeGoogle:
    """Signs ID tokens with a local RSA key served from a mocked JWKS endpoint; mocks the token endpoint."""

    private_key: rsa.RSAPrivateKey
    kid: str
    router: respx.MockRouter
    token_route: respx.Route

    def id_token(self, *, nonce: str, key: rsa.RSAPrivateKey | None = None, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "https://accounts.google.com",
            "aud": GOOGLE_CLIENT_ID,
            "azp": GOOGLE_CLIENT_ID,
            "sub": "google-sub-" + uuid.uuid4().hex[:12],
            "email": "rider@example.com",
            "email_verified": True,
            "name": "Rider Example",
            "iat": now,
            "exp": now + 3600,
            "nonce": nonce,
        }
        claims.update(overrides)
        return jwt.encode(claims, key or self.private_key, algorithm="RS256", headers={"kid": self.kid})

    def will_return(self, id_token: str) -> None:
        self.token_route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.test",
                    "expires_in": 3599,
                    "token_type": "Bearer",
                    "id_token": id_token,
                },
            )
        )


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(rsa_key: rsa.RSAPrivateKey) -> Iterator[FakeGoogle]:
    kid = "test-key-1"
    jwk = RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    oidc.jwks_client.cache_clear()
    with respx.mock(assert_all_called=False) as router:
        router.get(oidc.JWKS_URI).mock(return_value=httpx.Response(200, json={"keys": [jwk]}))
        token_route = router.post(oidc.TOKEN_ENDPOINT)
        yield FakeGoogle(private_key=rsa_key, kid=kid, router=router, token_route=token_route)
    oidc.jwks_client.cache_clear()
