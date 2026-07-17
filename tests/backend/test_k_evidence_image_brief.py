from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

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


def test_image_brief_requires_dimension_role_when_dimensions_exist() -> None:
    brief = _valid_brief()
    brief["images"] = [
        image
        for image in brief["images"]
        if isinstance(image, dict) and image.get("role") != "dimension"
    ]

    with pytest.raises(KWorkflowExecutionError, match="must contain a dimension image"):
        _normalize_evidence_driven_image_brief(
            brief,
            _points(),
            require_dimension=True,
        )


def test_render_model_automatically_retries_twice_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("K_IMAGE_RENDER_RETRY_BACKOFF_SECONDS", "0.25")
    outcomes = iter([RuntimeError("provider timeout"), [], ["rendered"]])
    delays: list[float] = []
    calls = 0

    def generate() -> list[object]:
        nonlocal calls
        calls += 1
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = image_render_jobs._generate_candidates_with_retry(
        generate,
        job_id=uuid4(),
        sleep=delays.append,
    )

    assert result == ["rendered"]
    assert calls == 3
    assert delays == [0.25, 0.5]


def test_renderer_never_uses_alicdn_as_an_external_reference_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = SimpleNamespace(
        id=uuid4(),
        reference_image_url="https://cbu01.alicdn.com/supplier-reference.jpg",
    )
    download_calls: list[str] = []

    class _DB:
        commits = 0

        def commit(self) -> None:
            self.commits += 1

    db = _DB()
    monkeypatch.setattr(
        image_render_jobs,
        "_original_photo_assets",
        lambda _db, _product: [],
    )
    monkeypatch.setattr(
        image_render_jobs,
        "download_reference_image",
        lambda url: download_calls.append(url),
    )

    with pytest.raises(image_render_jobs.KImageRenderError) as caught:
        image_render_jobs._resolve_reference_image(db, product)  # type: ignore[arg-type]

    assert caught.value.code == "REFERENCE_IMAGE_MISSING"
    assert download_calls == []
    assert db.commits == 0
    assert image_render_jobs.reference_available(db, product) is False  # type: ignore[arg-type]
    assert (
        image_render_jobs.render_reference_url_fallback_allowed(
            "https://images-na.ssl-images-amazon.com/example.jpg"
        )
        is True
    )


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
    assert "MUST include at least one role=dimension image" in image
