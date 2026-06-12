import ast
import builtins
import importlib
import inspect
from pathlib import Path

import pytest

from backend.app.modules.k_series.product_knowledge import unit_conversion


MODULE_NAME = "backend.app.modules.k_series.product_knowledge.unit_conversion"
MODULE_PATH = Path("backend/app/modules/k_series/product_knowledge/unit_conversion.py")
REQUIRED_PAYLOAD_FIELDS = {
    "value_kind",
    "original_value",
    "original_unit",
    "normalized_metric_value",
    "normalized_metric_unit",
    "normalized_imperial_value",
    "normalized_imperial_unit",
    "display_value",
    "display_unit",
    "display_market",
    "conversion_source",
    "conversion_precision",
    "source_text",
    "source_language",
    "parsed_from_text",
    "review_status",
    "reviewer_corrected",
    "warnings",
    "errors",
}


def assert_close(actual: int | float | None, expected: float, abs_tol: float = 0.01) -> None:
    assert actual is not None
    assert actual == pytest.approx(expected, abs=abs_tol)


def normalized_payload(
    value_kind: str,
    original_value: object,
    original_unit: str | None,
    display_market: str | None = "US",
    **overrides: object,
) -> dict[str, object]:
    return unit_conversion.normalize_unit_value(
        value_kind=value_kind,
        original_value=original_value,
        original_unit=original_unit,
        display_market=display_market,
        **overrides,
    )


def test_unit_conversion_module_imports_without_framework_database_env_or_network_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_roots = {
        "fastapi",
        "sqlalchemy",
        "requests",
        "httpx",
        "dotenv",
        "subprocess",
    }
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        root = name.split(".", maxsplit=1)[0]
        if root in forbidden_roots:
            raise AssertionError(f"forbidden import attempted: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(unit_conversion)


def test_unit_conversion_source_has_no_forbidden_runtime_imports_or_env_reads() -> None:
    source = inspect.getsource(unit_conversion)
    parsed = ast.parse(source)
    imported_roots: set[str] = set()

    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])

    assert imported_roots.isdisjoint(
        {
            "fastapi",
            "sqlalchemy",
            "requests",
            "httpx",
            "dotenv",
            "subprocess",
        }
    )
    for token in ("os.environ", "getenv(", "environ[", "load_dotenv", "subprocess."):
        assert token not in source


@pytest.mark.parametrize(
    ("unit", "group"),
    [
        ("mm", "length"),
        ("cm", "length"),
        ("m", "length"),
        ("in", "length"),
        ("ft", "length"),
        ("g", "weight"),
        ("kg", "weight"),
        ("oz", "weight"),
        ("lb", "weight"),
        ("ml", "volume"),
        ("l", "volume"),
        ("fl_oz", "volume"),
        ("c", "temperature"),
        ("f", "temperature"),
    ],
)
def test_supported_canonical_units_are_recognized(unit: str, group: str) -> None:
    assert unit_conversion.is_supported_unit(unit) is True
    assert unit_conversion.get_unit_group(unit) == group


def test_unsupported_units_are_not_supported_or_guessed() -> None:
    assert unit_conversion.is_supported_unit("stone") is False
    assert unit_conversion.get_unit_group("stone") is None
    assert unit_conversion.canonicalize_unit("stone") is None


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("inch", "in"),
        ("inches", "in"),
        ("foot", "ft"),
        ("feet", "ft"),
        ("gram", "g"),
        ("grams", "g"),
        ("kilogram", "kg"),
        ("kilograms", "kg"),
        ("ounce", "oz"),
        ("ounces", "oz"),
        ("pound", "lb"),
        ("pounds", "lb"),
        ("liter", "l"),
        ("litre", "l"),
        ("liters", "l"),
        ("litres", "l"),
        (" INCHES ", "in"),
        (" Kilograms ", "kg"),
        (" LITRES ", "l"),
    ],
)
def test_safe_aliases_canonicalize_without_guessing(alias: str, canonical: str) -> None:
    assert unit_conversion.canonicalize_unit(alias) == canonical


@pytest.mark.parametrize("unknown_alias", ["yard", "meter", "stones", "fluiddram"])
def test_unknown_aliases_do_not_canonicalize_by_guessing(unknown_alias: str) -> None:
    assert unit_conversion.canonicalize_unit(unknown_alias) is None
    assert unit_conversion.is_supported_unit(unknown_alias) is False


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "precision", "expected", "abs_tol"),
    [
        (1, "m", "cm", None, 100, 0),
        (1, "cm", "mm", None, 10, 0),
        (1, "in", "cm", None, 2.54, 0.001),
        (1, "ft", "in", None, 12, 0),
        (10, "cm", "in", None, 3.94, 0.01),
    ],
)
def test_length_conversions(
    value: object,
    from_unit: str,
    to_unit: str,
    precision: int | None,
    expected: float,
    abs_tol: float,
) -> None:
    assert_close(
        unit_conversion.convert_value(value, from_unit, to_unit, precision),
        expected,
        abs_tol=abs_tol,
    )


def test_cross_group_conversion_fails_safely_without_numeric_fallback() -> None:
    assert unit_conversion.convert_value(1, "cm", "kg") is None
    payload = normalized_payload("length", 1, "kg")

    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_value"] is None


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "precision", "expected", "abs_tol"),
    [
        (1, "kg", "g", None, 1000, 0),
        (1, "lb", "oz", None, 16, 0),
        (1, "lb", "kg", 8, 0.45359237, 0.00000001),
        (1, "oz", "g", 9, 28.349523125, 0.000000001),
        (2.2, "lb", "kg", 3, 0.998, 0.001),
    ],
)
def test_weight_conversions(
    value: object,
    from_unit: str,
    to_unit: str,
    precision: int | None,
    expected: float,
    abs_tol: float,
) -> None:
    assert_close(
        unit_conversion.convert_value(value, from_unit, to_unit, precision),
        expected,
        abs_tol=abs_tol,
    )


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "precision", "expected", "abs_tol"),
    [
        (1, "l", "ml", None, 1000, 0),
        (1, "fl_oz", "ml", 10, 29.5735295625, 0.0000000001),
        (750, "ml", "fl_oz", 2, 25.36, 0.01),
        (12, "fl_oz", "l", 3, 0.355, 0.001),
    ],
)
def test_volume_conversions(
    value: object,
    from_unit: str,
    to_unit: str,
    precision: int | None,
    expected: float,
    abs_tol: float,
) -> None:
    assert_close(
        unit_conversion.convert_value(value, from_unit, to_unit, precision),
        expected,
        abs_tol=abs_tol,
    )


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (0, "c", "f", 32),
        (100, "c", "f", 212),
        (32, "f", "c", 0),
        (212, "f", "c", 100),
    ],
)
def test_temperature_conversions(value: object, from_unit: str, to_unit: str, expected: float) -> None:
    assert_close(unit_conversion.convert_value(value, from_unit, to_unit), expected, abs_tol=0)


def test_normalize_unit_value_returns_k09b_contract_shape_and_preserves_source_metadata() -> None:
    payload = normalized_payload(
        "length",
        10,
        "cm",
        display_market="US",
        source_text="10 cm width",
        source_language="en",
        parsed_from_text=True,
    )

    assert REQUIRED_PAYLOAD_FIELDS.issubset(payload)
    assert payload["original_value"] == 10
    assert payload["original_unit"] == "cm"
    assert payload["normalized_metric_unit"] == "cm"
    assert payload["normalized_imperial_unit"] == "in"
    assert payload["display_unit"] == "in"
    assert payload["display_market"] == "US"
    assert payload["source_text"] == "10 cm width"
    assert payload["source_language"] == "en"
    assert payload["parsed_from_text"] is True
    assert payload["errors"] == []


def test_display_market_choice_does_not_rewrite_original_metric_value_or_unit() -> None:
    payload = normalized_payload("length", 25, "cm", display_market="US")

    assert payload["original_value"] == 25
    assert payload["original_unit"] == "cm"
    assert payload["display_unit"] == "in"
    assert payload["normalized_metric_unit"] == "cm"
    assert payload["normalized_imperial_unit"] == "in"


def test_eu_metric_display_preserves_original_imperial_value_and_unit() -> None:
    payload = normalized_payload("weight", 2, "lb", display_market="EU")

    assert payload["original_value"] == 2
    assert payload["original_unit"] == "lb"
    assert payload["display_unit"] == "kg"
    assert payload["normalized_metric_unit"] == "kg"
    assert payload["normalized_imperial_unit"] == "lb"


def test_reviewer_corrected_payload_preserves_original_input() -> None:
    payload = normalized_payload(
        "weight",
        1,
        "kg",
        display_market="EU",
        reviewer_corrected=True,
    )

    assert payload["original_value"] == 1
    assert payload["original_unit"] == "kg"
    assert payload["conversion_source"] == "reviewer_corrected"
    assert payload["reviewer_corrected"] is True


@pytest.mark.parametrize(
    ("original_value", "expected_error_codes"),
    [
        (None, {"missing_value"}),
        ("", {"missing_value"}),
        ("unknown", {"missing_value"}),
        ("not numeric", {"invalid_numeric_value"}),
    ],
)
def test_missing_unknown_or_invalid_values_do_not_become_zero(
    original_value: object,
    expected_error_codes: set[str],
) -> None:
    payload = normalized_payload("length", original_value, "cm")

    assert expected_error_codes.issubset(set(payload["errors"]))
    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_value"] is None
    assert payload["normalized_metric_value"] is None
    assert payload["normalized_imperial_value"] is None


def test_missing_unit_returns_missing_unit_without_uncaught_exception() -> None:
    payload = normalized_payload("length", 10, None)

    assert "missing_unit" in payload["errors"]
    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_value"] is None


def test_missing_value_and_unit_can_return_multiple_errors_without_throwing() -> None:
    payload = normalized_payload("length", None, None)

    assert {"missing_value", "missing_unit", "conversion_not_possible"}.issubset(
        set(payload["errors"])
    )
    assert payload["display_value"] is None


def test_unsupported_unit_returns_error_without_silent_fallback_or_exception() -> None:
    payload = normalized_payload("weight", 10, "stone", display_market="UK")

    assert payload["original_value"] == 10
    assert payload["original_unit"] == "stone"
    assert "unsupported_unit" in payload["errors"]
    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_unit"] is None
    assert payload["display_value"] is None


@pytest.mark.parametrize(
    ("market", "value_kind", "value", "unit", "expected_unit", "expected_warnings"),
    [
        ("US", "length", 10, "cm", "in", set()),
        ("US", "weight", 1, "kg", "lb", set()),
        ("US", "volume", 1, "l", "fl_oz", set()),
        ("US", "temperature", 0, "c", "f", set()),
        ("EU", "length", 1, "in", "cm", set()),
        ("EU", "weight", 1, "lb", "kg", set()),
        ("EU", "volume", 1, "fl_oz", "l", set()),
        ("EU", "temperature", 32, "f", "c", set()),
        ("AU", "length", 1, "in", "cm", set()),
        ("AU", "weight", 1, "lb", "kg", set()),
        ("AU", "volume", 1, "fl_oz", "l", set()),
        ("AU", "temperature", 32, "f", "c", set()),
        ("UK", "length", 1, "in", "cm", {"market_display_unknown"}),
        ("CA", "weight", 1, "lb", "kg", {"market_display_unknown"}),
        ("BR", "volume", 1, "fl_oz", "l", {"market_display_unknown"}),
    ],
)
def test_market_display_defaults(
    market: str,
    value_kind: str,
    value: object,
    unit: str,
    expected_unit: str,
    expected_warnings: set[str],
) -> None:
    payload = normalized_payload(value_kind, value, unit, display_market=market)

    assert payload["display_unit"] == expected_unit
    assert expected_warnings.issubset(set(payload["warnings"]))
    assert payload["errors"] == []


def test_validate_unit_value_payload_accepts_valid_normalized_payload_without_db() -> None:
    payload = normalized_payload("length", 10, "cm", display_market="US")
    validation = unit_conversion.validate_unit_value_payload(payload)

    assert validation == {"is_valid": True, "warnings": [], "errors": []}


@pytest.mark.parametrize(
    ("payload_updates", "expected_error"),
    [
        ({"original_value": None}, "missing_value"),
        ({"original_value": None, "display_value": 0}, "original_value_missing"),
        ({"original_unit": None}, "missing_unit"),
        ({"original_unit": "stone"}, "unsupported_unit"),
    ],
)
def test_validate_unit_value_payload_reports_blocking_errors(
    payload_updates: dict[str, object],
    expected_error: str,
) -> None:
    payload = normalized_payload("weight", 1, "kg", display_market="EU")
    payload.update(payload_updates)
    validation = unit_conversion.validate_unit_value_payload(payload)

    assert validation["is_valid"] is False
    assert expected_error in validation["errors"]
    assert "conversion_not_possible" in validation["errors"]


def test_ai_structured_source_only_converts_provided_value_and_unit() -> None:
    payload = normalized_payload(
        "length",
        10,
        "cm",
        display_market="US",
        conversion_source="ai_structured_from_provided_input",
        source_text="10 cm",
        parsed_from_text=True,
    )

    assert payload["conversion_source"] == "ai_structured_from_provided_input"
    assert payload["original_value"] == 10
    assert payload["original_unit"] == "cm"
    assert payload["display_unit"] == "in"
    assert payload["errors"] == []


@pytest.mark.parametrize(
    ("original_value", "original_unit", "expected_errors"),
    [
        (None, "cm", {"missing_value"}),
        (10, None, {"missing_unit"}),
    ],
)
def test_ai_structured_source_with_missing_value_or_unit_does_not_guess(
    original_value: object,
    original_unit: str | None,
    expected_errors: set[str],
) -> None:
    payload = normalized_payload(
        "length",
        original_value,
        original_unit,
        conversion_source="ai_structured_from_provided_input",
    )

    assert expected_errors.issubset(set(payload["errors"]))
    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_value"] is None


def test_unapproved_ai_source_expresses_guessing_forbidden() -> None:
    payload = normalized_payload(
        "length",
        10,
        "cm",
        conversion_source="ai_guessed_from_context",
    )

    assert "ai_guessing_forbidden" in payload["errors"]
    assert "conversion_not_possible" in payload["errors"]
    assert payload["display_value"] is None


def test_unit_conversion_does_not_define_dimensions_parser_helpers() -> None:
    public_names = {name for name in dir(unit_conversion) if not name.startswith("_")}

    assert "parse_dimensions" not in public_names
    assert "parse_dimension_string" not in public_names
    assert "normalize_dimensions_json" not in public_names
    assert "normalize_package_dimensions_json" not in public_names


def test_free_text_dimensions_input_is_not_parsed_as_single_unit_value() -> None:
    payload = normalized_payload(
        "length",
        "10 x 5 x 3 cm",
        None,
        source_text="10 x 5 x 3 cm",
        parsed_from_text=True,
    )

    assert {"invalid_numeric_value", "missing_unit", "conversion_not_possible"}.issubset(
        set(payload["errors"])
    )
    assert payload["display_value"] is None
    assert payload["source_text"] == "10 x 5 x 3 cm"


def test_source_file_path_check_is_static_and_local() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert MODULE_NAME.endswith("unit_conversion")
    assert "def normalize_unit_value(" in source
    assert "def validate_unit_value_payload(" in source
