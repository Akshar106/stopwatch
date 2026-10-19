"""Read-only tools for "Ask Stopwatch". They read *published* JSON only: no SQL, no user data, no writes.

Every numeric result is returned both in seconds and in minutes (rounded) so the model can quote numbers
verbatim; the grounding check (grounding.py) then verifies the answer only uses numbers that appear here.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from stopwatch.core.metrics import percentile_from_histogram
from stopwatch.platform.blobstore import BlobStore

DAYS = {"wkd": "weekdays", "sat": "Saturdays", "sun": "Sundays", "any": "all days"}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_stop",
        "description": "Search transit stops by name. Returns up to 5 matches with their ids and the routes that "
        "serve them. Use this first whenever the user names a stop or street.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Stop or street name, e.g. 'Harvard'"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "route_summary",
        "description": "Route-level reliability over the published window: on-time %, typical (median) and "
        "worst-case (90th percentile) delay, data coverage, and the weekly trend.",
        "parameters": {
            "type": "object",
            "properties": {"route_id": {"type": "string", "description": "Route id, e.g. '1', 'Red', 'Green-B'"}},
            "required": ["route_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stop_reliability",
        "description": "Reliability of one route at one stop for a day type and an hour range (local time, 0-23, "
        "inclusive). Returns sample size, on-time %, typical and worst-case delay, cancellations "
        "and excess wait time when the route is frequent.",
        "parameters": {
            "type": "object",
            "properties": {
                "stop_id": {"type": "string"},
                "route_id": {"type": "string"},
                "day": {"type": "string", "enum": ["wkd", "sat", "sun", "any"]},
                "hour_from": {"type": "integer", "minimum": 0, "maximum": 23},
                "hour_to": {"type": "integer", "minimum": 0, "maximum": 23},
            },
            "required": ["stop_id", "route_id", "day", "hour_from", "hour_to"],
            "additionalProperties": False,
        },
    },
]

# Chat-completions (OpenAI-compatible) tool format, as Groq expects.
TOOL_DEFINITIONS: list[dict[str, Any]] = [{"type": "function", "function": tool} for tool in _TOOLS]


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def _mins(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


@dataclass
class PublishedData:
    """Lazily loaded published documents for one build (cached per warm container)."""

    site: BlobStore
    agency_id: str = "mbta"
    _manifest: dict[str, Any] | None = None
    _docs: dict[str, Any] = field(default_factory=dict)

    def _get(self, path: str) -> Any:
        if path not in self._docs:
            blob = self.site.get(path.lstrip("/"))
            if blob is None:
                raise LookupError(path)
            self._docs[path] = json.loads(blob.data)
        return self._docs[path]

    @property
    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            blob = self.site.get("data/v1/manifest.json")
            if blob is None:
                raise LookupError("no published build yet")
            self._manifest = json.loads(blob.data)
        return self._manifest

    def agency(self) -> dict[str, Any]:
        for a in self.manifest["agencies"]:
            if a["id"] == self.agency_id:
                return dict(a)
        raise LookupError(self.agency_id)

    def stops(self) -> list[dict[str, Any]]:
        return list(self._get(self.agency()["paths"]["stops"])["stops"])

    def routes(self) -> list[dict[str, Any]]:
        return list(self._get(self.agency()["paths"]["routes"])["routes"])

    def route(self, route_id: str) -> dict[str, Any]:
        path = self.agency()["paths"]["route_template"].replace("{route_id}", route_id)
        return dict(self._get(path))


def find_stop(data: PublishedData, query: str) -> dict[str, Any]:
    q = _fold(query.strip())
    if not q:
        return {"matches": []}
    scored = []
    for s in data.stops():
        name = _fold(s["name"])
        if name.startswith(q):
            score = 0
        elif any(w.startswith(q) for w in name.split()):
            score = 1
        elif q in name:
            score = 2
        else:
            continue
        scored.append((score, len(name), s))
    scored.sort(key=lambda x: (x[0], x[1], x[2]["id"]))
    return {"matches": [{"stop_id": s["id"], "name": s["name"], "routes": s["routes"][:12]} for _, _, s in scored[:5]]}


def route_summary(data: PublishedData, route_id: str) -> dict[str, Any]:
    try:
        detail = data.route(route_id)
    except LookupError:
        known = [r["id"] for r in data.routes()][:40]
        return {"error": f"unknown route {route_id!r}", "some_known_routes": known}
    summary: dict[str, Any] = next((r["summary"] for r in data.routes() if r["id"] == route_id), {})
    return {
        "route_id": route_id,
        "name": detail["route"].get("long_name") or detail["route"].get("short_name"),
        "window": detail["window"],
        "observations": summary.get("n"),
        "on_time_pct": summary.get("on_time_pct"),
        "typical_delay_min": _mins(summary.get("p50_s")),
        "worst_case_delay_min": _mins(summary.get("p90_s")),
        "coverage_pct": detail["coverage"].get("coverage_pct"),
        "weekly_trend": [
            {"week_start": t["week_start"], "on_time_pct": t["on_time_pct"], "worst_case_delay_min": _mins(t["p90_s"])}
            for t in detail["trend"][-8:]
        ],
        "on_time_definition_min": [x / 60 for x in detail["on_time_definition_s"]],
        "link": f"/r/{data.agency_id}/{route_id}",
    }


def stop_reliability(
    data: PublishedData, stop_id: str, route_id: str, day: str, hour_from: int, hour_to: int
) -> dict[str, Any]:
    try:
        detail = data.route(route_id)
    except LookupError:
        return {"error": f"unknown route {route_id!r}"}
    lo, hi = sorted((max(0, min(23, hour_from)), max(0, min(23, hour_to))))
    edges = detail["histogram_edges_s"]
    min_n = detail.get("min_samples", 8)
    result: dict[str, Any] = {
        "stop_id": stop_id,
        "route_id": route_id,
        "day": DAYS.get(day, day),
        "hours": f"{lo}:00-{hi}:59",
        "directions": [],
    }
    for d in detail["directions"]:
        stop = next((s for s in d["stops"] if s["stop_id"] == stop_id), None)
        if stop is None:
            continue
        cells = [c for c in stop["cells"] if (day == "any" or c["day"] == day) and lo <= c["hour"] <= hi]
        n = sum(c["n"] for c in cells)
        hist = [sum(c["hist"][i] for c in cells) for i in range(len(edges) + 1)] if cells else []
        weighted = [(c["on_time_pct"], c["n"]) for c in cells if c["on_time_pct"] is not None]
        on_time = (
            round(sum(p * w for p, w in weighted) / sum(w for _, w in weighted), 1) if weighted and n >= min_n else None
        )
        ewt = [c["ewt_s"] for c in cells if c["ewt_s"] is not None]
        result["directions"].append(
            {
                "direction_id": d["direction_id"],
                "headsign": d.get("headsign"),
                "stop_name": stop["name"],
                "observations": n,
                "enough_data": n >= min_n,
                "on_time_pct": on_time,
                "typical_delay_min": _mins(percentile_from_histogram(hist, edges, 0.5)) if n >= min_n else None,
                "worst_case_delay_min": _mins(percentile_from_histogram(hist, edges, 0.9)) if n >= min_n else None,
                "canceled_trips": sum(c["canceled"] for c in cells),
                "excess_wait_min": _mins(sum(ewt) / len(ewt)) if ewt else None,
            }
        )
    if not result["directions"]:
        return {"error": f"route {route_id} does not serve stop {stop_id}"}
    result["link"] = f"/s/{data.agency_id}/{stop_id}"
    result["note"] = "Delays are approximate (from histogram buckets); on time means -1 to +5 minutes."
    return result


def run_tool(data: PublishedData, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "find_stop":
        return find_stop(data, str(args["query"]))
    if name == "route_summary":
        return route_summary(data, str(args["route_id"]))
    if name == "stop_reliability":
        return stop_reliability(
            data,
            str(args["stop_id"]),
            str(args["route_id"]),
            str(args["day"]),
            int(args["hour_from"]),
            int(args["hour_to"]),
        )
    return {"error": f"unknown tool {name!r}"}
