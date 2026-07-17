from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.modules.k_series.product_knowledge.evidence_guard import (
    TitleEvidenceConsistencyError,
    enforce_package_evidence_consistency,
    enforce_title_evidence_consistency,
    package_claim_error,
)
from backend.app.modules.k_series.product_knowledge.faq_research import (
    answer_spec_number_matches,
    structured_spec_number_tokens,
    validate_generated_faq,
)
from backend.app.modules.k_series.product_knowledge.prompt_skills import (
    marketing_copy_instruction,
    selling_points_instruction,
)
from backend.app.modules.k_series.product_knowledge.router import (
    SellingPointBullet,
    _selling_point_support_error,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowOrchestratorV2,
    _copy_evidence_product_snapshot,
    _final_keywords_for_copy,
    _keyword_coverage_receipt,
)


pytestmark = pytest.mark.unit


def test_package_gate_drops_ghost_components_and_downgrades_wrong_piece_count() -> None:
    package = ["Cooking pot", "Pot lid"]
    result = enforce_package_evidence_consistency(
        {
            "seo": {"title": "7-piece camping cookware set with kettle"},
            "product_page_copy": {
                "chunk_sections": [
                    {
                        "heading": "A kettle for camp coffee.",
                        "body": "The set nests neatly for packing.",
                    }
                ]
            },
        },
        package_includes=package,
        structured_specs={},
    )

    rendered = str(
        {
            "seo": result["seo"],
            "product_page_copy": result["product_page_copy"],
        }
    ).casefold()
    assert "kettle" not in rendered
    assert "7-piece" not in rendered
    assert result["package_evidence_consistency"]["status"] == "sanitized"
    assert package_claim_error(
        "A 2-piece set with a pot",
        package_includes=package,
        structured_specs={},
    ) is None
    assert "does not match" in str(
        package_claim_error(
            "A 7-piece set",
            package_includes=package,
            structured_specs={},
        )
    )


@pytest.mark.parametrize(
    "claim",
    [
        "A 7-piece cookware set",
        "A seven-piece cookware set",
        "A set of 7",
        "A set of seven pieces",
    ],
)
def test_package_count_gate_normalizes_numeric_and_word_forms(claim: str) -> None:
    seven_items = [f"Item {index}" for index in range(7)]
    assert package_claim_error(claim, package_includes=seven_items) is None
    assert "does not match" in str(
        package_claim_error(claim, package_includes=["Pot", "Lid"])
    )

    guarded = enforce_package_evidence_consistency(
        {
            "seo": {"title": claim},
            "product_page_copy": {"body": f"Built as {claim.lower()} for camp."},
        },
        package_includes=["Pot", "Lid"],
    )
    rendered = str(guarded).casefold()
    assert claim.casefold() not in rendered
    assert guarded["package_evidence_consistency"]["status"] == "sanitized"
    assert guarded["package_evidence_consistency"]["downgraded_piece_claim_paths"] == [
        "product_page_copy.body",
        "seo.title",
    ]


@pytest.mark.parametrize(
    ("component", "supported_item"),
    [
        ("teapot", "Teapot"),
        ("steamer basket", "Steamer basket"),
        ("kitchen tongs", "Kitchen tongs"),
        ("cutting board", "Cutting board"),
    ],
)
def test_package_component_gate_covers_concrete_cookware_accessories(
    component: str,
    supported_item: str,
) -> None:
    claim = f"Includes a {component} for campsite prep."
    assert "Unsupported package component" in str(
        package_claim_error(claim, package_includes=["Pot", "Lid"])
    )
    assert package_claim_error(claim, package_includes=[supported_item]) is None

    guarded = enforce_package_evidence_consistency(
        {
            "seo": {"title": f"Cookware Set with {component}"},
            "product_page_copy": {"body": claim},
        },
        package_includes=["Pot", "Lid"],
    )
    rendered = str(
        {"seo": guarded["seo"], "copy": guarded["product_page_copy"]}
    ).casefold()
    assert component not in rendered
    assert len(
        guarded["package_evidence_consistency"]["removed_unsupported_components"]
    ) == 2


def test_title_fallback_cannot_restore_unverified_piece_or_component_claims() -> None:
    guarded = enforce_title_evidence_consistency(
        {"seo": {"title": "", "h1": ""}},
        product_name="Seven-piece Camping Cookware Set with Cutting Board",
        product_type="cookware",
        site_brand="Barong",
        approved_selling_points={"bullets": []},
        structured_specs={},
        package_includes=["Pot", "Lid"],
    )

    rendered = str(guarded["seo"]).casefold()
    assert "seven-piece" not in rendered
    assert "cutting" not in rendered
    assert "board" not in rendered
    assert "camping cookware set" in rendered


def test_degenerate_titles_fall_back_to_clean_product_name_en() -> None:
    guarded = enforce_title_evidence_consistency(
        {"seo": {"title": "Product", "h1": "Barong Yekhna"}},
        product_name="DS-308 3-in-1 Portable Camping Cookware",
        product_type="simple_product",
        category_name="Camping Cookware",
        site_brand="Barong Yekhna",
        approved_selling_points={"bullets": []},
        structured_specs={},
    )

    assert guarded["seo"] == {
        "title": "3-in-1 Portable Camping Cookware",
        "h1": "3-in-1 Portable Camping Cookware",
    }
    assert guarded["evidence_consistency"]["product_name_fallback_fields"] == [
        "title",
        "h1",
    ]


def test_degenerate_title_blocks_when_product_name_en_is_also_degenerate() -> None:
    with pytest.raises(
        TitleEvidenceConsistencyError,
        match="product_name_en does not provide at least two meaningful",
    ):
        enforce_title_evidence_consistency(
            {"seo": {"title": "Product", "h1": "Barong Yekhna"}},
            product_name="DS-308 Barong Yekhna Product",
            product_type="simple_product",
            category_name="Camping Cookware",
            site_brand="Barong Yekhna",
            approved_selling_points={"bullets": []},
            structured_specs={},
        )


def test_normal_title_uses_name_category_and_verified_selling_point_corpus_unchanged() -> None:
    title = "Camping Cookware | Trail Stove | Piezo Ignition"
    guarded = enforce_title_evidence_consistency(
        {"seo": {"title": title, "h1": title}},
        product_name="Trail Stove",
        product_type="simple_product",
        category_name="Camping Cookware",
        site_brand="Barong Yekhna",
        approved_selling_points={
            "bullets": [
                {
                    "text": "Piezo ignition starts without a separate lighter",
                    "verification_status": "verified",
                }
            ]
        },
        structured_specs={},
    )

    assert guarded["seo"] == {"title": title, "h1": title}
    assert guarded["evidence_consistency"]["status"] == "passed"
    assert guarded["evidence_consistency"]["product_name_fallback_fields"] == []


def test_selling_point_generation_uses_same_number_and_component_rules_as_approval() -> None:
    snapshot = {
        "kind": "spec",
        "path": "weight",
        "label": "Weight",
        "value_text": "1.6 lb",
    }
    assert "700" in str(
        _selling_point_support_error(
            SellingPointBullet(
                category="weight",
                text="Only 700 g for easy packing",
                importance_score=1,
                evidence="spec:weight",
            ),
            snapshot,
        )
    )
    assert _selling_point_support_error(
        SellingPointBullet(
            category="weight",
            text="Only 1.6 lb for easy packing",
            importance_score=1,
            evidence="spec:weight",
        ),
        snapshot,
    ) is None
    assert "kettle" in str(
        _selling_point_support_error(
            SellingPointBullet(
                category="contents",
                text="Kettle included for camp drinks",
                importance_score=1,
                evidence="spec:material",
            ),
            {"kind": "spec", "path": "material", "value_text": "Aluminum"},
            package_includes=["Cooking pot"],
            structured_specs={"material": {"value": "Aluminum"}},
        )
    )


def test_faq_rejects_raw_spec_numbers_and_package_count_even_when_cited() -> None:
    research = {
        "quality_ready": True,
        "sources": [
            {
                "id": "cold",
                "question": "How should cookware be used in cold weather?",
                "snippet": "Keep it sheltered; 720 g examples are common.",
                "intent_cluster": "cold_weather",
            },
            {
                "id": "wind",
                "question": "How do I keep cookware stable in wind?",
                "snippet": "Use a windbreak and check all 7 pieces.",
                "intent_cluster": "wind_weather",
            },
            {
                "id": "care",
                "question": "How should cookware be cleaned after a trip?",
                "snippet": "Let it cool and use mild soap.",
                "intent_cluster": "maintenance",
            },
        ],
    }
    result = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "How should cookware be used in cold weather?",
                    "answer": "Shelter this 720 g set before cooking.",
                    "evidence_refs": ["cold"],
                },
                {
                    "question": "How do I keep cookware stable in wind?",
                    "answer": "Keep all 7 pieces behind a windbreak.",
                    "evidence_refs": ["wind"],
                },
                {
                    "question": "How should cookware be cleaned after a trip?",
                    "answer": "Let it cool, then use mild soap and dry it fully.",
                    "evidence_refs": ["care"],
                },
            ]
        },
        research,
        structured_specs={"weight": {"value": 720, "unit": "g"}},
        package_includes=[f"Item {index}" for index in range(7)],
    )

    assert [item["question"] for item in result["page_faq"]] == [
        "How should cookware be cleaned after a trip?"
    ]
    assert {
        item["reason"] for item in result["faq_quality"]["dropped"]
    } == {"answer_repeats_product_specification_number"}
    assert structured_spec_number_tokens(
        {"schema_version": "1.0", "dimensions": {"raw_value": "160×110 mm"}}
    ) == {"160", "110"}
    assert structured_spec_number_tokens(
        {"weight": {"value": 0.72, "unit": "kg"}}
    ) == {"0.72", "1.6"}

    converted = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "How should cookware be used in cold weather?",
                    "answer": "Shelter this 1.6 lb set before cooking.",
                    "evidence_refs": ["cold"],
                }
            ]
        },
        research,
        structured_specs={"weight": {"value": 0.72, "unit": "kg"}},
    )
    assert converted["page_faq"] == []
    assert converted["faq_quality"]["dropped"][0]["reason"] == (
        "answer_repeats_product_specification_number"
    )


def test_faq_spec_numbers_ignore_translation_and_additional_spec_metadata() -> None:
    specs = {
        "schema_version": "2.0",
        "source": {
            "platform": "1688",
            "offer_id": "offer-3803",
            "source_url": "https://example.test/items/2025",
        },
        "buyer_translation": {
            "request_digest": "3812deadbeef",
            "completed_request_ids": ["buyer-request-700"],
            "failed_request_ids": ["buyer-request-701"],
        },
        "additional_specs": [
            {
                "key": "series_2026_attribute_9",
                "label": "Series 12 finish",
                "label_en": "Series 12 Finish",
                "value": "Matte black",
                "raw_value": "Matte black",
                "value_en": "Matte black",
            }
        ],
        "weight": {
            "value": 0.72,
            "raw_value": "720 g",
            "unit": "kg",
        },
    }

    tokens = structured_spec_number_tokens(specs)

    assert tokens == {"0.72", "720", "1.6"}
    assert tokens.isdisjoint(
        {"2", "9", "12", "700", "701", "1688", "2025", "2026", "3803", "3812"}
    )
    assert answer_spec_number_matches(
        "The cited 2026 care guide recommends air drying.", specs
    ) == set()
    assert answer_spec_number_matches("It weighs 1.6 lb.", specs) == {"1.6"}


def test_faq_numeric_failure_rewrites_once_and_preserves_research_binding() -> None:
    research = {
        "quality_ready": True,
        "sources": [
            {
                "id": "cold",
                "question": "How should cookware be used in cold weather?",
                "snippet": "Shelter the cooking area before use.",
                "intent_cluster": "cold_weather",
            },
            {
                "id": "care",
                "question": "How should cookware be cleaned after a trip?",
                "snippet": "Let it cool and use mild soap.",
                "intent_cluster": "maintenance",
            },
        ],
    }
    original = {
        "page_faq": [
            {
                "question": "How should cookware be used in cold weather?",
                "answer": "Shelter this 720 g set before cooking.",
                "evidence_refs": ["cold"],
                "intent_cluster": "cold_weather",
            },
            {
                "question": "How should cookware be cleaned after a trip?",
                "answer": "Let it cool, then use mild soap and dry it fully.",
                "evidence_refs": ["care"],
                "intent_cluster": "maintenance",
            },
        ]
    }
    engine = object.__new__(KWorkflowOrchestratorV2)
    calls: list[dict[str, object]] = []

    def execute_provider(**kwargs):
        calls.append(kwargs["payload"])
        return {
            "page_faq": [
                {
                    "question": "How should cookware be used in cold weather?",
                    "answer": "Shelter the cooking area and preheat gradually.",
                    "evidence_refs": ["invented"],
                    "intent_cluster": "invented",
                }
            ]
        }

    engine._execute_provider = execute_provider  # type: ignore[method-assign]
    validated = engine._validate_faq_with_single_rewrite(
        original,
        research=research,
        approved_points=[],
        structured_specs={"weight": {"value": 720, "unit": "g"}},
        package_includes=[],
        key=SimpleNamespace(),  # type: ignore[arg-type]
        gate_context=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert len(calls) == 1
    rewritten = next(
        item
        for item in validated["page_faq"]
        if item["question"] == "How should cookware be used in cold weather?"
    )
    assert rewritten["evidence_refs"] == ["cold"]
    assert rewritten["intent_cluster"] == "cold_weather"
    assert "720" not in rewritten["answer"]
    assert validated["faq_quality"]["numeric_answer_rewrite"]["status"] == "succeeded"


def test_only_risk_approved_keywords_feed_copy_and_coverage_warns_below_sixty_percent() -> None:
    pending = SimpleNamespace(
        risk_approval_log_json={"approved": False},
        final_keyword_set_json={
            "primary_keywords": ["camping cookware set"],
            "secondary_keywords": ["compact camp cookware"],
            "longtail_keywords": ["cookware set for backpacking trips"],
        },
    )
    assert _final_keywords_for_copy(pending) == []
    pending.risk_approval_log_json = {"approved": True}
    keywords = _final_keywords_for_copy(pending)
    assert keywords == [
        "camping cookware set",
        "compact camp cookware",
        "cookware set for backpacking trips",
    ]
    receipt = _keyword_coverage_receipt(
        {
            "seo": {"h1": "Camping Cookware Set"},
            "product_page_copy": {"chunk_sections": []},
        },
        keywords,
    )
    assert receipt["rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert receipt["status"] == "warning"


def test_copy_snapshot_supplies_server_converted_buyer_specs() -> None:
    snapshot = _copy_evidence_product_snapshot(
        SimpleNamespace(
            id="product-1",
            product_key="cookware",
            sku="CCD-003",
            product_name_en="Camping Cookware Set",
            product_type="cookware_set",
            target_market="US",
            structured_specs_json={
                "weight": {"value": 0.72, "unit": "kg"},
            },
            package_includes_json=["Cooking pot", "Pot lid"],
            organization_name="Barong Yekhna",
        )
    )

    assert snapshot["structured_specs_json"]["weight"]["unit"] == "kg"
    assert snapshot["structured_specs_buyer_display"]["rows"][0]["display_value"] == "1.6"
    assert snapshot["structured_specs_buyer_display"]["rows"][0]["display_unit"] == "lb"


def test_round3_prompts_require_imperial_h2_keywords_and_number_safe_faq() -> None:
    selling = selling_points_instruction()
    copy = marketing_copy_instruction("dtc")
    assert "structured_specs_buyer_display" in selling
    assert "customer_translations" in selling
    assert "every number in a bullet MUST appear verbatim" in selling
    assert "final_keywords" in copy
    assert "H2" in copy
    assert "MUST NOT repeat any product-specific numeric" in copy
    assert "What's in the box" in copy
