"""A0 建号 + 种子导入的集成测试(真 Postgres):幂等两次、四组织 amazon、王创鑫 admin + 五店 grant、
机器人四条成员关系 + 四条 C19 归属、种子文件导两次只算一次。"""

from __future__ import annotations

import textwrap
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
from backend.app.modules.amz_series import work_log
from backend.app.modules.amz_series.models import AmzJob, AmzSuggestion, AmzWorkLog
from backend.app.modules.amz_series.catalog import COMPANIES, COMPANY_ORG_IDS, STORE_CODES
from backend.app.modules.amz_series.constants import EMPLOYEE_USERNAMES, EMPLOYEES
from backend.app.modules.amz_series.models import AmzAdSearchTerm, AmzSeedImport, AmzStore, AmzStoreGrant, AmzTransaction
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
    session.execute(delete(AmzWorkLog))
    session.execute(delete(AmzSuggestion))
    session.execute(delete(AmzJob))
    session.execute(delete(AmzSeedImport))
    session.execute(delete(AmzAdSearchTerm))
    session.execute(delete(AmzTransaction))
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

    # 第二次跑:同样的建议只更新不新增;决定过的不再重发。
    again = rules.run_rules_for_store(db, store_code="03us", currency="USD")
    db.commit()
    assert again["created"] == 0 and again["updated"] >= 3
    decided = sug.decide_suggestion(db, suggestion_id=harvest.id, decision="reject", reason="先不收", actor=manager, allowed_store_codes=None)
    db.commit()
    assert decided.status == "rejected" and decided.reject_reason == "先不收"

    # 硬记忆:每条建议一条 suggested;驳回一条带原因;按问题能检索出来;没授权的店看不到
    assert work_log.counts(db, employee="D", store_codes=None)["suggested"] == counts["created"]
    hits = work_log.relevant(db, employee="D", store_codes=["03us"], question="03us 的 camping shower 最近怎么了")
    assert [h.kind for h in hits[:2]] == ["rejected", "suggested"] and hits[0].why == "先不收" and hits[0].actor_user_id == manager.id
    assert work_log.relevant(db, employee="D", store_codes=["01us"], question="camping shower") == []
    spoken = work_log.record(db, employee="A", kind="note", title="01us 的泵标题加了 heater", why="冬季", store_code="01us", subject="B0ABCDEFGH", source="chat", actor_user_id=owner.id)
    db.commit()
    assert spoken.asin == "B0ABCDEFGH"
    assert work_log.relevant(db, employee="A", store_codes=None, question="B0ABCDEFGH 标题为什么改")[0].why == "冬季"
    assert work_log.backfill_from_suggestions(db) == 0  # 都已经记过
    section = __import__("backend.app.modules.amz_series.agents.context", fromlist=["work_log_section"]).work_log_section(db, employee="D", store_codes=None, question="camping shower")
    assert section["总条数"] >= counts["created"] + 1 and section["跟这句话有关的"][0]["为什么"] == "先不收"
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

    # 作业:排队 → 领取 → 执行 → 心跳(验收只认这个)
    created = schedule_due_jobs(db)
    assert created == 5  # 五店各一条 rules_daily
    jobs = claim(db, 5)
    assert len(jobs) == 5
    for job in jobs:
        assert process_job(job) is True
    beats = {beat["worker_name"]: beat for beat in list_heartbeats(db)}
    assert "amz-worker:03us:rules_daily" in beats and beats["amz-worker:03us:rules_daily"]["stale"] is False
    assert schedule_due_jobs(db) == 0  # 刚跑完,间隔内不再补
