"""ASGI middleware: request IDs and access logs, last-resort 500s, and cross-site request defenses.

Kept as pure ASGI (not ``BaseHTTPMiddleware``) so it adds no task overhead and can see every response,
including the ones it produces itself.
"""

from __future__ import annotations

import re
import time
import traceback
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stopwatch.accounts import csrf
from stopwatch.accounts.sessions import hash_token
from stopwatch.platform.config import Settings
from stopwatch.platform.observability import get_logger, put_metric
from stopwatch.platform.security import origin_verified, session_secret

from .cookies import session_cookie_name
from .errors import problem_response

log = get_logger("api")

REQUEST_ID_HEADER = "X-Request-Id"
REQUESTED_WITH_VALUE = "stopwatch"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
API_PREFIX = "/api/"
# Creating a demo account is a sign-in: there is no CSRF token yet. X-Requested-With still applies.
CSRF_EXEMPT_PATHS = frozenset({"/api/v1/auth/demo"})
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _request_id(headers: Headers) -> str:
    """Reuse a well-formed incoming ID (e.g. from a load test) or mint one. Anything else is replaced."""
    incoming = headers.get(REQUEST_ID_HEADER)
    return incoming if incoming and _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex


class RequestContextMiddleware:
    """Assigns ``X-Request-Id``, logs one line per request, and turns unhandled errors into a bare 500."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.verbose_errors = not settings.is_cloud

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(Headers(scope=scope))
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        status: dict[str, int] = {}
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                if scope["path"].startswith(API_PREFIX) and "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"  # personal data must not sit in shared caches
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            if "code" in status:  # the response already started; nothing sensible left to send
                raise
            self._log_unhandled(exc, request_id)
            await problem_response(500)(scope, receive, send_with_id)
        finally:
            # Path only (no query string: it can carry OAuth codes). User IDs are pseudonymous; no emails.
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status.get("code"),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                request_id=request_id,
                user_id=state.get("user_id"),
            )

    def _log_unhandled(self, exc: Exception, request_id: str) -> None:
        if self.verbose_errors:
            log.exception("unhandled_error", request_id=request_id)
            return
        # In the cloud, exception messages can embed SQL parameters (i.e. personal data): log where, not what.
        frame = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        where = f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}" if frame else "unknown"
        log.error("unhandled_error", request_id=request_id, error_type=type(exc).__name__, where=where)


class CrossSiteRequestMiddleware:
    """Rejects state-changing API requests that could have been forged by another site.

    1. ``X-Requested-With: stopwatch`` is required on every unsafe method. A custom header can't be sent
       cross-origin without a CORS preflight, which this API never approves.
    2. When a session cookie is present, ``X-CSRF-Token`` must match the HMAC of the session token. The check
       needs no database lookup, and it runs before any route code, so no handler can forget it.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.cookie_name = session_cookie_name(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("x-requested-with") != REQUESTED_WITH_VALUE:
            put_metric("AuthFailures", 1)
            await problem_response(
                403,
                slug="missing-requested-with",
                detail="State-changing requests must send X-Requested-With: stopwatch.",
            )(scope, receive, send)
            return
        if scope["path"] not in CSRF_EXEMPT_PATHS and not self._csrf_ok(headers):
            put_metric("AuthFailures", 1)
            log.warning("csrf_rejected", path=scope["path"], request_id=scope.get("state", {}).get("request_id"))
            await problem_response(403, slug="csrf", detail="Missing or invalid X-CSRF-Token.")(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _csrf_ok(self, headers: Headers) -> bool:
        token = cookie_parser(headers.get("cookie", "")).get(self.cookie_name)
        if not token:
            return True  # not signed in: the route's own auth check answers 401
        return csrf.is_valid(session_secret(self.settings), hash_token(token), headers.get(CSRF_HEADER))


class OriginVerifyMiddleware:
    """In staging/prod, only accept /api requests that came through CloudFront.

    API Gateway HTTP APIs can't be restricted to CloudFront by network policy, so CloudFront adds a shared
    secret header (``X-Origin-Verify``) to origin requests and the API rejects anything without it. That makes
    ``CloudFront-Viewer-Address`` trustworthy for rate limiting and keeps WAF-less abuse paths closed.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        secret = settings.origin_verify_secret
        self.secret = secret.get_secret_value() if (secret is not None and settings.is_cloud) else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.secret is None or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return
        if not origin_verified(Headers(scope=scope).get("x-origin-verify"), self.secret):
            put_metric("AuthFailures", 1)
            await problem_response(403, slug="origin", detail="Requests must come through the site.")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
