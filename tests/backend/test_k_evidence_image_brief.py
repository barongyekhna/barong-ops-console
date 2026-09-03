from __future__ import annotations

import hashlib
import json
import logging
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
    _bind_image_to_selling_point,
    _normalize_evidence_driven_image_brief,
    _validate_image_brief_gallery_composition,
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


def _round4_gallery_brief(
    *,
    include_accessory: bool = True,
    description_count: int = 3,
) -> dict[str, object]:
    images: list[dict[str, object]] = [
        {
            "position": 1,
            "role": "main",
            "placement": "gallery",
            "prompt": "Pure white main.",
        },
        {
            "position": 2,
            "role": "feature_callout",
            "placement": "gallery",
            "prompt": "Clean verified callout base.",
            "overlay": {
                "schema_version": "k-info-overlay-v1",
                "role": "feature_callout",
                "items": [
                    {
                        "type": "callout",
                        "source_field": "material",
                        "anchor": {"x": 0.45, "y": 0.5},
                        "text_anchor": {"x": 0.75, "y": 0.25},
                        "leader_direction": "right",
                    }
                ],
            },
        },
        {
            "position": 3,
            "role": "dimension",
            "placement": "gallery",
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
        {
            "position": 4,
            "role": "proof_scene",
            "placement": "gallery",
            "prompt": "Product in verified real use, angle one.",
            "selling_point_id": "camp-cooking",
            "proof_intent": "Show active outdoor cooking from the front.",
            "scene_motif": "campsite_dinner_cook",
        },
        {
            "position": 5,
            "role": "proof_scene",
            "placement": "gallery",
            "prompt": "Product in verified real use, angle two.",
            "selling_point_id": "camp-cooking",
            "proof_intent": "Show active outdoor cooking from the side.",
            "scene_motif": "backyard_family_lunch",
        },
    ]
    if include_accessory:
        images.append(
            {
                "position": 6,
                "role": "accessory",
                "placement": "gallery",
                "prompt": "Reviewed package contents laid out together.",
                "selling_point_id": "portable",
                "proof_intent": "Show every reviewed included item once.",
            }
        )
    for description_index in range(description_count):
        images.append(
            {
                "position": len(images) + 1,
                "role": "proof_scene",
                "placement": "description",
                "prompt": (
                    "Landscape verified-use scene for description module "
                    f"{description_index + 1}."
                ),
                "selling_point_id": "camp-cooking",
                "proof_intent": (
                    "Show active outdoor cooking in wide composition "
                    f"{description_index + 1}."
                ),
                "scene_motif": f"wide_use_scene_{description_index + 1}",
            }
        )
    return {"images": images}


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


def test_image_brief_binding_exact_id_wins_over_sparse_id_metadata_conflicts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    approved_points = [
        {"id": "bp1", "text": "First approved point"},
        {"id": "bp3", "text": "Third source point, second approved point"},
        {"id": "bp4", "text": "Fourth source point, third approved point"},
    ]

    with caplog.at_level(
        logging.DEBUG,
        logger="backend.app.modules.k_series.product_knowledge.workflow_engine",
    ):
        bound = _bind_image_to_selling_point(
            {
                "selling_point_id": "bp3",
                "selling_point_index": 3,
                "selling_point_text": "Fourth source point, third approved point",
            },
            approved_points,
        )

    assert bound is approved_points[1]
    record = next(
        record
        for record in caplog.records
        if "binding by id" in record.getMessage()
    )
    assert record.selling_point_binding_conflicts == [
        "index_mismatch",
        "text_mismatch",
    ]


def test_image_brief_binding_without_id_still_falls_back_to_index() -> None:
    approved_points = [
        {"id": "bp1", "text": "First approved point"},
        {"id": "bp3", "text": "Third source point, second approved point"},
    ]

    assert _bind_image_to_selling_point(
        {"selling_point_index": 2},
        approved_points,
    ) is approved_points[1]


def test_image_brief_binding_unknown_id_does_not_fall_back() -> None:
    approved_points = [
        {"id": "bp1", "text": "First approved point"},
        {"id": "bp3", "text": "Third source point, second approved point"},
    ]

    assert (
        _bind_image_to_selling_point(
            {
                "selling_point_id": "missing",
                "selling_point_index": 2,
            },
            approved_points,
        )
        is None
    )


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


def test_round4_gallery_quota_ignores_description_images() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(),
        _points(),
    )
    _validate_image_brief_gallery_composition(
        normalized,
        accessory_required=True,
    )

    images = normalized["images"]
    assert isinstance(images, list)
    proof = next(
        image
        for image in images
        if isinstance(image, dict)
        and image.get("role") == "proof_scene"
        and image.get("position") == 5
    )
    proof["placement"] = "description"
    images.append(
        {
            **proof,
            "position": 8,
            "placement": "description",
        }
    )

    with pytest.raises(KWorkflowExecutionError) as caught:
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=True,
        )
    assert caught.value.code == "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID"
    issues = caught.value.error_report["issues"]
    assert any(issue.get("role") == "proof_scene" for issue in issues)
    assert any(issue.get("role") == "gallery_total" for issue in issues)


def test_round6_description_quota_rejects_six_gallery_plus_one_description() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(description_count=1),
        _points(),
    )

    with pytest.raises(KWorkflowExecutionError) as caught:
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=True,
        )

    assert caught.value.code == "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID"
    assert caught.value.error_report["description_proof_scene_minimum"] == 3
    issue = next(
        issue
        for issue in caught.value.error_report["issues"]
        if issue.get("role") == "description_proof_scene"
    )
    assert issue["expected_minimum"] == 3
    assert issue["actual"] == 1
    assert "Image brief composition is invalid" in str(caught.value)


def test_round6_description_quota_counts_only_proof_scene_roles() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(description_count=3),
        _points(),
    )
    description_images = [
        image
        for image in normalized["images"]
        if isinstance(image, dict) and image.get("placement") == "description"
    ]
    description_images[1]["role"] = "detail"
    description_images[2]["role"] = "accessory"

    with pytest.raises(KWorkflowExecutionError) as caught:
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=True,
        )

    issue = next(
        issue
        for issue in caught.value.error_report["issues"]
        if issue.get("role") == "description_proof_scene"
    )
    assert issue["expected_minimum"] == 3
    assert issue["actual"] == 1


def test_round6_description_quota_accepts_six_gallery_plus_three_description() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(description_count=3),
        _points(),
    )

    assert (
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=True,
        )
        is normalized
    )


def test_round4_single_item_accessory_exemption_still_requires_five_gallery_images() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(include_accessory=False),
        _points(),
    )
    _validate_image_brief_gallery_composition(
        normalized,
        accessory_required=False,
    )

    with pytest.raises(KWorkflowExecutionError) as caught:
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=True,
        )
    assert caught.value.error_report["gallery_minimum"] == 6
    assert any(
        issue.get("role") == "accessory"
        for issue in caught.value.error_report["issues"]
    )


def test_dimension_role_cannot_satisfy_quota_without_verified_dimension_evidence() -> None:
    normalized = _normalize_evidence_driven_image_brief(
        _round4_gallery_brief(include_accessory=False),
        _points(),
    )

    with pytest.raises(KWorkflowExecutionError) as caught:
        _validate_image_brief_gallery_composition(
            normalized,
            accessory_required=False,
            dimension_evidence_available=False,
        )

    assert caught.value.code == "IMAGE_BRIEF_GALLERY_COMPOSITION_INVALID"
    dimension_issue = next(
        issue
        for issue in caught.value.error_report["issues"]
        if issue.get("role") == "dimension"
    )
    assert "do not fabricate" in dimension_issue["message"]


def test_render_enqueue_ratio_is_owned_by_placement_not_ai_output() -> None:
    instruction = {"aspect_ratio": "9:16"}
    assert (
        image_render_jobs._resolve_aspect_ratio(
            {"aspect_ratio": "4:5"},
            instruction,
            "dtc",
            image_render_jobs.PLACEMENT_GALLERY,
        )
        == "1:1"
    )
    assert (
        image_render_jobs._resolve_aspect_ratio(
            {"aspect_ratio": "1:1"},
            instruction,
            "dtc",
            image_render_jobs.PLACEMENT_DESCRIPTION,
        )
        == "4:3"
    )


def test_enqueue_persists_forced_ratio_in_each_job_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted: list[dict[str, object]] = []

    class _DB:
        def execute(self, statement, parameters=None, **_kwargs):
            if "INSERT INTO k_image_render_jobs" in str(statement):
                inserted.append(dict(parameters))
            return SimpleNamespace(scalar=lambda: 0)

    product = SimpleNamespace(
        id=uuid4(),
        channel="dtc",
        detected_brand_terms=[],
        image_instruction_json={
            "aspect_ratio": "9:16",
            "images": [
                {
                    "position": 1,
                    "role": "main",
                    "placement": "gallery",
                    "aspect_ratio": "4:3",
                    "prompt": "Pure white product main.",
                },
                {
                    "position": 2,
                    "role": "proof_scene",
                    "placement": "description",
                    "aspect_ratio": "1:1",
                    "prompt": "Wide real-use scene.",
                },
            ],
        },
    )
    monkeypatch.setattr(image_render_jobs, "reference_available", lambda *_args: True)

    _batch_id, jobs = image_render_jobs.enqueue_image_render_jobs(
        _DB(),  # type: ignore[arg-type]
        product=product,  # type: ignore[arg-type]
        user=None,
        scope_context=SimpleNamespace(
            workspace_key="workspace",
            business_context="catalog",
            scope_mode="global",
        ),
    )

    assert len(jobs) == 2
    snapshots = {str(row["placement"]): row for row in inserted}
    assert snapshots["gallery"]["aspect_ratio"] == "1:1"
    assert snapshots["description"]["aspect_ratio"] == "4:3"


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
    assert "at least three separate placement=description proof_scene images" in image
