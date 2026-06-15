from backend.app.modules.k.k20_risk.ingestion import (
    K20_E_DATA_FLOW,
    K20_E_MODE,
    K20_EXTERNAL_ACCESS,
    K20_RUNTIME,
    RiskIngestionService,
)
from backend.app.modules.k.k20_risk.models import RiskTerm
from backend.app.modules.k.k20_risk.service import RiskService


def _ingestion_service() -> tuple[RiskIngestionService, dict[str, RiskTerm]]:
    store: dict[str, RiskTerm] = {}
    return RiskIngestionService(RiskService(store=store)), store


def test_k20_e_safety_locks_are_ingestion_only() -> None:
    assert K20_E_MODE == "ingestion_only"
    assert K20_RUNTIME == "no_execution"
    assert K20_EXTERNAL_ACCESS is False
    assert K20_E_DATA_FLOW == (
        "K13 output",
        "K17 output",
        "K18 output",
        "K20-E ingestion",
        "K20 RiskTerm storage",
    )


def test_ingest_from_k17_maps_structured_risk_flags_to_risk_terms() -> None:
    ingestion_service, store = _ingestion_service()

    risk_terms = ingestion_service.ingest_from_k17(
        {
            "product_id": "product-1",
            "risk_flags": [
                {
                    "keyword": "Guaranteed Cure",
                    "risk_flag": "high",
                    "category": "legal",
                },
                {
                    "term": "No competitors after rules",
                    "risk_level": "medium",
                    "category": "platform",
                },
            ],
        }
    )

    assert len(risk_terms) == 2
    assert len(store) == 2
    assert risk_terms[0].product_id == "product-1"
    assert risk_terms[0].term == "guaranteed cure"
    assert risk_terms[0].risk_level == "high"
    assert risk_terms[0].category == "legal"
    assert risk_terms[0].source == "K17"


def test_ingest_from_k18_reads_nested_context_risk_flags() -> None:
    ingestion_service, store = _ingestion_service()

    risk_terms = ingestion_service.ingest_from_k18(
        {
            "product_id": "product-2",
            "context": {
                "risk_flags": [
                    {
                        "keyword": "Platform Forbidden Terms",
                        "risk_level": "critical",
                        "category": "compliance",
                    }
                ]
            },
        }
    )

    assert len(risk_terms) == 1
    assert len(store) == 1
    assert risk_terms[0].term == "platform forbidden terms"
    assert risk_terms[0].risk_level == "critical"
    assert risk_terms[0].category == "compliance"
    assert risk_terms[0].source == "K18"


def test_same_term_and_product_merge_with_higher_risk_level_override() -> None:
    ingestion_service, store = _ingestion_service()

    first_terms = ingestion_service.ingest_from_k13(
        {
            "product_id": "product-3",
            "risk_flags": [
                {
                    "keyword": "Miracle Claim",
                    "risk_level": "medium",
                    "category": "marketing",
                }
            ],
        }
    )
    second_terms = ingestion_service.ingest_from_k18(
        {
            "product_id": "product-3",
            "context": {
                "risk_flags": [
                    {
                        "keyword": " miracle claim ",
                        "risk_level": "critical",
                        "category": "legal",
                    }
                ]
            },
        }
    )

    assert len(store) == 1
    assert first_terms[0].id == second_terms[0].id
    stored_term = next(iter(store.values()))
    assert stored_term.term == "miracle claim"
    assert stored_term.risk_level == "critical"
    assert stored_term.category == "legal"
    assert stored_term.source == "K18"


def test_lower_risk_level_does_not_override_existing_term() -> None:
    ingestion_service, store = _ingestion_service()

    ingestion_service.ingest_from_k13(
        {
            "product_id": "product-4",
            "risk_flags": [
                {
                    "keyword": "Medical Claim",
                    "risk_level": "high",
                    "category": "legal",
                }
            ],
        }
    )
    ingestion_service.ingest_from_k17(
        {
            "product_id": "product-4",
            "risk_flags": [
                {
                    "keyword": "medical claim",
                    "risk_level": "low",
                    "category": "platform",
                }
            ],
        }
    )

    assert len(store) == 1
    stored_term = next(iter(store.values()))
    assert stored_term.risk_level == "high"
    assert stored_term.category == "legal"
    assert stored_term.source == "K13"


def test_same_term_different_product_does_not_dedupe() -> None:
    ingestion_service, store = _ingestion_service()

    ingestion_service.ingest_from_k17(
        {
            "product_id": "product-a",
            "risk_flags": [{"keyword": "restricted term", "risk_level": "high"}],
        }
    )
    ingestion_service.ingest_from_k17(
        {
            "product_id": "product-b",
            "risk_flags": [{"keyword": "restricted term", "risk_level": "high"}],
        }
    )

    assert len(store) == 2
    product_ids = {term.product_id for term in store.values()}
    assert product_ids == {"product-a", "product-b"}


def test_batch_duplicates_return_final_merged_record() -> None:
    ingestion_service, store = _ingestion_service()

    risk_terms = ingestion_service.ingest_from_k17(
        {
            "product_id": "product-5",
            "risk_flags": [
                {"keyword": "policy term", "risk_level": "low"},
                {"keyword": " policy term ", "risk_level": "critical"},
            ],
        }
    )

    assert len(risk_terms) == 1
    assert len(store) == 1
    assert risk_terms[0].risk_level == "critical"
    assert next(iter(store.values())).risk_level == "critical"
