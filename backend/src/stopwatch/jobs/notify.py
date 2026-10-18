"""Lambda entry point: deliver alert candidates (async invoke from ingest-tick; retries + DLQ on failure)."""

from __future__ import annotations

from typing import Any

from stopwatch.alerts.notify import deliver_with_settings
from stopwatch.platform.observability import flush_metrics


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        return deliver_with_settings(event or {})
    finally:
        flush_metrics()
