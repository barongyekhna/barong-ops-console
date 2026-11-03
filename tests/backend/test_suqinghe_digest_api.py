"""运营看板(10-30):真库 integration。造几行流量/订单/体检数据 → 日报周报算出来、落 sqh_digests → 接口读得到(登录即可,匿名 401)→
周报出一张 ops_digest 卡且不重复 → 日报里的 warn 出 ops_alert 卡、异常消失那天被 settle_issues 作废 → 订单 ingest 记心跳。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.core.target_org_guard import INTERNATIONAL_TRADE_ORG_NAME
from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.modules.agent_series.suqinghe import brain, cards, digest, worker_main
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDigest
from backend.app.modules.h_series.sitehealth.models import HHealthRun
from backend.app.modules.w_series.shipping.models import WOrder
from backend.app.modules.w_series.traffic.models import WTrafficDaily
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import OWNER, REGULAR, _login, people  # noqa: F401 —— 同一套人

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)  # 用真实的「今天」:快照那一节按真实日期算昨天,夹具的数据要和它对得上
YESTERDAY = digest.la_date(NOW) - timedelta(days=1)
LAST_WEEK = digest.previous_week_key(NOW)
NEXT_MONDAY = (NOW + timedelta(days=(8 - NOW.astimezone(digest.LA).isoweekday()) % 7 or 7)).replace(hour=16, minute=0, second=0, microsecond=0)  # LA 周一 08:00/09:00
TRADE_ORG_ID = "org_5d19e5700d1900000000000000000001"
HEALTH_RUN_ID = UUID("5d19e570-0d19-4000-8000-000000000001")  # 测试库没有贸易组织;看板按它的名字找 workspace_key,所以造一个同名的


def _wipe_digest_data() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhDigest))
        db.execute(delete(WTrafficDaily).where(WTrafficDaily.workspace_key == TRADE_ORG_ID))
        db.execute(delete(WOrder).where(WOrder.order_number.like("DG-%")))
        db.execute(delete(HHealthRun).where(HHealthRun.id == HEALTH_RUN_ID))
        db.execute(delete(OrganizationRecord).where(OrganizationRecord.org_id == TRADE_ORG_ID))
        db.commit()


def _org_id(db) -> str:
    org = digest._trade_org_id(db)
    assert org == TRADE_ORG_ID, org
    return org


@pytest.fixture
def seeded(people):  # noqa: F811
    _wipe_digest_data()
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(OrganizationRecord(org_id=TRADE_ORG_ID, org_name=INTERNATIONAL_TRADE_ORG_NAME, org_type="store", owner_user_id=str(people["owner"]), status="active", metadata_json={}))
        db.flush()
        org = _org_id(db)
        for offset in range(1, 22):  # 三周流量,昨天掉到 3
            day = YESTERDAY - timedelta(days=offset - 1)
            views = 3 if offset == 1 else 40 + (offset % 5)
            db.add(WTrafficDaily(workspace_key=org, day=day, views=views, visitors=views // 2, referrers_json=[{"group": "search", "name": "Google", "url": None, "views": views // 2}], top_posts_json=[], countries_json=[{"code": "US", "name": "United States", "views": views}], search_terms_json={"terms": [], "encrypted": 0}, clicks_json=[]))
        for i, (day, status, total) in enumerate(((YESTERDAY, "processing", "29.99"), (YESTERDAY - timedelta(days=2), "completed", "40.00"), (YESTERDAY - timedelta(days=9), "completed", "12.50"), (YESTERDAY - timedelta(days=3), "cancelled", "99.00"))):
            placed = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
            db.add(WOrder(woo_order_id=900000 + i, order_number=f"DG-{i}", woo_status=status, customer_name="T", country="US", total=total, currency="USD", items_json=[{"name": "Battery", "qty": 1, "sku": "PTB-001"}], placed_at=placed, tracking_status="none"))
        db.add(HHealthRun(id=HEALTH_RUN_ID, trigger="manual", status="completed", started_at=NOW - timedelta(hours=11), finished_at=NOW - timedelta(hours=11), urls_total=50, urls_ok=48, urls_broken=2, urls_slow=0, avg_response_ms=300, p95_response_ms=800, sitemap_ok=True, homepage_ok=True))
        db.commit()
    yield people
    _wipe_digest_data()


def test_day_and_week_digests_are_built_from_the_tables_and_served(seeded, auth_client: TestClient) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        row = digest.build_and_save(db, kind=digest.DAY, period_key=YESTERDAY.isoformat(), now=NOW)
        db.commit()
        payload, findings = row.payload, {f["code"]: f for f in row.findings}
        assert payload["traffic"]["days"][-1] == {"day": YESTERDAY.isoformat(), "views": 3, "visitors": 1}
        assert payload["orders"]["count"] == 1 and payload["orders"]["revenue"] == {"USD": 29.99}
        assert payload["orders_7d"]["count"] == 2 and payload["orders_7d"]["cancelled"] == 1 and payload["orders_7d"]["prev_count"] == 1
        assert payload["site"]["urls_broken"] == 2 and payload["catalog"].get("error") == "读不到"  # 没有快照就是读不到,不是 0
        assert "traffic_drop" in findings and findings["traffic_drop"]["severity"] == "warn" and "site_broken_links" in findings
        assert "order_sync_silent" in findings  # 测试库里没有 w-orders 心跳 = 同步没跑过
        assert row.headline.startswith("昨日 1 人 3 次浏览") and any(s["heading"] == "订单(Woo)" for s in payload["sections"])
        week = digest.build_and_save(db, kind=digest.WEEK, period_key=LAST_WEEK, now=NOW)
        db.commit()
        assert week.payload["day_from"] == digest.week_days(LAST_WEEK)[0].isoformat() and week.payload["traffic"]["views"] > 0 and week.payload["cards"]["created"] >= 0
    # 接口:登录即可看,匿名 401;列表 + 全量
    auth_client.post("/api/public/auth/logout")
    assert auth_client.get("/api/app/suqinghe/digests").status_code == 401
    _login(auth_client, REGULAR)
    listing = auth_client.get("/api/app/suqinghe/digests?limit=5").json()["items"]
    assert sorted((i["kind"], i["period_key"]) for i in listing) == sorted([("day", YESTERDAY.isoformat()), ("week", LAST_WEEK)])
    assert next(i for i in listing if i["kind"] == "day")["warnings"] >= 2
    detail = auth_client.get(f"/api/app/suqinghe/digests/day/{YESTERDAY.isoformat()}").json()
    assert detail["sections"][0]["heading"] == "流量(Jetpack)" and detail["payload"]["orders"]["count"] == 1
    assert auth_client.get("/api/app/suqinghe/digests/week/2026-W99").status_code == 404
    assert auth_client.get("/api/app/suqinghe/office").json()["digest"]["day"]["period_key"] == YESTERDAY.isoformat()


def test_weekly_card_once_and_daily_warnings_become_alert_cards_that_settle(seeded) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhCard))
        db.commit()
        monday = NEXT_MONDAY
        want_week = digest.previous_week_key(monday)
        assert worker_main.should_run_weekly(monday, exists=digest.exists(db, kind=digest.WEEK, period_key=want_week))
        out = worker_main.run_weekly(db, now=monday)
        assert out["week"] == want_week and out["card_new"]
        again = worker_main.run_weekly(db, now=monday)
        assert again["card_ref"] == out["card_ref"] and not again["card_new"]  # 同一周不重复发卡
        card = db.scalar(select(SqhCard).where(SqhCard.ref == out["card_ref"]))
        assert card.kind == "ops_digest" and card.status == "pending" and card.evidence["sections"] and card.evidence["week"] == want_week
        assert not worker_main.should_run_weekly(monday, exists=digest.exists(db, kind=digest.WEEK, period_key=want_week))
        # 日报:warn → ops_alert 卡(最多两张),issue=ops:<code>
        today = digest.la_date(NOW)
        snap = {"date": today.isoformat(), "ops": worker_main.snapshot.ops_section(db)}
        worker_main._save_day_digest(db, snap, now=NOW)
        assert digest.exists(db, kind=digest.DAY, period_key=YESTERDAY.isoformat())
        created = worker_main._ops_alert_cards(db, snap, today=today, raised=set())
        db.commit()
        alerts = list(db.scalars(select(SqhCard).where(SqhCard.kind == "ops_alert")))
        assert created == 2 and len(alerts) == 2 and all(a.evidence["issue"].startswith("ops:") for a in alerts)
        assert worker_main._ops_alert_cards(db, snap, today=today, raised=cards.raised_issues(db)) == 0  # 已经发过的事不再发
        # 第二天异常没了(快照里 ops 读得到但 findings 空)→ 等批的提醒卡作废
        live, readable = brain.issues_in({"ops": {"day": today.isoformat(), "findings": []}})
        settled = cards.settle_issues(db, live=set(live), readable=readable, today=(today + timedelta(days=1)).isoformat())
        db.commit()
        assert settled["gone"] == 2 and all(a.status == "stale" for a in db.scalars(select(SqhCard).where(SqhCard.kind == "ops_alert")))
        # 读不到的那天不动卡
        assert "ops" not in brain.issues_in({"ops": {"error": "读不到"}})[1]


def test_orders_ingest_records_a_heartbeat(seeded, auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.worker_heartbeat import list_heartbeats

    monkeypatch.setenv("W_ORDERS_INGEST_TOKEN", "t-digest")
    resp = auth_client.post("/w/orders/ingest", json={"orders": [{"woo_order_id": 900900, "order_number": "DG-hb", "woo_status": "processing", "customer_name": "H", "country": "US", "total": "1.00", "currency": "USD", "items": [], "placed_at": NOW.isoformat()}]}, headers={"X-Ingest-Token": "t-digest"})
    assert resp.status_code == 200, resp.text
    with without_org_data_isolation(), SessionLocal() as db:
        beat = next(b for b in list_heartbeats(db) if b["worker_name"] == "w-orders")
        assert beat["last_success_at"] and not beat["stale"]
        db.execute(delete(WOrder).where(WOrder.order_number == "DG-hb"))
        db.commit()


def test_backfill_fills_missing_periods_only(seeded) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        made = digest.backfill(db, days=3, weeks=1, now=NOW)
        assert made == {"day": 3, "week": 1}
        assert digest.backfill(db, days=3, weeks=1, now=NOW) == {"day": 0, "week": 0}
        keys = sorted(r.period_key for r in db.scalars(select(SqhDigest).where(SqhDigest.kind == digest.DAY)))
        assert keys == [(YESTERDAY - timedelta(days=n)).isoformat() for n in (2, 1, 0)]


def test_week_digest_carries_search_console_data_when_pulled(seeded) -> None:
    """看板第二期:拉过的 Search Console 数据进周报的「搜索」和「搜索缺口」两节;没拉过(没钥匙)就写「还没接」。
    11-03 改按「页」存:全站合计记在天的那一行(含被匿名的词),页面榜按页合计,缺口按近 28 天算;
    词窗口拉过但谷歌一个词都没给 → 「搜索词」一行说谷歌没给;词窗口有词 → 点击最多的词 + 差一步/排得远的词。"""
    from backend.app.modules.agent_series.suqinghe import gsc
    from backend.app.modules.agent_series.suqinghe.models import SqhGscDay, SqhGscPage, SqhGscQuery

    def wipe(db) -> None:
        for model in (SqhGscPage, SqhGscQuery, SqhGscDay):
            db.execute(delete(model))
        db.commit()

    monday, sunday = digest.week_days(LAST_WEEK)
    with without_org_data_isolation(), SessionLocal() as db:
        wipe(db)
        before = digest.build_and_save(db, kind=digest.WEEK, period_key=LAST_WEEK, now=NOW)
        search_before = before.payload["search"]
        assert search_before.get("configured") is False or search_before.get("last_day") is None  # 测试库没钥匙 / 没拉过
        for offset in range(7):
            day = monday + timedelta(days=offset)
            gsc.save_day(db, day, {
                "site": {"clicks": 3, "impressions": 90, "ctr": 0.0333, "position": 10.0},  # 比两页加起来多:有被匿名的词落在别的页上
                "pages": [
                    {"page": "https://barongyekhna.com/product/lantern/", "clicks": 2, "impressions": 60, "ctr": 0.033, "position": 9.0},
                    {"page": "https://barongyekhna.com/blog/poles/", "clicks": 0, "impressions": 20, "ctr": 0.0, "position": 28.0},
                ],
            })
        gsc.save_window(db, sunday, [])  # 截止周日的 28 天窗口:谷歌一个词都没给
        db.commit()
        assert gsc.pulled_days(db) >= {monday, sunday}
        row = digest.build_and_save(db, kind=digest.WEEK, period_key=LAST_WEEK, now=NOW)
        db.commit()
        search = row.payload["search"]
        assert search["configured"] and search["covered_days"] == 7 and search["clicks"] == 21 and search["impressions"] == 630  # 全站合计,不是按页加
        assert [(p["label"], p["clicks"], p["impressions"]) for p in search["top_pages"]] == [("lantern", 14, 420), ("poles", 0, 140)]
        assert search["queries_hidden"] is True and search["top_queries"] == [] and search["query_window"]["rows"] == 0
        assert [x["page"] for x in search["gaps"]["quick_win_pages"]] == ["https://barongyekhna.com/product/lantern/"]  # 28 天 420 展现、排 9
        assert search["gap_window"]["impressions"] == 630
        sections = {s["heading"]: s for s in row.payload["sections"]}
        assert "搜索(Search Console)" in sections and "搜索缺口" in sections
        assert {r[0]: r[1] for r in sections["搜索(Search Console)"]["rows"]}["搜索词"].startswith("谷歌没给")
        assert "谷歌搜索 21 点击 630 展现" in row.headline

        # 量上来以后谷歌开始给词:同一窗重拉,词进周报
        gsc.save_window(db, sunday, [
            {"query": "camping lantern", "clicks": 8, "impressions": 300, "ctr": 0.0267, "position": 9.0},
            {"query": "tent pole repair", "clicks": 0, "impressions": 40, "ctr": 0.0, "position": 28.0},
        ])
        db.commit()
        search = digest.build_and_save(db, kind=digest.WEEK, period_key=LAST_WEEK, now=NOW).payload["search"]
        db.commit()
        assert search["queries_hidden"] is False and [q["query"] for q in search["top_queries"]] == ["camping lantern", "tent pole repair"]
        assert [x["query"] for x in search["gaps"]["quick_wins"]] == ["camping lantern"] and [x["query"] for x in search["gaps"]["far_queries"]] == ["tent pole repair"]
        assert search["gaps"]["new_queries"] == []  # 只有一窗,不比
        wipe(db)


def test_search_console_key_is_read_through_the_console_binding(seeded) -> None:
    """10-31:钥匙按控制台家规走——密钥管理登记一把 google_search_console,绑到 w.site_ops/google_search_console,她就读得到;
    不绑读不到(当「没接」),绑错类型也读不到。原来走 SecretManager,白名单里没这一类,登记了照样读不到。"""
    import json as _json

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
    from backend.app.modules.agent_series.suqinghe import gsc
    from backend.app.schemas.api_key_orchestration import ApiKeyBindingCreateRequest, ApiKeyCreateRequest
    from backend.app.services import api_key_orchestration as keys

    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    raw = _json.dumps({"type": "service_account", "project_id": "p", "private_key_id": "x", "private_key": pem, "client_email": "sqh@p.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token"})
    actor = str(seeded["owner"])
    with without_org_data_isolation(), SessionLocal() as db:
        try:
            with pytest.raises(gsc.GscNotConfigured):
                gsc.credentials(db)
            key = keys.create_api_key(db, org_id=TRADE_ORG_ID, payload=ApiKeyCreateRequest(name="Search Console 服务账号", url="https://searchconsole.googleapis.com", key_value=raw, key_type="google_search_console"), actor_user_id=actor)
            with pytest.raises(gsc.GscNotConfigured):  # 登记了没绑 = 还没接
                gsc.credentials(db)
            keys.create_api_key_binding(db, org_id=TRADE_ORG_ID, payload=ApiKeyBindingCreateRequest(module_id=gsc.BINDING_MODULE_ID, key_id=key.key_id, key_alias=gsc.BINDING_KEY_ALIAS), actor_user_id=actor)
            account = gsc.credentials(db)
            assert account.client_email == "sqh@p.iam.gserviceaccount.com" and "PRIVATE KEY" in account.private_key_pem
        finally:
            db.rollback()
            db.execute(delete(ApiKeyModuleBindingRecord).where(ApiKeyModuleBindingRecord.org_id == TRADE_ORG_ID))
            db.execute(delete(ApiKeyRecord).where(ApiKeyRecord.org_id == TRADE_ORG_ID))
            db.commit()
