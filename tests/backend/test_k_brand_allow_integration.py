"""放行词表(11-03)· 真库:迁移种下 panda;老板加词后,已经审过的商品里被它盖住的文字发现一并放行(留痕);接口只给老板改。"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.modules.k_series.product_knowledge import brand_allow, brand_guard
from backend.app.modules.k_series.product_knowledge.models import KBrandAllowTerm, KProductKnowledgeProduct
from backend.app.services.data_isolation import without_org_data_isolation

pytestmark = pytest.mark.integration


def _product(db, sku: str, violations: list[dict]) -> KProductKnowledgeProduct:
    product = KProductKnowledgeProduct(
        id=uuid4(),
        workspace_key="ws_test",
        business_context="intl_trade",
        scope_mode="production",
        product_key=str(uuid4()),
        source_system="manual",
        source_record_id=sku,
        sku=sku,
        parent_sku=sku,
        product_name_en="Outdoor shower",
        product_status="draft",
        product_type="simple_product",
        review_status="draft",
        canonical_language="en",
        channel="dtc",
        brand_audit_json={"clean": False, "text_violations": violations, "image_violations": [], "ignored_findings": []},
    )
    db.add(product)
    db.flush()
    return product


def test_migration_seeds_panda_with_the_boss_words() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        row = db.scalar(select(KBrandAllowTerm).where(KBrandAllowTerm.term == "panda"))
        assert row is not None
        assert "只限餐饮类" in (row.note or "")
        assert "panda" in brand_allow.allowed_words(db, fresh=True)


def test_adding_a_word_releases_matching_findings_on_every_audited_product() -> None:
    sku_a, sku_b, sku_c = (f"TST-{uuid4().hex[:6]}" for _ in range(3))
    owner = SimpleNamespace(username="owner", id=1)
    with without_org_data_isolation(), SessionLocal() as db:
        a = _product(db, sku_a, [{"surface": "copy.h1", "term": "Kiwi pump"}])
        b = _product(db, sku_b, [{"surface": "seo.title", "term": "kiwi"}, {"surface": "copy.k[1]", "term": "Coleman"}])
        c = _product(db, sku_c, [{"surface": "copy.h1", "term": "Coleman kiwi"}])
        brand_allow.add_term(db, term="Kiwi", note="测试:奇异果造型", user_id=None)
        released = brand_guard.release_allowed_findings(db, term="kiwi", user=owner, reason="测试放行")
        db.flush()
        assert sorted(released) == sorted([sku_a, sku_b])
        assert a.brand_audit_json["clean"] is True
        assert b.brand_audit_json["clean"] is False and b.brand_audit_json["unresolved_count"] == 1  # Coleman 还在
        assert c.brand_audit_json["clean"] is False  # 旁边带真竞品,不放
        trail = a.brand_audit_json["ignored_findings_trail"]
        assert list(trail.values())[0]["reason"] == "测试放行"
        # 再跑一次不重复放行
        assert brand_guard.release_allowed_findings(db, term="kiwi", user=owner) == []
        assert brand_allow.remove_term(db, term="kiwi") is True
        assert brand_allow.remove_term(db, term="kiwi") is False
        db.rollback()


def test_add_term_refuses_real_competitor_brands_and_updates_note() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        with pytest.raises(brand_allow.BrandAllowError):
            brand_allow.add_term(db, term="DeWalt", note="", user_id=None)
        row = brand_allow.add_term(db, term="  Mango ", note="第一次", user_id=None)
        assert row["term"] == "mango"
        again = brand_allow.add_term(db, term="mango", note="改备注", user_id=None)
        assert again["id"] == row["id"] and again["note"] == "改备注"
        db.rollback()


def test_allow_list_endpoints_are_owner_only() -> None:
    from backend.app.modules.k_series.product_knowledge import router as k_router

    k_router._brand_allow_owner(SimpleNamespace(role="owner"))
    for role in ("operator", "viewer", "", None):
        with pytest.raises(HTTPException) as err:
            k_router._brand_allow_owner(SimpleNamespace(role=role))
        assert err.value.status_code == 403


def test_owner_lists_the_allow_list_over_http(owner_client) -> None:
    response = owner_client.get("/api/app/k/brand-allow-terms")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_edit"] is True
    assert "panda" in [t["term"] for t in body["terms"]]
