"""Cookie names and attributes (docs/contracts.md §4).

- Session: ``__Host-sw_session`` (Secure; HttpOnly; SameSite=Lax; Path=/) in staging/prod, ``sw_session``
  without Secure in local/test (plain-HTTP dev servers). Persistent until the session's absolute expiry.
- OIDC transaction: ``sw_oidc`` (HttpOnly; SameSite=Lax; Path=/api/v1/auth; 10 minutes). Lax is required:
  Google's redirect back to the callback is a cross-site top-level GET.
"""

from __future__ import annotations

from datetime import datetime

from starlette.responses import Response

from stopwatch.accounts.oidc import TRANSACTION_TTL
from stopwatch.platform.config import Settings

SESSION_COOKIE_SECURE = "__Host-sw_session"
SESSION_COOKIE_DEV = "sw_session"
OIDC_COOKIE = "sw_oidc"
OIDC_COOKIE_PATH = "/api/v1/auth"


def session_cookie_name(settings: Settings) -> str:
    return SESSION_COOKIE_SECURE if settings.is_cloud else SESSION_COOKIE_DEV


def set_session_cookie(
    response: Response, settings: Settings, token: str, *, expires_at: datetime, now: datetime
) -> None:
    response.set_cookie(
        session_cookie_name(settings),
        token,
        max_age=max(0, int((expires_at - now).total_seconds())),
        path="/",
        secure=settings.is_cloud,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        session_cookie_name(settings), path="/", secure=settings.is_cloud, httponly=True, samesite="lax"
    )


def set_oidc_cookie(response: Response, settings: Settings, value: str) -> None:
    response.set_cookie(
        OIDC_COOKIE,
        value,
        max_age=int(TRANSACTION_TTL.total_seconds()),
        path=OIDC_COOKIE_PATH,
        secure=settings.is_cloud,
        httponly=True,
        samesite="lax",
    )


def clear_oidc_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(OIDC_COOKIE, path=OIDC_COOKIE_PATH, secure=settings.is_cloud, httponly=True, samesite="lax")
