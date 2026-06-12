import ast
import builtins
import importlib
import inspect
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.modules.k_series.product_knowledge import unit_conversion, unit_payloads


MODULE_NAME = "backend.app.modules.k_series.product_knowledge.unit_payloads"
MODULE_PATH = Path("backend/app/modules/k_series/product_knowledge/unit_payloads.py")
AI_SOURCE = "ai_structured_from_provided_input"


def assert_close(actual: int | float | None, expected: float, abs_tol: float = 0.01) -> None:
    assert actual is not None
    assert actual == pytest.approx(expected, abs=abs_tol)


def test_unit_payloads_module_imports_without_framework_database_env_or_network_imports(
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
    importlib.reload(unit_payloads)


def test_unit_payloads_source_has_no_forbidden_runtime_imports_or_env_reads() -> None:
    source = inspect.getsource(unit_payloads)
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


def test_build_product_dimensions_payload_preserves_values_and_normalizes_for_us_display() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit="cm",
        width=5,
        width_unit="cm",
        height=3,
        height_unit="cm",
        display_market="US",
    )

    assert payload["unit_group"] == "length"
    assert payload["length"]["original_value"] == 10
    assert payload["width"]["original_value"] == 5
    assert payload["height"]["original_value"] == 3
    assert payload["length"]["original_unit"] == "cm"
    assert payload["width"]["original_unit"] == "cm"
    assert payload["height"]["original_unit"] == "cm"
    assert payload["length"]["normalized_imperial_unit"] == "in"
    assert payload["width"]["normalized_imperial_unit"] == "in"
    assert payload["height"]["normalized_imperial_unit"] == "in"
    assert payload["length"]["display_unit"] == "in"
    assert payload["width"]["display_unit"] == "in"
    assert payload["height"]["display_unit"] == "in"
    assert payload["diameter"] is None
    assert payload["thickness"] is None
    assert unit_payloads.collect_payload_errors(payload) == []
    assert unit_payloads.WARNING_DIMENSION_ORDER_MISSING in payload["warnings"]


def test_product_dimensions_missing_optional_fields_do_not_become_zero() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=7,
        length_unit="in",
        dimension_order=["length"],
        display_market="US",
    )

    assert payload["diameter"] is None
    assert payload["thickness"] is None
    assert payload["length"]["original_value"] == 7
    assert payload["length"]["display_value"] == 7
    assert unit_payloads.collect_payload_errors(payload) == []


def test_product_dimensions_without_any_values_returns_dimension_value_missing() -> None:
    payload = unit_payloads.build_dimensions_payload()

    assert payload["length"] is None
    assert payload["width"] is None
    assert payload["height"] is None
    assert payload["diameter"] is None
    assert payload["thickness"] is None
    assert unit_payloads.ERROR_DIMENSION_VALUE_MISSING in payload["errors"]


def test_product_dimensions_source_text_is_preserved_but_not_used_for_inference() -> None:
    payload = unit_payloads.build_dimensions_payload(
        source_text="10 x 5 x 3 cm",
        source_language="en",
        parsed_from_text=True,
    )

    assert payload["source_text"] == "10 x 5 x 3 cm"
    assert payload["source_language"] == "en"
    assert payload["parsed_from_text"] is True
    assert payload["length"] is None
    assert payload["width"] is None
    assert payload["height"] is None
    assert unit_payloads.ERROR_DIMENSION_VALUE_MISSING in payload["errors"]
    assert unit_payloads.WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED in payload["warnings"]


def test_build_package_dimensions_payload_uses_only_package_fields() -> None:
    payload = unit_payloads.build_package_dimensions_payload(
        package_length=12,
        package_length_unit="in",
        package_width=8,
        package_width_unit="in",
        package_height=4,
        package_height_unit="in",
        package_dimension_order=[
            "package_length",
            "package_width",
            "package_height",
        ],
        display_market="US",
    )

    assert payload["package_unit_group"] == "length"
    assert "length" not in payload
    assert "width" not in payload
    assert "height" not in payload
    assert payload["package_length"]["original_value"] == 12
    assert payload["package_width"]["original_value"] == 8
    assert payload["package_height"]["original_value"] == 4
    assert payload["package_length"]["normalized_metric_unit"] == "cm"
    assert_close(payload["package_length"]["normalized_metric_value"], 30.48)
    assert payload["package_length"]["display_unit"] == "in"
    assert unit_payloads.collect_payload_errors(payload) == []


def test_package_dimensions_conflict_validation_rejects_product_dimension_keys() -> None:
    payload = unit_payloads.build_package_dimensions_payload(
        package_length=12,
        package_length_unit="in",
        display_market="US",
    )
    bad_payload = dict(payload)
    bad_payload["length"] = payload["package_length"]

    validation = unit_payloads.validate_package_dimensions_payload(bad_payload)

    assert validation["is_valid"] is False
    assert unit_payloads.ERROR_PRODUCT_VS_PACKAGE_CONFLICT in validation["errors"]


def test_package_and_product_dimensions_do_not_copy_each_other() -> None:
    product_payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit="cm",
        dimension_order=["length"],
    )
    package_payload = unit_payloads.build_package_dimensions_payload(
        package_length=12,
        package_length_unit="in",
        package_dimension_order=["package_length"],
    )

    assert "package_length" not in product_payload
    assert "length" not in package_payload
    assert product_payload["length"]["original_value"] == 10
    assert package_payload["package_length"]["original_value"] == 12


def test_build_weight_payload_preserves_net_weight_and_normalizes_imperial() -> None:
    payload = unit_payloads.build_weight_payload(
        net_weight=1.2,
        net_weight_unit="kg",
        display_market="US",
    )

    assert payload["unit_group"] == "weight"
    assert payload["net_weight"]["original_value"] == 1.2
    assert payload["net_weight"]["original_unit"] == "kg"
    assert payload["net_weight"]["normalized_imperial_unit"] == "lb"
    assert_close(payload["net_weight"]["normalized_imperial_value"], 2.65)
    assert payload["net_weight"]["display_unit"] == "lb"
    assert payload["gross_weight"] is None
    assert unit_payloads.collect_payload_errors(payload) == []


def test_weight_payload_without_net_or_gross_returns_weight_value_missing() -> None:
    payload = unit_payloads.build_weight_payload()

    assert payload["net_weight"] is None
    assert payload["gross_weight"] is None
    assert unit_payloads.ERROR_WEIGHT_VALUE_MISSING in payload["errors"]


def test_generic_weight_source_text_does_not_guess_net_or_gross_weight() -> None:
    payload = unit_payloads.build_weight_payload(
        source_text="weight: 2 lb",
        source_language="en",
        parsed_from_text=True,
    )

    assert payload["source_text"] == "weight: 2 lb"
    assert payload["net_weight"] is None
    assert payload["gross_weight"] is None
    assert unit_payloads.ERROR_WEIGHT_VALUE_MISSING in payload["errors"]
    assert unit_payloads.ERROR_NET_VS_GROSS_WEIGHT_AMBIGUOUS in payload["warnings"]
    assert unit_payloads.WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED in payload["warnings"]


def test_build_package_weight_payload_preserves_package_weight_and_normalizes_metric() -> None:
    payload = unit_payloads.build_package_weight_payload(
        package_weight=3,
        package_weight_unit="lb",
        display_market="EU",
    )

    assert payload["unit_group"] == "weight"
    assert "net_weight" not in payload
    assert payload["package_weight"]["original_value"] == 3
    assert payload["package_weight"]["original_unit"] == "lb"
    assert payload["package_weight"]["normalized_metric_unit"] == "kg"
    assert_close(payload["package_weight"]["normalized_metric_value"], 1.36)
    assert payload["shipping_weight"] is None
    assert unit_payloads.collect_payload_errors(payload) == []


def test_package_weight_conflict_validation_rejects_product_weight_keys() -> None:
    payload = unit_payloads.build_package_weight_payload(
        package_weight=3,
        package_weight_unit="lb",
        display_market="US",
    )
    bad_payload = dict(payload)
    bad_payload["net_weight"] = payload["package_weight"]
    bad_payload["gross_weight"] = None

    validation = unit_payloads.validate_package_weight_payload(bad_payload)

    assert validation["is_valid"] is False
    assert unit_payloads.ERROR_PRODUCT_VS_PACKAGE_CONFLICT in validation["errors"]


def test_package_weight_does_not_backfill_product_net_weight() -> None:
    package_payload = unit_payloads.build_package_weight_payload(
        package_weight=3,
        package_weight_unit="lb",
        display_market="US",
    )

    assert "net_weight" not in package_payload
    assert package_payload["package_weight"]["original_value"] == 3


def test_validate_dimensions_payload_valid_case_does_not_mutate_input() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit="cm",
        width=5,
        width_unit="cm",
        height=3,
        height_unit="cm",
        dimension_order=["length", "width", "height"],
        display_market="US",
    )
    before = deepcopy(payload)

    validation = unit_payloads.validate_dimensions_payload(payload)

    assert validation == {"is_valid": True, "errors": [], "warnings": []}
    assert payload == before


def test_validate_package_dimensions_payload_valid_case() -> None:
    payload = unit_payloads.build_package_dimensions_payload(
        package_length=12,
        package_length_unit="in",
        package_width=8,
        package_width_unit="in",
        package_height=4,
        package_height_unit="in",
        package_dimension_order=[
            "package_length",
            "package_width",
            "package_height",
        ],
        display_market="US",
    )

    validation = unit_payloads.validate_package_dimensions_payload(payload)

    assert validation == {"is_valid": True, "errors": [], "warnings": []}


def test_validate_weight_payload_valid_case() -> None:
    payload = unit_payloads.build_weight_payload(
        net_weight=1.2,
        net_weight_unit="kg",
        display_market="US",
    )

    validation = unit_payloads.validate_weight_payload(payload)

    assert validation == {"is_valid": True, "errors": [], "warnings": []}


def test_validate_package_weight_payload_valid_case() -> None:
    payload = unit_payloads.build_package_weight_payload(
        package_weight=3,
        package_weight_unit="lb",
        display_market="EU",
    )

    validation = unit_payloads.validate_package_weight_payload(payload)

    assert validation == {"is_valid": True, "errors": [], "warnings": []}


def test_collect_payload_errors_recursively_finds_nested_unit_value_errors() -> None:
    payload = {
        "nested": [
            {
                "bad_length": unit_conversion.normalize_unit_value(
                    "length",
                    10,
                    "yard",
                )
            },
            {
                "missing_unit": unit_conversion.normalize_unit_value(
                    "length",
                    5,
                    None,
                )
            },
            {
                "missing_value": unit_conversion.normalize_unit_value(
                    "weight",
                    None,
                    "kg",
                )
            },
        ]
    }

    errors = unit_payloads.collect_payload_errors(payload)

    assert unit_conversion.ERROR_UNSUPPORTED_UNIT in errors
    assert unit_conversion.ERROR_MISSING_UNIT in errors
    assert unit_conversion.ERROR_MISSING_VALUE in errors


def test_collect_payload_warnings_recursively_finds_nested_warnings() -> None:
    payload = {
        "warnings": [unit_payloads.WARNING_OPTIONAL_FIELD_MISSING],
        "nested": {
            "weight": unit_conversion.normalize_unit_value(
                "weight",
                1,
                "lb",
                display_market="CA",
            )
        },
    }

    warnings = unit_payloads.collect_payload_warnings(payload)

    assert unit_payloads.WARNING_OPTIONAL_FIELD_MISSING in warnings
    assert unit_conversion.WARNING_MARKET_DISPLAY_UNKNOWN in warnings


def test_ai_structured_source_with_provided_value_and_unit_works_without_review_promotion() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit="cm",
        source_text="length 10 cm",
        parsed_from_text=True,
        conversion_source=AI_SOURCE,
        display_market="US",
    )

    assert payload["length"]["conversion_source"] == AI_SOURCE
    assert payload["length"]["review_status"] == "draft"
    assert payload["review_status"] == "draft"
    assert payload["width"] is None
    assert payload["height"] is None
    assert unit_payloads.collect_payload_errors(payload) == []


def test_ai_structured_source_with_missing_value_does_not_guess() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=None,
        length_unit="cm",
        conversion_source=AI_SOURCE,
    )

    errors = unit_payloads.collect_payload_errors(payload)

    assert unit_conversion.ERROR_MISSING_VALUE in errors
    assert unit_conversion.ERROR_AI_GUESSING_FORBIDDEN in errors
    assert unit_payloads.ERROR_DIMENSION_VALUE_MISSING in errors
    assert payload["width"] is None
    assert payload["height"] is None


def test_ai_structured_source_with_missing_unit_does_not_guess() -> None:
    payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit=None,
        conversion_source=AI_SOURCE,
    )

    errors = unit_payloads.collect_payload_errors(payload)

    assert unit_conversion.ERROR_MISSING_UNIT in errors
    assert unit_conversion.ERROR_AI_GUESSING_FORBIDDEN in errors
    assert payload["width"] is None
    assert payload["height"] is None


def test_ai_structured_source_does_not_create_missing_context_fields() -> None:
    dimensions_payload = unit_payloads.build_dimensions_payload(
        length=10,
        length_unit="cm",
        conversion_source=AI_SOURCE,
    )
    package_weight_payload = unit_payloads.build_package_weight_payload(
        shipping_weight=2,
        shipping_weight_unit="lb",
        conversion_source=AI_SOURCE,
    )
    weight_payload = unit_payloads.build_weight_payload(
        gross_weight=2,
        gross_weight_unit="lb",
        conversion_source=AI_SOURCE,
    )

    assert dimensions_payload["width"] is None
    assert dimensions_payload["height"] is None
    assert package_weight_payload["package_weight"] is None
    assert weight_payload["net_weight"] is None


def test_free_text_dimensions_source_is_not_parsed_without_numeric_arguments() -> None:
    payload = unit_payloads.build_dimensions_payload(
        source_text="10 x 5 x 3 cm",
        parsed_from_text=True,
    )

    assert payload["source_text"] == "10 x 5 x 3 cm"
    assert payload["length"] is None
    assert payload["width"] is None
    assert payload["height"] is None
    assert unit_payloads.ERROR_DIMENSION_VALUE_MISSING in payload["errors"]
    assert unit_payloads.WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED in payload["warnings"]


def test_unit_payloads_does_not_expose_free_text_dimensions_parser_functions() -> None:
    public_function_names = {
        name
        for name, value in inspect.getmembers(unit_payloads, inspect.isfunction)
        if value.__module__ == unit_payloads.__name__ and not name.startswith("_")
    }

    assert "parse_dimensions" not in public_function_names
    assert "parse_dimension_string" not in public_function_names
    assert "normalize_dimensions_json" not in public_function_names
    assert not any("parse" in name.lower() for name in public_function_names)
    assert MODULE_NAME.endswith("unit_payloads")
    assert "def build_dimensions_payload(" in MODULE_PATH.read_text(encoding="utf-8")
