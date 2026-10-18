"""The signed-in user: profile + CSRF token, data export, and account deletion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from stopwatch.accounts import csrf
from stopwatch.accounts import service as accounts
from stopwatch.accounts.models import MeFeatures, MeResponse, User, UserOut
from stopwatch.alerts import rules
from stopwatch.commutes import service as commutes
from stopwatch.commutes.schemas import CommuteOut
from stopwatch.platform import audit
from stopwatch.platform.config import Settings
from stopwatch.platform.db import transaction
from stopwatch.platform.security import session_secret

from .. import ratelimits
from ..cookies import clear_session_cookie
from ..deps import ContextDep, EngineDep, SettingsDep, SignedIn, limit_per_user
from ..snapshots import republish
from .config import google_login_enabled

router = APIRouter(tags=["account"])


def build_me_response(settings: Settings, user: User, token_hash: bytes) -> MeResponse:
    return MeResponse(
        user=UserOut.from_user(user),
        csrf_token=csrf.csrf_token_for(session_secret(settings), token_hash),
        features=MeFeatures(
            alerts=settings.alerts_enabled and not user.is_demo,
            ask=settings.ask_enabled and not user.is_demo,
            google_login=google_login_enabled(settings),
        ),
    )


@router.get("/me", response_model=MeResponse, dependencies=[Depends(limit_per_user(ratelimits.ME))])
def get_me(auth: SignedIn, settings: SettingsDep) -> MeResponse:
    return build_me_response(settings, auth.user, auth.token_hash)


class ExportSession(BaseModel):
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None


class ExportPushSubscription(BaseModel):
    id: str
    created_at: datetime


class ExportAuditEntry(BaseModel):
    at: datetime
    action: str
    outcome: str


class AccountExport(BaseModel):
    exported_at: datetime
    user: UserOut
    commutes: list[CommuteOut]
    sessions: list[ExportSession]
    push_subscriptions: list[ExportPushSubscription]
    audit: list[ExportAuditEntry]


@router.get("/me/export", response_model=AccountExport, dependencies=[Depends(limit_per_user(ratelimits.ME_EXPORT))])
def export_account(auth: SignedIn, engine: EngineDep, ctx: ContextDep) -> AccountExport:
    """Everything we hold about the caller, assembled from each module's owner-scoped queries."""
    with transaction(engine) as conn:
        profile: dict[str, Any] = accounts.export_profile(conn, auth.user)
        export = AccountExport.model_validate(
            {
                "exported_at": ctx.now,
                "user": profile["user"],
                "commutes": commutes.list_commutes(conn, auth.user.id),
                "sessions": profile["sessions"],
                "push_subscriptions": rules.list_subscriptions_for_owner(conn, auth.user.id),
                "audit": audit.list_for_actor(conn, auth.user.id),
            }
        )
        audit.record(conn, ctx.audit(auth.user), "account.export")
    return export


@router.delete(
    "/me",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(limit_per_user(ratelimits.ME_DELETE))],
)
def delete_account(auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep) -> Response:
    with transaction(engine) as conn:
        affected_agencies = rules.rule_agencies_for_owner(conn, auth.user.id)
        accounts.delete_account(conn, auth.user.id, ctx.audit())
    republish(engine, settings, affected_agencies)
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response
