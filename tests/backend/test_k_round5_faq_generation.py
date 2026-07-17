from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

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

