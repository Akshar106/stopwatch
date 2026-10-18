"""CSRF tokens bound to the session: ``base64url(HMAC-SHA256(SESSION_SECRET, sha256(session_token)))``.

Derivable from the cookie alone, so the check needs no database round trip and nothing extra is stored.
Rotating the session (login, demo creation) rotates the CSRF token with it.
"""

from __future__ import annotations

from stopwatch.platform.security import b64url_encode, constant_time_equals, hmac_sha256


def csrf_token_for(key: bytes, token_hash: bytes) -> str:
    return b64url_encode(hmac_sha256(key, token_hash))


def is_valid(key: bytes, token_hash: bytes, presented: str | None) -> bool:
    if not presented:
        return False
    return constant_time_equals(presented, csrf_token_for(key, token_hash))
