"""Web Push subscriptions. A user's rules only reach the snapshot while they have a subscription."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from stopwatch.alerts import rules
from stopwatch.alerts.rules import PushSubscriptionIn
from stopwatch.platform import audit
from stopwatch.platform.db import transaction

from .. import ratelimits
from ..deps import (
    ContextDep,
    EngineDep,
    FullAccount,
    SettingsDep,
    SignedIn,
    limit_per_user,
    require_full_account,
)
from ..errors import ProblemError
from ..snapshots import republish
from .alerts import require_alerts_enabled

router = APIRouter(prefix="/push-subscriptions", tags=["push"])
_write_limit = Depends(limit_per_user(ratelimits.PUSH_WRITE))


class SubscriptionCreated(BaseModel):
    id: str


@router.post(
    "",
    status_code=201,
    response_model=SubscriptionCreated,
    dependencies=[Depends(require_full_account), Depends(require_alerts_enabled), _write_limit],
)
def subscribe(
    body: PushSubscriptionIn, auth: FullAccount, settings: SettingsDep, engine: EngineDep, ctx: ContextDep
) -> SubscriptionCreated:
    with transaction(engine) as conn:
        subscription_id = rules.add_subscription(conn, auth.user.id, body)
        agencies = rules.rule_agencies_for_owner(conn, auth.user.id)
        audit.record(
            conn,
            ctx.audit(auth.user),
            "push.subscribe",
            target_kind="push_subscription",
            target_id=str(subscription_id),
        )
    # An endpoint can move between accounts in the same browser, so reconcile every configured agency.
    republish(engine, settings, agencies | set(settings.agency_ids))
    return SubscriptionCreated(id=str(subscription_id))


@router.delete("/{subscription_id}", status_code=204, response_class=Response, dependencies=[_write_limit])
def unsubscribe(
    subscription_id: UUID, auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep
) -> Response:
    with transaction(engine) as conn:
        if not rules.delete_subscription_for_owner(conn, auth.user.id, subscription_id):
            raise ProblemError(404)
        agencies = rules.rule_agencies_for_owner(conn, auth.user.id)
        audit.record(
            conn,
            ctx.audit(auth.user),
            "push.unsubscribe",
            target_kind="push_subscription",
            target_id=str(subscription_id),
        )
    republish(engine, settings, agencies)
    return Response(status_code=204)
