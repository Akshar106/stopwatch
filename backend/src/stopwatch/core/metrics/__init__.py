"""Reliability metrics as pure functions.

The daily rollup computes these in DuckDB SQL for speed; tests/property and tests/integration check that the
SQL matches these reference implementations (parity tests), so the definitions live in exactly one place
conceptually and are documented in docs/methodology.md.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Literal

# Delay histogram bucket edges in seconds -> 7 buckets:
# (<-1m) [-1m,+1m) [+1m,+3m) [+3m,+5m) [+5m,+10m) [+10m,+20m) (>=+20m)
HISTOGRAM_EDGES_S: tuple[int, ...] = (-60, 60, 180, 300, 600, 1200)
MIN_SAMPLES = 8

Punctuality = Literal["early", "on_time", "late"]


def classify(delay_s: int, early_s: int = -60, late_s: int = 300) -> Punctuality:
    """On time means early_s <= delay <= late_s (default -1 min .. +5 min)."""
    if delay_s < early_s:
        return "early"
    if delay_s > late_s:
        return "late"
    return "on_time"


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (same definition as DuckDB/Postgres quantile_cont)."""
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def histogram(values: Sequence[float], edges: Sequence[float] = HISTOGRAM_EDGES_S) -> list[int]:
    """Counts per bucket; bucket i holds edges[i-1] <= v < edges[i] (first and last are open-ended)."""
    counts = [0] * (len(edges) + 1)
    for v in values:
        i = 0
        while i < len(edges) and v >= edges[i]:
            i += 1
        counts[i] += 1
    return counts


def percentile_from_histogram(counts: Sequence[int], edges: Sequence[float], q: float) -> float | None:
    """Approximate percentile from bucket counts (linear within a bucket; open buckets use their edge)."""
    total = sum(counts)
    if total == 0:
        return None
    target = q * total
    cum = 0.0
    for i, c in enumerate(counts):
        if c == 0:
            continue
        if cum + c >= target:
            if i == 0:
                return float(edges[0])
            if i == len(edges):
                return float(edges[-1])
            lo, hi = edges[i - 1], edges[i]
            return float(lo + (hi - lo) * ((target - cum) / c))
        cum += c
    return float(edges[-1])


def average_wait(headways_s: Sequence[float]) -> float | None:
    """Expected wait for a rider arriving at random: sum(h^2) / (2 * sum(h))."""
    total = sum(headways_s)
    if total <= 0:
        return None
    return sum(h * h for h in headways_s) / (2 * total)


def excess_wait_time(actual_headways_s: Sequence[float], scheduled_headways_s: Sequence[float]) -> float | None:
    """Average actual wait minus average scheduled wait (standard high-frequency reliability metric)."""
    actual = average_wait(actual_headways_s)
    scheduled = average_wait(scheduled_headways_s)
    if actual is None or scheduled is None:
        return None
    return actual - scheduled


def headways(times_s: Sequence[float]) -> list[float]:
    s = sorted(times_s)
    return [b - a for a, b in itertools.pairwise(s) if b > a]


__all__ = [
    "HISTOGRAM_EDGES_S",
    "MIN_SAMPLES",
    "Punctuality",
    "average_wait",
    "classify",
    "excess_wait_time",
    "headways",
    "histogram",
    "percentile",
    "percentile_from_histogram",
]
