"""Alert evaluation inside the ingest tick (should-tier, docs/contracts.md §5).

The ingest path never touches Postgres: active rules come from a small JSON snapshot the API writes to the
lake, and scheduled times come from the Parquet schedule. Only when a rule actually fires does the tick
hand candidates to the `notify` function (async invoke), which records and delivers them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from stopwatch.core.gtfs import gtfs_time_to_epoch, parse_gtfs_date
from stopwatch.core.inference import Snapshot, TripStatus
from stopwatch.ingest.state import IngestState
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.observability import get_logger

log = get_logger("alerts")
LOOKAHEAD_S = 60 * 60  # only alert about buses due within the next hour
PRE_WINDOW_S = 60 * 60  # start evaluating a rule up to an hour before its window opens


@dataclass(frozen=True)
class Rule:
    rule_id: str
    route_id: str
    direction_id: int
    stop_id: str
    days_mask: int
    window_start: str
    window_end: str
    threshold_min: int
    notify_cancellations: bool


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    kind: str  # delay | canceled
    service_date: str
    trip_id: str
    route_id: str
    stop_id: str
    scheduled_at: str
    predicted_at: str | None
    delay_s: int | None

    @property
    def dedupe_key(self) -> str:
        return f"{self.rule_id}:{self.service_date}:{self.trip_id}:{self.kind}"


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def rule_is_live(rule: Rule, now: int, tz: str) -> bool:
    local = datetime.fromtimestamp(now, ZoneInfo(tz))
    if not rule.days_mask & (1 << local.weekday()):
        return False
    start = datetime.combine(local.date(), _hhmm(rule.window_start), tzinfo=ZoneInfo(tz))
    end = datetime.combine(local.date(), _hhmm(rule.window_end), tzinfo=ZoneInfo(tz))
    return start.timestamp() - PRE_WINDOW_S <= now <= end.timestamp()


def find_candidates(rules: Iterable[Rule], snapshot: Snapshot, scheduled: Mapping[tuple[str, str], int],
                    now: int, tz: str) -> list[Candidate]:
    """Pure: which (rule, trip) pairs should alert right now.

    ``scheduled`` maps (trip_id, stop_id) to GTFS seconds for trips running today.
    """
    out: list[Candidate] = []
    for rule in rules:
        local_day = datetime.fromtimestamp(now, ZoneInfo(tz)).date()
        w_start = datetime.combine(local_day, _hhmm(rule.window_start), tzinfo=ZoneInfo(tz)).timestamp()
        w_end = datetime.combine(local_day, _hhmm(rule.window_end), tzinfo=ZoneInfo(tz)).timestamp()
        for key in sorted(snapshot.trips):
            trip = snapshot.trips[key]
            if trip.route_id != rule.route_id or trip.direction_id != rule.direction_id:
                continue
            secs = scheduled.get((key.trip_id, rule.stop_id))
            if secs is None:
                continue
            service_date: date = parse_gtfs_date(key.start_date)
            sched = gtfs_time_to_epoch(service_date, secs, tz)
            if not (w_start <= sched <= w_end) or sched < now - 300 or sched > now + LOOKAHEAD_S:
                continue
            base = {"rule_id": rule.rule_id, "service_date": service_date.isoformat(), "trip_id": key.trip_id,
                    "route_id": trip.route_id, "stop_id": rule.stop_id, "scheduled_at": _iso(sched)}
            if trip.status is TripStatus.CANCELED:
                if rule.notify_cancellations:
                    out.append(Candidate(kind="canceled", predicted_at=None, delay_s=None, **base))
                continue
            pred = next((s for s in trip.stops.values() if s.stop_id == rule.stop_id and not s.skipped), None)
            if pred is None or pred.time is None or pred.time < now:
                continue
            delay = pred.time - sched
            if delay >= rule.threshold_min * 60:
                out.append(Candidate(kind="delay", predicted_at=_iso(pred.time), delay_s=delay, **base))
    return out


def load_rules(lake: BlobStore, agency_id: str) -> list[Rule]:
    blob = lake.get(f"config/alert_rules/{agency_id}.json")
    if blob is None:
        return []
    doc = json.loads(blob.data)
    return [Rule(**{k: r[k] for k in Rule.__dataclass_fields__}) for r in doc.get("rules", [])]


class ScheduleLookup:
    """(trip_id, stop_id) -> GTFS seconds for the stops that have rules; cached per warm container."""

    def __init__(self, lake: BlobStore, agency: AgencyConfig, workdir: Path) -> None:
        self.lake, self.agency, self.workdir = lake, agency, workdir
        self._cache: dict[tuple[str, frozenset[str]], dict[tuple[str, str], int]] = {}

    def for_stops(self, stop_ids: Iterable[str], service_date: date) -> dict[tuple[str, str], int]:
        from stopwatch.catalog.schedule import ScheduleCatalog
        from stopwatch.platform.duck import connect

        catalog = ScheduleCatalog(self.lake, self.agency.id)
        version = catalog.version_for(service_date)
        key = (version, frozenset(stop_ids))
        if key not in self._cache:
            path = catalog.table_path(version, "stop_times", self.workdir).as_posix()
            con = connect(self.workdir / "duck-alerts")
            rows = con.execute(f"SELECT trip_id, stop_id, arrival_s FROM '{path}' WHERE stop_id IN "
                               f"(SELECT unnest(?))", [sorted(key[1])]).fetchall()
            con.close()
            self._cache = {key: {(t, s): int(a) for t, s, a in rows if a is not None}}
        return self._cache[key]


Invoker = Callable[[dict[str, Any]], None]


def _default_invoker(function_name: str | None) -> Invoker:
    if function_name:
        import boto3

        client = boto3.client("lambda")

        def invoke(payload: dict[str, Any]) -> None:
            client.invoke(FunctionName=f"{function_name}:live", InvocationType="Event",
                          Payload=json.dumps(payload).encode())

        return invoke

    def local(payload: dict[str, Any]) -> None:  # local dev: deliver in-process
        from stopwatch.jobs.notify import handler

        handler(payload, None)

    return local


class _Lookup(Protocol):
    def for_stops(self, stop_ids: Iterable[str], service_date: date) -> Mapping[tuple[str, str], int]: ...


def make_alert_hook(agency: AgencyConfig, lake: BlobStore, notify_function_name: str | None,
                    invoker: Invoker | None = None, workdir: Path = Path("/tmp/stopwatch-alerts"),  # noqa: S108
                    lookup: _Lookup | None = None) -> Callable[[Snapshot, IngestState, int], None]:
    lookup = lookup or ScheduleLookup(lake, agency, workdir)
    send = invoker or _default_invoker(notify_function_name)

    def hook(cur: Snapshot, state: IngestState, now: int) -> None:
        try:
            rules = [r for r in load_rules(lake, agency.id) if rule_is_live(r, now, agency.timezone)]
            if not rules:
                return
            today = datetime.fromtimestamp(now, ZoneInfo(agency.timezone)).date()
            scheduled = lookup.for_stops({r.stop_id for r in rules}, today)
            fresh = [c for c in find_candidates(rules, cur, scheduled, now, agency.timezone)
                     if c.dedupe_key not in state.alerts_sent]
            if fresh:
                send({"agency_id": agency.id, "candidates": [asdict(c) for c in fresh]})
                state.alerts_sent.extend(c.dedupe_key for c in fresh)
                log.info("alert candidates sent", count=len(fresh))
            prefix = {f":{today.isoformat()}:"}
            state.alerts_sent = [k for k in state.alerts_sent if any(p in k for p in prefix)][-5000:]
        except Exception as exc:  # noqa: BLE001 - alerts must never break ingestion
            log.warning("alert evaluation failed", error_type=type(exc).__name__)

    return hook
