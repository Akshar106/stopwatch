"""platform.ratelimit: atomic fixed-window counters, and IP-prefix bucketing."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from stopwatch.platform import ratelimit
from stopwatch.platform.ratelimit import RateLimit, RateLimitExceededError
from stopwatch.platform.security import client_address, ip_prefix

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 18, 12, 0, 30, tzinfo=UTC)


def _rule(limit: int = 3, window: timedelta = timedelta(minutes=1)) -> RateLimit:
    return RateLimit(name=f"test_{uuid.uuid4().hex[:8]}", limit=limit, window=window)


def test_window_alignment() -> None:
    assert ratelimit.window_start(T0, timedelta(minutes=1)) == datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert ratelimit.window_start(T0, timedelta(hours=1)) == datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert ratelimit.window_start(T0, timedelta(days=1)) == datetime(2026, 10, 18, tzinfo=UTC)


def test_counts_up_to_the_limit_then_rejects(app_engine: Engine) -> None:
    rule = _rule(limit=3)
    with app_engine.begin() as conn:
        decisions = [ratelimit.hit(conn, rule, "ip:203.0.113.0/24", now=T0) for _ in range(5)]
    assert [d.allowed for d in decisions] == [True, True, True, False, False]
    assert [d.first_rejection for d in decisions] == [False, False, False, True, False]
    assert decisions[-1].retry_after_s == 30


def test_new_window_resets_and_keys_are_independent(app_engine: Engine) -> None:
    rule = _rule(limit=1)
    with app_engine.begin() as conn:
        assert ratelimit.hit(conn, rule, "user:a", now=T0).allowed
        assert not ratelimit.hit(conn, rule, "user:a", now=T0).allowed
        assert ratelimit.hit(conn, rule, "user:b", now=T0).allowed
        assert ratelimit.hit(conn, rule, "user:a", now=T0 + timedelta(minutes=1)).allowed
        with pytest.raises(RateLimitExceededError):
            ratelimit.enforce(conn, rule, "user:b", now=T0)


def test_concurrent_hits_are_counted_exactly(app_engine: Engine) -> None:
    rule = _rule(limit=1000)

    def one_hit(_: int) -> int:
        with app_engine.begin() as conn:
            return ratelimit.hit(conn, rule, "ip:x", now=T0).count

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = sorted(pool.map(one_hit, range(20)))
    assert counts == list(range(1, 21))


def test_purge_removes_old_windows(app_engine: Engine) -> None:
    rule = _rule()
    with app_engine.begin() as conn:
        ratelimit.hit(conn, rule, "k", now=T0 - timedelta(days=3))
        ratelimit.hit(conn, rule, "k", now=T0)
        assert ratelimit.purge_before(conn, T0 - timedelta(days=1)) >= 1
        assert ratelimit.hit(conn, rule, "k", now=T0).count == 2


@pytest.mark.parametrize(
    ("address", "prefix"),
    [
        ("203.0.113.77", "203.0.113.0/24"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd::/48"),
        ("::ffff:198.51.100.9", "198.51.100.0/24"),
        ("testclient", None),
        (None, None),
    ],
)
def test_ip_prefix(address: str | None, prefix: str | None) -> None:
    assert ip_prefix(address) == prefix


def test_client_address_uses_cloudfront_viewer_address_never_forwarded_for() -> None:
    assert client_address(viewer_address="198.51.100.7:46532", peer="10.0.0.1", behind_edge=True) == "198.51.100.7"
    assert client_address(viewer_address="2001:db8::1:443", peer="10.0.0.1", behind_edge=True) == "2001:db8::1"
    assert client_address(viewer_address="garbage", peer="10.0.0.1", behind_edge=True) is None
    # Locally there is no edge: the socket peer is the client.
    assert client_address(viewer_address="198.51.100.7:1", peer="10.0.0.1", behind_edge=False) == "10.0.0.1"
