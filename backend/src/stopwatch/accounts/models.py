"""Account data shapes: internal records (dataclasses) and the public JSON models (docs/contracts.md §4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


@dataclass(frozen=True)
class User:
    id: UUID
    email: str | None
    display_name: str | None
    is_demo: bool
    demo_expires_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> User:
        return cls(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            is_demo=bool(row["is_demo"]),
            demo_expires_at=as_utc(row["demo_expires_at"]) if row["demo_expires_at"] else None,
            created_at=as_utc(row["created_at"]),
        )


@dataclass(frozen=True)
class ClientInfo:
    """What we keep about the device behind a session: an IP prefix (never the full address) and UA."""

    ip_prefix: str | None
    user_agent: str | None


@dataclass(frozen=True)
class GoogleIdentity:
    """Verified claims from a Google ID token. ``email`` is None unless Google marked it verified."""

    issuer: str
    subject: str
    email: str | None
    display_name: str | None


class UserOut(BaseModel):
    id: str
    display_name: str | None
    email: str | None
    is_demo: bool
    demo_expires_at: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        return cls(
            id=str(user.id),
            display_name=user.display_name,
            email=user.email,
            is_demo=user.is_demo,
            demo_expires_at=user.demo_expires_at,
            created_at=user.created_at,
        )


class MeFeatures(BaseModel):
    alerts: bool
    ask: bool
    google_login: bool


class MeResponse(BaseModel):
    user: UserOut
    csrf_token: str
    features: MeFeatures
