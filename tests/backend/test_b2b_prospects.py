"""B2B prospecting: dedupe, quota gating, sweep bookkeeping."""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.modules.b2b.prospects import service
from backend.app.modules.b2b.prospects.models import (
    PROSPECT_STATUS_APPROVED,
    PROSPECT_STATUS_REJECTED,
    B2BProspect,
    B2BProspectQuery,
    B2BProspectSweep,
    B2BTargetCity,
)
from backend.app.modules.b2b.prospects.schemas import ProspectQueryCreate
from backend.app.modules.b2b.prospects.seed import seed_prospect_config

# 需要真库(建表由 integration 通道的 alembic 完成);unit 通道不建库。
pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    with SessionLocal() as session:
        for model in (B2BProspectSweep, B2BProspect, B2BProspectQuery, B2BTargetCity):
            session.execute(delete(model))
        session.commit()
        yield session
        for model in (B2BProspectSweep, B2BProspect, B2BProspectQuery, B2BTargetCity):
            session.execute(delete(model))
        session.commit()


def test_query_template_must_contain_city_placeholder() -> None:
    """没有 {city} 的模板跑批时无法按城市展开,必须在入口就拦住。"""
    with pytest.raises(ValueError):
        ProspectQueryCreate(
            store_type="pet_boutique",
            store_type_label="宠物精品店",
            country="US",
            language="en",
            query_template="pet boutique",
        )
    ok = ProspectQueryCreate(
        store_type="pet_boutique",
        store_type_label="宠物精品店",
        country="US",
        language="en",
        query_template="pet boutique {city}",
    )
    assert "{city}" in ok.query_template


def test_dedupe_key_prefers_domain_and_strips_www() -> None:
    """同一家店会被多个查询词抓到,域名是最可靠的去重键。"""
    a = service._dedupe_key(
        {"title": "Happy Paws", "website": "https://www.happypaws.com/contact"},
        city="Austin",
        country="US",
    )
    b = service._dedupe_key(
        {"title": "Happy Paws Boutique", "website": "http://happypaws.com"},
        city="Dallas",
        country="US",
    )
    assert a == b == "domain:happypaws.com"


def test_dedupe_key_falls_back_to_name_and_city_without_website() -> None:
    key = service._dedupe_key(
        {"title": "  Corner   Pet  Shop "},
        city="Moab",
        country="US",
    )
    assert key == "name:US:moab:corner pet shop"


def test_seed_is_idempotent(db) -> None:
    first = seed_prospect_config(db)
    assert first["queries_added"] > 0
    assert first["cities_added"] > 0

    second = seed_prospect_config(db)
    assert second["queries_added"] == 0
    assert second["cities_added"] == 0


def test_seed_covers_three_countries_and_localised_queries(db) -> None:
    """墨西哥必须用西班牙语词——用英文搜墨西哥抓不到什么东西。"""
    seed_prospect_config(db)
    rows = list(db.query(B2BProspectQuery).all())
    countries = {row.country for row in rows}
    assert countries == {"US", "CA", "MX"}
    spanish = [r for r in rows if r.country == "MX"]
    assert spanish
    assert all(r.language == "es" for r in spanish)
    assert any("tienda de mascotas" in r.query_template for r in spanish)


def test_seed_includes_small_towns_not_only_big_cities(db) -> None:
    """用户拍板:小城市机会更大,城市表不能只有大城市。"""
    seed_prospect_config(db)
    populations = [
        row.population
        for row in db.query(B2BTargetCity).all()
        if row.population is not None
    ]
    assert min(populations) < 20000


def test_sweep_requires_active_queries(db) -> None:
    with pytest.raises(service.ProspectError):
        service.run_sweep(db, max_queries=1)


def test_review_sets_status_and_reason(db) -> None:
    prospect = B2BProspect(
        dedupe_key="domain:example-shop.com",
        store_name="Example Shop",
        country="US",
        store_type="pet_boutique",
        language="en",
    )
    db.add(prospect)
    db.commit()

    rejected = service.review_prospect(
        db,
        prospect_id=prospect.id,
        approve=False,
        reject_reason="不卖宠物用品",
    )
    assert rejected.status == PROSPECT_STATUS_REJECTED
    assert rejected.reject_reason == "不卖宠物用品"

    approved = service.review_prospect(db, prospect_id=prospect.id, approve=True)
    assert approved.status == PROSPECT_STATUS_APPROVED
    assert approved.reject_reason is None


def test_quota_status_reports_budget(db) -> None:
    status = service.quota_status(db)
    assert status["quota_budget"] >= 1
    assert status["quota_used_today"] >= 0


def test_persist_dedupes_within_a_single_batch(db) -> None:
    """连锁店多个门店共用一个域名 → 同批去重键相同。

    早期版本只查库不查批内,两条都插进去,提交时唯一键冲突,整轮抓取 500
    (2026-07-27 用户实际踩到)。
    """
    query = B2BProspectQuery(
        store_type="pet_boutique",
        store_type_label="宠物精品店",
        country="US",
        language="en",
        query_template="pet boutique {city}",
    )
    city = B2BTargetCity(country="US", region="TX", city="Austin", population=970000)
    db.add_all([query, city])
    db.commit()

    places = [
        {"title": "Happy Paws North", "website": "https://www.happypaws.com/north"},
        {"title": "Happy Paws South", "website": "http://happypaws.com/south"},
        {"title": "Corner Pet Shop", "website": None},
    ]
    created = service._persist_places(
        db,
        places=places,
        query=query,
        city=city,
        rendered_query="pet boutique Austin",
    )
    db.commit()

    assert created == 2
    assert db.query(B2BProspect).count() == 2


def test_persist_skips_places_already_in_database(db) -> None:
    query = B2BProspectQuery(
        store_type="pet_boutique",
        store_type_label="宠物精品店",
        country="US",
        language="en",
        query_template="pet boutique {city}",
    )
    city = B2BTargetCity(country="US", region="TX", city="Austin", population=970000)
    db.add_all([query, city])
    db.add(
        B2BProspect(
            dedupe_key="domain:happypaws.com",
            store_name="Happy Paws",
            country="US",
            store_type="pet_boutique",
            language="en",
        )
    )
    db.commit()

    created = service._persist_places(
        db,
        places=[{"title": "Happy Paws North", "website": "https://happypaws.com"}],
        query=query,
        city=city,
        rendered_query="pet boutique Austin",
    )
    db.commit()

    assert created == 0
    assert db.query(B2BProspect).count() == 1


def test_city_order_mixes_small_and_big_at_four_to_one(db) -> None:
    """用户拍板:小城优先但不只做小城,大城两成、小城八成。"""

    class _City:
        def __init__(self, name: str, population: int) -> None:
            self.city = name
            self.population = population

    cities = [_City(f"Big{i}", 900_000) for i in range(3)]
    cities += [_City(f"Small{i}", 30_000) for i in range(9)]

    ordered = [c.city for c in service._mixed_city_order(cities)]

    assert ordered[0].startswith("Small")
    assert ordered[4] == "Big0"
    assert ordered[9] == "Big1"
    # 大城市一个都不能漏
    assert {c for c in ordered if c.startswith("Big")} == {"Big0", "Big1", "Big2"}
    assert len(ordered) == len(cities)


def test_chain_hint_flags_repeated_names_and_huge_review_counts(db) -> None:
    """MEC 出现在 5 个城市、评价数上千——这些不是独立小店,要一眼跳过。"""
    for index, city in enumerate(["Toronto", "Calgary", "Edmonton"]):
        db.add(
            B2BProspect(
                dedupe_key=f"name:CA:{city.lower()}:mec",
                store_name="MEC",
                city=city,
                country="CA",
                store_type="outdoor_store",
                language="en",
                reviews_count=2500,
            )
        )
    indie = B2BProspect(
        dedupe_key="name:us:austin:paws on chicon",
        store_name="Paws on Chicon",
        city="Austin",
        country="US",
        store_type="pet_boutique",
        language="en",
        reviews_count=567,
    )
    db.add(indie)
    db.commit()

    rows = db.query(B2BProspect).all()
    hints = service.chain_hints(db, rows)

    chains = [r for r in rows if r.store_name == "MEC"]
    assert all(r.id in hints for r in chains)
    assert "3 个城市" in hints[chains[0].id]
    # 独立小店不该被误标
    assert indie.id not in hints


def test_maps_url_needs_cid(db) -> None:
    with_cid = B2BProspect(
        dedupe_key="name:us:austin:a",
        store_name="A",
        country="US",
        store_type="pet_boutique",
        language="en",
        place_cid="6816627984772319118",
    )
    without = B2BProspect(
        dedupe_key="name:us:austin:b",
        store_name="B",
        country="US",
        store_type="pet_boutique",
        language="en",
    )
    assert service.maps_url_for(with_cid).endswith("6816627984772319118")
    assert service.maps_url_for(without) is None
