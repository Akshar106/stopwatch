"""Lambda entry point: one ingest tick per configured agency (EventBridge Scheduler, every minute)."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from stopwatch.ingest.tick import TickDeps, TickResult, run_tick
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.config import get_settings
from stopwatch.platform.http import fetch_bytes
from stopwatch.platform.observability import flush_metrics, get_logger, put_metric

log = get_logger("ingest")
TICK_BUDGET_S = 40.0  # Lambda timeout is 50 s; leave headroom for the state write


def _fetcher(deadline: float) -> Any:
    def fetch(url: str, max_bytes: int) -> bytes:
        return fetch_bytes(url, max_bytes=max_bytes, deadline=deadline).data

    return fetch


def _emit(result: TickResult) -> None:
    put_metric("IngestSuccess", 1 if result.outcome in ("ok", "not_advanced") else 0)
    put_metric("IngestDurationMs", result.duration_ms)
    if result.feed_age_s is not None:
        put_metric("FeedAgeSeconds", result.feed_age_s)
    if result.outcome == "ok":
        put_metric("ArrivalsEmitted", result.counts.get("arrival", 0))
        if result.low_confidence_ratio is not None:
            put_metric("LowConfidenceRatio", result.low_confidence_ratio)


def run(now_fn: Any = None) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.ingest_enabled:
        log.info("ingest disabled by flag")
        return []
    lake = open_blobstore(settings.lake_url)
    site = open_blobstore(settings.site_url)
    hook = None
    if settings.alerts_enabled:
        from stopwatch.alerts.evaluate import make_alert_hook

        hook_factory = make_alert_hook
    summaries = []
    for agency_id in settings.agency_ids:
        agency = get_agency(agency_id)
        if settings.alerts_enabled:
            hook = hook_factory(agency, lake, settings.notify_function_name)
        deps = TickDeps(lake=lake, site=site, fetch=_fetcher(time.monotonic() + TICK_BUDGET_S), on_snapshot=hook)
        if now_fn is not None:
            deps.now = now_fn
        try:
            result = run_tick(agency, deps)
        except Exception as exc:
            log.exception("tick crashed", agency=agency_id, error_type=type(exc).__name__)
            put_metric("IngestSuccess", 0)
            raise
        _emit(result)
        summary = {
            "agency": agency_id,
            "outcome": result.outcome,
            "feed_ts": result.feed_ts,
            "feed_age_s": result.feed_age_s,
            "events": result.counts,
            "low_conf_pct": result.low_confidence_ratio,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }
        (log.info if result.outcome != "failed" else log.error)("tick", **summary)
        summaries.append(summary)
    return summaries


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        return {"ticks": run()}
    finally:
        flush_metrics()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
    sys.exit(0)
