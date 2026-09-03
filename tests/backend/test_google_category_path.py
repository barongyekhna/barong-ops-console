from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.modules.k_series.product_knowledge.category_resolver import (
    bind_google_category_id,
    google_category_path,
    repair_legacy_google_category_path,
)

pytestmark = pytest.mark.unit


def _row(
    google_id: str,
    name: str,
    full_path: str,
    *,
    parent_id: str | None,
    level: int,
) -> dict[str, object]:
    return {
        "id": google_id,
        "name": name,
        "full_path": full_path,
        "parent_id": parent_id,
        "level": level,
    }


class _FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.id_lookups: list[str] = []
        self.name_lookups: list[str] = []

    def execute(
        self,
        statement: Any,
        params: dict[str, object] | None = None,
        **_kwargs: Any,
    ) -> _FakeResult:
        sql = str(statement)
        if "WHERE id = :google_id" in sql:
            google_id = str(params["google_id"])
            self.id_lookups.append(google_id)
            return _FakeResult(
                [row for row in self._rows if str(row["id"]) == google_id]
            )
        if "lower(name) = lower(:name)" in sql:
            name = str(params["name"])
            self.name_lookups.append(name)
            return _FakeResult(
                [
                    row
                    for row in self._rows
                    if str(row["name"]).casefold() == name.casefold()
                ]
            )
        raise AssertionError(f"unexpected query: {sql}")


def test_google_category_path_prefers_complete_parent_chain() -> None:
    db = _FakeSession(
        [
            _row("1", "Home", "Home", parent_id=None, level=1),
            _row("2", "Decor", "Home > Decor", parent_id="1", level=2),
            _row(
                "3",
                "Mirrors",
                "Home > Decor > Mirrors",
                parent_id="2",
                level=3,
            ),
        ]
    )

    assert google_category_path(db, "3") == [  # type: ignore[arg-type]
        {"google_id": "1", "name": "Home"},
        {"google_id": "2", "name": "Decor"},
        {"google_id": "3", "name": "Mirrors"},
    ]
    assert db.id_lookups == ["3", "2", "1"]
    assert db.name_lookups == []


@pytest.mark.parametrize("separator", [">", "›"])
def test_google_category_path_falls_back_for_both_separators(separator: str) -> None:
    paths = [
        "Sporting Goods",
        f"Sporting Goods {separator} Outdoor Recreation",
        f"Sporting Goods {separator} Outdoor Recreation {separator} Camp Showers",
    ]
    db = _FakeSession(
        [
            _row("10", "Sporting Goods", paths[0], parent_id=None, level=1),
            _row("11", "Outdoor Recreation", paths[1], parent_id=None, level=2),
            _row("12", "Camp Showers", paths[2], parent_id=None, level=3),
        ]
    )

    assert google_category_path(db, "12") == [  # type: ignore[arg-type]
        {"google_id": "10", "name": "Sporting Goods"},
        {"google_id": "11", "name": "Outdoor Recreation"},
        {"google_id": "12", "name": "Camp Showers"},
    ]
    assert db.name_lookups == [
        "Sporting Goods",
        "Outdoor Recreation",
        "Camp Showers",
    ]


def test_full_path_fallback_disambiguates_same_name_under_different_parents() -> None:
    db = _FakeSession(
        [
            _row("20", "Home", "Home", parent_id=None, level=1),
            _row("21", "Storage", "Home > Storage", parent_id=None, level=2),
            _row(
                "22",
                "Accessories",
                "Home > Storage > Accessories",
                parent_id=None,
                level=3,
            ),
            _row("30", "Electronics", "Electronics", parent_id=None, level=1),
            _row(
                "31",
                "Cables",
                "Electronics > Cables",
                parent_id=None,
                level=2,
            ),
            _row(
                "32",
                "Accessories",
                "Electronics > Cables > Accessories",
                parent_id=None,
                level=3,
            ),
        ]
    )

    assert google_category_path(db, "22") == [  # type: ignore[arg-type]
        {"google_id": "20", "name": "Home"},
        {"google_id": "21", "name": "Storage"},
        {"google_id": "22", "name": "Accessories"},
    ]
    assert db.name_lookups[-1] == "Accessories"


def test_dangling_parent_falls_back_to_complete_full_path() -> None:
    db = _FakeSession(
        [
            _row("40", "Garden", "Garden", parent_id=None, level=1),
            _row(
                "41",
                "Watering",
                "Garden > Watering",
                parent_id="40",
                level=2,
            ),
            _row(
                "42",
                "Hoses",
                "Garden > Watering > Hoses",
                parent_id="missing",
                level=3,
            ),
        ]
    )

    assert google_category_path(db, "42") == [  # type: ignore[arg-type]
        {"google_id": "40", "name": "Garden"},
        {"google_id": "41", "name": "Watering"},
        {"google_id": "42", "name": "Hoses"},
    ]


def test_parent_cycle_is_bounded_and_never_returns_a_partial_chain() -> None:
    db = _FakeSession(
        [
            _row(
                "50",
                "Branch",
                "Missing Root > Branch",
                parent_id="51",
                level=2,
            ),
            _row(
                "51",
                "Leaf",
                "Missing Root > Branch > Leaf",
                parent_id="50",
                level=3,
            ),
        ]
    )

    assert google_category_path(db, "51") == []  # type: ignore[arg-type]
    assert db.id_lookups == ["51", "50", "51"]
    assert db.name_lookups == ["Missing Root"]


def test_unknown_or_empty_google_category_returns_empty_path() -> None:
    db = _FakeSession([])

    assert google_category_path(db, None) == []  # type: ignore[arg-type]
    assert google_category_path(db, "") == []  # type: ignore[arg-type]
    assert google_category_path(db, "unknown") == []  # type: ignore[arg-type]
    assert db.id_lookups == ["unknown"]


def test_google_category_binding_accepts_only_existing_numeric_ids() -> None:
    db = _FakeSession(
        [
            _row(
                "7401",
                "Pathway Lighting",
                "Lighting > Pathway Lighting",
                parent_id=None,
                level=2,
            )
        ]
    )
    product = SimpleNamespace(google_product_category=None)

    assert bind_google_category_id(  # type: ignore[arg-type]
        db, product, " 7401 "
    ) is True
    assert product.google_product_category == "7401"

    assert bind_google_category_id(  # type: ignore[arg-type]
        db, product, "Lighting > Pathway Lighting"
    ) is False
    assert product.google_product_category is None

    assert bind_google_category_id(  # type: ignore[arg-type]
        db, product, "9999"
    ) is False
    assert product.google_product_category is None


def test_legacy_google_category_path_repairs_to_unique_leaf_id() -> None:
    full_path = "Lighting > Pathway Lighting"
    db = _FakeSession(
        [
            _row("7", "Lighting", "Lighting", parent_id=None, level=1),
            _row(
                "7401",
                "Pathway Lighting",
                full_path,
                parent_id="7",
                level=2,
            ),
        ]
    )
    product = SimpleNamespace(
        google_product_category=full_path,
        category_hint=None,
        category_review_needed=True,
    )

    assert repair_legacy_google_category_path(  # type: ignore[arg-type]
        db, product
    ) is True
    assert product.google_product_category == "7401"
    assert product.category_hint == full_path
    assert product.category_review_needed is False
