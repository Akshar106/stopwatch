"""Response models for "Ask Stopwatch" (docs/contracts.md §4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskFact(BaseModel):
    label: str
    value: str
    source: str


class AskLink(BaseModel):
    label: str
    href: str


class AskResponse(BaseModel):
    answer: str | None
    fallback: bool
    reason: str | None = None
    facts: list[AskFact] = Field(default_factory=list)
    links: list[AskLink] = Field(default_factory=list)


class AskQuotaExceededError(Exception):
    """The user's daily question quota is used up (HTTP 429)."""


class AskDisabledError(Exception):
    """The feature flag is off (HTTP 503)."""
