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
