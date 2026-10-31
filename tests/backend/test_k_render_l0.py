"""作图家规「底子」(10-31):存 L0、先放大后叠字、重做只送 L0、生图进台账。unit,不连库、不出网。"""
from __future__ import annotations

import inspect
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image

from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

pytestmark = pytest.mark.unit


def _png(size: tuple[int, int], color=(200, 150, 100)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeDb:
    def __init__(self, asset: Any = None) -> None:
        self.added: list[Any] = []
        self.executed: list[dict[str, Any]] = []
        self.asset = asset

    def get(self, model: Any, pk: Any, **kw: Any) -> Any:
        return self.asset

    def add(self, row: Any) -> None:
        self.added.append(row)

    def flush(self) -> None:
        pass

    def execute(self, stmt: Any, params: dict[str, Any] | None = None, **kw: Any) -> Any:
        self.executed.append(params or {})
        return SimpleNamespace(rowcount=1)


@pytest.fixture()
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(irj, "_media_storage_root_path", lambda: tmp_path)
    monkeypatch.setattr(irj, "_first_variant", lambda db, product: None)
    return tmp_path


def _product() -> Any:
    return SimpleNamespace(id=uuid4(), product_key="PTB-001", sku="PTB-001", structured_specs_json={}, target_market="US")


def _job(placement: str = irj.PLACEMENT_GALLERY, overlay: str | None = None) -> dict[str, Any]:
    return {
        "id": uuid4(), "batch_id": uuid4(), "position": 3, "placement": placement,
        "asset_role": "gallery", "overlay_text": overlay, "seo_json": {}, "aspect_ratio": "1:1",
    }


def test_l0_is_stored_lossless_and_text_goes_on_after_the_upscale(media_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _png((1024, 1024))
    seen: list[tuple[int, int]] = []

    def fake_overlay(contents, overlay, specs, *, target_market=None):
        with Image.open(BytesIO(contents)) as img:
            seen.append(img.size)
        return contents, {"status": "applied", "applied_items": 1}

    monkeypatch.setattr(irj, "_decode_overlay_snapshot", lambda value, asset_role: {"items": [1]})
    monkeypatch.setattr(irj, "compose_info_overlay", fake_overlay)
    db = FakeDb()
    row = irj._store_render_asset(
        db, product=_product(), job=_job(), contents=raw, mime_type="image/png",
        width=1024, height=1024, content_sha256="x", prompt_used="p", user=None,
    )
    # 字叠在 1500 的成品尺寸上,不是叠在 1024 上再放大
    assert seen == [(1500, 1500)]
    meta = row.metadata_json
    l0 = media_root / meta["l0_object_key"]
    assert l0.read_bytes() == raw  # 原样存,一个字节不动
    assert (meta["l0_width"], meta["l0_height"]) == (1024, 1024) and meta["l0_object_key"].endswith("-l0.png")
    assert row.mime_type == "image/webp" and (row.width, row.height) == (1500, 1500)
    # L0 和成图同一个文件名前缀,能互相找到
    assert Path(meta["l0_object_key"]).name.replace("-l0.png", "") == Path(row.object_key).stem
    # l0_bytes 读回来的就是那一份
    name, data, mime = irj.l0_bytes(row)
    assert data == raw and mime == "image/png"


def test_non_png_l0_is_converted_to_png_and_old_images_have_no_l0(media_root: Path) -> None:
    buf = BytesIO()
    Image.new("RGB", (64, 48), (1, 2, 3)).save(buf, format="JPEG")
    meta = irj._store_l0(media_root, "P", "default", "abc", buf.getvalue())
    with Image.open(media_root / meta["l0_object_key"]) as img:
        assert img.format == "PNG" and img.size == (64, 48)
    old = SimpleNamespace(id=uuid4(), metadata_json={"render_pipeline": irj.RENDER_PIPELINE_TAG})
    assert irj.l0_bytes(old) is None
    gone = SimpleNamespace(id=uuid4(), metadata_json={"l0_object_key": "images/none/x-l0.png"})
    assert irj.l0_bytes(gone) is None


def test_base_is_resized_to_the_final_size_before_text() -> None:
    out = irj._resize_base_png(_png((1024, 1024)), irj.PLACEMENT_GALLERY)
    with Image.open(BytesIO(out)) as img:
        assert img.format == "PNG" and img.size == (1500, 1500)
    out = irj._resize_base_png(_png((1536, 1024)), "description")
    with Image.open(BytesIO(out)) as img:
        assert img.size == (1500, 1000)


def _rework_asset(meta_extra: dict[str, Any]) -> Any:
    product_id = uuid4()
    asset = SimpleNamespace(
        id=uuid4(), product_id=product_id, status="staged", asset_role="gallery",
        metadata_json={"render_pipeline": irj.RENDER_PIPELINE_TAG, "image_prompt_enhanced": "base prompt", "position": 2, **meta_extra},
    )
    return asset, SimpleNamespace(id=product_id)


def _scope() -> Any:
    return SimpleNamespace(workspace_key="w", business_context="b", scope_mode="m")


def test_rework_on_an_old_image_without_l0_never_sends_the_finished_image(media_root: Path) -> None:
    asset, product = _rework_asset({})
    db = FakeDb(asset)
    irj.enqueue_rework_job(db, product=product, user=None, scope_context=_scope(), asset_id=asset.id, extra_prompt="去掉阴影", use_current_as_reference=True)
    params = db.executed[-1]
    assert params["reference_asset_id"] is None
    assert "previous accepted version" not in params["prompt"]


def test_rework_on_an_image_with_l0_points_at_it(media_root: Path) -> None:
    meta = irj._store_l0(media_root, "P", "default", "s1", _png((32, 32)))
    asset, product = _rework_asset(meta)
    db = FakeDb(asset)
    irj.enqueue_rework_job(db, product=product, user=None, scope_context=_scope(), asset_id=asset.id, extra_prompt="去掉阴影", use_current_as_reference=True)
    params = db.executed[-1]
    assert params["reference_asset_id"] == asset.id
    assert "clean base, before any text was added" in params["prompt"]


def test_renderer_sends_l0_not_the_finished_render() -> None:
    src = inspect.getsource(irj._process_render_job)
    assert "l0_bytes(ref_asset)" in src
    assert 'ref_meta.get("render_pipeline") == RENDER_PIPELINE_TAG' in src
    assert "_ledgered_generate(" in src


def test_every_image_call_lands_in_the_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services import ai_usage_ledger

    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(ai_usage_ledger, "record_ai_usage", lambda **kw: rows.append(kw))
    assert irj._ledgered_generate(lambda: ["img"], task="proof_scene")() == ["img"]

    def boom():
        raise RuntimeError("502")

    with pytest.raises(RuntimeError):
        irj._ledgered_generate(boom, task="proof_scene")()
    assert irj._ledgered_generate(lambda: [], task="main")() == []
    assert [(r["success"], r["error_code"]) for r in rows] == [(True, None), (False, "RuntimeError"), (False, "empty_result")]
    assert {r["provider"] for r in rows} == {irj.IMAGE_LEDGER_PROVIDER} and rows[0]["module"] == "k.image_render"
    assert rows[0]["task"] == "proof_scene" and rows[0]["latency_ms"] is not None
    # 重试的每一次都是一次出网,都要记:台账包在重试里面
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise irj.httpx.ReadTimeout("slow")
        return ["ok"]

    rows.clear()
    irj._generate_candidates_with_retry(irj._ledgered_generate(flaky, task="t"), job_id=uuid4(), sleep=lambda s: None)
    assert [r["success"] for r in rows] == [False, True]
