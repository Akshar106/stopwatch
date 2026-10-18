"""Lambda entry point: deliver alert candidates (async invoke from ingest-tick; retries + DLQ on failure)."""

from __future__ import annotations

from typing import Any

from stopwatch.alerts.notify import deliver
from stopwatch.alerts.webpush import PushTarget, send_web_push
from stopwatch.platform.config import get_settings
from stopwatch.platform.db import transaction
from stopwatch.platform.observability import flush_metrics, get_logger, put_metric

log = get_logger("notify")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    if settings.vapid_private_key is None:
        log.warning("VAPID key not configured; dropping alert candidates",
                    count=len((event or {}).get("candidates", [])))
        return {"skipped": True}
    key = settings.vapid_private_key.get_secret_value()

    def send(target: PushTarget, message: dict[str, Any]) -> str:
        return send_web_push(target, message, vapid_private_key=key, subject=settings.vapid_subject)

    try:
        stats = deliver(transaction, event, send)
        put_metric("NotificationsSent", stats["sent"])
        log.info("notify", **stats)
        return stats
    finally:
        flush_metrics()
