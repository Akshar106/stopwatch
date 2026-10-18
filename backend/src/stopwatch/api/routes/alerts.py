"""Delay/cancellation alert rules on a saved commute (one rule per commute)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from stopwatch.alerts import rules
from stopwatch.alerts.rules import AlertRuleIn, AlertRuleOut
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

router = APIRouter(prefix="/commutes/{commute_id}/alert", tags=["alerts"])
_write_limit = Depends(limit_per_user(ratelimits.ALERTS_WRITE))


def require_alerts_enabled(settings: SettingsDep) -> None:
    if not settings.alerts_enabled:
        raise ProblemError(404, "feature-disabled", "Alerts are not enabled.")


@router.put(
    "",
    response_model=AlertRuleOut,
    dependencies=[Depends(require_full_account), Depends(require_alerts_enabled), _write_limit],
)
def put_alert(
    commute_id: UUID,
    body: AlertRuleIn,
    *,
    auth: FullAccount,
    settings: SettingsDep,
    engine: EngineDep,
    ctx: ContextDep,
) -> AlertRuleOut:
    with transaction(engine) as conn:
        result = rules.upsert_rule_for_owner(conn, auth.user.id, commute_id, body)
        if result is None:
            raise ProblemError(404)
        rule, agency_id = result
        audit.record(
            conn,
            ctx.audit(auth.user),
            "alert.configure",
            target_kind="commute",
            target_id=str(commute_id),
            details={"op": "put", "threshold_min": rule.threshold_min},
        )
    republish(engine, settings, {agency_id})
    return rule


@router.delete("", status_code=204, response_class=Response, dependencies=[_write_limit])
def delete_alert(
    commute_id: UUID, auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep
) -> Response:
    with transaction(engine) as conn:
        agency_id = rules.delete_rule_for_owner(conn, auth.user.id, commute_id)
        if agency_id is None:
            raise ProblemError(404)
        audit.record(
            conn,
            ctx.audit(auth.user),
            "alert.configure",
            target_kind="commute",
            target_id=str(commute_id),
            details={"op": "delete"},
        )
    republish(engine, settings, {agency_id})
    return Response(status_code=204)
