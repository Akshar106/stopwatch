"""FastAPI dependencies: settings, database, request context, authentication and rate limits.

Authorization policy per route (docs/05 §3) is expressed by which of these a route depends on:
``public`` (none), ``session`` (:data:`SignedIn`), ``session, non-demo`` (:data:`FullAccount`).
Object ownership is enforced one layer down, in the owner-scoped repositories.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine

from stopwatch.accounts import csrf
from stopwatch.accounts import service as accounts
from stopwatch.accounts.models import ClientInfo, User
from stopwatch.platform import audit, ratelimit
from stopwatch.platform.audit import AuditContext
from stopwatch.platform.clock import utc_now
from stopwatch.platform.config import Settings
from stopwatch.platform.db import get_engine, transaction
from stopwatch.platform.observability import get_logger
from stopwatch.platform.ratelimit import RateLimit, RateLimitExceededError
from stopwatch.platform.security import client_address, ip_prefix, session_secret

from .cookies import session_cookie_name
from .errors import ProblemError

log = get_logger("api")


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db() -> Engine:
    return get_engine()


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_db)]


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    ip_prefix: str | None
    user_agent: str | None
    now: datetime

    @property
    def client(self) -> ClientInfo:
        return ClientInfo(ip_prefix=self.ip_prefix, user_agent=self.user_agent)

    def audit(self, user: User | None = None) -> AuditContext:
        if user is None:
            return AuditContext("anonymous", None, self.request_id, self.ip_prefix)
        return AuditContext("user", user.id, self.request_id, self.ip_prefix)


def get_request_context(request: Request, settings: SettingsDep) -> RequestContext:
    address = client_address(
        viewer_address=request.headers.get("cloudfront-viewer-address"),
        peer=request.client.host if request.client else None,
        behind_edge=settings.is_cloud,
    )
    return RequestContext(
        request_id=getattr(request.state, "request_id", "-"),
        ip_prefix=ip_prefix(address),
        user_agent=request.headers.get("user-agent"),
        now=utc_now(),
    )


ContextDep = Annotated[RequestContext, Depends(get_request_context)]


@dataclass(frozen=True)
class Auth:
    """The signed-in caller."""

    user: User
    session_token: str
    token_hash: bytes
    csrf_token: str


def session_token(request: Request, settings: SettingsDep) -> str | None:
    return request.cookies.get(session_cookie_name(settings))


def require_session(request: Request, settings: SettingsDep, engine: EngineDep, ctx: ContextDep) -> Auth:
    token = session_token(request, settings)
    if token is None:
        raise ProblemError(401, "unauthenticated", "Sign in to continue.")
    with transaction(engine) as conn:
        active = accounts.authenticate(conn, token, now=ctx.now)
    if active is None:
        raise ProblemError(401, "unauthenticated", "Your session has expired; sign in again.")
    request.state.user_id = str(active.user.id)  # for the access log (pseudonymous)
    return Auth(
        user=active.user,
        session_token=token,
        token_hash=active.token_hash,
        csrf_token=csrf.csrf_token_for(session_secret(settings), active.token_hash),
    )


SignedIn = Annotated[Auth, Depends(require_session)]


def require_full_account(auth: SignedIn) -> Auth:
    if auth.user.is_demo:
        raise ProblemError(403, "demo-restricted", "Sign in with Google to use this feature.")
    return auth


FullAccount = Annotated[Auth, Depends(require_full_account)]


# --- rate limits ----------------------------------------------------------------------------------------


def _enforce(engine: Engine, rule: RateLimit, key: str, ctx: RequestContext, user: User | None) -> None:
    """Count the request in its own committed transaction, then raise outside it if over the limit."""
    with transaction(engine) as conn:
        decision = ratelimit.hit(conn, rule, key, now=ctx.now)
        if decision.first_rejection:  # sampled: one audit row per bucket per window
            audit.record(conn, ctx.audit(user), "ratelimit.blocked", outcome="denied", details={"rule": rule.name})
    if not decision.allowed:
        log.warning("rate_limited", rule=rule.name, request_id=ctx.request_id)
        raise RateLimitExceededError(decision, rule)


def limit_per_user(rule: RateLimit) -> Callable[..., None]:
    """Dependency: ``rule`` applied per signed-in user (implies a session)."""

    def dependency(auth: SignedIn, engine: EngineDep, ctx: ContextDep) -> None:
        _enforce(engine, rule, f"user:{auth.user.id}", ctx, auth.user)

    return dependency


def limit_per_ip(rule: RateLimit) -> Callable[..., None]:
    """Dependency: ``rule`` applied per client IP prefix (/24 or /48)."""

    def dependency(engine: EngineDep, ctx: ContextDep) -> None:
        _enforce(engine, rule, f"ip:{ctx.ip_prefix or 'unknown'}", ctx, None)

    return dependency
