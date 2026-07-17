from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from backend.app.db.base import Base
from backend.app.models.user import User
from backend.app.modules.k_series.product_knowledge.faq_research import (
    build_faq_research,
    faq_schema_is_eligible,
    validate_generated_faq,
)
from backend.app.modules.k_series.product_knowledge.evidence_guard import (
    enforce_title_evidence_consistency,
    project_approved_selling_points,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeAttribute,
    KProductKnowledgeProduct,
)
from backend.app.modules.k_series.product_knowledge.router import (
    ApproveSellingPointsRequest,
    SellingPointBullet,
    _selling_point_evidence_error,
    _selling_point_evidence_snapshot,
    _selling_point_support_error,
    _selling_points_snapshot,
    _structured_spec_path_exists,
    approve_product_selling_points,
)
from backend.app.modules.k_series.product_knowledge.schemas import ProductKnowledgeUpdate
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import update_product
from backend.app.modules.p_series.upload.assemble import (
    _evidence_gate_blockers,
    _title_for_upload,
)


pytestmark = pytest.mark.unit


def _approved_point(text: str = "Operator verified compact storage") -> dict:
    snapshot = {
        "evidence": "operator_fact",
        "kind": "operator_fact",
        "value_text": text,
    }
    return {
        "id": "manual-1",
        "category": "operator",
        "text": text,
        "importance_score": 1,
        "evidence": "operator_fact",
        "evidence_excerpt": text,
        "evidence_snapshot": snapshot,
        "evidence_digest": hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "verification_status": "verified",
        "review_decision": "approve",
    }


def test_selling_point_evidence_resolves_specs_features_and_operator_fact() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="evidence-test",
        structured_specs_json={
            "schema_version": "1.0",
            "source": {"platform": "operator", "evidence_type": "operator_fact"},
            "material": {
                "value": "Stainless steel",
                "raw_value": "Stainless steel",
                "source_label": "Material",
                "evidence": "operator_fact",
            },
            "additional_specs": [
                {
                    "key": "ignition_type",
                    "label": "Ignition Type",
                    "value": "Piezo",
                    "raw_value": "Piezo",
                }
            ],
        },
    )
    db.add(product)
    db.flush()
    feature = KProductKnowledgeAttribute(
        id=uuid4(),
        product_id=product.id,
        attribute_key="folding_legs",
        attribute_value_text="Yes",
        source="operator",
        requires_review=False,
    )
    db.add(feature)
    db.commit()

    assert _structured_spec_path_exists(product.structured_specs_json, "material")
    assert _structured_spec_path_exists(product.structured_specs_json, "ignition_type")
    assert _selling_point_evidence_error(db, product, "spec:material") is None
    assert _selling_point_evidence_error(db, product, "spec:ignition_type") is None
    assert (
        _selling_point_evidence_error(
            db, product, f"verified_feature:{feature.id}"
        )
        is None
    )
    assert _selling_point_evidence_error(db, product, "operator_fact") is None
    assert "not found" in str(
        _selling_point_evidence_error(db, product, "spec:windproof")
    )


def test_faq_research_keeps_paa_and_forum_evidence_and_drops_spec_repeats() -> None:
    research = build_faq_research(
        [
            {
                "peopleAlsoAsk": [
                    {
                        "question": "Does a cassette stove lose power at high altitude?",
                        "snippet": "Performance can change as elevation rises.",
                    },
                    {
                        "question": "Can a butane stove work in cold weather?",
                        "snippet": "Cold affects canister pressure.",
                    },
                ],
                "organic": [
                    {
                        "title": "Why will my camping stove not light?",
                        "link": "https://www.reddit.com/r/camping/example",
                        "snippet": "Buyers discuss ignition and fuel issues.",
                    }
                ],
            }
        ],
        queries=["portable cassette stove questions"],
    )
    assert research["quality_ready"] is True
    refs = [item["id"] for item in research["sources"]]

    validated = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "Will this cassette stove lose power at high altitude?",
                    "answer": "Flame output can change with elevation; plan extra cooking time and follow the fuel maker's guidance.",
                    "evidence_refs": [refs[0]],
                },
                {
                    "question": "Can this butane stove work in cold weather?",
                    "answer": "Keep the approved fuel canister within its stated temperature range and never heat the canister directly.",
                    "evidence_refs": [refs[1]],
                },
                {
                    "question": "What is the weight?",
                    "answer": "It weighs 2 lb.",
                    "evidence_refs": [refs[0]],
                },
                {
                    "question": "Is it windproof?",
                    "answer": "Yes.",
                    "evidence_refs": ["made-up-source"],
                },
                {
                    "question": "Why will this camping stove not light?",
                    "answer": "It will run for 99 hours after ignition.",
                    "evidence_refs": [refs[2]],
                },
            ]
        },
        research,
    )

    assert len(validated["page_faq"]) == 2
    assert validated["faq_quality"]["eligible_for_schema"] is True
    assert faq_schema_is_eligible(validated) is True
    assert {item["reason"] for item in validated["faq_quality"]["dropped"]} == {
        "missing_serper_evidence",
        "specification_paraphrase",
        "answer_contains_unsupported_number",
    }


def test_unsupported_title_claims_are_removed_and_entities_are_decoded() -> None:
    guarded = enforce_title_evidence_consistency(
        {
            "seo": {
                "title": "Portable Cassette Stove | Windproof Home Use",
                "h1": "Portable Cassette Stove &amp; Piezo Ignition",
            }
        },
        product_name="Portable Cassette Stove",
        product_type="cassette stove",
        site_brand="Barong Yekhna",
        approved_selling_points={
            "bullets": [
                {
                    "text": "Piezo ignition starts without a separate lighter",
                    "verification_status": "verified",
                }
            ]
        },
        structured_specs=None,
    )

    assert guarded["seo"]["title"] == "Portable Cassette Stove"
    assert guarded["seo"]["h1"] == "Portable Cassette Stove & Piezo Ignition"
    assert guarded["evidence_consistency"]["removed_unsupported_title_segments"] == {
        "title": ["Windproof Home Use"]
    }


def test_irrelevant_specs_changed_numbers_and_untrusted_features_are_rejected() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="support-check",
        structured_specs_json={
            "schema_version": "1.0",
            "source": {"platform": "operator"},
            "color": {"value": "Red", "raw_value": "Red"},
            "runtime_h": {"value": 2, "raw_value": "2 h", "unit": "h"},
        },
    )
    db.add(product)
    db.flush()
    untrusted = KProductKnowledgeAttribute(
        id=uuid4(),
        product_id=product.id,
        attribute_key="wind_guard",
        attribute_value_text="Yes",
        source="claude_opus",
        requires_review=False,
    )
    db.add(untrusted)
    db.commit()

    color, error = _selling_point_evidence_snapshot(db, product, "spec:color")
    assert error is None and color is not None
    assert "wind" in str(
        _selling_point_support_error(
            SellingPointBullet(
                category="performance",
                text="Windproof performance in strong gusts",
                importance_score=1,
                evidence="spec:color",
                review_decision="approve",
            ),
            color,
        )
    ).lower()

    runtime, error = _selling_point_evidence_snapshot(db, product, "spec:runtime_h")
    assert error is None and runtime is not None
    assert "10" in str(
        _selling_point_support_error(
            SellingPointBullet(
                category="runtime",
                text="Runs for 10 hours",
                importance_score=1,
                evidence="spec:runtime_h",
                review_decision="approve",
            ),
            runtime,
        )
    )
    assert "trusted/operator" in str(
        _selling_point_evidence_error(
            db, product, f"verified_feature:{untrusted.id}"
        )
    )
    _, operator_error = _selling_point_evidence_snapshot(
        db, product, "operator_fact", operator_excerpt=None
    )
    assert "evidence_excerpt" in str(operator_error)


def test_fact_change_invalidates_approved_points_copy_faq_and_image_brief() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="invalidation-check",
        workspace_key="org-evidence",
        business_context="independent_store",
        scope_mode="production",
        structured_specs_json={
            "schema_version": "1.0",
            "source": {"platform": "operator", "evidence_type": "operator_fact"},
            "additional_specs": [
                {"key": "runtime", "label": "Runtime", "value": "2 h"}
            ],
        },
        selling_points_candidates_json={"bullets": [{"text": "Old"}]},
        selling_points_approved_json={
            "review_status": "approved",
            "bullets": [_approved_point()],
        },
        faq_research_json={"quality_ready": True},
        marketing_copy_json={"evidence_contract": "pdp-evidence-v1"},
        image_instruction_json={"images": []},
        ai_warnings_json={"selling_points": {}, "selling_points_review": {}, "keep": True},
    )
    db.add(product)
    db.commit()

    changed = update_product(
        db,
        product_id=product.id,
        payload=ProductKnowledgeUpdate(
            structured_specs_json={
                "schema_version": "1.0",
                "source": {"platform": "operator"},
                "additional_specs": [
                    {"key": "runtime", "label": "Runtime", "value": "3 h"}
                ],
            }
        ),
        scope_context=KScopeContext(
            workspace_key="org-evidence",
            business_context="independent_store",
            scope_mode="production",
        ),
    )

    assert changed.selling_points_candidates_json is None
    assert changed.selling_points_approved_json is None
    assert changed.faq_research_json is None
    assert changed.marketing_copy_json is None
    assert changed.image_instruction_json is None
    assert changed.ai_warnings_json == {"keep": True}


def test_p_gate_rejects_candidates_and_stale_copy_and_uses_guarded_h1() -> None:
    point = _approved_point()
    product = SimpleNamespace(
        selling_points_approved_json=None,
        structured_specs_json=None,
        marketing_copy_json={},
        product_name_en="Old &amp; Unsupported H1",
        product_key="fallback",
    )
    assert "逐条证据审批" in _evidence_gate_blockers(product)[0]

    product.selling_points_approved_json = {
        "review_status": "approved",
        "bullets": [point],
    }
    points = [point]
    evidence_digest = hashlib.sha256(
        json.dumps(
            {
                "selling_points_approved": points,
                "structured_specs_json": None,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    product.marketing_copy_json = {
        "evidence_contract": "pdp-evidence-v1",
        "evidence_digest": evidence_digest,
        "seo": {"h1": "Guarded &amp; Clean H1"},
    }
    assert _evidence_gate_blockers(product) == []
    assert _title_for_upload(product.marketing_copy_json, product) == "Guarded & Clean H1"

    product.structured_specs_json = {"runtime_h": {"value": 3}}
    assert "过期" in _evidence_gate_blockers(product)[0]


def test_customer_bullet_grid_is_exactly_the_approved_set() -> None:
    projected = project_approved_selling_points(
        {
            "product_page_copy": {
                "key_bullets": ["Invented windproof claim"],
                "chunk_sections": [],
            }
        },
        [_approved_point("Operator verified compact storage")],
    )
    assert projected["product_page_copy"]["key_bullets"] == [
        "Operator verified compact storage"
    ]


def test_manual_approval_rejects_duplicate_ids_and_freezes_evidence_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="approval-check",
        workspace_key="org-approval",
        business_context="independent_store",
        scope_mode="production",
        canonical_language="en",
    )
    db.add(product)
    db.commit()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.org_id = "org-approval"
    user = User(id=7, username="reviewer", password_hash="x", role="owner", is_active=True)

    duplicate = ApproveSellingPointsRequest(
        bullets=[
            SellingPointBullet(
                id="same-id",
                category="operator",
                text="Compact storage",
                importance_score=1,
                evidence="operator_fact",
                evidence_excerpt="Operator verified compact storage",
                review_decision="approve",
            ),
            SellingPointBullet(
                id="same-id",
                category="operator",
                text="Easy storage",
                importance_score=1,
                evidence="operator_fact",
                evidence_excerpt="Operator verified easy storage",
                review_decision="approve",
            ),
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        approve_product_selling_points(product.id, duplicate, request, db, user)
    assert "Duplicate selling-point id" in str(exc_info.value.detail)

    response = approve_product_selling_points(
        product.id,
        ApproveSellingPointsRequest(
            bullets=[
                SellingPointBullet(
                    id="manual-unique",
                    category="operator",
                    text="Compact storage",
                    importance_score=1,
                    evidence="operator_fact",
                    evidence_excerpt="Operator verified compact storage",
                    review_decision="approve",
                )
            ]
        ),
        request,
        db,
        user,
    )
    assert response.bullets[0].verification_status == "verified"
    assert response.bullets[0].evidence_snapshot == {
        "evidence": "operator_fact",
        "kind": "operator_fact",
        "value_text": "Operator verified compact storage",
    }
    assert len(response.bullets[0].evidence_digest or "") == 64
    db.refresh(product)
    assert _selling_points_snapshot(product)["digest"] == (
        product.ai_warnings_json["selling_points_review"]["selling_points_digest"]
    )
