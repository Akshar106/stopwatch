"""platform.idempotency: replay, conflict detection, expiry and key validation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine

from stopwatch.platform import idempotency
from stopwatch.platform.clock import utc_now
from stopwatch.platform.idempotency import IdempotencyConflictError, InvalidIdempotencyKeyError, StoredResponse
from tests.api.factories import create_google_user

pytestmark = pytest.mark.integration


def test_fingerprint_ignores_key_order() -> None:
    assert idempotency.request_fingerprint({"a": 1, "b": [1, 2]}) == idempotency.request_fingerprint(
        {"b": [1, 2], "a": 1}
    )
    assert idempotency.request_fingerprint({"a": 1}) != idempotency.request_fingerprint({"a": 2})


def test_replay_and_conflict(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    now = utc_now()
    fingerprint = idempotency.request_fingerprint({"x": 1})
    with app_engine.begin() as conn:
        assert idempotency.begin(conn, user.id, "key-replay-01", fingerprint, now=now) is None
        idempotency.save(conn, user.id, "key-replay-01", fingerprint, StoredResponse(201, {"id": "c1"}), now=now)
    with app_engine.begin() as conn:
        stored = idempotency.begin(conn, user.id, "key-replay-01", fingerprint, now=now)
    assert stored == StoredResponse(201, {"id": "c1"})
    with pytest.raises(IdempotencyConflictError), app_engine.begin() as conn:
        idempotency.begin(conn, user.id, "key-replay-01", idempotency.request_fingerprint({"x": 2}), now=now)


def test_expired_keys_are_reusable(app_engine: Engine) -> None:
    user = create_google_user(app_engine)
    then = utc_now() - timedelta(hours=25)
    fp_old, fp_new = idempotency.request_fingerprint("old"), idempotency.request_fingerprint("new")
    with app_engine.begin() as conn:
        idempotency.save(conn, user.id, "key-expiry-01", fp_old, StoredResponse(201, {"id": "old"}), now=then)
    now = utc_now()
    with app_engine.begin() as conn:
        assert idempotency.begin(conn, user.id, "key-expiry-01", fp_new, now=now) is None
        idempotency.save(conn, user.id, "key-expiry-01", fp_new, StoredResponse(201, {"id": "new"}), now=now)
        assert idempotency.begin(conn, user.id, "key-expiry-01", fp_new, now=now) == StoredResponse(201, {"id": "new"})
        assert idempotency.purge_before(conn, now - idempotency.KEY_TTL) >= 0


@pytest.mark.parametrize("key", ["", "1234567", "x" * 65, "tab\tkey123"])
def test_key_validation(key: str) -> None:
    with pytest.raises(InvalidIdempotencyKeyError):
        idempotency.validate_key(key)
    assert idempotency.validate_key("a1b2c3d4-e5f6") == "a1b2c3d4-e5f6"
