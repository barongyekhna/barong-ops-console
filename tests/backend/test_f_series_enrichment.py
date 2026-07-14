"""F 类目富化集成测试：树浏览 → 富化运行（mock Serper）→ 候选池 → 进 K → 权限门。

跑在 Alembic 管理的隔离 PostgreSQL 上（scripts/run_backend_tests.sh integration）。
谷歌树共享 K 的 k_category_google，测试自己种一棵迷你树。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.modules.f_series.enrichment import runs as run_engine
from backend.app.modules.f_series.enrichment import serper_client

pytestmark = pytest.mark.integration

_TREE_ROWS = (
    ("f988", "Sporting Goods", "Sporting Goods", None, 1, False),
    (
        "f989",
        "Outdoor Recreation",
        "Sporting Goods > Outdoor Recreation",
        "f988",
        2,
        False,
    ),
    (
        "f990",
        "Camping & Hiking",
        "Sporting Goods > Outdoor Recreation > Camping & Hiking",
        "f989",
        3,
        False,
    ),
    (
        "f991",
        "Camp Showers",
        "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camp Showers",
        "f990",
        4,
        True,
    ),
    (
        "f992",
        "Knives",
        "Sporting Goods > Hunting > Knives",
        "f988",
        2,
        True,
    ),
)

_ZH_NAMES = {
    "f988": "体育用品",
    "f989": "户外休闲",
    "f990": "露营与徒步",
    "f991": "便携式淋浴与更衣帐篷",
}

_SERPER_FIXTURE = {
    "relatedSearches": [
        {"query": "portable camp shower"},
        {"query": "solar camp shower"},
    ],
    "peopleAlsoAsk": [{"question": "How does a camp shower work?"}],
    "organic": [{"title": "10 Best Camp Showers"}],
}


@pytest.fixture
def f_env(owner_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """种迷你谷歌树 + mock Serper + 同步执行 + 清空当日 Serper 额度记账。"""
    with SessionLocal() as db:
        for row in _TREE_ROWS:
            db.execute(
                text(
                    "INSERT INTO k_category_google "
                    "(id, name, name_zh, full_path, parent_id, level, is_leaf) "
                    "VALUES (:i, :n, :zh, :f, :p, :l, :leaf) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "i": row[0],
                    "n": row[1],
                    "zh": _ZH_NAMES.get(row[0]),
                    "f": row[2],
                    "p": row[3],
                    "l": row[4],
                    "leaf": row[5],
                },
            )
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS ra_provider_quota_usage ("
                "provider TEXT NOT NULL, day DATE NOT NULL, "
                "used INTEGER NOT NULL DEFAULT 0, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (provider, day))"
            )
        )
        db.execute(
            text(
                "DELETE FROM ra_provider_quota_usage "
                "WHERE provider IN ('serper_search', 'alibaba1688_app_calls')"
            )
        )
        db.commit()

    monkeypatch.setenv("F_ENRICHMENT_INLINE", "1")
    monkeypatch.setattr(run_engine, "_serper_key", lambda db: "test-key")
    monkeypatch.setattr(
        serper_client, "serper_search", lambda **kwargs: dict(_SERPER_FIXTURE)
    )

    yield owner_client

    with SessionLocal() as db:
        db.execute(text("DELETE FROM f_category_profiles"))
        db.execute(text("DELETE FROM f_category_candidates"))
        db.execute(text("DELETE FROM f_category_keywords"))
        db.execute(text("DELETE FROM f_enrichment_runs"))
        db.execute(
            text(
                "DELETE FROM k_product_knowledge_products "
                "WHERE source_system = 'f_enrichment'"
            )
        )
        db.execute(
            text("DELETE FROM k_category_google WHERE id LIKE 'f98%' OR id LIKE 'f99%'")
        )
        db.execute(
            text(
                "DELETE FROM ra_provider_quota_usage "
                "WHERE provider IN ('serper_search', 'alibaba1688_app_calls')"
            )
        )
        db.commit()


def test_tree_browse_and_search(f_env: TestClient) -> None:
    response = f_env.get("/api/app/f/categories/tree")
    assert response.status_code == 200
    roots = {item["id"]: item for item in response.json()["items"] if item["id"].startswith("f9")}
    assert "f988" in roots
    assert roots["f988"]["children_count"] >= 2

    response = f_env.get("/api/app/f/categories/tree", params={"parent_id": "f990"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ["f991"]

    response = f_env.get("/api/app/f/categories/search", params={"q": "camp show"})
    assert response.status_code == 200
    assert any(item["id"] == "f991" for item in response.json()["items"])

    # 中文名随树返回 + 中文搜索命中
    roots_zh = {item["id"]: item["name_zh"] for item in roots.values()}
    assert roots_zh.get("f988") == "体育用品"
    response = f_env.get("/api/app/f/categories/search", params={"q": "淋浴"})
    assert response.status_code == 200
    matched = response.json()["items"]
    assert any(item["id"] == "f991" for item in matched)
    assert any(item["name_zh"] == "便携式淋浴与更衣帐篷" for item in matched)


def test_run_harvests_keywords_over_subtree(f_env: TestClient) -> None:
    response = f_env.post(
        "/api/app/f/runs",
        json={"category_ids": ["f989"], "mode": "keywords_only"},
    )
    assert response.status_code == 201, response.text
    run = response.json()
    # f989 展开 = f989 + f990 + f991 三个节点
    assert run["categories_total"] == 3

    response = f_env.get(f"/api/app/f/runs/{run['run_id']}")
    assert response.status_code == 200
    finished = response.json()
    assert finished["status"] == "succeeded"
    assert finished["categories_done"] == 3
    assert finished["serper_calls"] == 3
    # 每节点 4 个词（2 related + 1 PAA + 1 organic）
    assert finished["keywords_found"] == 12

    response = f_env.get("/api/app/f/keywords", params={"category_id": "f991"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert {item["keyword_type"] for item in payload["items"]} == {
        "related",
        "people_also_ask",
        "organic_title",
    }

    # 重跑同一选段：全部去重，keywords_found = 0
    response = f_env.post(
        "/api/app/f/runs",
        json={"category_ids": ["f989"], "mode": "keywords_only"},
    )
    assert response.status_code == 201
    rerun = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert rerun["status"] == "succeeded"
    assert rerun["keywords_found"] == 0

    # 树上的 F 标记层统计跟着更新
    response = f_env.get("/api/app/f/categories/tree", params={"parent_id": "f990"})
    assert response.json()["items"][0]["keywords_count"] == 4


def test_run_stops_gracefully_when_quota_exhausted(
    f_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RA_SERPER_DAILY_BUDGET", "2")
    response = f_env.post(
        "/api/app/f/runs",
        json={"category_ids": ["f989"], "mode": "keywords_only"},
    )
    assert response.status_code == 201
    run = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert run["status"] == "quota_exhausted"
    assert run["categories_done"] == 2
    assert "预算已用完" in (run["error"] or "")

    quota = f_env.get("/api/app/f/quota").json()
    assert quota["serper"]["used"] == 2


def test_candidate_red_flag_review_and_import_to_k(f_env: TestClient) -> None:
    # 红线类目（Knives）：只标记不毙掉
    response = f_env.post(
        "/api/app/f/candidates",
        json={
            "category_id": "f992",
            "title": "outdoor folding knife",
            "source_url": "https://detail.1688.com/offer/123.html",
            "price_cny": "12.50",
            "weight_note": "0.2kg",
        },
    )
    assert response.status_code == 201, response.text
    flagged = response.json()
    assert flagged["automation_blocked"] is True
    assert flagged["red_flags"][0]["type"] == "category_red_line"
    assert flagged["status"] == "pending_review"

    # 未放行就想进 K → 409
    response = f_env.post(f"/api/app/f/candidates/{flagged['id']}/import-to-k")
    assert response.status_code == 409

    # 正常类目候选：无标记 → 放行 → 进 K
    response = f_env.post(
        "/api/app/f/candidates",
        json={
            "category_id": "f991",
            "title": "便携太阳能淋浴袋 camping shower",
            "source_url": "https://detail.1688.com/offer/456.html",
            "supplier_name": "示例供应商",
            "moq": 50,
        },
    )
    assert response.status_code == 201
    candidate = response.json()
    assert candidate["automation_blocked"] is False

    response = f_env.patch(
        f"/api/app/f/candidates/{candidate['id']}",
        json={"action": "approve"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    response = f_env.post(f"/api/app/f/candidates/{candidate['id']}/import-to-k")
    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["deduped"] is False

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT channel, google_product_category, category_review_needed, "
                "source_system, moq FROM k_product_knowledge_products "
                "WHERE id = :i"
            ),
            {"i": imported["product_id"]},
        ).mappings().first()
    assert row is not None
    assert row["channel"] == "dtc"
    assert row["google_product_category"] == "f991"
    assert row["category_review_needed"] is False
    assert row["source_system"] == "f_enrichment"
    assert row["moq"] == 50

    # 幂等：重复进 K → deduped
    response = f_env.patch(
        f"/api/app/f/candidates/{candidate['id']}",
        json={"action": "reopen"},
    )
    assert response.status_code == 409  # 已进 K 不能再改状态


class _FakeSourcingProvider:
    """替身 1688 词搜通道：每类目回两个 offer（一个重复 URL 供去重验证）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search_offers_keyword_only(self, *, product, keyword_profile, limit):
        from decimal import Decimal

        from r_system_v2.ra.supplier_api import SupplierApiOffer

        self.calls.append(str(product.get("category")))
        slug = str(product.get("category") or "cat").replace(" ", "-").lower()

        def _offer(index: int, title: str, url_key: str) -> SupplierApiOffer:
            return SupplierApiOffer(
                supplier_name=f"{slug}源头工厂{index + 1}",
                supplier_url=f"https://detail.1688.com/offer/{url_key}.html",
                title=title,
                unit_price_cny=Decimal("38.50"),
                domestic_shipping_cny=None,
                moq=2,
                rating=None,
                match_score=90,
                stock=100,
                monthly_sales=500,
                one_piece_hint=False,
                source="alibaba1688_official_keyword_search",
                payload={
                    "offer_id": url_key,
                    "image_url": f"https://cbu01.alicdn.com/{url_key}.jpg",
                },
            )

        offers = [
            _offer(
                index,
                f"露营淋浴袋 {product.get('category')} 现货 一件代发 {index + 1}",
                f"{slug}-{index}",
            )
            for index in range(2)
        ]
        # 1688 分销池的兜底垃圾（不含采购词）——相关性把关必须滤掉它
        offers.append(_offer(2, "外贸剁骨刀家用砍骨头刀加厚锰钢", f"junk-{slug}"))
        return offers[:limit]


def test_full_run_harvests_keywords_and_sources_candidates(
    f_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.modules.f_series.enrichment import sourcing

    fake = _FakeSourcingProvider()
    monkeypatch.setattr(sourcing, "build_provider", lambda db, org_id: fake)
    monkeypatch.setattr(
        sourcing,
        "build_supplier_keyword_profile",
        lambda db, *, org_id, product: {
            "product_type_zh": "露营淋浴袋",
            "core_keywords_zh": ["露营 淋浴", "户外 洗澡袋"],
        },
    )

    response = f_env.post(
        "/api/app/f/runs", json={"category_ids": ["f990"], "mode": "full"}
    )
    assert response.status_code == 201, response.text
    run = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert run["status"] == "succeeded"
    assert run["mode"] == "full"
    # f990 子树 = f990 + f991 两个节点
    assert run["categories_done"] == 2
    assert run["keywords_found"] == 8
    assert run["candidates_found"] == 4  # 每节点 2 个 offer
    assert run["alibaba_calls"] > 0
    assert fake.calls == ["Camping & Hiking", "Camp Showers"]

    response = f_env.get(
        "/api/app/f/candidates", params={"category_id": "f991", "status": "pending_review"}
    )
    items = response.json()["items"]
    assert len(items) == 2
    assert all(item["source"] == "alibaba1688" for item in items)
    assert all(item["image_url"] for item in items)
    assert all(item["price_cny"] == "38.50" for item in items)
    # 兜底垃圾（剁骨刀）被相关性把关拦下，不进候选池
    assert all("剁骨刀" not in item["title"] for item in items)

    # 同类目重跑 sourcing_only：offer URL 相同 → 全部去重
    response = f_env.post(
        "/api/app/f/runs", json={"category_ids": ["f991"], "mode": "sourcing_only"}
    )
    assert response.status_code == 201
    rerun = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert rerun["status"] == "succeeded"
    assert rerun["candidates_found"] == 0
    assert rerun["keywords_found"] == 0  # sourcing_only 不动词


def test_full_run_degrades_gracefully_without_1688_key(f_env: TestClient) -> None:
    # 不 mock provider：SecretManager 里没有 alibaba1688 密钥 → 找货段跳过，词照收
    response = f_env.post(
        "/api/app/f/runs", json={"category_ids": ["f991"], "mode": "full"}
    )
    assert response.status_code == 201
    run = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert run["status"] == "succeeded"
    assert run["keywords_found"] == 4
    assert run["candidates_found"] == 0
    assert "1688 找货段已跳过" in (run["error"] or "")

    # sourcing_only 无密钥 → 直接失败，不空转
    response = f_env.post(
        "/api/app/f/runs", json={"category_ids": ["f991"], "mode": "sourcing_only"}
    )
    assert response.status_code == 201
    run = f_env.get(f"/api/app/f/runs/{response.json()['run_id']}").json()
    assert run["status"] == "failed"


def test_category_profile_generate_and_cache(
    f_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.modules.f_series.enrichment import profiles

    class _FakeSecretManager:
        def __init__(self, db_session=None) -> None:
            del db_session

        def get_key(self, service: str, org_id: str) -> str:
            assert service == "deepseek"
            return "test-deepseek-key"

    monkeypatch.setattr(profiles, "SecretManager", _FakeSecretManager)

    calls = {"n": 0}

    def fake_deepseek(*, api_key, category_path, name_zh):
        calls["n"] += 1
        assert "Camp Showers" in category_path
        assert name_zh == "便携式淋浴与更衣帐篷"
        return [
            {"en": "Solar camp shower bag", "zh": "太阳能淋浴袋", "note_zh": "晒热水洗澡"},
            {"en": "Privacy shower tent", "zh": "更衣帐篷", "note_zh": "户外更衣遮挡"},
        ]

    monkeypatch.setattr(profiles, "_call_deepseek_profile", fake_deepseek)

    # 无缓存：GET exists=false
    response = f_env.get("/api/app/f/categories/f991/profile")
    assert response.status_code == 200
    assert response.json()["exists"] is False

    # 生成：POST 调 DeepSeek 一次并落库
    response = f_env.post("/api/app/f/categories/f991/profile")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["exists"] is True
    assert payload["products"][0]["zh"] == "太阳能淋浴袋"
    assert calls["n"] == 1

    # 缓存命中：GET 直接回、重复 POST 不再调 DeepSeek
    assert f_env.get("/api/app/f/categories/f991/profile").json()["exists"] is True
    assert f_env.post("/api/app/f/categories/f991/profile").status_code == 200
    assert calls["n"] == 1

    # 不存在的类目 → 404
    assert f_env.post("/api/app/f/categories/nonexistent/profile").status_code == 404


def test_run_rejects_oversized_or_unknown_selection(f_env: TestClient) -> None:
    response = f_env.post("/api/app/f/runs", json={"category_ids": ["nonexistent"]})
    assert response.status_code == 422

    response = f_env.post("/api/app/f/runs", json={"category_ids": []})
    assert response.status_code == 422


def test_f_endpoints_require_permission(
    f_env: TestClient, auth_client: TestClient
) -> None:
    from backend.app.core.security import hash_password
    from backend.app.models.user import User

    username = "f_series_plain_viewer"
    password = "f-series-example-viewer-pass"
    with SessionLocal() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="viewer",
                is_active=True,
            )
        )
        db.commit()

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200

    assert auth_client.get("/api/app/f/categories/tree").status_code == 403
    assert (
        auth_client.post(
            "/api/app/f/runs", json={"category_ids": ["f989"]}
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            "/api/app/f/candidates",
            json={"category_id": "f991", "title": "x"},
        ).status_code
        == 403
    )
