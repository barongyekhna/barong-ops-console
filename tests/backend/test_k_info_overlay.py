from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from backend.app.modules.k_series.product_knowledge import image_render_jobs
from backend.app.modules.k_series.product_knowledge.info_overlay import (
    OVERLAY_SCHEMA_VERSION,
    OVERLAY_SOURCE_FIELDS,
    _FONT_CANDIDATES,
    _font,
    _foreground_bbox,
    _snapped_dimension_geometry,
    _text_box,
    OverlayContractError,
    compose_info_overlay,
    normalize_overlay_contract,
    resolve_structured_spec_text,
)


pytestmark = pytest.mark.unit


def _png() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (800, 600), "#f7f6f4")
    ImageDraw.Draw(image).rounded_rectangle(
        (250, 120, 550, 500), radius=30, fill="#355b48"
    )
    image.save(output, format="PNG")
    return output.getvalue()


def _png_at_size(width: int, height: int) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (width, height), "#f7f6f4")
    ImageDraw.Draw(image).rounded_rectangle(
        (
            round(width * 0.30),
            round(height * 0.20),
            round(width * 0.70),
            round(height * 0.82),
        ),
        radius=max(8, round(min(width, height) * 0.04)),
        fill="#355b48",
    )
    image.save(output, format="PNG")
    return output.getvalue()


def _overlay() -> dict[str, object]:
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "role": "feature_callout",
        "items": [
            {
                "type": "callout",
                "source_field": "ip_rating",
                "label": "10-year guaranteed waterproof",
                "anchor": {"x": 0.42, "y": 0.50},
                "text_anchor": {"x": 0.68, "y": 0.28},
                "leader_direction": "right",
            },
            {
                "type": "dimension",
                "source_field": "dimensions.height",
                "label": "Model-authored height claim",
                "line": {
                    "start": {"x": 0.15, "y": 0.20},
                    "end": {"x": 0.15, "y": 0.80},
                },
                "text_anchor": {"x": 0.12, "y": 0.50},
            },
        ],
    }


def _verified_specs() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source": {
            "platform": "1688",
            "offer_id": "123456",
            "url": "https://detail.1688.com/offer/123456.html",
        },
        "ip_rating": {
            "value": "IP65",
            "raw_value": "防护等级 IP65",
            "source_label": "防护等级",
        },
        "dimensions": {
            "height": {
                "value": 42,
                "unit": "cm",
                "raw_value": "42厘米",
                "source_label": "高度",
            },
            "unit": "cm",
            "raw_value": "42 x 12厘米",
            "source_label": "尺寸",
        },
        "runtime_h": {
            "value": {"min": 8, "max": 12},
            "unit": "h",
            "raw_value": "8-12小时",
            "source_label": "续航时间",
        },
        "weight": {
            "value": 2,
            "unit": "kg",
            "raw_value": "2千克",
            "source_label": "重量",
        },
        "material": {
            "value": "304 stainless steel",
            "raw_value": "304不锈钢",
            "source_label": "材质",
        },
    }


def test_overlay_resolves_only_supplier_backed_evidence_values() -> None:
    specs = _verified_specs()

    assert resolve_structured_spec_text(specs, "ip_rating") == "IP rating: IP65"
    assert (
        resolve_structured_spec_text(
            specs,
            "dimensions.height",
            label="Invented model label is ignored",
        )
        == "Height: 42 cm"
    )
    assert resolve_structured_spec_text(specs, "lumens") is None
    assert resolve_structured_spec_text(specs, "runtime_h") == "Runtime: 8–12 h"


def test_overlay_contract_rejects_unbound_text_and_bad_coordinates() -> None:
    value = _overlay()
    first = value["items"][0]  # type: ignore[index]
    assert isinstance(first, dict)
    first.pop("source_field")
    first["text"] = "IP68"

    with pytest.raises(OverlayContractError, match="source_field"):
        normalize_overlay_contract(value)

    value = _overlay()
    first = value["items"][0]  # type: ignore[index]
    assert isinstance(first, dict)
    first["anchor"] = {"x": 1.2, "y": 0.5}
    with pytest.raises(OverlayContractError, match="between 0 and 1"):
        normalize_overlay_contract(value)


def test_us_overlay_converts_metric_display_only() -> None:
    specs = _verified_specs()

    assert (
        resolve_structured_spec_text(
            specs,
            "dimensions.height",
            target_market="US",
        )
        == "Height: 16.5 in"
    )
    assert (
        resolve_structured_spec_text(specs, "weight", target_market="en-US")
        == "Weight: 4.4 lb"
    )
    assert resolve_structured_spec_text(specs, "weight") == "Weight: 2 kg"
    # Display conversion never mutates the canonical metric evidence.
    assert specs["dimensions"]["height"]["value"] == 42  # type: ignore[index]

def test_overlay_contract_allowlists_source_paths_and_drops_model_labels() -> None:
    normalized = normalize_overlay_contract(_overlay())
    assert normalized is not None
    assert all("label" not in item for item in normalized["items"])
    assert "ip_rating" in OVERLAY_SOURCE_FIELDS

    for source_field in ("source.url", "schema_version", "dimensions.unit"):
        value = _overlay()
        first = value["items"][0]  # type: ignore[index]
        assert isinstance(first, dict)
        first["source_field"] = source_field
        with pytest.raises(OverlayContractError, match="not an allowed"):
            normalize_overlay_contract(value)


def test_overlay_composes_callout_and_dimension_then_reports_missing_specs() -> None:
    source = _png()
    specs = _verified_specs()

    rendered, report = compose_info_overlay(source, _overlay(), specs)

    assert rendered != source
    assert report == {"status": "applied", "applied_items": 2, "warnings": []}
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (800, 600)
        assert image.format == "PNG"

    rendered, report = compose_info_overlay(source, _overlay(), {})
    assert rendered == source
    assert report["status"] == "skipped_unverified_specs"
    assert report["applied_items"] == 0
    assert report["warnings"] == [
        "unverified structured specs: schema_version must be 1.0",
    ]


def test_provider_dimension_overlay_cannot_render_without_verified_evidence() -> None:
    source = _png()
    provider_overlay = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "role": "dimension",
        "items": [
            {
                "type": "dimension",
                "source_field": "dimensions.height",
                "line": {
                    "start": {"x": 0.15, "y": 0.2},
                    "end": {"x": 0.15, "y": 0.8},
                },
                "text_anchor": {"x": 0.1, "y": 0.5},
            }
        ],
    }

    rendered, report = compose_info_overlay(source, provider_overlay, {})

    assert rendered == source
    assert report == {
        "status": "skipped_unverified_specs",
        "applied_items": 0,
        "warnings": ["unverified structured specs: schema_version must be 1.0"],
    }


@pytest.mark.parametrize("size", [(1200, 900), (1200, 675)])
def test_overlay_uses_actual_non_square_canvas_dimensions(
    size: tuple[int, int],
) -> None:
    source = _png_at_size(*size)

    rendered, report = compose_info_overlay(
        source,
        _overlay(),
        _verified_specs(),
        target_market="US",
    )

    assert report == {"status": "applied", "applied_items": 2, "warnings": []}
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == size


def test_callout_spec_and_imperial_dimension_roles_all_render_verified_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.modules.k_series.product_knowledge import info_overlay

    source = _png()
    specs = _verified_specs()
    rendered_labels: list[str] = []
    original_draw_label = info_overlay._draw_label

    def capture_label(*args, **kwargs):
        rendered_labels.append(str(kwargs.get("text") or ""))
        return original_draw_label(*args, **kwargs)

    monkeypatch.setattr(info_overlay, "_draw_label", capture_label)
    for role, source_field, expected in (
        ("feature_callout", "ip_rating", "IP65"),
        ("spec", "material", "304 stainless steel"),
        ("dimension", "dimensions.height", "16.5"),
    ):
        item = {
            "type": "callout",
            "source_field": source_field,
            "anchor": {"x": 0.5, "y": 0.5},
            "text_anchor": {"x": 0.82, "y": 0.2},
            "leader_direction": "right",
        }
        if role == "dimension":
            item = {
                "type": "dimension",
                "source_field": source_field,
                "line": {
                    "start": {"x": 0.15, "y": 0.2},
                    "end": {"x": 0.15, "y": 0.8},
                },
                "text_anchor": {"x": 0.1, "y": 0.5},
            }
        overlay = {
            "schema_version": OVERLAY_SCHEMA_VERSION,
            "role": role,
            "items": [item],
        }
        rendered_labels.clear()
        rendered, report = compose_info_overlay(
            source,
            overlay,
            specs,
            target_market="US",
        )
        assert rendered != source
        assert report == {"status": "applied", "applied_items": 1, "warnings": []}
        assert any(expected in label for label in rendered_labels)
        if role == "dimension":
            assert any("in" in label.lower() for label in rendered_labels)


def test_dimension_geometry_snaps_to_detected_product_bounds() -> None:
    with Image.open(BytesIO(_png())) as image:
        bbox = _foreground_bbox(image)
    assert bbox is not None
    left, top, right, bottom = bbox
    assert 240 <= left <= 260
    assert 110 <= top <= 130
    assert 540 <= right <= 560
    assert 490 <= bottom <= 510

    start, end, label_anchor, direction = _snapped_dimension_geometry(
        source_field="dimensions.height",
        foreground_bbox=bbox,
        text_anchor=(20, 300),
        image_size=(800, 600),
    )
    assert start[1] == top
    assert end[1] == bottom
    assert start[0] == end[0] < left
    assert direction == "left"
    assert 0 <= label_anchor[0] < 800


def test_overlay_text_box_wraps_long_tokens_and_stays_inside_canvas() -> None:
    image = Image.new("RGBA", (220, 120), "white")
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom, rendered, _fitted_font = _text_box(
        draw,
        text="Certifications: ULTRA_LONG_UNBROKEN_VERIFIED_VALUE_1234567890",
        anchor=(219, 1),
        direction="right",
        font=_font(28),
        image_size=image.size,
        padding=6,
    )
    assert "\n" in rendered
    assert 0 <= left < right <= image.width
    assert 0 <= top < bottom <= image.height


def test_overlay_rejects_wrong_provenance_and_evidence_free_leaves() -> None:
    source = _png()
    specs = _verified_specs()
    source_record = specs["source"]
    assert isinstance(source_record, dict)
    source_record["platform"] = "manual"

    rendered, report = compose_info_overlay(source, _overlay(), specs)
    assert rendered == source
    assert report == {
        "status": "skipped_unverified_specs",
        "applied_items": 0,
        "warnings": ["unverified structured specs: source.platform must be 1688"],
    }

    specs = _verified_specs()
    dimensions = specs["dimensions"]
    assert isinstance(dimensions, dict)
    height = dimensions["height"]
    assert isinstance(height, dict)
    height.pop("source_label")
    rendered, report = compose_info_overlay(source, _overlay(), specs)
    assert rendered != source  # the independently verified IP callout still applies
    assert report == {
        "status": "applied",
        "applied_items": 1,
        "warnings": [
            "unverified structured spec evidence: dimensions.height",
        ],
    }

    for evidence_key in ("raw_value", "source_label"):
        specs = _verified_specs()
        ip_rating = specs["ip_rating"]
        assert isinstance(ip_rating, dict)
        ip_rating.pop(evidence_key)
        assert resolve_structured_spec_text(specs, "ip_rating") is None

    specs = _verified_specs()
    specs["schema_version"] = "2.0"
    assert resolve_structured_spec_text(specs, "ip_rating") is None


def test_cjk_capable_font_is_the_first_default_candidate() -> None:
    assert "NotoSansCJK" in _FONT_CANDIDATES[0]
    dockerfile = (
        Path(__file__).resolve().parents[2] / "backend/Dockerfile"
    ).read_text(encoding="utf-8")
    assert "fonts-noto-cjk" in dockerfile


def test_image_prompt_requests_clean_base_and_never_asks_ai_to_spell_text() -> None:
    spec = {
        "prompt": "Outdoor product on warm white.",
        "overlay_text": "IP65 WEATHERPROOF",
    }

    prompt = image_render_jobs._compose_prompt(spec, {})

    assert image_render_jobs.INFO_OVERLAY_BASE_BLOCK.strip() in prompt
    assert "IP65 WEATHERPROOF" not in prompt
    assert "render this exact text" not in prompt


def test_invalid_overlay_is_ignored_fail_safe() -> None:
    invalid = {
        "overlay": {
            "schema_version": OVERLAY_SCHEMA_VERSION,
            "role": "dimension",
            "items": [{"type": "dimension", "source_field": "dimensions.height"}],
        }
    }

    assert image_render_jobs._overlay_snapshot(invalid) is None


def test_main_image_overlay_is_ignored_at_enqueue_and_decode_boundaries() -> None:
    spec = {
        "role": "主图",
        "prompt": "Pure-white storefront main image.",
        "overlay": _overlay(),
    }

    main_prompt = image_render_jobs._compose_prompt(
        spec,
        {},
        allow_overlay=False,
    )
    assert image_render_jobs.INFO_OVERLAY_BASE_BLOCK.strip() not in main_prompt

    assert (
        image_render_jobs._overlay_snapshot(
            spec,
            position=1,
            asset_role=image_render_jobs.ASSET_ROLE_MAIN,
        )
        is None
    )
    assert (
        image_render_jobs._decode_overlay_snapshot(
            image_render_jobs._json_dumps(_overlay()),
            asset_role=image_render_jobs.ASSET_ROLE_MAIN,
        )
        is None
    )

    overlay = image_render_jobs._overlay_snapshot(
        spec,
        position=2,
        asset_role=image_render_jobs.ASSET_ROLE_DESCRIPTION,
    )
    assert overlay is not None
    assert image_render_jobs._role_label(spec, overlay) == "feature_callout"


def test_art_direction_output_contract_uses_structured_overlay_not_ai_text() -> None:
    from backend.app.modules.k_series.product_knowledge.prompt_skills import (
        image_art_direction_instruction,
        image_art_direction_skill_context,
    )

    instruction = image_art_direction_instruction()
    skill = image_art_direction_skill_context()["skill_markdown"]

    assert '"schema_version": "k-info-overlay-v1"' in instruction
    assert '"source_field": "<structured_specs_json path>"' in instruction
    assert "PROGRAMMATIC OVERLAY RULE" in instruction
    assert "image model must render NO text" in instruction
    assert "never emit `label`, `text`, or a value field" in instruction
    assert "there is NO post-production step" not in instruction
    assert "`k-info-overlay-v1` 的 `overlay`" in skill
    assert "不得输出 `text`/`label`/数值" in skill
    assert "K 渲染 worker" in skill
    assert "selling_points_approved" in instruction
    assert "selling_point_id" in instruction
    assert "proof_intent" in instruction
    assert "role=dimension is ALWAYS placement=gallery" in instruction
