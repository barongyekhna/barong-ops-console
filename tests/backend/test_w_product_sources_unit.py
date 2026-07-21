"""Database-free tests for W-S source batching and item enrichment."""

from __future__ import annotations

from decimal import Decimal
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from backend.app.modules.w_series.product_sources import (
    enrich_items,
    load_sources_for_items,
    normalize_sku,
)
from backend.app.modules.w_series.router import (
    _order_items_with_sources,
    product_source_upsert,
)
from backend.app.modules.w_series.source_schemas import ProductSourceUpsertRequest


pytestmark = pytest.mark.unit


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _RecordingSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    def scalars(self, statement: object) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self.rows)


class _UpsertSession:
    def __init__(self) -> None:
        self.row: object | None = None
        self.add_calls = 0
        self.commit_calls = 0

    def scalar(self, _statement: object) -> object | None:
        return self.row

    def add(self, row: object) -> None:
        self.add_calls += 1
        self.row = row
        row.id = uuid4()
        now = datetime.now(UTC)
        row.created_at = now
        row.updated_at = now

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, _row: object) -> None:
        return None


class _RollbackSession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def rollback(self) -> None:
        self.rollback_calls += 1


def _source(sku: str, *, url_suffix: str = "1") -> object:
    return SimpleNamespace(
        sku=sku,
        source_url=f"https://detail.1688.com/offer/{url_suffix}.html",
        supplier_name=f"Supplier {url_suffix}",
        unit_cost=Decimal("12.34"),
        currency="CNY",
        moq=5,
    )


def test_normalize_sku_trims_and_uppercases_the_shared_key() -> None:
    assert normalize_sku(" igl-001 ") == "IGL-001"
    assert normalize_sku("IGL-001") == "IGL-001"
    assert normalize_sku("   ") == ""
    assert normalize_sku(None) == ""


def test_upsert_uses_the_normalized_path_sku_as_one_stable_key() -> None:
    session = _UpsertSession()
    initial = ProductSourceUpsertRequest(
        source_url="https://detail.1688.com/offer/1.html",
        supplier_name="Initial supplier",
    )
    updated = ProductSourceUpsertRequest(
        source_url="https://detail.1688.com/offer/2.html",
        supplier_name="Updated supplier",
    )

    first = product_source_upsert(
        " igl-001 ",
        initial,
        db=session,  # type: ignore[arg-type]
        user=object(),  # type: ignore[arg-type]
    )
    second = product_source_upsert(
        "IGL-001",
        updated,
        db=session,  # type: ignore[arg-type]
        user=object(),  # type: ignore[arg-type]
    )

    assert first.sku == "IGL-001"
    assert second.sku == "IGL-001"
    assert second.supplier_name == "Updated supplier"
    assert str(second.source_url).endswith("/2.html")
    assert session.add_calls == 1
    assert session.commit_calls == 2


def test_load_sources_batches_all_orders_into_exactly_one_in_query() -> None:
    session = _RecordingSession([_source("A-001"), _source("B-002")])
    item_payloads: list[list[dict[str, Any]] | None] = [
        [
            {"sku": " a-001 "},
            {"sku": "B-002"},
            {"sku": ""},
        ],
        [{"sku": "A-001"}, {"name": "legacy item"}],
        None,
    ]

    loaded = load_sources_for_items(session, item_payloads)  # type: ignore[arg-type]

    assert len(session.statements) == 1
    statement = session.statements[0]
    assert " IN " in str(statement).upper()
    in_values = next(
        value
        for value in statement.compile().params.values()
        if isinstance(value, list)
    )
    assert in_values == ["A-001", "B-002"]
    assert set(loaded) == {"A-001", "B-002"}


def test_load_sources_skips_the_database_when_every_sku_is_missing() -> None:
    session = _RecordingSession([])

    loaded = load_sources_for_items(
        session,  # type: ignore[arg-type]
        [[{"name": "legacy"}, {"sku": "  "}], None],
    )

    assert loaded == {}
    assert session.statements == []


def test_enrich_items_covers_linked_missing_and_blank_without_mutation() -> None:
    source = _source("IGL-001", url_suffix="99")
    original = [
        {"name": "Linked", "sku": " igl-001 ", "qty": 1},
        {"name": "Missing", "sku": "NO-SOURCE", "qty": 2},
        {"name": "Legacy", "qty": 1},
    ]

    enriched = enrich_items(original, {"IGL-001": source})  # type: ignore[dict-item]

    assert enriched is not None
    assert enriched[0] == {
        **original[0],
        "source_url": "https://detail.1688.com/offer/99.html",
        "supplier_name": "Supplier 99",
        "unit_cost": Decimal("12.34"),
        "currency": "CNY",
        "moq": 5,
        "source_state": "linked",
    }
    for item in enriched[1:]:
        assert item["source_state"] == "missing"
        assert item["source_url"] is None
        assert item["supplier_name"] is None
        assert item["unit_cost"] is None
        assert item["currency"] is None
        assert item["moq"] is None
    assert "source_state" not in original[0]


def test_enrich_items_preserves_a_null_items_payload() -> None:
    assert enrich_items(None, {}) is None


def test_order_enrichment_query_exception_is_fail_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RollbackSession()
    order = SimpleNamespace(
        id=uuid4(),
        woo_order_id=123,
        order_number="UNIT-FAIL-SAFE",
        woo_status="processing",
        customer_name="Unit customer",
        country="US",
        total=Decimal("10.00"),
        currency="USD",
        items_json=[
            {"name": "Would be linked", "sku": "IGL-001", "qty": 1},
            {"name": "Legacy item", "qty": 1},
        ],
        placed_at=datetime(2026, 7, 21, tzinfo=UTC),
        tracking_number=None,
        carrier_code=None,
        tracking_status="none",
        tracking_events_json=None,
        tracking_registered=False,
        last_tracking_update=None,
        writeback_status="none",
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
        updated_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    def fail_query(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("forced source lookup failure")

    monkeypatch.setattr(
        "backend.app.modules.w_series.router.product_sources.load_sources_for_items",
        fail_query,
    )

    result = _order_items_with_sources(
        session,  # type: ignore[arg-type]
        [order],  # type: ignore[list-item]
    )

    assert session.rollback_calls == 1
    assert len(result) == 1
    assert result[0].order_number == "UNIT-FAIL-SAFE"
    assert result[0].items_json is not None
    assert [item["source_state"] for item in result[0].items_json] == [
        "missing",
        "missing",
    ]
    assert all(item["source_url"] is None for item in result[0].items_json)
