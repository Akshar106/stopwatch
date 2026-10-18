"""Ask Stopwatch service entry point. Implementation in progress; returns the guided-form fallback."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection

from .models import AskResponse


def answer_question(conn: Connection, user_id: UUID, question: str) -> AskResponse:
    """Answer ``question`` for ``user_id`` using read-only tools over published data.

    Raises AskDisabledError (503) or AskQuotaExceededError (429). Never raises for model errors: those
    return ``AskResponse(fallback=True, reason="error")``.
    """
    return AskResponse(answer=None, fallback=True, reason="disabled")
