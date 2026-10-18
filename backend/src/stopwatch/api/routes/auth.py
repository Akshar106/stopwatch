"""Sign-in (Google OIDC), demo accounts, and sign-out."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine

from stopwatch.accounts import oidc
from stopwatch.accounts import service as accounts
from stopwatch.accounts.models import MeResponse
from stopwatch.platform.config import Settings
from stopwatch.platform.db import transaction
from stopwatch.platform.observability import get_logger, put_metric
from stopwatch.platform.security import session_secret

from .. import ratelimits
from ..cookies import (
    OIDC_COOKIE,
    clear_oidc_cookie,
    clear_session_cookie,
    set_oidc_cookie,
    set_session_cookie,
)
from ..deps import ContextDep, EngineDep, RequestContext, SettingsDep, SignedIn, limit_per_ip, session_token
from ..errors import ProblemError
from .config import google_login_enabled
from .me import build_me_response

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("api")

SIGNIN_PATH = "/signin"
OAuthParam = Annotated[str | None, Query(max_length=2048)]


def _google_config(settings: Settings) -> oidc.GoogleClientConfig:
    if not google_login_enabled(settings) or settings.google_client_secret is None:
        raise ProblemError(404, "google-login-disabled", "Google sign-in is not configured.")
    return oidc.GoogleClientConfig.build(
        client_id=str(settings.google_client_id),
        client_secret=settings.google_client_secret.get_secret_value(),
        public_base_url=settings.public_base_url,
    )


@router.get(
    "/login",
    status_code=302,
    response_class=RedirectResponse,
    dependencies=[Depends(limit_per_ip(ratelimits.AUTH_LOGIN))],
)
def login(
    settings: SettingsDep,
    ctx: ContextDep,
    next_path: Annotated[str | None, Query(alias="next", max_length=oidc.MAX_NEXT_LENGTH)] = None,
) -> RedirectResponse:
    """Start Google sign-in. ``next`` must be a same-site relative path (``/routes/1``), never a URL."""
    config = _google_config(settings)
    try:
        safe_next = oidc.safe_next_path(next_path)
    except oidc.InvalidNextPathError as exc:
        raise ProblemError(
            422, "validation", title="Validation failed", errors=[{"field": "next", "message": str(exc)}]
        ) from exc
    start = oidc.start_login(config, session_secret(settings), safe_next, now=ctx.now)
    response = RedirectResponse(start.authorization_url, status_code=302)
    set_oidc_cookie(response, settings, start.transaction_cookie)
    return response


def _login_failed(engine: Engine, settings: Settings, ctx: RequestContext, exc: oidc.OIDCError) -> RedirectResponse:
    put_metric("AuthFailures", 1)
    log.warning("login_failed", reason=exc.reason, request_id=ctx.request_id)
    with transaction(engine) as conn:
        accounts.record_failed_login(conn, ctx.audit(), exc.reason)
    response = RedirectResponse(f"{SIGNIN_PATH}?{urlencode({'error': exc.public_code})}", status_code=302)
    clear_oidc_cookie(response, settings)
    return response


@router.get(
    "/callback",
    status_code=302,
    response_class=RedirectResponse,
    dependencies=[Depends(limit_per_ip(ratelimits.AUTH_CALLBACK))],
)
def callback(
    request: Request,
    *,
    settings: SettingsDep,
    engine: EngineDep,
    ctx: ContextDep,
    code: OAuthParam = None,
    state: OAuthParam = None,
    error: OAuthParam = None,
) -> RedirectResponse:
    """Google redirects here. On success: rotate into a new session and redirect to ``next``."""
    config = _google_config(settings)
    try:
        identity, next_path = oidc.complete_login(
            config,
            session_secret(settings),
            transaction_cookie=request.cookies.get(OIDC_COOKIE),
            state=state,
            code=code,
            error=error,
            now=ctx.now,
        )
    except oidc.OIDCError as exc:
        return _login_failed(engine, settings, ctx, exc)
    with transaction(engine) as conn:
        signed_in = accounts.sign_in_with_google(
            conn,
            identity,
            now=ctx.now,
            client=ctx.client,
            previous_token=session_token(request, settings),
            ctx=ctx.audit(),
        )
    request.state.user_id = str(signed_in.user.id)
    response = RedirectResponse(next_path, status_code=302)
    clear_oidc_cookie(response, settings)
    set_session_cookie(
        response, settings, signed_in.session.token, expires_at=signed_in.session.expires_at, now=ctx.now
    )
    return response


def require_demo_enabled(settings: SettingsDep) -> None:
    if not settings.demo_enabled:
        raise ProblemError(404, "demo-disabled", "Demo accounts are not available.")


@router.post(
    "/demo",
    status_code=201,
    response_model=MeResponse,
    dependencies=[Depends(require_demo_enabled), Depends(limit_per_ip(ratelimits.DEMO_CREATE))],
)
def create_demo(
    request: Request, response: Response, settings: SettingsDep, engine: EngineDep, ctx: ContextDep
) -> MeResponse:
    """Create a 24-hour demo account and sign into it (replacing any current session)."""
    with transaction(engine) as conn:
        signed_in = accounts.start_demo(
            conn,
            now=ctx.now,
            client=ctx.client,
            previous_token=session_token(request, settings),
            ctx=ctx.audit(),
        )
    request.state.user_id = str(signed_in.user.id)
    set_session_cookie(
        response, settings, signed_in.session.token, expires_at=signed_in.session.expires_at, now=ctx.now
    )
    return build_me_response(settings, signed_in.user, signed_in.session.token_hash)


@router.post("/logout", status_code=204, response_class=Response)
def logout(auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep) -> Response:
    with transaction(engine) as conn:
        accounts.sign_out(conn, user_id=auth.user.id, token_hash=auth.token_hash, ctx=ctx.audit())
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.post("/logout-all", status_code=204, response_class=Response)
def logout_all(auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep) -> Response:
    with transaction(engine) as conn:
        accounts.sign_out_everywhere(conn, auth.user.id, ctx.audit())
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response
