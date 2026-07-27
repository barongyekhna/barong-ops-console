from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.modules.p_series.upload import assemble


pytestmark = pytest.mark.unit


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _statement, _params):
        return _Rows(self._rows)


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "render_pipeline": "k_auto_render",
            "position": 3,
            "placement": "description",
            "role_label": "dimension",
        },
        {
            "render_pipeline": "k_auto_render",
            "position": 3,
            "placement": "description",
            "role_label": "legacy-label",
            "overlay": {"role": "dimension"},
        },
    ],
)
def test_dimension_render_is_published_in_gallery_even_for_stale_description_metadata(
    metadata,
) -> None:
    asset_id = uuid4()
    rows = [
        {
            "id": asset_id,
            "asset_role": "gallery",
            "mime_type": "image/webp",
            "metadata_json": metadata,
        }
    ]

    images = assemble._image_assets(
        _DB(rows),
        SimpleNamespace(id=uuid4()),
        "https://ops.example",
        job_id="job-1",
        job_token="token-1",
    )

    assert len(images) == 1
    assert images[0].placement == "gallery"
    assert images[0].embed_token is None


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (735, 635, "description"),  # 横版手动场景图 → 描述
        (485, 710, "description"),  # 竖版 → 描述
        (1500, 1500, "gallery"),    # 方形 → 画廊
        (1500, 1460, "gallery"),    # 5% 容差内视作方形 → 画廊
    ],
)
def test_bound_manual_image_gallery_requires_square(width, height, expected) -> None:
    # 画廊铁律:画廊只放方形图,非方形(横/竖版)一律进描述内嵌。
    asset_id = uuid4()
    rows = [
        {
            "id": asset_id,
            "asset_role": "gallery",
            "mime_type": "image/webp",
            "width": width,
            "height": height,
            "metadata_json": {"upload_bound": "true", "position": 201},
        }
    ]

    images = assemble._image_assets(
        _DB(rows),
        SimpleNamespace(id=uuid4()),
        "https://ops.example",
        job_id="job-1",
        job_token="token-1",
    )

    assert len(images) == 1
    assert images[0].placement == expected
    if expected == "description":
        assert images[0].embed_token == "{{KP_IMG_201}}"


def test_non_square_main_image_stays_in_gallery() -> None:
    # 主图恒留画廊,即便像素非方形(不能把主图踢进描述)。
    rows = [
        {
            "id": uuid4(),
            "asset_role": "main",
            "mime_type": "image/webp",
            "width": 1500,
            "height": 1000,
            "metadata_json": {"render_pipeline": "k_auto_render", "position": 1},
        }
    ]

    images = assemble._image_assets(
        _DB(rows),
        SimpleNamespace(id=uuid4()),
        "https://ops.example",
        job_id="job-1",
        job_token="token-1",
    )

    assert images[0].placement == "gallery"
