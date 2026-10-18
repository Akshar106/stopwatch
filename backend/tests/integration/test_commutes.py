"""commutes: owner-scoped repository, catalog validation, caps and day-mask encoding."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import Engine

from stopwatch.commutes import repository, service
from stopwatch.commutes.schemas import CommuteCreate, CommutePatch, days_to_mask, mask_to_days
from stopwatch.platform.audit import AuditContext
from stopwatch.platform.clock import utc_now
from tests.api.factories import Catalog, create_google_user, seed_catalog

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog(app_engine: Engine) -> Catalog:
    return seed_catalog(app_engine)


def _create(engine: Engine, owner: UUID, catalog: Catalog, *, is_demo: bool = False, **overrides: object) -> str:
    data = CommuteCreate.model_validate(catalog.commute_body(**overrides))
    with engine.begin() as conn:
        result = service.create_commute(
            conn, owner_id=owner, is_demo=is_demo, data=data, now=utc_now(), ctx=AuditContext("user", owner)
        )
    return str(result.body["id"])


def test_days_mask_bit_zero_is_monday() -> None:
    assert days_to_mask(["mon"]) == 1
    assert days_to_mask(["mon", "tue", "wed", "thu", "fri"]) == 31
    assert days_to_mask(["sun"]) == 64
    assert mask_to_days(96) == ["sat", "sun"]
    assert mask_to_days(days_to_mask(["sun", "mon"])) == ["mon", "sun"]


def test_repository_functions_are_owner_scoped(app_engine: Engine, catalog: Catalog) -> None:
    alice = create_google_user(app_engine).id
    mallory = create_google_user(app_engine).id
    commute_id = UUID(_create(app_engine, alice, catalog))
    now = utc_now()
    with app_engine.begin() as conn:
        assert repository.get_for_owner(conn, mallory, commute_id) is None
        assert repository.list_for_owner(conn, mallory) == []
        assert repository.update_for_owner(conn, mallory, commute_id, {"label": "pwned"}, now=now) is False
        assert repository.delete_for_owner(conn, mallory, commute_id) is False
        record = repository.get_for_owner(conn, alice, commute_id)
    assert record is not None and record.label == "Home to work"


def test_service_raises_not_found_for_other_owners(app_engine: Engine, catalog: Catalog) -> None:
    alice = create_google_user(app_engine).id
    mallory = create_google_user(app_engine).id
    commute_id = UUID(_create(app_engine, alice, catalog))
    ctx = AuditContext("user", mallory)
    with pytest.raises(service.CommuteNotFoundError), app_engine.begin() as conn:
        service.update_commute(
            conn, owner_id=mallory, commute_id=commute_id, patch=CommutePatch(label="x"), now=utc_now(), ctx=ctx
        )
    with pytest.raises(service.CommuteNotFoundError), app_engine.begin() as conn:
        service.delete_commute(conn, owner_id=mallory, commute_id=commute_id, ctx=ctx)


def test_catalog_validation(app_engine: Engine, catalog: Catalog) -> None:
    owner = create_google_user(app_engine).id
    _create(app_engine, owner, catalog, direction_id=1, stop_id="65")
    with pytest.raises(service.CommuteValidationError) as err:
        _create(app_engine, owner, catalog, direction_id=1, stop_id="64")
    assert err.value.errors[0][0] == "stop_id"


def test_caps(app_engine: Engine, catalog: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    demo_owner = create_google_user(app_engine).id
    for _ in range(service.MAX_DEMO_COMMUTES):
        _create(app_engine, demo_owner, catalog, is_demo=True)
    with pytest.raises(service.CommuteLimitError) as err:
        _create(app_engine, demo_owner, catalog, is_demo=True)
    assert err.value.limit == 3
    _create(app_engine, demo_owner, catalog, is_demo=False)  # the full-account cap is 20


def test_schema_rejects_inverted_windows_and_mass_assignment() -> None:
    from pydantic import ValidationError

    base = Catalog(agency_id="x").commute_body()
    with pytest.raises(ValidationError):
        CommuteCreate.model_validate({**base, "window_start": "08:30", "window_end": "08:30"})
    with pytest.raises(ValidationError):
        CommuteCreate.model_validate({**base, "user_id": "00000000-0000-4000-8000-000000000000"})
    with pytest.raises(ValidationError):
        CommutePatch.model_validate({"days": None})
    assert CommutePatch.model_validate({"label": None}).changes() == {"label": None}
    assert CommuteCreate.model_validate({**base, "label": "  "}).label is None
