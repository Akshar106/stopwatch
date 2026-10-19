"""Ask Stopwatch with a fake model client (no API calls, no cost) over really published fixture data."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, insert, text

from stopwatch.ask import service
from stopwatch.ask.grounding import ungrounded_numbers
from stopwatch.ask.models import AskDisabledError, AskQuotaExceededError
from stopwatch.ask.tools import PublishedData, find_stop, run_tool, stop_reliability
from stopwatch.catalog.schedule import ScheduleCatalog
from stopwatch.ingest.replay import replay_into_lake
from stopwatch.platform import dbschema as t
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.config import Settings
from stopwatch.rollups import publish as pub
from stopwatch.rollups.compact import compact_day
from stopwatch.rollups.compute import compute_agency
from tests.pipeline_helpers import SAMPLE_DATE, SAMPLE_RT, make_lake


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("ask")
    lake, site = make_lake(root)
    mbta = get_agency("mbta")
    replay_into_lake(SAMPLE_RT, mbta, lake, site)
    catalog = ScheduleCatalog(lake, "mbta")
    d = date.fromisoformat(SAMPLE_DATE)
    compact_day(mbta, lake, catalog, d, root / "c")
    build = compute_agency(mbta, lake, catalog, d, root / "k")
    pub.publish(site, "B1", build.files, pub.build_manifest("B1", "x", [build.manifest]))
    return site


# ---- fake Groq (OpenAI-compatible chat completions) client ---------------------------------------------------


@dataclass
class Fn:
    name: str
    arguments: str


@dataclass
class Call:
    id: str
    function: Fn
    type: str = "function"


@dataclass
class Msg:
    content: str | None = None
    tool_calls: list[Call] | None = None


@dataclass
class Choice:
    message: Msg
    finish_reason: str = "stop"


@dataclass
class U:
    prompt_tokens: int = 1000
    completion_tokens: int = 200


@dataclass
class Resp:
    choices: list[Choice]
    model: str = "openai/gpt-oss-120b"
    usage: U = field(default_factory=U)


def tool_call(name: str, args: dict[str, Any] | str, call_id: str = "call_1") -> Resp:
    raw = args if isinstance(args, str) else json.dumps(args)
    return Resp([Choice(Msg(tool_calls=[Call(call_id, Fn(name, raw))]), "tool_calls")])


def answer(text: str, finish_reason: str = "stop") -> Resp:
    return Resp([Choice(Msg(content=text), finish_reason)])


class FakeClient:
    def __init__(self, script: list[Resp | Exception]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs: Any) -> Resp:
        self.calls.append(kwargs)
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def busiest_stop(site) -> tuple[str, str, dict]:  # type: ignore[no-untyped-def]
    data = PublishedData(site)
    out = stop_reliability(data, *_pick(data), day="sun", hour_from=0, hour_to=23)
    return out["stop_id"], out["route_id"], out


def _pick(data: PublishedData) -> tuple[str, str]:
    detail = data.route("1")
    stop = max(detail["directions"][0]["stops"], key=lambda s: s["summary"]["n"])
    return stop["stop_id"], "1"


def test_tools_return_published_numbers(site) -> None:  # type: ignore[no-untyped-def]
    data = PublishedData(site)
    assert find_stop(data, "harvard")["matches"]
    _, _, out = busiest_stop(site)
    assert out["directions"][0]["observations"] > 0
    assert run_tool(data, "route_summary", {"route_id": "1"})["route_id"] == "1"
    assert "error" in run_tool(data, "route_summary", {"route_id": "nope"})
    assert "error" in run_tool(
        data, "stop_reliability", {"stop_id": "zzz", "route_id": "1", "day": "any", "hour_from": 0, "hour_to": 23}
    )


def test_tool_loop_returns_grounded_answer(site) -> None:  # type: ignore[no-untyped-def]
    stop_id, _, out = busiest_stop(site)
    n = out["directions"][0]["observations"]
    client = FakeClient(
        [
            tool_call(
                "stop_reliability",
                {"stop_id": stop_id, "route_id": "1", "day": "sun", "hour_from": 0, "hour_to": 23},
            ),
            answer(f"Route 1 was observed {n} times at that stop on Sundays."),
        ]
    )
    resp, usage = service.ask_with_client(
        client, "openai/gpt-oss-120b", "How reliable is the 1 on Sundays?", PublishedData(site), 10**9
    )
    assert resp.fallback is False and str(n) in (resp.answer or "")
    assert any(f.label.endswith("Observations") for f in resp.facts)
    assert resp.links and resp.links[0].href.startswith("/s/mbta/")
    assert usage.input_tokens == 2000 and usage.output_tokens == 400
    first = client.calls[0]
    assert first["tool_choice"] == "auto" and first["reasoning_effort"] == "low"
    assert {t["function"]["name"] for t in first["tools"]} == {"find_stop", "route_summary", "stop_reliability"}
    assert all(t["type"] == "function" for t in first["tools"])
    # Second request: system + user + the assistant's tool call + the tool result, in order.
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["id"] == second[3]["tool_call_id"] == "call_1"


def test_hallucinated_numbers_fall_back_to_facts(site) -> None:  # type: ignore[no-untyped-def]
    client = FakeClient(
        [tool_call("route_summary", {"route_id": "1"}), answer("Route 1 is on time 97.3% of the time.")]
    )
    resp, _ = service.ask_with_client(client, "openai/gpt-oss-120b", "Is the 1 reliable?", PublishedData(site), 10**9)
    assert resp.fallback and resp.reason == "ungrounded" and resp.answer is None


def test_malformed_tool_arguments_become_tool_errors(site) -> None:  # type: ignore[no-untyped-def]
    client = FakeClient([tool_call("route_summary", "{not json"), answer("I can only answer reliability questions.")])
    resp, _ = service.ask_with_client(client, "openai/gpt-oss-120b", "q", PublishedData(site), 10**9)
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "error" in tool_msg["content"]
    assert resp.fallback is False


def test_truncated_answer_and_api_errors_degrade_gracefully(site) -> None:  # type: ignore[no-untyped-def]
    import groq

    resp, _ = service.ask_with_client(
        FakeClient([answer("Route 1 is", finish_reason="length")]),
        "openai/gpt-oss-120b",
        "q",
        PublishedData(site),
        10**9,
    )
    assert resp.fallback and resp.reason == "ungrounded"
    err = groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    resp, _ = service.ask_with_client(FakeClient([err]), "openai/gpt-oss-120b", "q", PublishedData(site), 10**9)
    assert resp.fallback and resp.reason == "error"


def test_spend_cap_stops_the_loop(site) -> None:  # type: ignore[no-untyped-def]
    client = FakeClient([tool_call("route_summary", {"route_id": "1"})])
    resp, usage = service.ask_with_client(
        client, "openai/gpt-oss-120b", "q", PublishedData(site), spend_left_microusd=10
    )
    assert resp.reason == "cap_reached" and len(client.calls) == 1 and usage.cost_microusd() > 10


def test_non_gpt_oss_models_get_no_reasoning_effort(site) -> None:  # type: ignore[no-untyped-def]
    client = FakeClient([answer("I can only answer reliability questions.")])
    service.ask_with_client(client, "llama-3.3-70b-versatile", "hello", PublishedData(site), 10**9)
    assert "reasoning_effort" not in client.calls[0]


def test_cost_accounting_uses_model_prices() -> None:
    u = service.Usage(model="openai/gpt-oss-120b", input_tokens=1_000_000, output_tokens=1_000_000)
    assert u.cost_microusd() == 750_001  # $0.15 + $0.60, rounded up
    assert service.Usage(model="mystery", input_tokens=1_000_000).cost_microusd() == 1_000_001


def test_grounding_rules() -> None:
    results = [{"on_time_pct": 61.2, "typical_delay_min": 3.5, "directions": [{"observations": 74}]}]
    assert ungrounded_numbers("On time 61.2% (about 61%), typically 3.5 min late, 74 trips.", results, "") == []
    assert ungrounded_numbers("Usually 9 minutes late.", results, "") == [9.0]
    assert ungrounded_numbers("At 8 am it is 61.2% on time.", results, "What about 8 am?") == []


# ---- quotas and caps against the real database -------------------------------------------------------------

pytestmark_db = pytest.mark.integration


@pytest.fixture
def user_id(app_engine: Engine) -> uuid.UUID:
    uid = uuid.uuid4()
    with app_engine.begin() as conn:
        conn.execute(
            insert(t.users).values(
                id=uid, email=f"{uid}@example.com", oidc_issuer="https://accounts.google.com", oidc_subject=str(uid)
            )
        )
    return uid


def _settings(tmp_path: Path, **kw: Any) -> Settings:
    base = {
        "STOPWATCH_ENV": "test",
        "ASK_ENABLED": True,
        "GROQ_API_KEY": "gsk-test",
        "SITE_URL": f"file://{tmp_path}",
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.integration
def test_quota_cap_and_disabled(app_engine: Engine, user_id: uuid.UUID, site, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ok = FakeClient([answer("I can only answer reliability questions.")] * 30)
    with app_engine.begin() as conn:
        with pytest.raises(AskDisabledError):
            service.answer_question(conn, user_id, "q", settings=_settings(tmp_path, ASK_ENABLED=False))
        no_key = _settings(tmp_path, GROQ_API_KEY=None)
        assert service.answer_question(conn, user_id, "q", settings=no_key).reason == "disabled"
        s = _settings(tmp_path)
        r = service.answer_question(conn, user_id, "hello", settings=s, client_factory=lambda k: ok, site=site)
        assert r.fallback is False
        cost = conn.execute(text("select cost_microusd from ask_usage where user_id = :u"), {"u": user_id}).scalar()
        assert cost > 0
        conn.execute(text("update ask_usage set requests = 20 where user_id = :u"), {"u": user_id})
        with pytest.raises(AskQuotaExceededError):
            service.answer_question(conn, user_id, "q", settings=s, client_factory=lambda k: ok, site=site)
        conn.execute(
            text("update ask_usage set requests = 1, cost_microusd = 5000000 where user_id = :u"), {"u": user_id}
        )
        r = service.answer_question(conn, user_id, "q", settings=s, client_factory=lambda k: ok, site=site)
        assert r.fallback and r.reason == "cap_reached"
