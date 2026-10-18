"""Saved commutes: owner-scoped CRUD. Another user's commute ID behaves exactly like a missing one (404)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse

from stopwatch.commutes import service as commutes
from stopwatch.commutes.schemas import CommuteCreate, CommuteList, CommuteOut, CommutePatch
from stopwatch.platform import idempotency
from stopwatch.platform.db import transaction

from .. import ratelimits
from ..deps import ContextDep, EngineDep, SettingsDep, SignedIn, limit_per_user
from ..snapshots import republish

router = APIRouter(prefix="/commutes", tags=["commutes"])
_write_limit = Depends(limit_per_user(ratelimits.COMMUTES_WRITE))


@router.get("", response_model=CommuteList, dependencies=[Depends(limit_per_user(ratelimits.COMMUTES_READ))])
def list_commutes(auth: SignedIn, engine: EngineDep) -> CommuteList:
    with transaction(engine) as conn:
        return CommuteList(commutes=commutes.list_commutes(conn, auth.user.id))


@router.post("", status_code=201, response_model=CommuteOut, dependencies=[_write_limit])
def create_commute(
    body: CommuteCreate,
    auth: SignedIn,
    engine: EngineDep,
    ctx: ContextDep,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Create a commute. Retrying with the same ``Idempotency-Key`` and body replays the first response."""
    key = idempotency.validate_key(idempotency_key) if idempotency_key is not None else None
    with transaction(engine) as conn:
        result = commutes.create_commute(
            conn,
            owner_id=auth.user.id,
            is_demo=auth.user.is_demo,
            data=body,
            now=ctx.now,
            ctx=ctx.audit(auth.user),
            idempotency_key=key,
        )
    headers = {"Idempotent-Replayed": "true"} if result.replayed else None
    return JSONResponse(result.body, status_code=201, headers=headers)


@router.patch("/{commute_id}", response_model=CommuteOut, dependencies=[_write_limit])
def update_commute(
    commute_id: UUID,
    body: CommutePatch,
    *,
    auth: SignedIn,
    settings: SettingsDep,
    engine: EngineDep,
    ctx: ContextDep,
) -> CommuteOut:
    with transaction(engine) as conn:
        result = commutes.update_commute(
            conn,
            owner_id=auth.user.id,
            commute_id=commute_id,
            patch=body,
            now=ctx.now,
            ctx=ctx.audit(auth.user),
        )
    if result.commute.alert is not None:
        republish(engine, settings, {result.previous_agency_id, result.commute.agency_id})
    return result.commute


@router.delete("/{commute_id}", status_code=204, response_class=Response, dependencies=[_write_limit])
def delete_commute(
    commute_id: UUID, auth: SignedIn, settings: SettingsDep, engine: EngineDep, ctx: ContextDep
) -> Response:
    with transaction(engine) as conn:
        deleted = commutes.delete_commute(conn, owner_id=auth.user.id, commute_id=commute_id, ctx=ctx.audit(auth.user))
    if deleted.alert is not None:
        republish(engine, settings, {deleted.agency_id})
    return Response(status_code=204)
