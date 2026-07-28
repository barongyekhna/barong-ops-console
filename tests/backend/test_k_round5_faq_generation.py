from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.modules.k_series.product_knowledge.faq_research import (
    build_faq_research,
    is_faq_question_candidate,
    validate_generated_faq,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowOrchestratorV2,
    _faq_question_clusters,
)


pytestmark = pytest.mark.unit


def _research() -> dict[str, Any]:
    return {
        "quality_ready": True,
        "sources": [
            {
                "id": "cold-use",
                "question": "How should cookware be used in cold weather?",
                "snippet": "Shelter the cooking area and preheat gradually.",
                "intent_cluster": "cold_weather",
            },
            {
                "id": "care",
                "question": "How should cookware be cleaned after a trip?",
                "snippet": "Let it cool, use mild soap, and dry it fully.",
                "intent_cluster": "maintenance",
            },
            {
                "id": "packing",
                "question": "What is the best way to pack cookware for a trip?",
                "snippet": "Keep dry pieces together and protect contact surfaces.",
                "intent_cluster": "packing",
            },
        ],
        "clusters": {
            "cold_weather": ["cold-use"],
            "maintenance": ["care"],
            "packing": ["packing"],
        },
    }


def test_quality_ready_research_rewrites_to_three_server_bound_faq() -> None:
    research = _research()
    clusters = _faq_question_clusters(research)
    assert [item["intent_cluster"] for item in clusters] == [
        "cold_weather",
        "maintenance",
        "packing",
    ]

    engine = object.__new__(KWorkflowOrchestratorV2)
    calls: list[dict[str, Any]] = []

    def execute_provider(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        calls.append(payload)
        answers = {
            "cold_weather": "Shelter the cooking area and preheat gradually.",
            "maintenance": "Let it cool, use mild soap, and dry it fully.",
            "packing": "Keep dry pieces together and protect contact surfaces.",
        }
        return {
            "page_faq": [
                {
                    **item,
                    "answer": answers[item["intent_cluster"]],
                    # Provider provenance is untrusted and must be discarded.
                    "evidence_refs": ["invented"],
                    "intent_cluster": "invented",
                }
                for item in payload["page_faq"]
            ]
        }

    engine._execute_provider = execute_provider  # type: ignore[method-assign]
    validated = engine._validate_faq_with_single_rewrite(
        {
            "page_faq": [
                {
                    "question": "Is this cookware premium?",
                    "answer": "Yes.",
                }
            ]
        },
        research=research,
        approved_points=[],
        structured_specs={},
        package_includes=[],
        key=SimpleNamespace(),  # type: ignore[arg-type]
        gate_context=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert len(calls) == 1
    assert calls[0]["task"] == "faq_cluster_rewrite"
    assert calls[0]["faq_question_clusters"] == clusters
    assert validated["faq_quality"]["eligible_for_schema"] is True
    assert validated["faq_quality"]["accepted_count"] == 3
    assert validated["faq_quality"]["faq_cluster_rewrite"]["status"] == "succeeded"
    assert [item["evidence_refs"] for item in validated["page_faq"]] == [
        ["cold-use"],
        ["care"],
        ["packing"],
    ]
    assert [item["intent_cluster"] for item in validated["page_faq"]] == [
        "cold_weather",
        "maintenance",
        "packing",
    ]


def test_missing_research_stays_empty_without_a_rewrite_call() -> None:
    engine = object.__new__(KWorkflowOrchestratorV2)
    engine._execute_provider = lambda **_kwargs: pytest.fail(  # type: ignore[method-assign]
        "FAQ provider must not run without quality-ready research"
    )

    validated = engine._validate_faq_with_single_rewrite(
        {
            "page_faq": [
                {
                    "question": "Can I invent a question?",
                    "answer": "No.",
                }
            ]
        },
        research={"quality_ready": False, "sources": [], "clusters": {}},
        approved_points=[],
        structured_specs={},
        package_includes=[],
        key=SimpleNamespace(),  # type: ignore[arg-type]
        gate_context=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert validated["page_faq"] == []
    assert validated["faq_quality"]["eligible_for_schema"] is False


def test_generation_rejects_similar_noncanonical_questions_before_validation() -> None:
    research = _research()
    noncanonical = {
        "page_faq": [
            {
                "question": "How should cookware be prepared in cold weather?",
                "answer": "Shelter the cooking area and preheat gradually.",
                "evidence_refs": ["cold-use"],
            },
            {
                "question": "How should cookware be maintained after a trip?",
                "answer": "Let it cool, use mild soap, and dry it fully.",
                "evidence_refs": ["care"],
            },
            {
                "question": "What is the best method to pack cookware for a trip?",
                "answer": "Keep dry pieces together and protect contact surfaces.",
                "evidence_refs": ["packing"],
            },
        ]
    }
    # The reusable validator keeps its historical evidence-bound paraphrase
    # behavior; the stricter canonical boundary belongs to generation.
    assert validate_generated_faq(noncanonical, research)["faq_quality"][
        "eligible_for_schema"
    ] is True

    engine = object.__new__(KWorkflowOrchestratorV2)
    calls: list[dict[str, Any]] = []

    def execute_provider(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        calls.append(payload)
        answers = {
            "cold_weather": "Shelter the cooking area and preheat gradually.",
            "maintenance": "Let it cool, use mild soap, and dry it fully.",
            "packing": "Keep dry pieces together and protect contact surfaces.",
        }
        return {
            "page_faq": [
                {**item, "answer": answers[item["intent_cluster"]]}
                for item in payload["page_faq"]
            ]
        }

    engine._execute_provider = execute_provider  # type: ignore[method-assign]
    validated = engine._validate_faq_with_single_rewrite(
        noncanonical,
        research=research,
        approved_points=[],
        structured_specs={},
        package_includes=[],
        key=SimpleNamespace(),  # type: ignore[arg-type]
        gate_context=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert len(calls) == 1
    assert [item["question"] for item in validated["page_faq"]] == [
        source["question"] for source in research["sources"]
    ]
    assert [item["evidence_refs"] for item in validated["page_faq"]] == [
        ["cold-use"],
        ["care"],
        ["packing"],
    ]


def test_cluster_projection_skips_spec_question_and_uses_next_source() -> None:
    research = {
        "quality_ready": True,
        "sources": [
            {
                "id": "weight",
                "question": "What is the weight?",
                "intent_cluster": "maintenance",
            },
            {
                "id": "care",
                "question": "How should cookware be cleaned after a trip?",
                "intent_cluster": "maintenance",
            },
            {
                "id": "packing",
                "question": "What is the best way to pack cookware for a trip?",
                "intent_cluster": "packing",
            },
        ],
        "clusters": {
            "maintenance": ["weight", "care"],
            "packing": ["packing"],
        },
    }

    clusters = _faq_question_clusters(research)

    assert len(clusters) == 2
    assert clusters[0]["preferred_question"] == (
        "How should cookware be cleaned after a trip?"
    )
    assert clusters[0]["preferred_evidence_refs"] == ["care"]
    assert [source["id"] for source in clusters[0]["sources"]] == ["care"]


def test_spec_only_research_is_not_marked_quality_ready() -> None:
    research = build_faq_research(
        [
            {
                "peopleAlsoAsk": [
                    {
                        "question": "What is the weight in cold weather?",
                        "snippet": "0.8 kg",
                    },
                    {
                        "question": "What is the capacity in strong wind?",
                        "snippet": "1.4 L",
                    },
                ]
            }
        ],
        queries=["cookware questions"],
    )

    assert research["source_count"] == 2
    assert research["quality_ready"] is False
    assert research["intent_cluster_count"] == 0


@pytest.mark.parametrize("malformed_page_faq", ["not-a-list", {"question": "x"}, 3])
def test_malformed_page_faq_fails_safe_to_empty(malformed_page_faq: Any) -> None:
    validated = validate_generated_faq(
        {"page_faq": malformed_page_faq},
        _research(),
    )

    assert validated["page_faq"] == []
    assert validated["faq_quality"]["eligible_for_schema"] is False


@pytest.mark.parametrize("malformed_refs", ["cold-use", {"id": "cold-use"}, 3])
def test_malformed_evidence_refs_are_dropped(malformed_refs: Any) -> None:
    validated = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "How should cookware be used in cold weather?",
                    "answer": "Shelter the cooking area and preheat gradually.",
                    "evidence_refs": malformed_refs,
                }
            ]
        },
        _research(),
    )

    assert validated["page_faq"] == []
    assert validated["faq_quality"]["dropped"] == [
        {
            "question": "How should cookware be used in cold weather?",
            "reason": "malformed_evidence_refs",
        }
    ]


def test_malfunction_questions_are_rejected_from_faq_candidates() -> None:
    # Device-malfunction / repair questions are post-purchase troubleshooting, not
    # buyer intent, and invite generic answers that can contradict the product
    # (the submersible-pump "check the intake" bug). They must never be candidates.
    for question in (
        "Why does my shower pump keep running but no leak?",
        "Why is my camping shower not working?",
        "Why won't my shower pump turn on?",
        "Why is my pump leaking?",
        "Why does my battery keep draining?",
        "How do I fix a portable shower pump?",
        "How to reset the shower pump?",
    ):
        assert is_faq_question_candidate(question) is False, question


def test_genuine_buyer_questions_survive_the_malfunction_filter() -> None:
    for question in (
        "How does this portable camping shower pump draw water?",
        "Does this portable camping shower heat the water?",
        "How long does the battery last, and how do you recharge it?",
        "Can you adjust the water flow and pause it between rinses?",
        "Is the pump waterproof enough to sit in the water?",
        "What is the best portable shower for camping?",
        "Can I use it with a solar panel?",
        "How do I clean the shower head?",
    ):
        assert is_faq_question_candidate(question) is True, question


def test_faq_prompt_grounds_answers_in_product_mechanism() -> None:
    from backend.app.modules.k_series.product_knowledge.prompt_skills import (
        marketing_copy_instruction,
    )

    prompt = marketing_copy_instruction(channel="dtc")
    # Answers must ground in THIS product's facts, never generic snippet guidance
    # that could contradict the real mechanism; unanswerable clusters are dropped.
    assert "does NOT supply the answer" in prompt
    assert "THIS product's real mechanism" in prompt
    assert "DROP that cluster" in prompt
