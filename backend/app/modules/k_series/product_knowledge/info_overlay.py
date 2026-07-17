"""Deterministic information overlays for K rendered product images.

The image model produces a clean base image.  This module is the only place
that turns supplier-backed structured specifications into visible text,
leaders, and dimension lines.  Coordinates are normalized (0..1) so the
contract is independent of the rendered image size.

Contract (``k-info-overlay-v1``)::

    {
      "schema_version": "k-info-overlay-v1",
      "role": "feature_callout" | "dimension" | "spec",
      "items": [
        {
          "type": "callout",
          "source_field": "ip_rating",
          "anchor": {"x": 0.46, "y": 0.42},
          "text_anchor": {"x": 0.76, "y": 0.22},
          "leader_direction": "right"
        },
        {
          "type": "dimension",
          "source_field": "dimensions.height",
          "line": {
            "start": {"x": 0.18, "y": 0.16},
            "end": {"x": 0.18, "y": 0.84}
          },
          "text_anchor": {"x": 0.12, "y": 0.50}
        }
      ]
    }

``source_field`` is resolved only against verified ``structured_specs_json``.
The contract deliberately has no free-form label/value/text field: both the
display label and value are selected server-side from an allowlisted supplier
evidence path.
"""

from __future__ import annotations

import math
import os
from io import BytesIO
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .buyer_display import imperial_measurement

OVERLAY_SCHEMA_VERSION = "k-info-overlay-v1"
OVERLAY_ROLES = frozenset({"feature_callout", "dimension", "spec"})
OVERLAY_ITEM_TYPES = frozenset({"callout", "dimension"})
LEADER_DIRECTIONS = frozenset({"auto", "left", "right", "up", "down"})
MAX_OVERLAY_ITEMS = 12

# Only verified, customer-meaningful evidence leaves may reach the image.
# Source metadata, raw evidence, and container-level fields are never valid
# display paths even though they live in the same JSON document.
OVERLAY_SOURCE_FIELDS = frozenset(
    {
        "lumens",
        "color_temperature_k",
        "battery_type",
        "battery_capacity_mah",
        "charge_time_h",
        "runtime_h",
        "ip_rating",
        "dimensions.length",
        "dimensions.width",
        "dimensions.height",
        "weight",
        "material",
        "mount_type",
        "certifications",
    }
)

OVERLAY_FIELD_LABELS = {
    "lumens": "Luminous flux",
    "color_temperature_k": "Color temperature",
    "battery_type": "Battery type",
    "battery_capacity_mah": "Battery capacity",
    "charge_time_h": "Charge time",
    "runtime_h": "Runtime",
    "ip_rating": "IP rating",
    "dimensions.length": "Length",
    "dimensions.width": "Width",
    "dimensions.height": "Height",
    "weight": "Weight",
    "material": "Material",
    "mount_type": "Mount type",
    "certifications": "Certifications",
}

INK_COLOR = "#1b1a18"
PANEL_COLOR = (247, 246, 244, 232)
LINE_COLOR = (27, 26, 24, 255)

IMPERIAL_TARGET_MARKETS = frozenset(
    {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
)
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)


class OverlayContractError(ValueError):
    """The art-direction overlay payload does not match the v1 contract."""


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise OverlayContractError(f"{field} must be a number between 0 and 1")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise OverlayContractError(
            f"{field} must be a number between 0 and 1"
        ) from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise OverlayContractError(f"{field} must be between 0 and 1")
    return result


def _point(value: Any, *, field: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise OverlayContractError(f"{field} must be an object with x/y")
    return {
        "x": _number(value.get("x"), field=f"{field}.x"),
        "y": _number(value.get("y"), field=f"{field}.y"),
    }


def normalize_overlay_contract(value: Any) -> dict[str, Any] | None:
    """Validate and return the small, canonical overlay snapshot.

    ``None`` means that the art-direction item requested no programmatic
    overlay.  Unknown keys are dropped so job/media metadata cannot become an
    accidental channel for model-authored claims.
    """
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise OverlayContractError("overlay must be an object")
    version = str(value.get("schema_version") or "").strip()
    if version != OVERLAY_SCHEMA_VERSION:
        raise OverlayContractError(
            f"overlay.schema_version must be {OVERLAY_SCHEMA_VERSION}"
        )
    role = str(value.get("role") or "").strip().lower()
    if role not in OVERLAY_ROLES:
        raise OverlayContractError(
            "overlay.role must be feature_callout, dimension, or spec"
        )
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise OverlayContractError("overlay.items must be a non-empty list")
    if len(raw_items) > MAX_OVERLAY_ITEMS:
        raise OverlayContractError(
            f"overlay.items cannot contain more than {MAX_OVERLAY_ITEMS} entries"
        )

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        prefix = f"overlay.items[{index}]"
        if not isinstance(raw, dict):
            raise OverlayContractError(f"{prefix} must be an object")
        item_type = str(raw.get("type") or "").strip().lower()
        if item_type not in OVERLAY_ITEM_TYPES:
            raise OverlayContractError(f"{prefix}.type must be callout or dimension")
        source_field = str(raw.get("source_field") or "").strip()
        if source_field not in OVERLAY_SOURCE_FIELDS:
            raise OverlayContractError(
                f"{prefix}.source_field is not an allowed structured-spec field"
            )
        text_anchor = _point(raw.get("text_anchor"), field=f"{prefix}.text_anchor")
        item: dict[str, Any] = {
            "type": item_type,
            "source_field": source_field,
            "text_anchor": text_anchor,
        }
        if item_type == "callout":
            item["anchor"] = _point(raw.get("anchor"), field=f"{prefix}.anchor")
            direction = str(raw.get("leader_direction") or "auto").strip().lower()
            if direction not in LEADER_DIRECTIONS:
                raise OverlayContractError(
                    f"{prefix}.leader_direction must be auto/left/right/up/down"
                )
            item["leader_direction"] = direction
        else:
            line = raw.get("line")
            if not isinstance(line, dict):
                raise OverlayContractError(f"{prefix}.line must contain start/end")
            start = _point(line.get("start"), field=f"{prefix}.line.start")
            end = _point(line.get("end"), field=f"{prefix}.line.end")
            if start == end:
                raise OverlayContractError(
                    f"{prefix}.line start and end must be different"
                )
            item["line"] = {"start": start, "end": end}
        items.append(item)
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "role": role,
        "items": items,
    }


def _specs_contract_warning(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        return "unverified structured specs: schema_version must be 1.0"
    source = value.get("source")
    if (
        not isinstance(source, dict)
        or str(source.get("platform") or "").strip() != "1688"
    ):
        return "unverified structured specs: source.platform must be 1688"
    return None


def _verified_specs_root(value: Any) -> dict[str, Any] | None:
    return value if _specs_contract_warning(value) is None else None


def _lookup_path(specs: dict[str, Any], source_field: str) -> tuple[Any, Any]:
    """Return (resolved evidence leaf, parent) from the exact v1 root."""
    current: Any = specs
    parent: Any = None
    for segment in source_field.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None, None
        parent = current
        current = current[segment]
    return current, parent


def _verified_evidence_leaf(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "value" in value
        and isinstance(value.get("raw_value"), str)
        and bool(value["raw_value"].strip())
        and isinstance(value.get("source_label"), str)
        and bool(value["source_label"].strip())
    )


def _display_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        lower = _display_scalar(value.get("min"))
        upper = _display_scalar(value.get("max"))
        if lower and upper:
            return lower if lower == upper else f"{lower}–{upper}"
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        rendered = [part for item in value if (part := _display_scalar(item))]
        return ", ".join(rendered) or None
    if isinstance(value, float):
        return f"{value:g}"
    rendered = str(value).strip()
    return rendered or None


def _uses_imperial_units(target_market: Any) -> bool:
    market = str(target_market or "").strip().upper().replace("_", "-")
    return market in IMPERIAL_TARGET_MARKETS or market.endswith("-US")


def _display_value_and_unit(
    *,
    source_field: str,
    value: Any,
    unit: Any,
    target_market: Any,
) -> tuple[Any, Any]:
    del source_field
    if not _uses_imperial_units(target_market):
        return value, unit
    converted = imperial_measurement(value, unit)
    return converted if converted is not None else (value, unit)


def resolve_structured_spec_text(
    structured_specs: Any,
    source_field: str,
    *,
    label: str | None = None,
    target_market: str | None = None,
) -> str | None:
    """Resolve one evidence value without falling back to raw/model text."""
    # Kept for call-site compatibility only. Model-authored labels are never
    # displayed; the server owns the allowlisted field-to-label mapping.
    del label
    if source_field not in OVERLAY_SOURCE_FIELDS:
        return None
    specs = _verified_specs_root(structured_specs)
    if specs is None:
        return None
    node, parent = _lookup_path(specs, source_field)
    if not _verified_evidence_leaf(node):
        return None
    value = node.get("value")
    unit: Any = node.get("unit")
    if unit in (None, "") and isinstance(parent, dict):
        unit = parent.get("unit")
    value, unit = _display_value_and_unit(
        source_field=source_field,
        value=value,
        unit=unit,
        target_market=target_market,
    )
    rendered = _display_scalar(value)
    if not rendered:
        return None
    rendered_unit = _display_scalar(unit)
    if rendered_unit:
        rendered = f"{rendered} {rendered_unit}"
    return f"{OVERLAY_FIELD_LABELS[source_field]}: {rendered}"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    configured = os.getenv("K_INFO_OVERLAY_FONT_PATH", "").strip()
    candidates = ([configured] if configured else []) + list(_FONT_CANDIDATES)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _pixels(point: dict[str, float], width: int, height: int) -> tuple[int, int]:
    return round(point["x"] * width), round(point["y"] * height)


def _wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    def _fits(value: str) -> bool:
        left, _top, right, _bottom = draw.textbbox((0, 0), value, font=font)
        return right - left <= max_width

    def _split_token(token: str) -> list[str]:
        if _fits(token):
            return [token]
        chunks: list[str] = []
        current = ""
        for character in token:
            candidate = current + character
            if current and not _fits(candidate):
                chunks.append(current)
                current = character
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    words = [chunk for word in text.split() for chunk in _split_token(word)]
    if len(words) < 2:
        return words[0] if words else ""
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        left, _top, right, _bottom = draw.textbbox((0, 0), candidate, font=font)
        if right - left <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    image_size: tuple[int, int],
    padding: int,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont, int, int]:
    """Wrap and shrink a verified label until its panel fits the canvas."""
    width, height = image_size
    available_width = max(8, width - padding * 2)
    available_height = max(8, height - padding * 2)
    max_box_width = min(max(24, round(width * 0.40)), available_width)
    max_box_height = available_height
    start_size = max(10, int(getattr(font, "size", 18)))
    chosen_font = font
    rendered = text
    text_width = text_height = 0
    for size in range(start_size, 9, -2):
        chosen_font = font if size == start_size else _font(size)
        rendered = _wrapped_text(
            draw,
            text,
            chosen_font,
            max(12, max_box_width - padding * 2),
        )
        bbox = draw.multiline_textbbox(
            (0, 0), rendered, font=chosen_font, spacing=max(2, size // 5)
        )
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        if (
            text_width + padding * 2 <= max_box_width
            and text_height + padding * 2 <= max_box_height
        ):
            break
    if text_height + padding * 2 > max_box_height:
        lines = rendered.splitlines()
        while len(lines) > 1:
            lines.pop()
            candidate = "\n".join([*lines[:-1], f"{lines[-1]}…"])
            bbox = draw.multiline_textbbox(
                (0, 0),
                candidate,
                font=chosen_font,
                spacing=max(2, int(getattr(chosen_font, "size", 10)) // 5),
            )
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            rendered = candidate
            if text_height + padding * 2 <= max_box_height:
                break
    return rendered, chosen_font, text_width, text_height


def _text_box(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    anchor: tuple[int, int],
    direction: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    image_size: tuple[int, int],
    padding: int,
) -> tuple[
    int,
    int,
    int,
    int,
    str,
    ImageFont.FreeTypeFont | ImageFont.ImageFont,
]:
    width, height = image_size
    rendered, fitted_font, text_width, text_height = _fit_text(
        draw,
        text=text,
        font=font,
        image_size=image_size,
        padding=padding,
    )
    box_width = text_width + padding * 2
    box_height = text_height + padding * 2
    x, y = anchor
    if direction == "right":
        left, top = x, y - box_height // 2
    elif direction == "left":
        left, top = x - box_width, y - box_height // 2
    elif direction == "up":
        left, top = x - box_width // 2, y - box_height
    elif direction == "down":
        left, top = x - box_width // 2, y
    else:
        left, top = x - box_width // 2, y - box_height // 2
    left = min(max(padding, left), max(padding, width - box_width - padding))
    top = min(max(padding, top), max(padding, height - box_height - padding))
    return left, top, left + box_width, top + box_height, rendered, fitted_font


def _auto_direction(
    origin: tuple[int, int], target: tuple[int, int], configured: str
) -> str:
    if configured != "auto":
        return configured
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "down" if dy >= 0 else "up"


def _draw_label(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    anchor: tuple[int, int],
    direction: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    image_size: tuple[int, int],
    padding: int,
    line_width: int,
) -> tuple[int, int, int, int]:
    box = _text_box(
        draw,
        text=text,
        anchor=anchor,
        direction=direction,
        font=font,
        image_size=image_size,
        padding=padding,
    )
    left, top, right, bottom, rendered, fitted_font = box
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=max(5, padding),
        fill=PANEL_COLOR,
        outline=LINE_COLOR,
        width=line_width,
    )
    draw.multiline_text(
        ((left + right) // 2, (top + bottom) // 2),
        rendered,
        font=fitted_font,
        fill=INK_COLOR,
        spacing=max(2, int(getattr(fitted_font, "size", 18)) // 5),
        anchor="mm",
        align="center",
    )
    return left, top, right, bottom


def _foreground_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Estimate the rendered product bounds from a clean base image.

    The art-direction contract deliberately asks for an uncluttered base for
    dimension overlays.  Sampling the border gives us its actual background
    colour, while a blurred colour-distance mask ignores compression noise and
    small shadows.  The result is geometry only; it never creates a product
    claim.
    """
    original_width, original_height = image.size
    if original_width < 16 or original_height < 16:
        return None
    scale = min(1.0, 512 / max(original_width, original_height))
    sample_size = (
        max(8, round(original_width * scale)),
        max(8, round(original_height * scale)),
    )
    sample = image.convert("RGB").resize(sample_size, Image.Resampling.LANCZOS)
    sample = sample.filter(ImageFilter.GaussianBlur(radius=1.0))
    width, height = sample.size
    border = max(1, min(width, height) // 50)
    pixels = sample.load()
    border_pixels: list[tuple[int, int, int]] = []
    for y in range(height):
        for x in range(width):
            if x < border or x >= width - border or y < border or y >= height - border:
                border_pixels.append(pixels[x, y])
    if not border_pixels:
        return None
    background = tuple(
        int(median(pixel[channel] for pixel in border_pixels))
        for channel in range(3)
    )
    deviations = sorted(
        math.sqrt(sum((pixel[channel] - background[channel]) ** 2 for channel in range(3)))
        for pixel in border_pixels
    )
    background_noise = deviations[min(len(deviations) - 1, round(len(deviations) * 0.9))]
    threshold = max(20.0, background_noise * 3.0)
    column_counts = [0] * width
    row_counts = [0] * height
    inset = max(1, min(width, height) // 100)
    for y in range(inset, height - inset):
        for x in range(inset, width - inset):
            pixel = pixels[x, y]
            distance = math.sqrt(
                sum((pixel[channel] - background[channel]) ** 2 for channel in range(3))
            )
            if distance >= threshold:
                column_counts[x] += 1
                row_counts[y] += 1
    active_columns = [
        index
        for index, count in enumerate(column_counts)
        if count >= max(2, round(height * 0.008))
    ]
    active_rows = [
        index
        for index, count in enumerate(row_counts)
        if count >= max(2, round(width * 0.008))
    ]
    if not active_columns or not active_rows:
        return None
    left, right = active_columns[0], active_columns[-1] + 1
    top, bottom = active_rows[0], active_rows[-1] + 1
    if (right - left) * (bottom - top) < width * height * 0.005:
        return None
    scale_x = original_width / width
    scale_y = original_height / height
    return (
        max(0, round(left * scale_x)),
        max(0, round(top * scale_y)),
        min(original_width - 1, round(right * scale_x)),
        min(original_height - 1, round(bottom * scale_y)),
    )


def _snapped_dimension_geometry(
    *,
    source_field: str,
    foreground_bbox: tuple[int, int, int, int],
    text_anchor: tuple[int, int],
    image_size: tuple[int, int],
    lane: int = 0,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], str]:
    """Attach a dimension line to the detected product edges, not AI guesses."""
    width, height = image_size
    left, top, right, bottom = foreground_bbox
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    gap = max(10, round(min(width, height) * 0.025)) * (max(0, lane) + 1)
    edge_padding = max(4, round(min(width, height) * 0.008))
    if source_field.endswith(".height"):
        prefer_left = text_anchor[0] < center_x
        if prefer_left and left > gap * 2:
            x = left - gap
            direction = "left"
        elif right + gap < width - edge_padding:
            x = right + gap
            direction = "right"
        else:
            x = max(edge_padding, left - gap)
            direction = "left"
        start, end = (x, top), (x, bottom)
        label_anchor = (
            max(
                edge_padding,
                min(
                    width - edge_padding,
                    x + (-gap if direction == "left" else gap),
                ),
            ),
            center_y,
        )
    else:
        prefer_top = text_anchor[1] < center_y
        if prefer_top and top > gap * 2:
            y = top - gap
            direction = "up"
        elif bottom + gap < height - edge_padding:
            y = bottom + gap
            direction = "down"
        else:
            y = max(edge_padding, top - gap)
            direction = "up"
        start, end = (left, y), (right, y)
        label_anchor = (
            center_x,
            max(edge_padding, min(height - edge_padding, y + (-gap if direction == "up" else gap))),
        )
    return start, end, label_anchor, direction


def _draw_arrow_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    line_width: int,
    arrow_size: int,
) -> None:
    draw.line((start, end), fill=LINE_COLOR, width=line_width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    for tip, inward in ((start, 1.0), (end, -1.0)):
        base_x = tip[0] + ux * arrow_size * inward
        base_y = tip[1] + uy * arrow_size * inward
        points = [
            tip,
            (base_x + px * arrow_size * 0.45, base_y + py * arrow_size * 0.45),
            (base_x - px * arrow_size * 0.45, base_y - py * arrow_size * 0.45),
        ]
        draw.polygon(points, fill=LINE_COLOR)


def compose_info_overlay(
    contents: bytes,
    overlay: Any,
    structured_specs: Any,
    *,
    target_market: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Compose a validated overlay, returning PNG bytes plus an audit report.

    Missing source fields skip only their own annotation.  The caller should
    catch image/contract errors and retain the unmodified render so rendering
    and publication remain fail-safe.
    """
    contract = normalize_overlay_contract(overlay)
    if contract is None:
        return contents, {"status": "not_requested", "applied_items": 0}
    contract_warning = _specs_contract_warning(structured_specs)
    if contract_warning:
        return contents, {
            "status": "skipped_unverified_specs",
            "applied_items": 0,
            "warnings": [contract_warning],
        }

    with Image.open(BytesIO(contents)) as source:
        image = source.convert("RGBA")
    width, height = image.size
    if width < 32 or height < 32:
        raise ValueError("rendered image is too small for an information overlay")
    draw = ImageDraw.Draw(image, "RGBA")
    base = min(width, height)
    font = _font(max(18, min(64, round(base * 0.026))))
    line_width = max(2, round(base * 0.0025))
    padding = max(8, round(base * 0.009))
    arrow_size = max(8, round(base * 0.013))
    warnings: list[str] = []
    applied = 0
    dimension_lanes = {"vertical": 0, "horizontal": 0}
    foreground_bbox: tuple[int, int, int, int] | None = None
    if any(item["type"] == "dimension" for item in contract["items"]):
        foreground_bbox = _foreground_bbox(image)
        if foreground_bbox is None:
            warnings.append(
                "product foreground not detected; dimension lines used brief coordinates"
            )

    for item in contract["items"]:
        source_field = item["source_field"]
        text = resolve_structured_spec_text(
            structured_specs,
            source_field,
            target_market=target_market,
        )
        if not text:
            specs = _verified_specs_root(structured_specs) or {}
            node, _parent = _lookup_path(specs, source_field)
            warning_prefix = (
                "unverified structured spec evidence"
                if node is not None
                else "missing structured spec"
            )
            warnings.append(f"{warning_prefix}: {source_field}")
            continue
        text_anchor = _pixels(item["text_anchor"], width, height)
        if item["type"] == "callout":
            anchor = _pixels(item["anchor"], width, height)
            direction = _auto_direction(
                anchor, text_anchor, item.get("leader_direction", "auto")
            )
            box = _draw_label(
                draw,
                text=text,
                anchor=text_anchor,
                direction=direction,
                font=font,
                image_size=image.size,
                padding=padding,
                line_width=line_width,
            )
            leader_end = (
                min(max(anchor[0], box[0]), box[2]),
                min(max(anchor[1], box[1]), box[3]),
            )
            draw.line((anchor, leader_end), fill=LINE_COLOR, width=line_width)
            dot_radius = max(3, line_width * 2)
            draw.ellipse(
                (
                    anchor[0] - dot_radius,
                    anchor[1] - dot_radius,
                    anchor[0] + dot_radius,
                    anchor[1] + dot_radius,
                ),
                fill=LINE_COLOR,
            )
        else:
            if foreground_bbox is not None:
                orientation = (
                    "vertical"
                    if source_field.endswith(".height")
                    else "horizontal"
                )
                start, end, text_anchor, direction = _snapped_dimension_geometry(
                    source_field=source_field,
                    foreground_bbox=foreground_bbox,
                    text_anchor=text_anchor,
                    image_size=image.size,
                    lane=dimension_lanes[orientation],
                )
                dimension_lanes[orientation] += 1
            else:
                start = _pixels(item["line"]["start"], width, height)
                end = _pixels(item["line"]["end"], width, height)
                midpoint = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
                direction = _auto_direction(midpoint, text_anchor, "auto")
            _draw_arrow_line(
                draw,
                start,
                end,
                line_width=line_width,
                arrow_size=arrow_size,
            )
            _draw_label(
                draw,
                text=text,
                anchor=text_anchor,
                direction=direction,
                font=font,
                image_size=image.size,
                padding=padding,
                line_width=line_width,
            )
        applied += 1

    if not applied:
        return contents, {
            "status": "skipped_missing_specs",
            "applied_items": 0,
            "warnings": warnings,
        }
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), {
        "status": "applied",
        "applied_items": applied,
        "warnings": warnings,
    }
