"""Google sign-in: OpenID Connect authorization-code flow with PKCE (S256), ``state`` and ``nonce``.

The in-flight login lives in the ``sw_oidc`` cookie: an HMAC-signed, 10-minute envelope holding the state,
nonce, PKCE verifier and the post-login ``next`` path. Nothing is stored server-side until the ID token has
been verified (signature via Google's JWKS, ``iss``, ``aud``, ``exp`` and ``nonce``).
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt import PyJWKClient

from stopwatch.platform.security import (
    constant_time_equals,
    new_token,
    open_envelope,
    pkce_challenge,
    sign_envelope,
)

from .models import GoogleIdentity

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a credential
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
CANONICAL_ISSUER = "https://accounts.google.com"
SCOPES = "openid email profile"
CALLBACK_PATH = "/api/v1/auth/callback"
TRANSACTION_TTL = timedelta(minutes=10)
TRANSACTION_PURPOSE = "sw_oidc"
CLOCK_SKEW_S = 30
MAX_NEXT_LENGTH = 512
MAX_DISPLAY_NAME_LENGTH = 100
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
_FORBIDDEN_NEXT_CHARS = frozenset("\\") | frozenset(string.whitespace) | {chr(c) for c in range(32)} | {chr(127)}


class OIDCError(Exception):
    """A login attempt failed.

    ``public_code`` goes in the ``/signin?error=`` redirect; ``reason`` is for the audit log only.
    """

    def __init__(self, public_code: str, reason: str) -> None:
        super().__init__(reason)
        self.public_code = public_code
        self.reason = reason


class InvalidNextPathError(ValueError):
    pass


@dataclass(frozen=True)
class GoogleClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def build(cls, *, client_id: str, client_secret: str, public_base_url: str) -> GoogleClientConfig:
        return cls(client_id, client_secret, public_base_url.rstrip("/") + CALLBACK_PATH)


@dataclass(frozen=True)
class LoginStart:
    authorization_url: str
    transaction_cookie: str


def safe_next_path(value: str | None) -> str:
    """Accept only a same-site relative path such as ``/routes/1``; anything else is an open redirect risk."""
    if value is None or value == "":
        return "/"
    if len(value) > MAX_NEXT_LENGTH or any(ch in _FORBIDDEN_NEXT_CHARS for ch in value):
        raise InvalidNextPathError("next must be a relative path")
    parts = urlsplit(value)
    if not value.startswith("/") or value.startswith("//") or parts.scheme or parts.netloc:
        raise InvalidNextPathError("next must be a relative path")
    return value


def start_login(config: GoogleClientConfig, key: bytes, next_path: str, *, now: datetime) -> LoginStart:
    state, nonce, verifier = new_token(), new_token(), new_token() + new_token()  # verifier: 86 chars
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    cookie = sign_envelope(
        key,
        TRANSACTION_PURPOSE,
        {"state": state, "nonce": nonce, "verifier": verifier, "next": next_path},
        expires_at=now + TRANSACTION_TTL,
    )
    return LoginStart(f"{AUTHORIZATION_ENDPOINT}?{query}", cookie)


class _HttpxJWKClient(PyJWKClient):
    """PyJWKClient fetching over httpx (strict timeouts, no redirects); the base class caches the key set."""

    def fetch_data(self) -> Any:
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
                response = client.get(self.uri, headers={"Accept": "application/json"})
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise jwt.PyJWKClientConnectionError(f"JWKS fetch failed: {type(exc).__name__}") from exc


@lru_cache(maxsize=1)
def jwks_client() -> PyJWKClient:
    """Process-wide JWKS client: keys are cached for five minutes across warm invocations."""
    return _HttpxJWKClient(JWKS_URI, lifespan=300)


def _exchange_code(config: GoogleClientConfig, code: str, verifier: str) -> str:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code_verifier": verifier,
    }
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            response = client.post(TOKEN_ENDPOINT, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OIDCError("login_failed", f"token_endpoint_unreachable:{type(exc).__name__}") from exc
    if response.status_code != 200:
        raise OIDCError("login_failed", f"token_endpoint_status_{response.status_code}")
    try:
        id_token = response.json().get("id_token")
    except ValueError as exc:
        raise OIDCError("login_failed", "token_endpoint_bad_json") from exc
    if not isinstance(id_token, str) or not id_token:
        raise OIDCError("login_failed", "missing_id_token")
    return id_token


def verify_id_token(config: GoogleClientConfig, id_token: str, *, nonce: str, jwks: PyJWKClient) -> dict[str, Any]:
    """Verify signature, issuer, audience, expiry and nonce. Raises :class:`OIDCError`."""
    try:
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=ISSUERS,
            leeway=CLOCK_SKEW_S,
            options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OIDCError("login_failed", "token_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise OIDCError("login_failed", "invalid_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise OIDCError("login_failed", "invalid_issuer") from exc
    except jwt.PyJWKClientError as exc:
        raise OIDCError("login_failed", "jwks_unavailable") from exc
    except jwt.InvalidTokenError as exc:
        raise OIDCError("login_failed", "invalid_token") from exc
    if not constant_time_equals(str(claims["nonce"]), nonce):
        raise OIDCError("login_failed", "invalid_nonce")
    if "azp" in claims and claims["azp"] != config.client_id:
        raise OIDCError("login_failed", "invalid_azp")
    return claims


def identity_from_claims(claims: dict[str, Any]) -> GoogleIdentity:
    email = claims.get("email") if claims.get("email_verified") is True else None
    name = claims.get("name")
    return GoogleIdentity(
        issuer=CANONICAL_ISSUER,  # Google uses both issuer spellings for the same subject
        subject=str(claims["sub"]),
        email=email if isinstance(email, str) else None,
        display_name=name[:MAX_DISPLAY_NAME_LENGTH] if isinstance(name, str) else None,
    )


def complete_login(
    config: GoogleClientConfig,
    key: bytes,
    *,
    transaction_cookie: str | None,
    state: str | None,
    code: str | None,
    error: str | None,
    now: datetime,
    jwks: PyJWKClient | None = None,
) -> tuple[GoogleIdentity, str]:
    """Finish the callback: check the transaction, exchange the code, verify the ID token.

    Returns the verified identity and the ``next`` path to redirect to.
    """
    txn = open_envelope(key, TRANSACTION_PURPOSE, transaction_cookie, now=now)
    if txn is None:
        raise OIDCError("invalid_state", "missing_or_expired_transaction")
    if not state or not constant_time_equals(state, str(txn["state"])):
        raise OIDCError("invalid_state", "state_mismatch")
    if error:
        raise OIDCError("access_denied" if error == "access_denied" else "login_failed", "provider_error")
    if not code:
        raise OIDCError("login_failed", "missing_code")
    id_token = _exchange_code(config, code, str(txn["verifier"]))
    claims = verify_id_token(config, id_token, nonce=str(txn["nonce"]), jwks=jwks or jwks_client())
    try:
        next_path = safe_next_path(str(txn.get("next") or "/"))
    except InvalidNextPathError:
        next_path = "/"
    return identity_from_claims(claims), next_path
