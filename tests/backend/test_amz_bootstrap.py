"""A0 建号 + 种子导入的集成测试(真 Postgres):幂等两次、四组织 amazon、王创鑫 admin + 五店 grant、
机器人四条成员关系 + 四条 C19 归属、种子文件导两次只算一次。"""

from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.c19 import C19AffiliationRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.registry import AgentRegistry
from backend.app.models.user import User
from backend.app.modules.amz_series import bootstrap as bs
from backend.app.modules.amz_series import rules, seed_import as si
from backend.app.modules.amz_series import suggestions as sug
from backend.app.modules.amz_series.jobs import schedule_due_jobs, claim, process_job
from backend.app.modules.amz_series import experience, fact_sheets, images, launches, products, reports_sync, reviews, work_log
from backend.app.modules.amz_series.models import AmzCompetitor, AmzCompetitorSnapshot, AmzLaunch, AmzReview, AmzExperience, AmzFactSheet, AmzImageAsset, AmzImageBrief, AmzJob, AmzOutcome, AmzProduct, AmzReportRun, AmzSalesDaily, AmzSqp, AmzSuggestion, AmzWorkLog
from backend.app.modules.amz_series.catalog import COMPANIES, COMPANY_ORG_IDS, STORE_CODES
from backend.app.modules.amz_series.constants import EMPLOYEE_USERNAMES, EMPLOYEES
from backend.app.modules.amz_series.models import AmzAdSearchTerm, AmzFxRate, AmzSeedImport, AmzStore, AmzStoreGrant, AmzTransaction
from backend.app.services.data_isolation import without_org_data_isolation

pytestmark = pytest.mark.integration

USERNAMES = ("amz_t_owner", "amz_t_manager", *EMPLOYEE_USERNAMES.values())


@pytest.fixture
def db():
    with SessionLocal() as session, without_org_data_isolation():
        _cleanup(session)
        yield session
        _cleanup(session)


def _cleanup(session) -> None:
    from backend.app.modules.amz_series.models import AmzBaTopClick

    session.execute(delete(AmzBaTopClick))
    from backend.app.modules.amz_series.models import AmzInventoryDaily, AmzListingSnapshot, AmzSolicitation

    session.execute(delete(AmzInventoryDaily))
    session.execute(delete(AmzListingSnapshot))
    session.execute(delete(AmzSolicitation))
    session.execute(delete(AmzCompetitorSnapshot))
    session.execute(delete(AmzCompetitor))
    session.execute(delete(AmzReview))
    session.execute(delete(AmzLaunch))
    session.execute(delete(AmzExperience))
    session.execute(delete(AmzOutcome))
    session.execute(delete(AmzImageAsset))
    session.execute(delete(AmzImageBrief))
    session.execute(delete(AmzFactSheet))
    session.execute(delete(AmzSqp))
    session.execute(delete(AmzSalesDaily))
    session.execute(delete(AmzReportRun))
    session.execute(delete(AmzWorkLog))
    session.execute(delete(AmzProduct))
    session.execute(delete(AmzSuggestion))
    session.execute(delete(AmzJob))
    session.execute(delete(AmzSeedImport))
    session.execute(delete(AmzAdSearchTerm))
    session.execute(delete(AmzTransaction))
    session.execute(delete(AmzFxRate))
    session.execute(delete(AmzStoreGrant))
    session.execute(delete(AmzStore))
    user_ids = list(session.scalars(select(User.id).where(User.username.in_(USERNAMES))))
    if user_ids:
        session.execute(delete(C19AffiliationRecord).where(C19AffiliationRecord.user_id.in_(user_ids)))
        session.execute(delete(OrgMembershipRecord).where(OrgMembershipRecord.user_id.in_([str(i) for i in user_ids])))
    session.execute(delete(OrgMembershipRecord).where(OrgMembershipRecord.org_id.in_(COMPANY_ORG_IDS)))
    session.execute(delete(C19AffiliationRecord).where(C19AffiliationRecord.org_id.in_(COMPANY_ORG_IDS)))
    session.execute(delete(AgentRegistry).where(AgentRegistry.agent_id.like("amz.%")))
    session.execute(delete(OrganizationRecord).where(OrganizationRecord.org_id.in_(COMPANY_ORG_IDS)))
    session.execute(delete(User).where(User.username.in_(USERNAMES)))
    session.commit()


def _mk_user(db, username: str, role: str) -> User:
    user = User(username=username, password_hash=hash_password("Xy9!passwordPASS"), role=role, is_active=True)
    db.add(user)
    db.commit()
    return user


def test_bootstrap_is_idempotent_and_wires_orgs_stores_grants_and_bots(db) -> None:
    owner = _mk_user(db, "amz_t_owner", "owner")
    manager = _mk_user(db, "amz_t_manager", "super_admin")
    passwords = {e: f"Amz{e}-secret-2026!!" for e in EMPLOYEES}

    first = bs.bootstrap(db, passwords=passwords, owner_user_id=owner.id, manager_user_id=manager.id)
    second = bs.bootstrap(db, passwords=passwords, owner_user_id=owner.id, manager_user_id=manager.id)
    assert set(first["companies"].values()) == {"created"}
    assert set(second["companies"].values()) == {"updated"}
    assert first["agents_created"] and second["agents_created"] == []

    orgs = list(db.scalars(select(OrganizationRecord).where(OrganizationRecord.org_id.in_(COMPANY_ORG_IDS))))
    assert len(orgs) == 4 and {o.org_type for o in orgs} == {"amazon"} and {o.status for o in orgs} == {"active"}
    assert {o.org_name for o in orgs} == {c.org_name for c in COMPANIES}

    stores = list(db.scalars(select(AmzStore).order_by(AmzStore.store_code)))
    assert [s.store_code for s in stores] == sorted(STORE_CODES)
    assert all(s.company_org_id in COMPANY_ORG_IDS for s in stores)

    # 王创鑫:四组织 admin,五店 grant;owner:四组织 owner,零 grant。
    manager_memberships = list(db.scalars(select(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(manager.id))))
    assert {m.org_id for m in manager_memberships} == set(COMPANY_ORG_IDS) and {m.role for m in manager_memberships} == {"admin"}
    assert db.scalar(select(func.count()).select_from(AmzStoreGrant).where(AmzStoreGrant.user_id == manager.id)) == 5
    assert db.scalar(select(func.count()).select_from(AmzStoreGrant).where(AmzStoreGrant.user_id == owner.id)) == 0
    assert db.scalar(select(func.count()).select_from(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(owner.id), OrgMembershipRecord.org_id.in_(COMPANY_ORG_IDS))) == 4

    # 机器人:viewer + is_bot,四组织 member,四条 C19 归属,主组织=龙杰。
    for employee in EMPLOYEES:
        bot = db.scalar(select(User).where(User.username == EMPLOYEE_USERNAMES[employee]))
        assert bot is not None and bot.is_bot and bot.role == "viewer" and bot.is_active
        assert bot.organization_id == bs.AGENT_HOME_COMPANY.org_id
        assert db.scalar(select(func.count()).select_from(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(bot.id))) == 4
        assert db.scalar(select(func.count()).select_from(C19AffiliationRecord).where(C19AffiliationRecord.user_id == bot.id)) == 4
        assert db.scalar(select(func.count()).select_from(AmzStoreGrant).where(AmzStoreGrant.user_id == bot.id)) == 0
    assert db.scalar(select(func.count()).select_from(AgentRegistry).where(AgentRegistry.agent_id.like("amz.%"))) == 4


def test_seed_import_is_file_idempotent_and_row_idempotent(db, tmp_path: Path) -> None:
    owner = _mk_user(db, "amz_t_owner", "owner")
    manager = _mk_user(db, "amz_t_manager", "super_admin")
    bs.bootstrap(db, passwords={}, owner_user_id=owner.id, manager_user_id=manager.id)

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "ads__03us.csv").write_text(textwrap.dedent("""\
        日期,广告组合名称,货币,广告活动名称,广告组名称,国家/地区,投放,匹配类型,客户搜索词,展示量,点击量,点击率 (CTR),单次点击成本 (CPC),花费,7天总销售额,广告投入产出比 (ACOS) 总计,总广告投资回报率 (ROAS),7天总订单数(#),7天总销售量(#),7天的转化率,7天内广告SKU销售量(#),7天内其他SKU销售量(#),7天内广告SKU销售额,7天内其他SKU销售额
        2026-08-01,No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,camping shower,120,3,0.025,0.73,2.19,28.49,0.0769,13.0,1,1,0.33,1,0,28.49,0
        2026-08-02,No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,camping shower,90,2,0.022,0.70,1.40,0,,0,0,0,0,0,0,0,0
        """), encoding="utf-8")
    (csv_dir / "txn__01de__2026-08.csv").write_text(textwrap.dedent("""\
        "Alle Beträge in Euro sofern nicht anders gekennzeichnet"
        "Datum/Uhrzeit","Abrechnungsnummer","Typ","Bestellnummer","SKU","Beschreibung","Menge","Marketplace","Versand","Ort der Bestellung","Bundesland","Postleitzahl","Steuererhebungsmodell","Umsätze","Produktumsatzsteuer","Gutschrift für Versandkosten","Steuer auf Versandgutschrift","Gutschrift für Geschenkverpackung","Steuer auf Geschenkverpackungsgutschriften","Rabatte aus Werbeaktionen","Steuer auf Aktionsrabatte","Einbehaltene Steuer auf Marketplace","Verkaufsgebühren","Gebühren zu Versand durch Amazon","Andere Transaktionsgebühren","Andere","Gesamt","Transaktionsstatus","Freigabedatum der Transaktion"
        "31.07.2026 23:35:56 UTC","27672687742","Bestellung","305-8386510-5251526","DE-LYQ-03","B013 Dusche","1","amazon.de","Amazon","","","","MarketplaceFacilitator","24,33","4,62","0","0","0","0","0","0","-4,62","-4,33","-3,68","0","0","16,32","Freigegeben","01.08.2026"
        """), encoding="utf-8")

    first = si.import_directory(db, tmp_path)
    db.commit()
    second = si.import_directory(db, tmp_path)
    db.commit()
    assert {r["file"]: r.get("inserted") for r in first} == {"ads__03us.csv": 2, "txn__01de__2026-08.csv": 1}
    assert all(r.get("skipped") == "already_imported" for r in second)
    assert db.scalar(select(func.count()).select_from(AmzSeedImport)) == 2
    assert db.scalar(select(func.count()).select_from(AmzAdSearchTerm)) == 2
    txn = db.scalar(select(AmzTransaction))
    assert txn.store_code == "01de" and txn.currency == "EUR" and float(txn.total) == 16.32
    assert txn.fx_source == "seed_fixed" and float(txn.total_usd) == round(16.32 * float(si.DEFAULT_EUR_USD), 2)
    # 汇率:央行价到位后,种子期按 1.08 折的欧元行按「当天」汇率重算(周末用之前工作日的价)
    from decimal import Decimal as _D

    from backend.app.modules.amz_series import fx as _fx

    posted_day = txn.posted_at.date()
    assert _fx.upsert_rates(db, _fx.fill_calendar({posted_day - timedelta(days=1): _D("1.1467")}, posted_day - timedelta(days=1), posted_day)) == 2
    assert _fx.recompute_transactions(db, store_code="01de", currency="EUR") == 1
    db.commit()
    db.refresh(txn)
    assert txn.fx_source == "ecb" and float(txn.fx_rate) == 1.1467 and float(txn.total_usd) == round(16.32 * 1.1467, 2)
    assert _fx.recompute_transactions(db, store_code="01de", currency="EUR") == 0  # 幂等
    assert _fx.recompute_transactions(db, store_code="03us", currency="USD") == 0

    # 产品名册从交易行长出来:德国站 Bestellung 行 → 一个泵 SKU
    assert products.sync_from_transactions(db, store_code="01de") == {"skus": 1, "created": 1, "updated": 0}
    db.commit()
    product = db.scalar(select(AmzProduct).where(AmzProduct.store_code == "01de"))
    assert product.sku == "DE-LYQ-03" and product.product_line == "pump" and product.metadata_json["units_total"] == 1
    assert products.sync_from_transactions(db, store_code="01de")["updated"] == 1
    assert products.roster(db, store_codes=["01de"])[0]["SKU"] == "DE-LYQ-03" and products.roster(db, store_codes=[]) == []

    # 改一个字节 = 新文件,但行 row_key 相同 → 不重复插入。
    (csv_dir / "ads__03us.csv").write_text((csv_dir / "ads__03us.csv").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    third = si.import_directory(db, tmp_path)
    db.commit()
    ads_result = next(r for r in third if r["file"] == "ads__03us.csv")
    assert ads_result["parsed"] == 2 and ads_result["inserted"] == 0
    assert db.scalar(select(func.count()).select_from(AmzAdSearchTerm)) == 2


def test_rules_engine_runs_on_seed_rows_and_jobs_write_heartbeat(db, tmp_path: Path) -> None:
    from backend.app.services.worker_heartbeat import list_heartbeats

    owner = _mk_user(db, "amz_t_owner", "owner")
    manager = _mk_user(db, "amz_t_manager", "super_admin")
    bs.bootstrap(db, passwords={}, owner_user_id=owner.id, manager_user_id=manager.id)
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    header = "日期,广告组合名称,货币,广告活动名称,广告组名称,国家/地区,投放,匹配类型,客户搜索词,展示量,点击量,点击率 (CTR),单次点击成本 (CPC),花费,7天总销售额,广告投入产出比 (ACOS) 总计,总广告投资回报率 (ROAS),7天总订单数(#),7天总销售量(#),7天的转化率,7天内广告SKU销售量(#),7天内其他SKU销售量(#),7天内广告SKU销售额,7天内其他SKU销售额\n"
    lines = [header]
    # 一个赢家词(4 单 ACOS 低,在自动组)、一个 0 单大词、一个加热词、一个精准倒挂词
    for day in range(1, 11):
        lines.append(f"2026-08-{day:02d},No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,camping shower,200,10,0.05,0.70,7.00,60.00,0.11,8.5,1,1,0.1,1,0,60.00,0\n")
        lines.append(f"2026-08-{day:02d},No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,camping gear,50,3,0.06,0.70,2.10,0,,0,0,0,0,0,0,0,0\n")
        lines.append(f"2026-08-{day:02d},No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,portable shower with heater,50,3,0.06,0.70,2.10,0,,0,0,0,0,0,0,0,0\n")
        lines.append(f"2026-08-{day:02d},No Portfolio,USD,蓝色 精准0711,蓝色 精准0711,美国,outdoor shower,EXACT,outdoor shower,100,5,0.05,1.00,5.00,4.00,1.25,0.8,0,0,0,0,0,0,0\n")
    (csv_dir / "ads__03us.csv").write_text("".join(lines), encoding="utf-8")
    # 兄弟店 01us:同款泵、同两个词——camping shower 转化是 03us 的四倍;shower pump 点击率是 03us 的十几倍
    sibling = [header]
    for day in range(1, 11):
        sibling.append(f"2026-08-{day:02d},No Portfolio,USD,蓝色泵 自动0801,蓝色泵 自动0801,美国,loose-match,-,camping shower,200,10,0.05,0.70,7.00,240.00,0.03,34,4,4,0.4,4,0,240.00,0\n")
        sibling.append(f"2026-08-{day:02d},No Portfolio,USD,蓝色泵 自动0801,蓝色泵 自动0801,美国,loose-match,-,shower pump,1000,30,0.03,0.70,21.00,60.00,0.35,2.8,1,1,0.03,1,0,60.00,0\n")
        lines.append(f"2026-08-{day:02d},No Portfolio,USD,黑色泵 自动0712,黑色泵 自动0712,美国,loose-match,-,shower pump,1000,2,0.002,0.70,1.40,0,,0,0,0,0,0,0,0,0\n")
    (csv_dir / "ads__03us.csv").write_text("".join(lines), encoding="utf-8")
    (csv_dir / "ads__01us.csv").write_text("".join(sibling), encoding="utf-8")
    si.import_directory(db, tmp_path)
    db.commit()

    counts = rules.run_rules_for_store(db, store_code="03us", currency="USD")
    db.commit()
    assert counts["created"] >= 3
    rows = sug.list_suggestions(db, store_codes=["03us"], status="open")
    kinds = {row.action_type for row in rows}
    assert {"harvest", "negative", "demand_reserve", "bid_down"} <= kinds
    harvest = next(row for row in rows if row.action_type == "harvest")
    assert "camping shower" in harvest.title and harvest.level == "L0" and harvest.evidence_json["orders"] == 10
    reserve = next(row for row in rows if row.action_type == "demand_reserve")
    assert "portable shower with heater" in reserve.evidence_json["terms"]
    assert not any(row.action_type == "negative" and "heater" in row.title for row in rows)
    # 跨店对照:笑笑拿到 camping shower 的转化差,熊拿到 shower pump 的点击率差;01us 自己跑不会拿到这两条
    cvr_gap = next(row for row in rows if row.action_type == "listing_cvr_gap")
    assert cvr_gap.employee == "A" and "camping shower" in cvr_gap.title and cvr_gap.evidence_json["best"]["store"] == "01us" and cvr_gap.evidence_json["best"]["cvr_pct"] == 40.0
    ctr_gap = next(row for row in rows if row.action_type == "screen_ctr_gap")
    assert ctr_gap.employee == "B" and "shower pump" in ctr_gap.title and ctr_gap.evidence_json["mine"]["ctr_pct"] == 0.2
    rules.run_rules_for_store(db, store_code="01us", currency="USD")
    db.commit()
    assert not [r for r in sug.list_suggestions(db, store_codes=["01us"], status="open") if r.employee in ("A", "B")]

    # 第二次跑:同样的建议只更新不新增;决定过的不再重发。
    again = rules.run_rules_for_store(db, store_code="03us", currency="USD")
    db.commit()
    assert again["created"] == 0 and again["updated"] >= 3
    decided = sug.decide_suggestion(db, suggestion_id=harvest.id, decision="reject", reason="先不收", actor=manager, allowed_store_codes=None)
    db.commit()
    assert decided.status == "rejected" and decided.reject_reason == "先不收"

    # 硬记忆:每条建议一条 suggested;驳回一条带原因;按问题能检索出来;没授权的店看不到
    logged = sum(work_log.counts(db, employee=e, store_codes=None).get("suggested", 0) for e in EMPLOYEES)
    assert logged == db.scalar(select(func.count()).select_from(AmzSuggestion))
    hits = work_log.relevant(db, employee="D", store_codes=["03us"], question="03us 的 camping shower 最近怎么了")
    assert [h.kind for h in hits[:2]] == ["rejected", "suggested"] and hits[0].why == "先不收" and hits[0].actor_user_id == manager.id
    assert work_log.relevant(db, employee="D", store_codes=["01de"], question="camping shower") == []
    spoken = work_log.record(db, employee="A", kind="note", title="01us 的泵标题加了 heater", why="冬季", store_code="01us", subject="B0ABCDEFGH", source="chat", actor_user_id=owner.id)
    db.commit()
    assert spoken.asin == "B0ABCDEFGH"
    assert work_log.relevant(db, employee="A", store_codes=None, question="B0ABCDEFGH 标题为什么改")[0].why == "冬季"
    assert work_log.backfill_from_suggestions(db) == 0  # 都已经记过
    section = __import__("backend.app.modules.amz_series.agents.context", fromlist=["work_log_section"]).work_log_section(db, employee="D", store_codes=None, question="camping shower")
    assert section["总条数"] >= 3 and section["跟这句话有关的"][0]["为什么"] == "先不收"
    third = rules.run_rules_for_store(db, store_code="03us", currency="USD")
    db.commit()
    assert third["skipped_decided"] >= 1
    with pytest.raises(Exception):
        sug.decide_suggestion(db, suggestion_id=harvest.id, decision="reject", reason="", actor=manager, allowed_store_codes=None)

    # 员工面板与曲线
    panel = sug.employee_panel(db, store_codes=["03us"])
    d_panel = next(item for item in panel["items"] if item["employee"] == "D")
    assert d_panel["open"] >= 3 and d_panel["latest"] is not None
    series = sug.daily_series(db, store_codes=["03us"], days=14)
    assert series["as_of"] == "2026-08-10" and len(series["days"]) == 14 and series["days"][-1]["spend_usd"] > 0

    # A1 报表落库:夹具 → upsert 两遍幂等 → active_asins 按销量排
    import json as _json

    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures/amz"
    st = _json.loads((fixture_dir / "sales_traffic_day.json").read_text(encoding="utf-8"))
    rows = reports_sync.parse_sales_traffic(st, store_code="01us", currency_default="USD")
    assert reports_sync.upsert_sales_daily(db, rows) == 3 and reports_sync.upsert_sales_daily(db, rows) == 3
    db.commit()
    assert db.scalar(select(func.count()).select_from(AmzSalesDaily)) == 3
    assert reports_sync.active_asins(db, "01us", since=date(2026, 9, 1)) == ["B0TESTA0001", "B0TESTA0002"]
    sq = _json.loads((fixture_dir / "sqp_week.json").read_text(encoding="utf-8"))
    assert reports_sync.upsert_sqp(db, reports_sync.parse_sqp(sq, store_code="01us")) == 2
    db.commit()
    assert db.scalar(select(func.count()).select_from(AmzSqp)) == 2
    assert reports_sync.have_sqp_weeks(db, "01us") == {("B0TESTA0001", date(2026, 8, 30))}

    # 长辰:再造一周(09-06 起),camping shower 购买份额从 2% 掉到 0.5%、点击份额 10% → 详情页在漏 + 份额掉了 + 周简报
    week2 = _json.loads(_json.dumps(sq))
    for item in week2["dataByAsin"]:
        item["startDate"], item["endDate"] = "2026-09-06", "2026-09-12"
    week2["dataByAsin"][0]["purchaseData"]["asinPurchaseShare"] = 0.5
    week2["dataByAsin"][0]["purchaseData"]["asinPurchaseCount"] = 0
    assert reports_sync.upsert_sqp(db, reports_sync.parse_sqp(week2, store_code="01us")) == 2
    db.commit()
    rules.run_rules_for_store(db, store_code="01us", currency="USD")
    db.commit()
    c_rows = [r for r in sug.list_suggestions(db, store_codes=["01us"], status="open") if r.employee == "C"]
    kinds = {r.action_type for r in c_rows}
    assert {"sqp_detail_page_leak", "sqp_share_drop", "sqp_weekly_brief"} <= kinds
    leak = next(r for r in c_rows if r.action_type == "sqp_detail_page_leak")
    assert "camping shower" in leak.title and leak.why.startswith("事实:") and leak.evidence_json["handoff"] == ["A", "B"]
    drop = next(r for r in c_rows if r.action_type == "sqp_share_drop")
    assert drop.evidence_json["before_pct"] == 2.0 and drop.evidence_json["after_pct"] == 0.5 and "点击还在、购买掉了" in drop.why
    brief = next(r for r in c_rows if r.action_type == "sqp_weekly_brief")
    assert "camping shower(-1.5 点)" in brief.why and len([r for r in c_rows if r.action_type == "sqp_weekly_brief"]) == 1

    # 事实表:保存即代码判;同 scope 再存是 v2;判一下(模型桩)只加追问不改判定;够用的用途才给员工
    sheet = fact_sheets.upsert_sheet(db, product_line="pump", store_code=None, sku=None, title="沐浴泵 7800mAh", facts={"is": "便携淋浴泵", "cost": {"factory_cny": 60, "freight_cny": 7, "price_usd": 32.99}, "specs": {"weight_g": "650", "dimensions_cm": "10x10x20", "battery_mah": "7800"}}, actor=owner)
    db.commit()
    assert sheet.version == 1 and sheet.status == "draft" and sheet.sufficiency_json["ready"]["pnl"] is True and sheet.sufficiency_json["ready"]["copy"] is False
    assert fact_sheets.ready_for(db, product_line="pump", use="pnl") is not None and fact_sheets.ready_for(db, product_line="pump", use="copy") is None
    again = fact_sheets.upsert_sheet(db, product_line="pump", store_code=None, sku=None, title="沐浴泵 7800mAh", facts={"is": "便携淋浴泵,不加热"}, actor=owner)
    db.commit()
    assert again.id == sheet.id and again.version == 2 and again.sufficiency_json["ready"]["pnl"] is False
    judged = fact_sheets.judge_sheet(db, sheet_id=sheet.id, with_model=True, call=lambda messages, *, org_id: {"content": '{"contradictions": [], "questions": ["软管多长?"], "missing_hints": {"copy": [], "image": [], "faq": [], "pnl": []}}'})
    db.commit()
    assert judged.sufficiency_json["model"]["questions"] == ["软管多长?"] and judged.sufficiency_json["ready"]["copy"] is False
    assert [r.kind for r in work_log.recent(db, employee="A", store_codes=None, limit=2)] == ["observation", "observation"]
    assert len(fact_sheets.list_sheets(db, store_codes=["03us"])) == 1  # 跨店共用的表谁都看得到
    with pytest.raises(Exception):
        fact_sheets.upsert_sheet(db, product_line="rocket", store_code=None, sku=None, title="x", facts={}, actor=owner)

    # 图片通道:事实表不够 → 不建 brief;填够 → 从「同屏输了」建 brief → 参考图 → 交稿过四道门(看图桩)→ 选定 → 上线 → 28 天回看
    import io as _io

    from PIL import Image as _Image

    def _png(w, h, stripe):
        img = _Image.new("RGB", (w, h), (255, 255, 255))
        for x in range(stripe, min(w, stripe + w // 4)):
            for y in range(h):
                img.putpixel((x, y), (0, 0, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AMZ_MEDIA_ROOT", str(tmp_path / "amz-media"))
    try:
        with pytest.raises(Exception) as not_ready:
            images.create_brief_from_suggestion(db, suggestion_id=ctr_gap.id, actor=owner)
        assert getattr(not_ready.value, "code", "") == "amz_fact_sheet_not_ready"
        fact_sheets.upsert_sheet(db, product_line="pump", store_code=None, sku=None, title="沐浴泵 7800mAh", facts={"is": "便携淋浴泵,不加热", "how_it_works": "整机入水", "is_not": "不是热水器", "specs": {"weight_g": "650", "dimensions_cm": "10x10x20", "battery_mah": "7800"}, "indicators": "红灯充电", "package": "泵、软管、花洒", "audience": "露营", "misreadings": "以为能加热", "cost": {"factory_cny": 60, "freight_cny": 7, "price_usd": 32.99}, "competitor_asins": "B0AAAAAAA1"}, actor=owner)
        db.commit()
        brief = images.create_brief_from_suggestion(db, suggestion_id=ctr_gap.id, actor=owner)
        db.commit()
        assert brief.store_code == "03us" and brief.position == "main" and "shower pump" in brief.title and "01us" in brief.brief_md
        assert images.create_brief_from_suggestion(db, suggestion_id=ctr_gap.id, actor=owner).id == brief.id  # 幂等
        ref = images.add_reference(db, brief=brief, kind="sibling_main", contents=_png(600, 600, 100), note="01us", actor=owner)
        images.add_reference(db, brief=brief, kind="competitor_thumb", contents=_png(300, 300, 200), note="vignuto", actor=owner)
        db.commit()
        assert ref.dhash and images.asset_bytes(ref)
        stub = lambda messages, *, org_id: {"passed": True, "click_rank": 1, "stands_out": "亮", "fix": [], "must_have_missing": [], "forbidden_found": [], "text_or_logo": False, "notes": []}  # noqa: E731
        same_as_sibling = images.submit(db, brief=brief, contents=_png(1200, 1200, 200), note="r1", submitted_via="mcp", actor_user_id=owner.id, call=stub)
        db.commit()
        assert same_as_sibling.round == 1 and same_as_sibling.review_json["verdict"] == "failed"
        assert any("兄弟店" in g["name"] and g["passed"] is False for g in same_as_sibling.review_json["gates"])
        good = images.submit(db, brief=brief, contents=_png(1200, 1200, 900), note="r2", submitted_via="upload", actor_user_id=owner.id, call=stub)
        db.commit()
        assert good.round == 2 and good.review_json["verdict"] == "passed" and brief.status == "in_review"
        with pytest.raises(Exception):
            images.decide_asset(db, asset=good, decision="reject", reason="", actor=owner)
        images.decide_asset(db, asset=good, decision="choose", reason=None, actor=owner)
        db.commit()
        assert brief.status == "approved" and brief.chosen_asset_id == good.id
        live = images.mark_live(db, brief=brief, actor=owner, live_on=date(2026, 8, 5))
        db.commit()
        assert live.status == "live" and live.baseline_json["term"] == "shower pump" and live.baseline_json["ads_ctr_14d_before"]["impressions"] > 0
        assert images.run_lookbacks(db, today=date(2026, 8, 12)) == 0  # 未满 14 天
        assert images.run_lookbacks(db, today=date(2026, 9, 10)) == 2  # 14 与 28 天一起补
        db.commit()
        assert set(brief.lookback_json) == {"d14", "d28"} and images.run_lookbacks(db, today=date(2026, 9, 11)) == 0
        assert [r.kind for r in work_log.recent(db, employee="B", store_codes=["03us"], limit=3)] == ["observation", "observation", "executed"]
        with pytest.raises(Exception):
            images.submit(db, brief=brief, contents=_png(1200, 1200, 50), note="", submitted_via="upload", actor_user_id=owner.id, call=stub)  # 已上线不收稿
    finally:
        monkeypatch.undo()

    # 经验库:真建议判结果 → 6 条「收割」都没成立 → 03us 收割门槛抬一档 → 规则真的用上新门槛,且新建议附经验、降一档
    assert experience.evaluate_live(db, "03us") == 0  # 种子只有 10 天,as_of+14 还没到
    harvest_as_of = harvest.as_of
    for k in range(6):
        db.add(AmzOutcome(store_code="03us", action_type="harvest", subject=f"t{k}", as_of=harvest_as_of - timedelta(days=30 + k), horizon_days=28, source="backtest", verdict="wrong", metrics_json={"clicks": 20, "orders": 0}))
    db.commit()
    assert experience.learn_precision_and_params(db, "03us") == 2
    db.commit()
    assert experience.param_for(db, "03us", "harvest_min_orders", 3) == 4.0
    assert experience.param_for(db, "01us", "harvest_min_orders", 3) == 3.0  # 只动那家店
    advice = experience.consult(db, store_code="03us", action_type="harvest")
    assert advice["downgrade"] is True and any("0 条成立" in n or "(0.0%)" in n for n in advice["notes"])
    entries = experience.list_entries(db, store_codes=["03us"], employee="D")
    assert {e.kind for e in entries} >= {"precision", "param"}
    assert experience.backtest(db, db.get(AmzStore, "03us")) == 0  # 数据不够长,不硬回测

    # 推新六步:损益表门挡住 → 强制放行要写原因 → 贴对手差评归簇出「坑」→ listing 门(事实表 + 主图已选定)→
    # 上架前门没全绿 → 强制放行进蜜月 → 满 45 天判定落一条 bad 建议 → 复盘进经验库
    launch = launches.create(db, store_code="03us", product_line="pump", title="03us 泵 冬季重推", actor=owner)
    launches.update_inputs(db, launch=launch, patch={"price_usd": 32.99, "fba_fee_usd": 6, "fba_units": 100, "expected_daily_units": 5, "not_allowed": 1})
    db.commit()
    assert launch.stage == "pnl" and launch.pnl_json["ok"] is False and "not_allowed" not in launch.inputs_json
    with pytest.raises(Exception) as blocked:
        launches.advance(db, launch=launch, actor=owner)
    assert getattr(blocked.value, "code", "") == "amz_launch_gate_blocked" and "损益表门没过" in str(blocked.value)
    launches.advance(db, launch=launch, actor=owner, override_reason="冬季占位,先亏一点")
    db.commit()
    assert launch.stage == "battlefield"
    added = reviews.add_reviews(db, product_line="pump", whose="competitor", raw="1星 does not heat the water\n\n2星 no hot water, cold shower\n\n1星 leaked in a week", actor_user_id=owner.id, asin="B0AAAAAAA1")
    assert added == 3 and reviews.add_reviews(db, product_line="pump", whose="competitor", raw="1星 does not heat the water", actor_user_id=owner.id, asin="B0AAAAAAA1") == 0
    counts = reviews.cluster_pending(db, product_line="pump", call=lambda m, *, org_id: {"items": [{"n": 0, "family": "expectation", "theme": "以为能加热"}, {"n": 1, "family": "expectation", "theme": "以为能加热"}]})
    db.commit()
    assert counts == {"model": 2, "keywords": 1}
    pits = reviews.top_pits(db, product_line="pump")
    assert pits[0]["theme"] == "以为能加热" and pits[0]["count"] == 2 and pits[1]["theme"] == "漏水"
    launches.advance(db, launch=launch, actor=owner)
    db.commit()
    assert launch.stage == "listing" and launch.battlefield_json["pits"][0]["theme"] == "以为能加热"
    launches.advance(db, launch=launch, actor=owner)  # 事实表够 + 03us 泵主图已选定并上线
    db.commit()
    assert launch.stage == "prelaunch"
    items = {i["key"]: i for i in launch.checklist_json["items"]}
    assert items["main_image"]["ok"] and items["facts"]["ok"] and items["pits_known"]["ok"] and not items["stock"]["ok"]  # 100/5=20 天不够 45
    with pytest.raises(Exception):
        launches.tick(db, launch=launch, key="stock", ok=True, actor=owner)  # 自动项不能手勾
    launches.tick(db, launch=launch, key="vine", ok=True, actor=owner)
    with pytest.raises(Exception):
        launches.advance(db, launch=launch, actor=owner)
    launches.advance(db, launch=launch, actor=owner, override_reason="库存在路上,先上架")
    launches.update_inputs(db, launch=launch, patch={"reviews_count": 20, "main_term_rank": 12, "asin": "B0TESTA0001"})
    db.commit()
    assert launch.stage == "honeymoon" and launch.live_on is not None
    assert launches.run_daily(db, store_code="03us", today=launch.live_on + timedelta(days=10)) == {"updated": 1, "judged": 0}
    assert launches.run_daily(db, store_code="03us", today=launch.live_on + timedelta(days=44)) == {"updated": 1, "judged": 1}
    db.commit()
    assert launch.stage == "verdict" and launch.verdict_json["result"] == "incomplete"  # 03us 没接 SP-API,转化率拿不到,不硬判
    day45 = db.scalar(select(AmzSuggestion).where(AmzSuggestion.action_type == "launch_day45"))
    assert day45.severity == "bad" and day45.employee == "D" and "缺数没法判" in day45.title
    with pytest.raises(Exception):
        launches.close(db, launch=launch, outcome="growth", retro={"lessons": []}, actor=owner)
    launches.close(db, launch=launch, outcome="growth", retro={"lessons": ["冬季重推前先把「不加热」写进主图副标题"]}, actor=owner)
    db.commit()
    assert launch.stage == "growth" and db.scalar(select(AmzExperience).where(AmzExperience.kind == "launch")).statement.startswith("推新「03us 泵 冬季重推」进了成长期")

    # 竞品盯盘:事实表里的对手 ASIN 进名单 → 两天快照(假 Keepa)→ 只给泵线主场店出变化草稿
    from types import SimpleNamespace as _NS

    from backend.app.modules.amz_series import competitors as comps

    assert comps.sync_watchlist(db)["added"] >= 1  # 泵事实表里填了 B0AAAAAAA1
    assert comps.upsert_competitor(db, marketplace="US", asin="B0AAAAAAA1", product_line="pump", whose="competitor", source="manual") is False  # 已在名单
    db.commit()
    day1, day2 = date(2026, 9, 10), date(2026, 9, 11)

    def _keepa(price_cents, reviews):
        cur = [-1] * 20
        cur[comps.IDX_BUY_BOX], cur[comps.IDX_RATING], cur[comps.IDX_REVIEWS], cur[comps.IDX_SALES_RANK] = price_cents, 45, reviews, 2000

        def _get(url, params):
            import json as __json

            products = [{"asin": a, "brand": "rival", "stats": {"current": cur}} for a in params["asin"].split(",")]
            return _NS(status_code=200, text="", content=__json.dumps({"products": products, "tokensLeft": 99}).encode())

        return _get

    monkey2 = pytest.MonkeyPatch()
    monkey2.setattr(comps, "keepa_key", lambda db, store: ("https://api.keepa.com", "K"))
    spent = []
    try:
        us_store = db.get(AmzStore, "03us")
        r1 = comps.snapshot_marketplace(db, us_store, today=day1, get=_keepa(3298, 800), budget=lambda n: spent.append(n) or True)
        assert r1["snapped"] >= 1 and r1["tokens_left"] == 99
        assert comps.snapshot_marketplace(db, db.get(AmzStore, "04us"), today=day1, get=_keepa(1, 1), budget=lambda n: spent.append(n) or True)["snapped"] == 0  # 同站点今天拍过,不重复花 token
        comps.snapshot_marketplace(db, us_store, today=day2, get=_keepa(2798, 801), budget=lambda n: True)
        db.commit()
        assert sum(spent) == r1["snapped"]
        assert comps.snapshot_marketplace(db, us_store, today=date(2026, 9, 12), get=_keepa(1, 1), budget=lambda n: False)["skipped_budget"] >= 1  # 台账封顶就不拍
    finally:
        monkey2.undo()
    home = comps.home_store(db, marketplace="US", product_line="pump")
    drafts = comps.rule_competitor_changes(db, home, "USD", day2)
    assert any(d.evidence["asin"] == "B0AAAAAAA1" and d.evidence["kind"] == "price_drop" and d.employee == "C" for d in drafts)
    other = next(s for s in ("01us", "03us", "04us") if s != home)
    assert comps.rule_competitor_changes(db, other, "USD", day2) == []  # 非主场店不重复报
    board = comps.board(db, marketplace="US")
    assert any(b["asin"] == "B0AAAAAAA1" and b["latest"]["price"] == 27.98 and b["previous"]["price"] == 32.98 for b in board)

    # 竞品名单自动派生:核心词(真出过单的词)→ 品牌分析报表(假客户端,两步:没好 deferred → 好了流式过滤)→ 名单
    from backend.app.modules.amz_series import ba_competitors as ba

    today_ba = date(2026, 9, 17)
    db.add(AmzSqp(store_code="01us", period_start=date(2026, 9, 6), period_end=date(2026, 9, 12), asin="B0TESTA0001", search_query="Portable Shower", query_volume=190000, purchases_total=3000, purchases_asin=5, raw_json={}))
    db.add(AmzSqp(store_code="01us", period_start=date(2026, 9, 6), period_end=date(2026, 9, 12), asin="B0TESTA0001", search_query="camping essentials", query_volume=260000, purchases_total=5000, purchases_asin=9, raw_json={}))
    db.commit()
    core = ba.core_terms(db, "US", today=today_ba)
    assert "portable shower" in core["pump"] and all("camping essentials" not in terms for terms in core.values())

    class _FakeSp:
        def __init__(self) -> None:
            self.polls = 0
            self.created: list[str] = []

        def create_report(self, report_type, *, start, end, options=None):
            self.created.append(report_type)
            assert (start, end, options) == (date(2026, 9, 6), date(2026, 9, 12), {"reportPeriod": "WEEK"})
            return "RPT-BA-1"

        def get_report(self, report_id):
            self.polls += 1
            return {"processingStatus": "IN_PROGRESS"} if self.polls == 1 else {"processingStatus": "DONE", "reportDocumentId": "DOC-1"}

        def get_document(self, document_id):
            return {"url": "https://example.invalid/doc", "compressionAlgorithm": "GZIP"}

        def stream_document(self, document):
            body = _json.dumps({"reportSpecification": {}, "dataByDepartmentAndSearchTerm": [
                {"searchTerm": "portable shower", "searchFrequencyRank": 900, "clickedAsin": "B0RIVAL001", "clickedItemName": "Rival Portable Shower 7800mAh", "clickShareRank": 1, "clickShare": 0.23, "conversionShare": 0.2},
                {"searchTerm": "portable shower", "searchFrequencyRank": 900, "clickedAsin": "B0OURS0001", "clickedItemName": "Our shower", "clickShareRank": 2, "clickShare": 0.1, "conversionShare": 0.1},
                {"searchTerm": "portable shower", "searchFrequencyRank": 900, "clickedAsin": "B0CHAIR001", "clickedItemName": "Camping chair", "clickShareRank": 3, "clickShare": 0.05, "conversionShare": 0.0},
                {"searchTerm": "dog toys", "searchFrequencyRank": 10, "clickedAsin": "B0DOGTOY01", "clickedItemName": "Dog toy", "clickShareRank": 1, "clickShare": 0.3, "conversionShare": 0.3},
            ]}).encode()
            yield from (body[i : i + 50] for i in range(0, len(body), 50))

    comps.upsert_competitor(db, marketplace="US", asin="B0OURS0001", product_line="pump", whose="ours", source="sales_report")  # 自家 ASIN 点进前三也不算对手
    db.commit()
    fake = _FakeSp()
    us01 = db.get(AmzStore, "01us")
    step1 = ba.run(db, fake, us01, today=today_ba)
    assert step1["requested"] == "RPT-BA-1" and step1["deferred_seconds"] > 0
    step2 = ba.run(db, fake, us01, today=today_ba)
    assert step2["waiting"] == "IN_PROGRESS" and step2["deferred_seconds"] > 0 and fake.created == [ba.REPORT_BA_SEARCH_TERMS]
    step3 = ba.run(db, fake, us01, today=today_ba)
    assert step3["rows_scanned"] == 4 and step3["rows_kept"] == 3 and step3["watchlist"]["added"] == 1 and step3["watchlist"]["per_line"] == {"pump": ["B0RIVAL001"]}
    rival = db.scalar(select(AmzCompetitor).where(AmzCompetitor.asin == "B0RIVAL001"))
    assert rival.source == "brand_analytics" and rival.whose == "competitor" and rival.product_line == "pump" and rival.active
    assert db.scalar(select(AmzCompetitor).where(AmzCompetitor.asin == "B0CHAIR001")) is None  # 椅子不是泵的对手
    step4 = ba.run(db, fake, db.get(AmzStore, "03us"), today=today_ba)  # 同站点同周别的店:不再拉报表
    assert step4["skipped"] == "already imported" and fake.created == [ba.REPORT_BA_SEARCH_TERMS]
    board = comps.board(db, marketplace="US")
    rival_row = next(b for b in board if b["asin"] == "B0RIVAL001")
    assert rival_row["ba_terms"] == [{"term": "portable shower", "rank": 1, "click_share": 0.23, "week_start": "2026-09-06"}]
    # 掉出前五 → 系统来源的停盯;再回来 → 复活
    newcomer = {"search_term": "portable shower", "product_line": "pump", "search_frequency_rank": 800, "click_rank": 1, "asin": "B0RIVAL002", "item_name": "New Portable Shower", "click_share": 0.3, "conversion_share": 0.3}
    ba.store_week(db, marketplace="US", week_start=date(2026, 9, 6), rows=[newcomer])
    moved = ba.apply_watchlist(db, "US")
    db.commit()
    assert moved["added"] == 1 and moved["retired"] == 1 and db.get(AmzCompetitor, rival.id).active is False
    ba.store_week(db, marketplace="US", week_start=date(2026, 9, 6), rows=[newcomer, {**newcomer, "click_rank": 2, "asin": "B0RIVAL001", "item_name": "Rival Portable Shower", "click_share": 0.2}])
    assert ba.apply_watchlist(db, "US")["reactivated"] == 1
    db.commit()

    # ---- 补齐:主场词 / 库存规则 / 需求合成 / listing 变更进日志 / 财务交易 / 请求留评 / 评论按月 / 跨店抽象经验
    from decimal import Decimal as _Dec
    from types import SimpleNamespace as _SN

    from backend.app.modules.amz_series import experience as _exp, ops_sync, portfolio, reviews as _rv, rules_stock
    from backend.app.modules.amz_series.models import AmzInventoryDaily, AmzListingSnapshot, AmzOutcome as _Out, AmzSolicitation, AmzWorkLog as _WL

    own_day = date(2026, 8, 10)
    for store_code, clicks, orders, spend, sales in (("01us", 90, 12, "60", "380"), ("03us", 70, 2, "70", "50")):
        db.add(AmzAdSearchTerm(store_code=store_code, report_date=own_day, campaign_name="PSPE pump exact", adgroup_name="ag", targeting="shower pump", match_type="EXACT", search_term="shower pump", impressions=5000, clicks=clicks, spend=_Dec(spend), sales_7d=_Dec(sales), orders_7d=orders, units_7d=orders, currency="USD", source="test", row_key=f"own-{store_code}"))
    db.commit()
    yield_drafts = portfolio.rule_term_owner(db, "03us", "USD", own_day)
    assert [d.evidence["home_store"] for d in yield_drafts if d.evidence["term"] == "shower pump"] == ["01us"] and yield_drafts[0].action_type == "portfolio_yield" and yield_drafts[0].severity == "warn"
    assert portfolio.rule_term_owner(db, "01us", "USD", own_day) == []  # 主场店自己不出让位
    assert any(r["term"] == "shower pump" and r["home_store"] == "01us" and r["yield_stores"] == ["03us"] for r in portfolio.owner_board(db, marketplace="US", as_of=own_day))

    snap_day = date(2026, 9, 17)
    for i in range(14):
        db.add(AmzSalesDaily(store_code="01us", report_date=snap_day - timedelta(days=i), child_asin="B0STOCK001", parent_asin="", units_ordered=5, ordered_product_sales=_Dec("125"), currency="USD"))
        db.add(AmzSalesDaily(store_code="01us", report_date=snap_day - timedelta(days=i), child_asin="B0STOCK002", parent_asin="", units_ordered=2, ordered_product_sales=_Dec("50"), currency="USD"))
        db.add(AmzSalesDaily(store_code="01us", report_date=snap_day - timedelta(days=i), child_asin="B0STOCK003", parent_asin="", units_ordered=1, ordered_product_sales=_Dec("25"), currency="USD"))

    class _FakeOps:
        def __init__(self) -> None:
            self.posts: list[str] = []
            self.title = "Camping Shower Pump"

        def request(self, method, path, *, params=None, json_body=None):
            if path == "/fba/inventory/v1/summaries":
                return {"payload": {"inventorySummaries": [
                    {"sellerSku": "PSPE-A", "asin": "B0STOCK001", "inventoryDetails": {"fulfillableQuantity": 20}},
                    {"sellerSku": "PSPE-B", "asin": "B0STOCK002", "inventoryDetails": {"fulfillableQuantity": 0, "inboundShippedQuantity": 50}},
                    {"sellerSku": "PSPE-C", "asin": "B0STOCK003", "inventoryDetails": {"fulfillableQuantity": 300}},
                    {"sellerSku": "PSPE-C-OLD", "asin": "B0STOCK003", "inventoryDetails": {"fulfillableQuantity": 0}},  # 同 ASIN 的老 SKU:0 件不能报断货
                ]}, "pagination": {}}
            if path.startswith("/catalog/"):
                return {"attributes": {"item_name": [{"value": self.title}], "bullet_point": [{"value": "7800mAh battery"}]}}
            if path == "/finances/v0/financialEvents":
                if params and params.get("NextToken") == "p2":
                    return {"payload": {"FinancialEvents": {"RefundEventList": [{"AmazonOrderId": "111-0000002-0000002", "PostedDate": "2026-09-10T18:00:00Z", "ShipmentItemAdjustmentList": [{"SellerSKU": "PSPE-A", "QuantityShipped": 1, "ItemChargeAdjustmentList": [{"ChargeType": "Principal", "ChargeAmount": {"CurrencyAmount": -25.64}}], "ItemFeeAdjustmentList": [{"FeeType": "Commission", "FeeAmount": {"CurrencyAmount": 3.08}}]}]}]}}}
                ship = lambda oid, day: {"AmazonOrderId": oid, "PostedDate": f"2026-09-0{day}T17:00:00Z", "ShipmentItemList": [{"SellerSKU": "PSPE-A", "QuantityShipped": 1, "ItemChargeList": [{"ChargeType": "Principal", "ChargeAmount": {"CurrencyAmount": 25.64}}, {"ChargeType": "Tax", "ChargeAmount": {"CurrencyAmount": 2.0}}], "ItemFeeList": [{"FeeType": "Commission", "FeeAmount": {"CurrencyAmount": -3.85}}, {"FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": {"CurrencyAmount": -6.12}}], "PromotionList": []}]}  # noqa: E731
                return {"payload": {"FinancialEvents": {"ShipmentEventList": [ship("111-0000001-0000001", 5), ship("111-0000002-0000002", 6)]}, "NextToken": "p2"}}
            if path.startswith("/solicitations/"):
                if method == "POST":
                    self.posts.append(path)
                    return {}
                return {"_links": {"actions": [{"name": "productReviewAndSellerFeedback"}]}} if path.endswith("111-0000001-0000001") else {"_links": {"actions": []}}
            raise AssertionError(path)

        def run_report(self, report_type, *, start, end, options=None):
            if report_type == ops_sync.REPORT_LISTINGS:
                return "R", "item-name\tseller-sku\tprice\tasin1\tstatus\nCamping Shower Pump\tPSPE-A\t25.64\tB0STOCK001\tActive\n"
            raise AssertionError(report_type)

    fake_ops = _FakeOps()
    store01 = db.get(AmzStore, "01us")
    assert ops_sync.sync_inventory(db, fake_ops, store01, today=snap_day) == {"skus": 4, "fulfillable": 320, "inbound": 50}
    stock = {d.evidence["asin"]: d for d in rules_stock.rule_stock(db, "01us", "USD", own_day)}
    assert stock["B0STOCK001"].action_type == "stock_cover" and stock["B0STOCK001"].severity == "bad" and stock["B0STOCK001"].evidence["days_cover"] == 4.0
    assert stock["B0STOCK002"].action_type == "stockout" and "B0STOCK003" not in stock  # 同 ASIN 合计 300 件 / 日均 1 件,老 SKU 的 0 件不算断货
    assert {r["asin"]: r["sku"] for r in rules_stock.cover_table(db, "01us")}["B0STOCK003"] == "PSPE-C、PSPE-C-OLD"
    demand = {r["product_line"]: r for r in portfolio.demand_board(db, marketplace="US")}
    assert all("stock_complete" in r for r in demand.values())

    assert ops_sync.sync_listings(db, fake_ops, store01, today=date(2026, 9, 16)) == {"listings": 1, "changed": 0}
    fake_ops.title = "Camping Shower Pump 7800mAh"
    assert ops_sync.sync_listings(db, fake_ops, store01, today=snap_day) == {"listings": 1, "changed": 1}
    log = db.scalar(select(_WL).where(_WL.employee == "A", _WL.subject == "listing|PSPE-A"))
    assert log is not None and "标题" in log.title and log.detail_json["after"]["title"] == "Camping Shower Pump 7800mAh"
    assert db.scalar(select(func.count()).select_from(AmzListingSnapshot)) == 2

    fin_now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    fin = ops_sync.sync_finances(db, fake_ops, store01, now=fin_now)
    assert fin["pages"] == 2 and fin["rows"] == 3 and fin["inserted"] == 3 and ops_sync.sync_finances(db, fake_ops, store01, now=fin_now)["inserted"] == 0  # 翻页 + 幂等
    order_row = db.scalar(select(AmzTransaction).where(AmzTransaction.order_id == "111-0000001-0000001", AmzTransaction.source == "sp_api"))
    assert order_row.txn_type == "Order" and order_row.quantity == 1 and order_row.product_sales == _Dec("25.64") and order_row.fba_fees == _Dec("-6.12") and order_row.selling_fees == _Dec("-3.85") and order_row.total == _Dec("17.67")
    seed_last_01 = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == "01us", AmzTransaction.source == "seed"))
    seen_after: list[str] = []
    real_request = fake_ops.request
    fake_ops.request = lambda method, path, *, params=None, json_body=None: (seen_after.append((params or {}).get("PostedAfter", "")) or real_request(method, path, params=params, json_body=json_body))
    ops_sync.sync_finances(db, fake_ops, store01, now=fin_now)
    fake_ops.request = real_request
    expected_after = (max(order_row.posted_at, db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == "01us", AmzTransaction.source == "sp_api"))) - timedelta(days=3))
    gap = seed_last_01 is not None and (db.scalar(select(func.min(AmzTransaction.posted_at)).where(AmzTransaction.store_code == "01us", AmzTransaction.source == "sp_api")) - seed_last_01) > timedelta(days=1)
    assert seen_after[0] == ((seed_last_01 if gap else expected_after).strftime("%Y-%m-%dT%H:%M:%SZ"))  # 有缝补缝,没缝接着上次往前 3 天
    refund_row = db.scalar(select(AmzTransaction).where(AmzTransaction.txn_type == "Refund", AmzTransaction.source == "sp_api"))
    assert refund_row.quantity == -1 and refund_row.total == _Dec("-22.56")

    sol = ops_sync.run_solicitations(db, fake_ops, store01, today=date(2026, 9, 20))
    assert sol["would_request"] == 1 and sol["not_eligible"] == 1 and sol["sent"] == 0 and fake_ops.posts == []  # 影子期不发
    store01.metadata_json = {**(store01.metadata_json or {}), "solicitations_enabled": True}
    db.add(AmzSolicitation(store_code="01us", order_id="111-0000003-0000003", status="not_eligible"))
    db.commit()
    assert ops_sync.run_solicitations(db, fake_ops, store01, today=date(2026, 9, 20))["checked"] == 1  # would_request 的不重查;not_eligible 的会再查
    assert ops_sync.solicitation_summary(db, "01us")["would_request"] == 1
    store01.metadata_json = {k: v for k, v in (store01.metadata_json or {}).items() if k != "solicitations_enabled"}
    db.commit()

    _rv.add_reviews(db, product_line="pump", whose="ours", raw="1 out of 5 stars no hot water. Reviewed in the United States on July 3, 2026\n\n2星 leaked, Reviewed on August 9, 2026", actor_user_id=owner.id)
    _rv.cluster_pending(db, product_line="pump", call=lambda messages, *, org_id: (_ for _ in ()).throw(RuntimeError("offline")))
    db.commit()
    trend = _rv.monthly_trend(db, product_line="pump", whose="ours")
    months = {m["month"]: m for m in trend["months"]}
    assert months["2026-07"]["total"] == 1 and months["2026-08"]["total"] == 1 and next(f for f in months["2026-07"]["families"] if f["family"] == "expectation")["share_pct"] == 100.0

    for i in range(4):
        for store_code in ("01us", "03us"):
            db.add(_Out(store_code=store_code, action_type="negative", subject=f"camping shower {i}", as_of=date(2026, 7, 25), horizon_days=28, source="backtest", verdict="wrong", metrics_json={}))
            db.add(_Out(store_code=store_code, action_type="negative", subject=f"camping chair {i}", as_of=date(2026, 7, 25), horizon_days=28, source="backtest", verdict="right", metrics_json={}))
    db.commit()
    assert _exp.learn_abstract(db) >= 1
    advice = _exp.consult(db, store_code="04us", action_type="negative", product_line="pump", season_phase="peak")
    assert advice["downgrade"] is True and any("旺季 · 沐浴泵" in n for n in advice["notes"])
    db.execute(delete(_Out).where(_Out.source == "backtest", _Out.as_of == date(2026, 7, 25)))
    db.commit()

    # 作业:排队 → 领取 → 执行 → 心跳(验收只认这个)。没有 SP-API 凭据的店不排出网作业。
    created = schedule_due_jobs(db)
    assert created == 21  # 五店各一条 rules_daily + image_lookback + experience_weekly + launch_daily;fx_daily 只给欧元店 01de;出网作业因无凭据一条不排
    jobs = claim(db, 30)
    assert len(jobs) == 21 and {j["job_type"] for j in jobs} == {"rules_daily", "image_lookback", "experience_weekly", "launch_daily", "fx_daily"}
    assert [j["store_code"] for j in jobs if j["job_type"] == "fx_daily"] == ["01de"]
    from backend.app.modules.amz_series import fx as _fx

    def _no_network(start, end, *, base="EUR", quote="USD", get=None):  # 测试不出网
        return {start + timedelta(days=i): __import__("decimal").Decimal("1.15") for i in range((end - start).days + 1)}

    monkey = pytest.MonkeyPatch()
    monkey.setattr(_fx, "fetch_range", _no_network)
    try:
        for job in jobs:
            assert process_job(job) is True
    finally:
        monkey.undo()
    beats = {beat["worker_name"]: beat for beat in list_heartbeats(db)}
    for name in ("amz-worker:03us:rules_daily", "amz-worker:03us:experience_weekly", "amz-worker:03us:image_lookback"):
        assert name in beats and beats[name]["stale"] is False
    assert schedule_due_jobs(db) == 0  # 刚跑完,间隔内不再补
    # 报表没好:作业放回队列、不写心跳
    from backend.app.modules.amz_series import jobs as amz_jobs

    waiting = AmzJob(store_code="01us", job_type="ba_competitors", status="running", run_after=datetime.now(UTC))
    db.add(waiting)
    db.commit()
    monkey3 = pytest.MonkeyPatch()
    monkey3.setitem(amz_jobs.HANDLERS, "ba_competitors", lambda store_code: {"waiting": "IN_PROGRESS", "deferred_seconds": 900})
    try:
        assert process_job({"id": waiting.id, "store_code": "01us", "job_type": "ba_competitors"}) is True
    finally:
        monkey3.undo()
    db.expire_all()
    again = db.get(AmzJob, waiting.id)
    assert again.status == "pending" and again.run_after > datetime.now(UTC) + timedelta(seconds=800) and again.finished_at is None
    assert "amz-worker:01us:ba_competitors" not in {beat["worker_name"] for beat in list_heartbeats(db)}
