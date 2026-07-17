from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.modules.k_series.product_knowledge import image_render_jobs
from backend.app.modules.p_series.upload.assemble import (
    _append_package_includes_section,
)


pytestmark = pytest.mark.unit


def test_package_section_is_not_appended_when_copy_already_has_the_heading() -> None:
    description = (
        '<div class="kp-desc"><section class="kp-detail">'
        "<h2>What&#x27;s in the box</h2><p>Reviewed package contents.</p>"
        "</section></div>"
    )

    rendered = _append_package_includes_section(description, ["Pot", "Bowl"])

    assert rendered == description
    assert rendered.count("in the box") == 1
    assert 'class="kp-box"' not in rendered


def test_save_render_assets_is_idempotent_when_nothing_is_staged() -> None:
    class _Rows:
        @staticmethod
        def all() -> list[object]:
            return []

    class _DB:
        @staticmethod
        def scalars(_query: object) -> _Rows:
            return _Rows()

    result = image_render_jobs.save_render_assets(
        _DB(),  # type: ignore[arg-type]
        product=SimpleNamespace(id=uuid4(), marketing_copy_json={}),
        user=None,
        scope_context=SimpleNamespace(
            workspace_key="workspace",
            business_context="catalog",
            scope_mode="global",
        ),
    )

    assert result == {"saved": [], "audit_enqueued": False}
