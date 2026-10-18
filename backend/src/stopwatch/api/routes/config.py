"""Public client configuration: feature flags and the VAPID public key for Web Push."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from stopwatch.platform.config import Settings

from ..deps import SettingsDep

router = APIRouter(tags=["config"])


class Features(BaseModel):
    alerts: bool
    ask: bool
    google_login: bool
    demo: bool


class ClientConfig(BaseModel):
    features: Features
    vapid_public_key: str | None


def google_login_enabled(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def features_for(settings: Settings) -> Features:
    return Features(
        alerts=settings.alerts_enabled,
        ask=settings.ask_enabled,
        google_login=google_login_enabled(settings),
        demo=settings.demo_enabled,
    )


@router.get("/config", response_model=ClientConfig)
def client_config(settings: SettingsDep) -> ClientConfig:
    return ClientConfig(features=features_for(settings), vapid_public_key=settings.vapid_public_key or None)
