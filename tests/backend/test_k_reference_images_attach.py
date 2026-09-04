"""建好之后补参考图链接(POST /products/{id}/reference-images)的落库函数。

要守住的:逐条回结果,不压扁;白名单外域名直接判 host_not_allowed 不出网;
单条失败不拖累其他;产品级只在没有主参考图时才设主图;变体级打 colorway 标记。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.unit

from backend.app.db.base import Base
from backend.app.modules.k_series.product_knowledge import image_render_jobs
from backend.app.modules.k_series.product_knowledge.manual_reference import (
    attach_reference_image_urls,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductReferenceImagesRequest,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import create_product
from backend.app.modules.f_series.enrichment import images as f_images


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _product(db):
    payload = ProductKnowledgeCreate(
        product_name_en="Folding bucket",
        raw_input_text="bucket",
        target_market="US",
        regular_price=Decimal("1"),
    )
    return create_product(
        db,
        payload=payload,
        scope_context=KScopeContext(
            workspace_key="org_test",
            business_context="independent_store",
            scope_mode="production",
        ),
    )


def test_request_schema_dedupes_and_requires_http() -> None:
    req = ProductReferenceImagesRequest(
        urls=[" https://cbu01.alicdn.com/a.jpg ", "https://cbu01.alicdn.com/a.jpg", ""]
    )
    assert req.urls == ["https://cbu01.alicdn.com/a.jpg"]
    with pytest.raises(ValueError):
        ProductReferenceImagesRequest(urls=["ftp://x/y.jpg"])
    with pytest.raises(ValueError):
        ProductReferenceImagesRequest(urls=["   "])


def test_outcomes_are_per_url_and_bad_hosts_never_hit_the_network(monkeypatch) -> None:
    db = _session()
    product = _product(db)
    fetched: list[str] = []
    stored: list[dict] = []

    def fake_fetch(_cache_key, url, _variant):
        fetched.append(url)
        if url.endswith("boom.jpg"):
            raise f_images.FImageUnavailableError("图片回源失败:HTTP 404")
        return b"\xff\xd8\xffjpeg", "image/jpeg"

    def fake_store(_db, *, product, contents, mime_type, source_url, user, variant=None, extra_metadata=None):
        stored.append({"url": source_url, "variant": variant, "extra": extra_metadata})
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(f_images, "get_candidate_image", fake_fetch)
    monkeypatch.setattr(image_render_jobs, "store_reference_image_asset", fake_store)

    outcomes = attach_reference_image_urls(
        db,
        product=product,
        urls=[
            "https://example.com/not-allowed.jpg",
            "https://cbu01.alicdn.com/img/boom.jpg",
            "https://cbu01.alicdn.com/img/ok.jpg",
        ],
        variant=None,
        user=None,
    )

    assert [item["status"] for item in outcomes] == ["failed", "failed", "stored"]
    assert outcomes[0]["error"].startswith("host_not_allowed")
    assert "404" in outcomes[1]["error"]
    assert outcomes[2]["asset_id"] is not None
    # 白名单外的那条根本没出网
    assert fetched == [
        "https://cbu01.alicdn.com/img/boom.jpg",
        "https://cbu01.alicdn.com/img/ok.jpg",
    ]
    assert [item["url"] for item in stored] == ["https://cbu01.alicdn.com/img/ok.jpg"]
    # 产品没有主参考图 → 第一张存成功的成为主图
    assert product.reference_image_url == "https://cbu01.alicdn.com/img/ok.jpg"


def test_existing_main_reference_is_not_overwritten_and_variant_gets_colorway_tag(monkeypatch) -> None:
    db = _session()
    product = _product(db)
    product.reference_image_url = "https://cbu01.alicdn.com/img/original.jpg"
    db.commit()
    variant = db.scalar(
        select(KProductKnowledgeVariant).where(KProductKnowledgeVariant.product_id == product.id)
    )
    variant.color = "Blue"
    db.commit()
    stored: list[dict] = []

    monkeypatch.setattr(
        f_images, "get_candidate_image", lambda *_a: (b"\xff\xd8\xff", "image/jpeg")
    )
    monkeypatch.setattr(
        image_render_jobs,
        "store_reference_image_asset",
        lambda _db, **kw: stored.append(kw) or SimpleNamespace(id=uuid4()),
    )

    product_level = attach_reference_image_urls(
        db, product=product, urls=["https://cbu01.alicdn.com/img/extra.jpg"], variant=None, user=None
    )
    assert product_level[0]["status"] == "stored"
    assert product.reference_image_url.endswith("original.jpg")

    variant_level = attach_reference_image_urls(
        db, product=product, urls=["https://cbu01.alicdn.com/img/blue.jpg"], variant=variant, user=None
    )
    assert variant_level[0]["status"] == "stored"
    assert variant_level[0]["variant_sku"] == variant.variant_sku
    assert stored[-1]["variant"] is variant
    assert stored[-1]["extra_metadata"] == {"variant_reference": True, "variant_color": "Blue"}


def test_store_failure_is_reported_with_its_message(monkeypatch) -> None:
    db = _session()
    product = _product(db)
    monkeypatch.setattr(
        f_images, "get_candidate_image", lambda *_a: (b"\xff\xd8\xff", "image/jpeg")
    )

    def failing_store(_db, **_kw):
        raise image_render_jobs.KImageRenderError(
            "REFERENCE_NOT_IMAGE", "参考图回源内容与图片类型不匹配。", status_code=422
        )

    monkeypatch.setattr(image_render_jobs, "store_reference_image_asset", failing_store)
    outcomes = attach_reference_image_urls(
        db, product=product, urls=["https://cbu01.alicdn.com/img/x.jpg"], variant=None, user=None
    )
    assert outcomes[0]["status"] == "failed"
    assert outcomes[0]["error"] == "参考图回源内容与图片类型不匹配。"
    assert product.reference_image_url is None
