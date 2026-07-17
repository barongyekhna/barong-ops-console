from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from backend.app.modules.k_series.product_knowledge import image_render_jobs
from backend.app.modules.k_series.product_knowledge.prompt_skills import (
    image_art_direction_instruction,
    selling_points_instruction,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowExecutionError,
    _approved_selling_points_snapshot,
    _normalize_evidence_driven_image_brief,
)


pytestmark = pytest.mark.unit


def _points() -> list[dict[str, object]]:
    points = [
        {
            "id": "portable",
            "text": "Nests into its carry bag for compact packing",
            "evidence": "spec:dimensions.height",
            "verification_status": "verified",
        },
        {
            "id": "camp-cooking",
            "text": "Supports real outdoor cooking",
            "evidence": "operator_fact",
            "verification_status": "verified",
        },
    ]
    for point in points:
        snapshot = {
            "evidence": point["evidence"],
            "kind": "operator_fact" if point["evidence"] == "operator_fact" else "spec",
            "value_text": point["text"],
        }
        point["evidence_snapshot"] = snapshot
        point["evidence_digest"] = hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    return points


def _valid_brief() -> dict[str, object]:
    return {
        "image_count": 99,
        "images": [
            {
                "position": 1,
                "role": "main",
                "placement": "description",
                "prompt": "Pure white main.",
                "overlay": {"unsafe": True},
            },
            {
                "position": 2,
                "role": "proof_scene",
                "placement": "gallery",
                "prompt": "Cooking at a real campsite.",
                "selling_point_id": "camp-cooking",
                "proof_intent": "Visible lit burner, simmering pot and rising steam.",
            },
            {
                "position": 3,
                "role": "dimension",
                "placement": "description",
                "prompt": "Clean dimension base.",
                "overlay": {
                    "schema_version": "k-info-overlay-v1",
                    "role": "dimension",
                    "items": [
                        {
                            "type": "dimension",
                            "source_field": "dimensions.height",
                            "line": {
                                "start": {"x": 0.2, "y": 0.2},
                                "end": {"x": 0.2, "y": 0.8},
                            },
                            "text_anchor": {"x": 0.1, "y": 0.5},
                        }
                    ],
                },
            },
        ],
    }


def test_approved_snapshot_never_reads_candidates_or_invents_legacy_evidence() -> None:
    product = SimpleNamespace(
        selling_points_approved_json={
            "review_status": "approved",
            "bullets": _points(),
        },
        ai_warnings_json={
            "selling_points": {
                "review_status": "approved",
                "bullets": [{"text": "stale candidate"}],
            }
        },
    )
    assert [point["id"] for point in _approved_selling_points_snapshot(product)] == [
        "portable",
        "camp-cooking",
    ]

    legacy = SimpleNamespace(
        selling_points_approved_json=None,
        ai_warnings_json={
            "selling_points": {"bullets": [{"text": "Operator approved legacy point"}]},
            "selling_points_review": {"status": "approved"},
        },
    )
    snapshot = _approved_selling_points_snapshot(legacy)
    assert snapshot == []

    candidate_only = SimpleNamespace(
        selling_points_approved_json=None,
        ai_warnings_json={
            "selling_points": {
                "review_status": "candidate",
                "bullets": [{"text": "unreviewed"}],
            }
        },
    )
    assert _approved_selling_points_snapshot(candidate_only) == []


def test_image_brief_binds_proof_and_forces_main_and_dimension_into_gallery() -> None:
    normalized = _normalize_evidence_driven_image_brief(_valid_brief(), _points())

    images = normalized["images"]
    assert normalized["image_count"] == 3
    assert normalized["evidence_contract"] == "selling-points-approved-v1"
    assert normalized["selling_points_digest"]
    assert images[0]["placement"] == "gallery"
    assert images[0]["overlay"] is None
    assert images[1]["selling_point_index"] == 2
    assert images[1]["selling_point_text"] == "Supports real outdoor cooking"
    assert images[2]["placement"] == "gallery"


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda brief: brief["images"].pop(0), "exactly one main"),
        (
            lambda brief: brief["images"][1].pop("selling_point_id"),
            "must bind one approved",
        ),
        (
            lambda brief: brief["images"][1].update({"role": "white_background"}),
            "unsupported role",
        ),
    ],
)
def test_image_brief_rejects_unbound_or_white_secondary_images(
    mutation, message: str
) -> None:
    brief = _valid_brief()
    mutation(brief)
    with pytest.raises(KWorkflowExecutionError, match=message) as caught:
        _normalize_evidence_driven_image_brief(brief, _points())
    assert caught.value.code == "IMAGE_BRIEF_EVIDENCE_CONTRACT_INVALID"


def test_render_boundary_forces_dimension_gallery_and_white_style_only_on_main() -> None:
    dimension = {
        "role": "dimension",
        "placement": "description",
        "overlay": {"role": "dimension"},
    }
    assert image_render_jobs._spec_placement(dimension) == "gallery"
    assert image_render_jobs._HOUSE_STYLE_ROLES == (image_render_jobs.ASSET_ROLE_MAIN,)
    assert "not the storefront main" in image_render_jobs.NON_MAIN_EVIDENCE_BLOCK
    assert "NOT a white-background catalog shot" in image_render_jobs.PROOF_SCENE_BLOCK


def test_prompt_contracts_require_evidence_for_points_and_proof_shots() -> None:
    selling = selling_points_instruction()
    image = image_art_direction_instruction()

    for evidence in ("spec:<field>", "verified_feature:<id>", "operator_fact"):
        assert evidence in selling
    assert "verification_status=unverified" in selling
    assert "selling_points_approved" in image
    assert "selling_point_id" in image
    assert "proof_intent" in image
    assert "NO white-background secondary" in image
    assert "role=dimension is ALWAYS placement=gallery" in image
