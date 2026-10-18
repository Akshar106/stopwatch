"""Ask Stopwatch: plain-English questions answered from published data (docs/05 §6).

The question text is never logged or stored here; quota and $-cap enforcement live in the ask service.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints

from stopwatch.ask.models import AskResponse
from stopwatch.ask.service import answer_question
from stopwatch.platform.db import transaction

from .. import ratelimits
from ..deps import EngineDep, FullAccount, limit_per_user, require_full_account

router = APIRouter(tags=["ask"])
MAX_QUESTION_LENGTH = 300


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH)]


@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(require_full_account), Depends(limit_per_user(ratelimits.ASK))],
)
def ask(body: AskRequest, auth: FullAccount, engine: EngineDep) -> AskResponse:
    with transaction(engine) as conn:
        return answer_question(conn, auth.user.id, body.question)
