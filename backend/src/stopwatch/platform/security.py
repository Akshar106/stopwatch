"""Small cryptographic and request-identity helpers shared by the API and application modules.

Everything here is pure (no I/O) so it is easy to test: random tokens, SHA-256 hashing, HMAC signing with
constant-time verification, a signed + expiring JSON envelope (used for the OIDC transaction cookie), PKCE,
and IP-prefix derivation (we only ever store a /24 or /48, never a full client address).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import datetime
from typing import Any

from .config import Settings

TOKEN_BYTES = 32  # 256-bit session tokens, OIDC state and nonce
MIN_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """A required secret is missing or too weak."""


def session_secret(settings: Settings) -> bytes:
    """The HMAC key for sessions, CSRF tokens and signed cookies. Fails closed if missing or short."""
    if settings.session_secret is None:
        raise ConfigurationError("SESSION_SECRET is not set")
    raw = settings.session_secret.get_secret_value()
    if len(raw) < MIN_SECRET_LENGTH:
        raise ConfigurationError(f"SESSION_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return raw.encode()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    """Decode unpadded base64url. Raises ValueError on malformed input."""
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("malformed base64url") from exc


def new_token() -> str:
    """A fresh 256-bit random token, base64url-encoded (43 characters)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def sha256(value: str | bytes) -> bytes:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).digest()


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    a_bytes = a.encode() if isinstance(a, str) else a
    b_bytes = b.encode() if isinstance(b, str) else b
    return hmac.compare_digest(a_bytes, b_bytes)


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256 code challenge."""
    return b64url_encode(sha256(verifier.encode("ascii")))


# --- Signed, expiring JSON envelopes -------------------------------------------------------------------


def _envelope_mac(key: bytes, purpose: str, body: str) -> bytes:
    # The purpose is mixed into the MAC so a value signed for one cookie can't be replayed as another.
    return hmac_sha256(key, f"{purpose}|{body}".encode())


def sign_envelope(key: bytes, purpose: str, payload: dict[str, Any], *, expires_at: datetime) -> str:
    """Serialize ``payload`` with an expiry and an HMAC-SHA256 tag: ``<b64 json>.<b64 mac>``."""
    document = {**payload, "exp": int(expires_at.timestamp())}
    body = b64url_encode(json.dumps(document, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{b64url_encode(_envelope_mac(key, purpose, body))}"


def open_envelope(key: bytes, purpose: str, value: str | None, *, now: datetime) -> dict[str, Any] | None:
    """Verify and decode an envelope. Returns None if missing, tampered, malformed or expired."""
    if not value or value.count(".") != 1:
        return None
    body, tag = value.split(".")
    try:
        presented = b64url_decode(tag)
    except ValueError:
        return None
    if not constant_time_equals(presented, _envelope_mac(key, purpose, body)):
        return None
    try:
        document = json.loads(b64url_decode(body))
    except ValueError:
        return None
    if not isinstance(document, dict) or not isinstance(document.get("exp"), int):
        return None
    if document["exp"] <= int(now.timestamp()):
        return None
    return document


# --- Client address -----------------------------------------------------------------------------------


def ip_prefix(address: str | None) -> str | None:
    """Reduce a client address to its network prefix (/24 for IPv4, /48 for IPv6), in CIDR notation.

    Returns None for anything that isn't an IP address (e.g. a test client name).
    """
    if not address:
        return None
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    prefix_len = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix_len}", strict=False))


def parse_viewer_address(value: str | None) -> str | None:
    """CloudFront-Viewer-Address is "ip:port" (IPv6 without brackets, port after the last colon)."""
    if not value:
        return None
    host = value.strip().rsplit(":", 1)[0].strip("[]")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def client_address(*, viewer_address: str | None, peer: str | None, behind_edge: bool) -> str | None:
    """The client's IP address as seen by the edge.

    In staging/prod every request arrives through CloudFront, which sets ``CloudFront-Viewer-Address`` from
    the TCP connection (clients cannot spoof it, unlike ``X-Forwarded-For``); requests that bypass
    CloudFront are rejected by the origin-verify check. Locally there is no proxy, so the socket peer is used.
    """
    if behind_edge:
        return parse_viewer_address(viewer_address)
    return peer


def origin_verified(header_value: str | None, secret: str | None) -> bool:
    """Constant-time check of the X-Origin-Verify header CloudFront adds (always true if no secret configured)."""
    if not secret:
        return True
    return header_value is not None and hmac.compare_digest(header_value.encode(), secret.encode())
