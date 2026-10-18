"""Ask Stopwatch: plain-English questions answered from published reliability data via tool use.

Design (docs/05 §6):
  * read-only tools over published JSON (tools.py), schema-validated (`strict: true`);
  * a manual tool loop so the iteration count and the monthly spend cap are checked between every turn;
  * a grounding check (grounding.py) — answers citing numbers we never computed fall back to the facts;
  * per-user daily quota and a global monthly dollar cap tracked in `ask_usage`;
  * any API error or refusal degrades to the guided-form fallback, never a 500.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from stopwatch.platform import dbschema as t
from stopwatch.platform.blobstore import BlobStore, open_blobstore
from stopwatch.platform.config import Settings, get_settings
from stopwatch.platform.observability import get_logger, put_metric

from .grounding import compact, ungrounded_numbers
from .models import AskDisabledError, AskFact, AskLink, AskQuotaExceededError, AskResponse
from .tools import TOOL_DEFINITIONS, PublishedData, run_tool

log = get_logger("ask")

DAILY_QUESTIONS_PER_USER = 20
MAX_TURNS = 4
MAX_TOKENS = 4000  # thinking + a short answer; questions are small
QUESTION_MAX_CHARS = 300

# USD per million tokens (input, output, cache read). From Anthropic's published prices (cached 2026-10-06).
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}
UNKNOWN_MODEL_PRICE = (10.00, 50.00, 1.00)  # conservative: never under-count spend
# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}

SYSTEM_PROMPT = """You answer riders' questions about how reliable public transit routes and stops have been,
using only the tools provided. They return statistics computed from real-time feed observations.

Rules:
- Always call tools to get numbers; never estimate or recall statistics yourself.
- Use find_stop to turn stop or street names into stop ids before calling stop_reliability.
- Quote numbers exactly as the tools return them (minutes and percentages). Do not convert or compute new ones.
- If a tool says there is not enough data, say so plainly.
- These are independent, unofficial estimates; do not give safety advice or predictions about the future.
- If the question is not about transit reliability for this agency, say you can only answer reliability
  questions and suggest an example.
- Answer in at most 4 short sentences."""


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def cost_microusd(self) -> int:
        p_in, p_out, p_cache = PRICES.get(self.model, UNKNOWN_MODEL_PRICE)
        dollars = (self.input_tokens * p_in + self.output_tokens * p_out + self.cache_read_tokens * p_cache) / 1e6
        return int(dollars * 1_000_000) + 1  # round up


def _month_spend_microusd(conn: Connection, today: date) -> int:
    start = today.replace(day=1)
    return int(conn.execute(select(func.coalesce(func.sum(t.ask_usage.c.cost_microusd), 0))
                            .where(t.ask_usage.c.day >= start)).scalar_one())


def _today_requests(conn: Connection, user_id: UUID, today: date) -> int:
    return int(conn.execute(select(func.coalesce(t.ask_usage.c.requests, 0)).where(
        t.ask_usage.c.user_id == user_id, t.ask_usage.c.day == today)).scalar_one_or_none() or 0)


def _record_usage(conn: Connection, user_id: UUID, today: date, cost: int) -> None:
    stmt = pg_insert(t.ask_usage).values(user_id=user_id, day=today, requests=1, cost_microusd=cost)
    conn.execute(stmt.on_conflict_do_update(
        index_elements=["user_id", "day"],
        set_={"requests": t.ask_usage.c.requests + 1, "cost_microusd": t.ask_usage.c.cost_microusd + cost}))


def _facts_from(results: list[dict[str, Any]]) -> tuple[list[AskFact], list[AskLink]]:
    facts: list[AskFact] = []
    links: list[AskLink] = []
    labels = {"on_time_pct": "On time (%)", "typical_delay_min": "Typical delay (min)",
              "worst_case_delay_min": "Worst-case delay, 90th pct (min)", "observations": "Observations",
              "excess_wait_min": "Excess wait (min)", "coverage_pct": "Data coverage (%)",
              "canceled_trips": "Canceled trips"}
    for r in results:
        source = r.get("route_id") and f"route {r['route_id']}" or "published data"
        rows = r.get("directions") or [r]
        for row in rows:
            prefix = f"{row.get('headsign')}: " if row.get("headsign") else ""
            for key, label in labels.items():
                if row.get(key) is not None:
                    facts.append(AskFact(label=prefix + label, value=str(row[key]), source=source))
        if r.get("link"):
            links.append(AskLink(label=f"Open {source}", href=r["link"]))
    return facts[:20], links[:5]


Client = Any  # anthropic.Anthropic (kept untyped so tests can pass a fake)


def ask_with_client(client: Client, model: str, question: str, data: PublishedData,
                    spend_left_microusd: int) -> tuple[AskResponse, Usage]:
    """Run the tool loop. Pure with respect to the database (callers handle quotas and accounting)."""
    import anthropic

    usage = Usage(model=model)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    results: list[dict[str, Any]] = []
    extra: dict[str, Any] = {}
    if model in FALLBACK_MODELS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        for _turn in range(MAX_TURNS):
            response = client.beta.messages.create(
                model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, tools=TOOL_DEFINITIONS,
                tool_choice={"type": "auto"}, output_config={"effort": "low"}, messages=messages, **extra)
            usage.model = getattr(response, "model", model) or model
            u = response.usage
            usage.input_tokens += int(getattr(u, "input_tokens", 0) or 0)
            usage.output_tokens += int(getattr(u, "output_tokens", 0) or 0)
            usage.cache_read_tokens += int(getattr(u, "cache_read_input_tokens", 0) or 0)
            if response.stop_reason == "refusal":
                facts, links = _facts_from(results)
                return AskResponse(answer=None, fallback=True, reason="refused", facts=facts, links=links), usage
            if response.stop_reason != "tool_use":
                text = " ".join(b.text for b in response.content if b.type == "text").strip()
                facts, links = _facts_from(results)
                bad = ungrounded_numbers(text, results, question)
                if not text or bad:
                    if bad:
                        log.warning("ungrounded answer suppressed", numbers=bad[:5])
                    return AskResponse(answer=None, fallback=True, reason="ungrounded", facts=facts,
                                       links=links), usage
                return AskResponse(answer=text, fallback=False, facts=facts, links=links), usage
            if usage.cost_microusd() >= spend_left_microusd:
                facts, links = _facts_from(results)
                return AskResponse(answer=None, fallback=True, reason="cap_reached", facts=facts,
                                   links=links), usage
            # Append the full assistant content (append-only history keeps thinking blocks valid).
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = run_tool(data, block.name, dict(block.input))
                    is_error = "error" in out
                except (LookupError, KeyError, ValueError, TypeError) as exc:
                    out, is_error = {"error": f"{type(exc).__name__}: {exc}"}, True
                results.append(out)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": compact(out),
                                     "is_error": is_error})
            messages.append({"role": "user", "content": tool_results})
        facts, links = _facts_from(results)
        return AskResponse(answer=None, fallback=True, reason="ungrounded", facts=facts, links=links), usage
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("ask model call failed", error_type=type(exc).__name__)
        facts, links = _facts_from(results)
        return AskResponse(answer=None, fallback=True, reason="error", facts=facts, links=links), usage


def answer_question(conn: Connection, user_id: UUID, question: str, *, settings: Settings | None = None,
                    client_factory: Callable[[str], Client] | None = None,
                    site: BlobStore | None = None) -> AskResponse:
    """Answer ``question`` for ``user_id``.

    Raises AskDisabledError (503) or AskQuotaExceededError (429). Model errors never raise: they return
    ``AskResponse(fallback=True, reason="error")``.
    """
    s = settings or get_settings()
    if not s.ask_enabled:
        raise AskDisabledError("ask is disabled")
    question = question.strip()[:QUESTION_MAX_CHARS]
    today = datetime.now(UTC).date()
    if _today_requests(conn, user_id, today) >= DAILY_QUESTIONS_PER_USER:
        raise AskQuotaExceededError(f"daily limit of {DAILY_QUESTIONS_PER_USER} questions reached")
    if s.anthropic_api_key is None:
        return AskResponse(answer=None, fallback=True, reason="disabled")
    cap = int(s.ask_monthly_cap_usd * 1_000_000)
    left = cap - _month_spend_microusd(conn, today)
    if left <= 0:
        _record_usage(conn, user_id, today, 0)
        return AskResponse(answer=None, fallback=True, reason="cap_reached")

    if client_factory is None:
        import anthropic

        def client_factory(key: str) -> Client:
            return anthropic.Anthropic(api_key=key, max_retries=1, timeout=20.0)

    data = PublishedData(site or open_blobstore(s.site_url), agency_id=s.agency_ids[0])
    response, usage = ask_with_client(client_factory(s.anthropic_api_key.get_secret_value()), s.ask_model,
                                      question, data, left)
    cost = usage.cost_microusd() if usage.input_tokens or usage.output_tokens else 0
    _record_usage(conn, user_id, today, cost)
    put_metric("AskCostMicroUSD", cost)
    if _month_spend_microusd(conn, today) >= cap:
        log.warning("ask monthly cap reached; feature now serves the guided form until next month")
    return response
