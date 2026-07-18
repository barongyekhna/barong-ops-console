from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.modules.k_series.product_knowledge.evidence_guard import (
    enforce_title_evidence_consistency,
)
from backend.app.modules.k_series.product_knowledge.prompt_skills import (
    marketing_copy_instruction,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    _finalize_dtc_seo,
    _truncate_heading,
    _truncate_meta_description,
)
from backend.app.modules.p_series.upload import assemble


pytestmark = pytest.mark.unit


def test_round8_copy_prompt_requires_readable_h1_short_title_and_bounded_meta() -> None:
    instruction = marketing_copy_instruction("dtc")

    assert "not a supplier noun list" in instruction
    assert "lead with the primary keyword" in instruction
    assert "| Barong Yekhna" in instruction
    assert "never over 60 characters" in instruction
    assert "at most 160 characters" in instruction
    assert "nested storage or backpacking" in instruction


def test_dtc_seo_normalizes_ai_h1_title_meta_and_schema_name() -> None:
    long_meta = (
        "Pack a compact cooking setup with nested storage for backpacking trips, "
        "then keep pots and utensils together when every inch of bag space matters. "
        "This extra sentence must not push the metadata beyond its hard limit."
    )
    result = _finalize_dtc_seo(
        {
            "seo": {
                "h1": (
                    "Portable Camping Cookware Mess Kit | "
                    "Nested Pot, Kettle & Pan Set"
                ),
                "title": (
                    "Portable Camping Cookware Mess Kit Nested Pot Kettle Pan "
                    "Tableware Set"
                ),
                "meta_description": long_meta,
            },
            "json_ld": {
                "data": {
                    "@type": "Product",
                    "name": "Supplier Keyword Noun String",
                    "description": "Evidence-safe description",
                }
            },
        },
        final_keywords=["portable camping cookware mess kit"],
        site_brand="Barong Yekhna",
        structured_specs={},
    )

    seo = result["seo"]
    assert seo["h1"].startswith("Portable Camping Cookware Mess Kit")
    assert " – " in seo["h1"]
    assert len(seo["h1"]) <= 70
    assert seo["title"] == (
        "Portable Camping Cookware Mess Kit | Barong Yekhna"
    )
    assert len(seo["title"]) <= 60
    assert len(seo["meta_description"]) <= 160
    assert result["json_ld"]["data"]["name"] == seo["h1"]
    assert result["json_ld"]["data"]["description"] == (
        "Evidence-safe description"
    )


def test_dtc_seo_product_name_fallback_is_rewritten_not_republished_verbatim() -> None:
    supplier_fallback = (
        "Cookware Mess Kit Outdoor Camping Pot Kettle Pan Tableware Set"
    )
    result = _finalize_dtc_seo(
        {"seo": {"h1": supplier_fallback, "title": supplier_fallback}},
        final_keywords=["camping cookware mess kit"],
        site_brand="Barong Yekhna",
        structured_specs={},
    )

    seo = result["seo"]
    assert seo["h1"] != supplier_fallback
    assert seo["h1"].startswith("Camping Cookware Mess Kit – ")
    assert len(seo["h1"]) <= 70
    assert seo["title"] == "Camping Cookware Mess Kit | Barong Yekhna"
    assert len(seo["title"]) <= 60


def test_dtc_seo_fallback_without_keywords_still_breaks_up_supplier_noun_list() -> None:
    supplier_fallback = (
        "Cookware Mess Kit Outdoor Camping Pot Kettle Pan Tableware Set"
    )
    result = _finalize_dtc_seo(
        {"seo": {"h1": supplier_fallback, "title": supplier_fallback}},
        final_keywords=[],
        site_brand="Barong Yekhna",
        structured_specs={},
    )

    seo = result["seo"]
    assert seo["h1"] != supplier_fallback
    assert " – " in seo["h1"]
    assert len(seo["h1"]) <= 70
    assert seo["title"].endswith(" | Barong Yekhna")
    assert len(seo["title"]) <= 60


def test_malformed_provider_seo_uses_the_same_safe_identity_fallback() -> None:
    guarded = enforce_title_evidence_consistency(
        {"seo": ["not", "an", "object"]},
        product_name="Portable Camp Stove Cooking Burner Outdoor Equipment",
        product_type="camp_stove",
        site_brand="Barong Yekhna",
        approved_selling_points={"bullets": []},
        structured_specs={},
    )
    result = _finalize_dtc_seo(
        guarded,
        final_keywords=[],
        site_brand="Barong Yekhna",
        structured_specs={},
    )

    assert result["seo"]["h1"].startswith("Portable Camp Stove")
    assert " – " in result["seo"]["h1"]
    assert result["seo"]["title"].endswith(" | Barong Yekhna")


def test_dtc_seo_promotes_legacy_description_to_bounded_meta_description() -> None:
    result = _finalize_dtc_seo(
        {
            "seo": {
                "h1": "Portable Camp Stove",
                "title": "Portable Camp Stove",
                "description": "Nested storage for backpacking trips. " * 10,
            }
        },
        final_keywords=["portable camp stove"],
        site_brand="Barong Yekhna",
        structured_specs={},
    )

    assert result["seo"]["meta_description"]
    assert len(result["seo"]["meta_description"]) <= 160


def test_meta_description_truncates_on_a_natural_boundary() -> None:
    meta = " ".join(["Backpacking cookware with nested storage"] * 8)

    truncated = _truncate_meta_description(meta)

    assert len(truncated) <= 160
    assert truncated.endswith(".")
    assert not truncated.endswith("storage storage.")


def test_h1_boundary_truncation_drops_incomplete_numeric_or_preposition_tail() -> None:
    numeric = _truncate_heading(
        "Portable Camping Cookware Mess Kit for 2-3 People", 45
    )
    preposition = _truncate_heading(
        "Portable Camping Cookware Mess Kit for Backpacking Trips", 39
    )

    assert numeric == "Portable Camping Cookware Mess Kit"
    assert not numeric.endswith("2-3")
    assert not preposition.casefold().endswith(" for")


def test_p_series_projects_the_normalized_h1_and_short_meta_title() -> None:
    copy = _finalize_dtc_seo(
        {
            "seo": {
                "h1": "Portable Camp Stove | Piezo Ignition",
                "title": "Provider Long Title That Must Not Reach Woo",
                "meta_description": "A compact stove for campsite meals.",
            }
        },
        final_keywords=["portable camp stove"],
        site_brand="Barong Yekhna",
        structured_specs={},
    )
    product = SimpleNamespace(
        product_name_en="Supplier Stove Keyword String",
        product_key="stove",
        seo_title_en="Legacy title",
        seo_description_en="Legacy description",
    )

    assert assemble._title_for_upload(copy, product) == copy["seo"]["h1"]
    seo = assemble._seo_for_upload(copy, product)
    assert seo.title == "Portable Camp Stove | Barong Yekhna"
    assert seo.description == "A compact stove for campsite meals."
