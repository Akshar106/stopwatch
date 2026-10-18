"""RFC 9457 problem details for every error the API returns.

Shape: ``{type, title, status, detail?, errors?}`` with ``Content-Type: application/problem+json``.
``type`` is ``about:blank`` for plain HTTP errors and ``urn:stopwatch:problem:<slug>`` for errors the
frontend may want to branch on (``csrf``, ``rate-limited``, ``demo-restricted`` …). Domain exceptions from the
application modules are translated here, so route handlers stay free of status-code plumbing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stopwatch.accounts.demo import DemoCapacityError
from stopwatch.alerts.rules import SubscriptionLimitError
from stopwatch.ask.models import AskDisabledError, AskQuotaExceededError
from stopwatch.commutes.service import CommuteLimitError, CommuteNotFoundError, CommuteValidationError
from stopwatch.platform.idempotency import IdempotencyConflictError, InvalidIdempotencyKeyError
from stopwatch.platform.ratelimit import RateLimitExceededError

PROBLEM_JSON = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:stopwatch:problem:"


def problem_type(slug: str | None) -> str:
    return f"{PROBLEM_TYPE_PREFIX}{slug}" if slug else "about:blank"


class ProblemError(StarletteHTTPException):
    """An HTTP error with a problem ``type`` slug and optional field errors."""

    def __init__(
        self,
        status: int,
        slug: str | None = None,
        detail: str | None = None,
        *,
        title: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status, detail=detail, headers=headers)
        self.slug = slug
        self.title = title
        self.errors = errors


def problem_response(
    status: int,
    *,
    slug: str | None = None,
    title: str | None = None,
    detail: str | None = None,
    errors: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": problem_type(slug),
        "title": title or HTTPStatus(status).phrase,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


# --- handlers -------------------------------------------------------------------------------------------


async def _http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # Starlette fills ``detail`` with the status phrase when none is given; don't repeat the title.
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != HTTPStatus(exc.status_code).phrase else None
    if isinstance(exc, ProblemError):
        return problem_response(
            exc.status_code, slug=exc.slug, title=exc.title, detail=detail, errors=exc.errors, headers=exc.headers
        )
    return problem_response(exc.status_code, detail=detail, headers=exc.headers)


def _field_name(loc: tuple[Any, ...]) -> str:
    # ("body", "window_end") -> "window_end"; ("query", "next") -> "next"; ("body",) -> "body"
    parts = (
        [str(p) for p in loc[1:]]
        if len(loc) > 1 and loc[0] in ("body", "query", "path", "header", "cookie")
        else [str(p) for p in loc]
    )
    return ".".join(parts) or "body"


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Messages only: never echo the submitted values back (they may be personal data).
    errors = [
        {"field": _field_name(tuple(e.get("loc", ()))), "message": str(e.get("msg", "invalid value"))}
        for e in exc.errors()
    ]
    return problem_response(422, slug="validation", title="Validation failed", errors=errors)


def _rate_limited(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RateLimitExceededError)
    return problem_response(
        429,
        slug="rate-limited",
        detail="Too many requests; try again later.",
        headers={"Retry-After": str(exc.decision.retry_after_s)},
    )


def _commute_validation(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CommuteValidationError)
    errors = [{"field": field, "message": message} for field, message in exc.errors]
    return problem_response(422, slug="validation", title="Validation failed", errors=errors)


def _commute_limit(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CommuteLimitError)
    return problem_response(409, slug="commute-limit", detail=f"You can save up to {exc.limit} commutes.")


def _simple(status: int, slug: str | None, detail: str | None = None) -> Callable[[Request, Exception], JSONResponse]:
    def handler(_: Request, __: Exception) -> JSONResponse:
        return problem_response(status, slug=slug, detail=detail)

    return handler


def _field_error(field: str) -> Callable[[Request, Exception], JSONResponse]:
    def handler(_: Request, exc: Exception) -> JSONResponse:
        return problem_response(
            422, slug="validation", title="Validation failed", errors=[{"field": field, "message": str(exc)}]
        )

    return handler


def install_error_handlers(app: FastAPI) -> None:
    """Register problem+json rendering for HTTP, validation and domain errors.

    Unhandled exceptions are rendered as a 500 by the request-context middleware, which also keeps the
    ``X-Request-Id`` header on that response.
    """
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(RateLimitExceededError, _rate_limited)
    app.add_exception_handler(CommuteValidationError, _commute_validation)
    app.add_exception_handler(CommuteLimitError, _commute_limit)
    app.add_exception_handler(CommuteNotFoundError, _simple(404, None))
    app.add_exception_handler(IdempotencyConflictError, _field_error("Idempotency-Key"))
    app.add_exception_handler(InvalidIdempotencyKeyError, _field_error("Idempotency-Key"))
    app.add_exception_handler(
        DemoCapacityError,
        _simple(429, "demo-capacity", "Too many demo accounts are active right now; try again later."),
    )
    app.add_exception_handler(
        SubscriptionLimitError,
        _simple(409, "subscription-limit", "Too many push subscriptions on this account."),
    )
    app.add_exception_handler(
        AskQuotaExceededError, _simple(429, "ask-quota", "You've used today's questions; try again tomorrow.")
    )
    app.add_exception_handler(AskDisabledError, _simple(503, "ask-disabled", "Ask Stopwatch is unavailable."))
