"""Structured logging, metrics and tracing.

In Lambda this uses Powertools (JSON logs, CloudWatch EMF metrics, X-Ray). Locally it falls back to plain
structured logging so development output stays readable. Custom metrics are deliberately limited to the
ten listed in docs/06 §8 to stay inside CloudWatch's free tier.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

IN_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
NAMESPACE = "Stopwatch"

ALLOWED_METRICS: dict[str, MetricUnit] = {
    "IngestSuccess": MetricUnit.Count,
    "IngestDurationMs": MetricUnit.Milliseconds,
    "FeedAgeSeconds": MetricUnit.Seconds,
    "ArrivalsEmitted": MetricUnit.Count,
    "LowConfidenceRatio": MetricUnit.Percent,
    "RollupSuccess": MetricUnit.Count,
    "RollupCoveragePct": MetricUnit.Percent,
    "AuthFailures": MetricUnit.Count,
    "NotificationsSent": MetricUnit.Count,
    "AskCostMicroUSD": MetricUnit.Count,
}

# Keys that must never reach logs (privacy: emails, commute labels, tokens, secrets).
_SCRUB_KEYS = re.compile(r"(email|label|token|secret|password|cookie|authorization|p256dh|auth_secret|endpoint)",
                         re.IGNORECASE)


def scrub(value: Any) -> Any:
    """Recursively redact sensitive keys from a log payload."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if _SCRUB_KEYS.search(str(k)) else scrub(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value


class _ScrubbingLogger:
    """Thin wrapper so every structured field goes through ``scrub`` regardless of backend."""

    def __init__(self, service: str) -> None:
        self._pt = Logger(service=service, level=os.environ.get("LOG_LEVEL", "INFO")) if IN_LAMBDA else None
        self._std = logging.getLogger(f"stopwatch.{service}")
        if not IN_LAMBDA and not logging.getLogger().handlers:
            logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                                format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @property
    def powertools(self) -> Logger | None:
        return self._pt

    def _log(self, level: str, msg: str, **fields: Any) -> None:
        clean = scrub(fields)
        if self._pt is not None:
            getattr(self._pt, level)(msg, extra=clean)
        else:
            suffix = " ".join(f"{k}={v}" for k, v in clean.items())
            getattr(self._std, level)(f"{msg} {suffix}".rstrip())

    def debug(self, msg: str, **fields: Any) -> None:
        self._log("debug", msg, **fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._log("info", msg, **fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._log("warning", msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._log("error", msg, **fields)

    def exception(self, msg: str, **fields: Any) -> None:
        clean = scrub(fields)
        if self._pt is not None:
            self._pt.exception(msg, extra=clean)
        else:
            self._std.exception(f"{msg} " + " ".join(f"{k}={v}" for k, v in clean.items()))


def get_logger(service: str) -> _ScrubbingLogger:
    return _ScrubbingLogger(service)


_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics  # noqa: PLW0603 - one Metrics object per process, as Powertools expects
    if _metrics is None:
        _metrics = Metrics(namespace=NAMESPACE, service="stopwatch")
        _metrics.set_default_dimensions(env=os.environ.get("STOPWATCH_ENV", "local"))
    return _metrics


def put_metric(name: str, value: float) -> None:
    """Record one of the allowed custom metrics. Unknown names fail loudly (cost guardrail)."""
    if name not in ALLOWED_METRICS:
        raise ValueError(f"metric {name!r} is not in the allowed list (CloudWatch free tier = 10 metrics)")
    if IN_LAMBDA:
        get_metrics().add_metric(name=name, unit=ALLOWED_METRICS[name], value=value)
    else:
        logging.getLogger("stopwatch.metrics").debug("metric %s=%s", name, value)


def flush_metrics() -> None:
    if IN_LAMBDA and _metrics is not None:
        _metrics.flush_metrics()


@contextmanager
def traced(name: str) -> Iterator[None]:
    """Lightweight X-Ray subsegment when tracing is active; no-op locally."""
    if IN_LAMBDA and os.environ.get("POWERTOOLS_TRACE_DISABLED", "false").lower() != "true":
        try:
            from aws_xray_sdk.core import xray_recorder

            with xray_recorder.in_subsegment(name):
                yield
            return
        except Exception:  # noqa: BLE001 - tracing must never break the request
            pass
    yield
