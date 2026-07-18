from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.faq_research import (
    build_faq_research,
    is_faq_question_candidate,
    sanitize_faq_research,
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
        "Is EVA foam suitable for a sleeping pad?",
        "Can TPR and NBR parts handle cold weather?",
        "Is POM suitable for an outdoor buckle?",
        "Does a 3000 RPM fan provide enough airflow?",
        "Is 50 CFM enough airflow for a tent?",
        "Can a stove hose handle 30 PSI?",
        "Is IPX7 suitable for wet weather?",
        "Is SUS304 cookware easy to clean?",
        "Is UPF50 enough for a camping canopy?",
        "Can USB-C charge a camping light?",
        "Is SUS304 Stainless Steel Safe?",
        "Is IPX7 Protection Enough?",
        "Is UPF50 Fabric Suitable?",
        "Is USB-C Charging Safe?",
        "Is High Carbon Steel Safe?",
        "Is Food Grade Silicone Safe?",
        "Is Borosilicate Glass Safe?",
        "Is Bamboo Cookware Durable?",
        "Is Copper Cookware Durable?",
        "Is Aluminum Alloy Durable?",
        "Is Die-Cast Aluminum Durable?",
        "Is Tempered Glass Safe?",
        "Is Carbon Fiber Durable?",
        "Is Natural Wood Suitable?",
        "Is Polyester Fabric Durable?",
        "Is Ripstop Nylon Durable?",
        "Is Oxford Fabric Durable?",
        "Is Ceramic-Coated Cookware Durable?",
        "Is Enamel-Coated Cookware Durable?",
        "Is Polypropylene Plastic Safe?",
        "Is 40 dBA quiet enough for camping?",
        "Is AC110V suitable for this product?",
        "Is DC12V suitable for this product?",
        "Is AC110 suitable for this product?",
        "Is DC12 suitable for this product?",
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


@pytest.mark.parametrize(
    "question",
    [
        "Are NEMO tents reliable?",
        "Can KELTY cookware be used in winter?",
        "Does GSI make durable camping cookware?",
        "Is Decathlon cookware suitable for backpacking?",
        "Is Yeti cookware suitable for camping?",
        "Are ALPICO tents reliable?",
        "Are ALPICO's tents reliable?",
        "Does ALPICO-brand cookware last?",
        "Is Vango cookware reliable?",
        "Can Vango cookware be used in winter?",
        "Is Tritan cookware suitable for camping?",
        "Is Cordura fabric suitable for camping?",
    ],
)
def test_uppercase_and_titlecase_competitor_entities_are_rejected(
    question: str,
) -> None:
    assert is_faq_question_candidate(question) is False


def test_brand_patterns_do_not_block_normal_material_or_fuel_questions() -> None:
    assert is_faq_question_candidate("Is stainless steel easy to clean?") is True
    assert is_faq_question_candidate("Is This Camping Cookware Safe?") is True
    assert is_faq_question_candidate("Is Outdoor Cooking Safe?") is True
    assert is_faq_question_candidate("Is propane vs butane better?") is True
    assert is_faq_question_candidate("Is Titanium cookware durable?") is True
    assert is_faq_question_candidate("Is Barong Yekhna cookware reliable?") is True
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


def test_competitor_entities_in_source_context_are_removed() -> None:
    research = sanitize_faq_research(
        {
            "status": "completed",
            "quality_ready": True,
            "queries": ["Decathlon camping cookware questions"],
            "sources": [
                {
                    "id": "unsafe-snippet",
                    "question": "How should cookware be stored between trips?",
                    "snippet": "NEMO recommends dry storage.",
                    "source_type": "people_also_ask",
                    "intent_cluster": "maintenance",
                },
                {
                    "id": "unsafe-query",
                    "question": "Can cookware be used in cold weather?",
                    "query": "KELTY cookware questions",
                    "source_type": "people_also_ask",
                    "intent_cluster": "cold_weather",
                },
                {
                    "id": "unsafe-url",
                    "question": "Why does food stick while cooking?",
                    "source_url": "https://gsi.example.test/cookware",
                    "source_type": "organic_question",
                    "intent_cluster": "operation",
                },
                {
                    "id": "unsafe-trademark-snippet",
                    "question": "How can plastic cookware be cleaned?",
                    "snippet": "Tritan plastic is compared with other materials.",
                    "source_type": "organic_question",
                    "intent_cluster": "maintenance",
                },
                {
                    "id": "unsafe-trademark-query",
                    "question": "Can fabric gear handle rain?",
                    "query": "Cordura fabric questions",
                    "source_type": "people_also_ask",
                    "intent_cluster": "wet_weather",
                },
            ],
        }
    )

    assert research["queries"] == []
    assert research["sources"] == []
    assert research["clusters"] == {}
    assert research["quality_ready"] is False


def test_invalid_explicit_source_type_is_dropped_but_legacy_missing_type_remains() -> None:
    research = sanitize_faq_research(
        {
            "status": "completed",
            "quality_ready": True,
            "sources": [
                {
                    "id": "valid-paa",
                    "question": "How should cookware be cleaned after a trip?",
                    "snippet": "Let ABS and PVC pieces cool before cleaning.",
                    "query": "LPG and PTFE cookware care",
                    "source_type": "people_also_ask",
                    "intent_cluster": "maintenance",
                },
                {
                    "id": "legacy-missing-type",
                    "question": "Can cookware be used in cold weather?",
                    "snippet": "LiFePO4 and CO2 guidance uses technical terms.",
                    "intent_cluster": "cold_weather",
                },
                {
                    "id": "invalid-explicit-type",
                    "question": "How can cookware stay stable in wind?",
                    "source_type": "organic_title",
                    "intent_cluster": "wind_weather",
                },
            ],
        }
    )

    assert [source["id"] for source in research["sources"]] == [
        "valid-paa",
        "legacy-missing-type",
    ]
    assert research["source_count"] == 2
    assert research["quality_ready"] is True
    assert research["clusters"] == {
        "maintenance": ["valid-paa"],
        "cold_weather": ["legacy-missing-type"],
    }


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


@pytest.mark.parametrize(
    "brand",
    [
        "Odoland",
        "TrailForge",
        "Vango",
        "Tritan",
        "Cordura",
        "ALPICO's",
        "ALPICO-brand",
    ],
)
def test_competitor_name_in_generated_answer_is_not_publishable(brand: str) -> None:
    question = "How should camping cookware be stored after a trip?"
    validated = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": question,
                    "answer": f"Store it the same way as {brand} cookware.",
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
    assert validated["faq_quality"]["eligible_for_schema"] is False
