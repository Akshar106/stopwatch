from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stopwatch.core.metrics import (
    HISTOGRAM_EDGES_S,
    average_wait,
    classify,
    excess_wait_time,
    headways,
    histogram,
    percentile,
    percentile_from_histogram,
)


@pytest.mark.parametrize(("delay", "expected"), [(-61, "early"), (-60, "on_time"), (0, "on_time"),
                                                 (300, "on_time"), (301, "late")])
def test_on_time_window_edges(delay: int, expected: str) -> None:
    assert classify(delay) == expected


def test_percentile_matches_linear_interpolation() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10], 0.9) == 10.0
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([0, 10], 0.9) == pytest.approx(9.0)


@given(st.lists(st.integers(-3600, 7200), min_size=1, max_size=200), st.floats(0, 1))
def test_percentile_is_within_range_and_monotonic(values: list[int], q: float) -> None:
    p = percentile(values, q)
    assert p is not None
    assert min(values) <= p <= max(values)
    assert percentile(values, 0.1) <= percentile(values, 0.9)  # type: ignore[operator]


def test_histogram_bucket_boundaries() -> None:
    # edges (-60, 60, 180, 300, 600, 1200): lower edge inclusive, upper exclusive
    values = [-61, -60, 59, 60, 179, 180, 299, 300, 599, 600, 1199, 1200, 5000]
    assert histogram(values) == [1, 2, 2, 2, 2, 2, 2]


@given(st.lists(st.integers(-3600, 7200), max_size=300))
def test_histogram_counts_everything(values: list[int]) -> None:
    h = histogram(values)
    assert len(h) == len(HISTOGRAM_EDGES_S) + 1
    assert sum(h) == len(values)


def test_percentile_from_histogram() -> None:
    assert percentile_from_histogram([0] * 7, HISTOGRAM_EDGES_S, 0.5) is None
    # all mass in [60, 180): median interpolates to the middle of the bucket
    assert percentile_from_histogram([0, 0, 10, 0, 0, 0, 0], HISTOGRAM_EDGES_S, 0.5) == pytest.approx(120.0)
    # open-ended top bucket returns its lower edge
    assert percentile_from_histogram([0, 0, 0, 0, 0, 0, 4], HISTOGRAM_EDGES_S, 0.9) == 1200.0


def test_average_wait_even_vs_bunched() -> None:
    # Two buses an hour, evenly spaced (30, 30): avg wait 15 min.
    assert average_wait([1800, 1800]) == pytest.approx(900)
    # Same buses bunched (5, 55): riders wait much longer on average.
    assert average_wait([300, 3300]) == pytest.approx((300**2 + 3300**2) / (2 * 3600))
    assert average_wait([]) is None


def test_excess_wait_time() -> None:
    sched = [600, 600, 600, 600]  # every 10 min -> 5 min average wait
    actual = [300, 900, 300, 900]  # bunching -> 6.25 min average wait
    assert excess_wait_time(actual, sched) == pytest.approx(375 - 300)
    assert excess_wait_time([], sched) is None


def test_headways() -> None:
    assert headways([30, 10, 20, 20]) == [10, 10]
