"""Liveness. Deliberately touches nothing (no database, no storage) so it stays cheap and always fast."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import SettingsDep

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    version: str


@router.get("/healthz", response_model=Health)
def healthz(settings: SettingsDep) -> Health:
    return Health(status="ok", version=settings.version)
