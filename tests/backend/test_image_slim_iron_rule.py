"""图片体积铁律:入库后处理尺寸/质量 + 出站 webp 硬门。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_postprocess_targets_are_slimmed() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    assert irj.GALLERY_TARGET_SIDE == 1500
    assert irj.MAX_RENDER_SIDE == 1500
    assert irj._WEBP_QUALITY == 82


def test_postprocess_resizes_and_converts() -> None:
    from io import BytesIO

    from PIL import Image

    from backend.app.modules.k_series.product_knowledge.image_render_jobs import (
        PLACEMENT_GALLERY,
        _postprocess_rendered_image,
    )

    buf = BytesIO()
    Image.new("RGB", (2000, 2000), (200, 150, 100)).save(buf, format="PNG")
    out, mime, w, h = _postprocess_rendered_image(buf.getvalue(), PLACEMENT_GALLERY)
    assert (mime, w, h) == ("image/webp", 1500, 1500)

    buf2 = BytesIO()
    Image.new("RGB", (2400, 1200), (10, 20, 30)).save(buf2, format="PNG")
    out2, mime2, w2, h2 = _postprocess_rendered_image(buf2.getvalue(), "description")
    assert mime2 == "image/webp"
    assert max(w2, h2) == 1500 and (w2, h2) == (1500, 750)

    buf3 = BytesIO()
    Image.new("RGB", (900, 1200), (10, 20, 30)).save(buf3, format="PNG")
    _, _, w3, h3 = _postprocess_rendered_image(buf3.getvalue(), "description")
    assert (w3, h3) == (900, 1200)  # 小图不放大


def test_webp_gate_is_wired_into_gate_blockers() -> None:
    import inspect

    from backend.app.modules.p_series.upload import assemble

    source = inspect.getsource(assemble.gate_blockers)
    assert "_non_webp_image_blockers" in source
    gate = inspect.getsource(assemble._non_webp_image_blockers)
    assert "image/webp" in gate and "bound" in gate
