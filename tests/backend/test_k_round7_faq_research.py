from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.faq_research import (
    build_faq_research,
    is_faq_question_candidate,
    validate_generated_faq,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Is stainless steel vs titanium better for camping cookware?",
        "Is canister gas vs liquid fuel better for winter?",
        "Is alcohol vs white gas better for backpacking?",
        "Is isobutane vs propane better in cold weather?",
        "Is nonstick vs stainless steel easier to clean?",
        "Is gas vs electric cooking more convenient?",
        "Which lasts longer, titanium vs aluminum?",
        "What are pros and cons of propane vs butane?",
    ],
)
def test_generic_comparisons_ignore_trailing_buyer_context(question: str) -> None:
    assert is_faq_question_candidate(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Is LPG suitable for a camping stove?",
        "Are ABS and PVC durable for outdoor gear?",
        "Is PTFE cookware easy to clean?",
        "Is PFOA-free cookware safer?",
        "Is BPA-free plastic suitable for food storage?",
        "Can CO2 canisters be stored in cold weather?",
        "Can a 5000mAh battery power a camping light?",
        "Is LiFePO4 suitable for cold weather?",
        "Is 40 dB quiet enough for camping?",
    ],
)
def test_technical_notations_are_not_treated_as_brands(question: str) -> None:
    assert is_faq_question_candidate(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Are JetMaster stoves reliable?",
        "Can TrailForge cookware be used in winter?",
        "Which is easier to clean, TrailForge or CampNova?",
    ],
)
def test_distinctive_camelcase_brands_are_rejected_anywhere(question: str) -> None:
    assert is_faq_question_candidate(question) is False


def test_brand_patterns_do_not_block_normal_material_or_fuel_questions() -> None:
    assert is_faq_question_candidate("Is stainless steel easy to clean?") is True
    assert is_faq_question_candidate("Is This Camping Cookware Safe?") is True
    assert is_faq_question_candidate("Is Outdoor Cooking Safe?") is True
    assert is_faq_question_candidate("Is propane vs butane better?") is True
    assert is_faq_question_candidate("Is TrailForge cookware safe?") is False
    assert (
        is_faq_question_candidate("Is Odoland vs Coleman better for camping?")
        is False
    )


def test_research_rejects_competitor_questions_and_article_titles() -> None:
    research = build_faq_research(
        [
            {
                "peopleAlsoAsk": [
                    {"question": "Is Odoland a good brand?"},
                    {"question": "Is TrailForge a reliable brand?"},
                    {"question": "Which is better, TrailForge vs CampNova?"},
                    {
                        "question": "How should camping cookware be cleaned after a trip?",
                        "snippet": "Let each piece cool before washing and drying it.",
                    },
                ],
                "organic": [
                    {
                        "title": "Best Camping Cookware of 2026, Tested & Reviewed",
                        "link": "https://example.test/best-cookware",
                    },
                    {
                        "title": "The Best Campfire Cooking Kits Put to the Test",
                        "link": "https://example.test/campfire-kits",
                    },
                    {
                        "title": "Why does food stick to camping cookware?",
                        "link": "https://example.test/cookware-care",
                    },
                ],
            }
        ],
        queries=["camping cookware buyer questions"],
    )

    questions = [source["question"] for source in research["sources"]]
    assert questions == [
        "How should camping cookware be cleaned after a trip?",
        "Why does food stick to camping cookware?",
    ]
    assert all("Odoland" not in question for question in questions)


def test_paa_has_priority_over_duplicate_forum_and_organic_questions() -> None:
    question = "How should camping cookware be stored between trips?"
    research = build_faq_research(
        [
            {
                "organic": [
                    {
                        "title": question,
                        "link": "https://www.reddit.com/r/camping/duplicate",
                    }
                ]
            },
            {"peopleAlsoAsk": [{"question": question}]},
        ],
        queries=["cookware storage forum", "cookware storage"],
    )

    assert len(research["sources"]) == 1
    assert research["sources"][0]["source_type"] == "people_also_ask"
    assert research["sources"][0]["query"] == "cookware storage"


def test_unsafe_paa_duplicate_does_not_hide_safe_forum_fallback() -> None:
    question = "How should camping cookware be stored between trips?"
    research = build_faq_research(
        [
            {
                "peopleAlsoAsk": [
                    {
                        "question": question,
                        "snippet": "Odoland storage advice from a competitor article.",
                    }
                ],
                "organic": [
                    {
                        "title": question,
                        "link": "https://www.reddit.com/r/camping/safe-storage",
                        "snippet": "Dry each piece before packing it away.",
                    }
                ],
            }
        ],
        queries=["camping cookware storage"],
    )

    assert len(research["sources"]) == 1
    assert research["sources"][0]["source_type"] == "forum_question"
    assert research["sources"][0]["source_url"] == (
        "https://www.reddit.com/r/camping/safe-storage"
    )


def test_non_question_review_title_is_rejected_but_normal_forum_question_remains() -> None:
    research = build_faq_research(
        [
            {
                "organic": [
                    {
                        "title": "Odoland Camping Cookware Review",
                        "link": "https://reviews.example.test/odoland",
                    },
                    {
                        "title": "How can I keep a camp stove stable in wind?",
                        "link": "https://www.reddit.com/r/camping/stability",
                    },
                ]
            }
        ],
        queries=["camp stove buyer problems"],
    )

    assert [source["question"] for source in research["sources"]] == [
        "How can I keep a camp stove stable in wind?"
    ]
    assert research["sources"][0]["source_type"] == "forum_question"


def test_persisted_competitor_research_cannot_reach_visible_faq_or_schema() -> None:
    research = {
        "quality_ready": True,
        "sources": [
            {
                "id": "competitor",
                "question": "Is Odoland a good brand?",
                "snippet": "Odoland is discussed in competitor reviews.",
                "intent_cluster": "buyer_concern",
            },
            {
                "id": "care",
                "question": "How should camping cookware be cleaned after a trip?",
                "snippet": "Let it cool, wash it, and dry it fully.",
                "intent_cluster": "maintenance",
            },
        ],
        "clusters": {
            "buyer_concern": ["competitor"],
            "maintenance": ["care"],
        },
    }
    validated = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "Is Odoland a good brand?",
                    "answer": "Odoland appears in competitor reviews.",
                    "evidence_refs": ["competitor"],
                },
                {
                    "question": "How should camping cookware be cleaned after a trip?",
                    "answer": "Let it cool, wash it, and dry it fully.",
                    "evidence_refs": ["care"],
                },
            ]
        },
        research,
    )

    assert [item["question"] for item in validated["page_faq"]] == [
        "How should camping cookware be cleaned after a trip?"
    ]
    assert validated["faq_quality"]["eligible_for_schema"] is False
    assert validated["faq_quality"]["dropped"][0] == {
        "question": "Is Odoland a good brand?",
        "reason": "invalid_question_shape_or_third_party_brand",
    }


def test_competitor_name_in_generated_answer_is_not_publishable() -> None:
    question = "How should camping cookware be stored after a trip?"
    validated = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": question,
                    "answer": "Store it the same way as Odoland cookware.",
                    "evidence_refs": ["storage"],
                }
            ]
        },
        {
            "quality_ready": True,
            "sources": [
                {
                    "id": "storage",
                    "question": question,
                    "snippet": "Dry every piece before storage.",
                    "intent_cluster": "maintenance",
                }
            ],
            "clusters": {"maintenance": ["storage"]},
        },
    )

    assert validated["page_faq"] == []
    assert validated["faq_quality"]["dropped"] == [
        {"question": question, "reason": "third_party_brand_reference"}
    ]
