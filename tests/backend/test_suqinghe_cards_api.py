"""苏青禾审批卡与办公室接口:真库(integration)。

覆盖 10-20 定的规矩:只有 owner 能批、驳回必须写原因、幂等先到先得、
建卡后底层数据变了就作废(stale);办公室谁都能看,只有 owner 能管。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal, engine
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.agent_series.suqinghe import cards, memory
from backend.app.modules.agent_series.suqinghe.models import (
    SqhActivity,
    SqhCard,
    SqhGoal,
    SqhMemory,
    SqhSnapshot,
    SqhState,
)
from backend.app.services.data_isolation import without_org_data_isolation
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

pytestmark = pytest.mark.integration

OWNER = ("sqh_test_owner", "sqh-owner-example-password")
REGULAR = ("sqh_test_regular", "sqh-regular-example-password")
OFFICE_KEYS = {
    "state", "paused", "task", "progress", "state_updated_at", "heartbeat", "today",
    "snapshot", "goals", "pending_cards", "recent_cards", "activity", "can_command", "server_time",
}


def _wipe() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        for model in (SqhCard, SqhMemory, SqhGoal, SqhActivity, SqhSnapshot):
            db.execute(delete(model))
        state = db.get(SqhState, 1)
        if state is not None:
            state.paused = False
            state.activity = "working"
            db.add(state)
        db.commit()


@pytest.fixture
def people(auth_client: TestClient):
    _wipe()
    with SessionLocal() as db:
        owner = User(username=OWNER[0], password_hash=hash_password(OWNER[1]), role="owner", is_active=True, must_change_password=False)
        regular = User(username=REGULAR[0], password_hash=hash_password(REGULAR[1]), role="member", is_active=True, must_change_password=False)
        db.add_all((owner, regular))
        db.flush()
        owner.organization_id = DEFAULT_TEST_ORG_DB_ID
        regular.organization_id = DEFAULT_TEST_ORG_DB_ID
        db.add(OrganizationRecord(org_id=DEFAULT_TEST_ORG_DB_ID, org_name="Sqh Test Org", org_type="store", owner_user_id=str(owner.id), status="active", metadata_json={}))
        db.flush()
        db.add_all(
            (
                OrgMembershipRecord(membership_id="membership_sqh_owner", user_id=str(owner.id), org_id=DEFAULT_TEST_ORG_DB_ID, role="owner", status="active"),
                OrgMembershipRecord(membership_id="membership_sqh_regular", user_id=str(regular.id), org_id=DEFAULT_TEST_ORG_DB_ID, role="member", status="active"),
            )
        )
        db.commit()
        ids = {"owner": owner.id, "regular": regular.id}
    yield ids
    _wipe()
    cards.FINGERPRINTERS.pop("test_flip", None)


def _login(client: TestClient, who: tuple[str, str]) -> None:
    client.post("/api/public/auth/logout")
    resp = client.post("/api/public/auth/login", json={"username": who[0], "password": who[1]})
    assert resp.status_code == 200, resp.text


def _user(db, user_id) -> User:
    return db.get(User, user_id)


def _new_card(db, key: str = "k1", **extra) -> SqhCard:
    card, created = cards.create_card(db, dedupe_key=key, kind="product_blocker", title=f"卡 {key}", conclusion="先补价格", **extra)
    assert created
    return card


def test_migration_created_tables() -> None:
    names = set(inspect(engine).get_table_names())
    assert {"sqh_cards", "sqh_memory", "sqh_goals", "sqh_activity", "sqh_state", "sqh_snapshots"} <= names


def test_create_card_dedupes_and_records_suggestion(people) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        first = _new_card(db, "dup")
        again, created = cards.create_card(db, dedupe_key="dup", kind="product_blocker", title="别的标题", conclusion="别的")
        db.commit()
        assert created is False
        assert again.id == first.id and again.title == "卡 dup"
        suggestions = db.scalars(select(SqhMemory).where(SqhMemory.kind == "suggestion")).all()
        assert len(suggestions) == 1
        assert suggestions[0].refs["card_ref"] == first.ref


def test_owner_approve_then_second_channel_is_noop(people) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "approve")
        owner = _user(db, people["owner"])
        out = cards.decide_card(db, card_id=card.ref, decision="approve", actor=owner, channel="web")
        db.commit()
        assert out.changed is True
        assert out.card.status == "approved" and out.card.decided_via == "web"
        again = cards.decide_card(db, card_id=f"#{card.ref}", decision="reject", actor=owner, channel="c19", reason="改主意")
        db.commit()
        assert again.changed is False
        assert again.card.status == "approved" and again.card.decided_via == "web"
        decisions = db.scalars(select(SqhMemory).where(SqhMemory.kind == "decision")).all()
        assert len(decisions) == 1 and "批了" in decisions[0].body and decisions[0].refs["channel"] == "web"
        assert db.scalars(select(SqhActivity).where(SqhActivity.kind == "decision")).all()


def test_reject_requires_reason_and_stores_it(people) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "reject")
        owner = _user(db, people["owner"])
        with pytest.raises(cards.CardError) as err:
            cards.decide_card(db, card_id=card.ref, decision="reject", actor=owner, channel="web", reason="  ")
        assert err.value.code == "SQH_REJECT_REASON_REQUIRED"
        out = cards.decide_card(db, card_id=card.ref, decision="reject", actor=owner, channel="c19", reason="价格先别动")
        db.commit()
        assert out.card.status == "rejected" and out.card.decision_reason == "价格先别动"
        body = db.scalars(select(SqhMemory).where(SqhMemory.kind == "decision")).one().body
        assert "价格先别动" in body


def test_non_owner_cannot_decide_via_service(people) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "nonowner")
        with pytest.raises(cards.CardError) as err:
            cards.decide_card(db, card_id=card.ref, decision="approve", actor=_user(db, people["regular"]), channel="web")
        assert err.value.code == "SQH_OWNER_REQUIRED" and err.value.status_code == 403


def test_changed_data_marks_card_stale(people) -> None:
    value = {"v": 1}
    cards.register_fingerprinter("test_flip", lambda db, recheck: cards.fingerprint(value))
    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "stale", evidence={"recheck": {"type": "test_flip"}})
        assert card.data_fingerprint
        value["v"] = 2
        out = cards.decide_card(db, card_id=card.ref, decision="approve", actor=_user(db, people["owner"]), channel="web")
        db.commit()
        assert out.changed is True and out.card.status == "stale"


def test_office_visible_to_all_but_commands_owner_only(auth_client: TestClient, people) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "office")
        goal = SqhGoal(text="上到 30 个品", metric={}, status="active")
        db.add(goal)
        db.commit()
        ref, goal_id = card.ref, goal.id

    _login(auth_client, REGULAR)
    resp = auth_client.get("/api/app/suqinghe/office")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert OFFICE_KEYS <= set(body)
    assert body["can_command"] is False
    assert body["state"] == "offline"  # 没有 suqinghe-worker 心跳行
    assert [c["ref"] for c in body["pending_cards"]] == [ref]
    for method, path, payload in (
        ("post", f"/api/app/suqinghe/cards/{ref}/decide", {"decision": "approve"}),
        ("post", "/api/app/suqinghe/goals", {"text": "试试越权"}),
        ("patch", f"/api/app/suqinghe/goals/{goal_id}", {"status": "done"}),
        ("post", "/api/app/suqinghe/control", {"action": "pause"}),
        ("post", "/api/app/suqinghe/instruct", {"text": "越权"}),
    ):
        denied = getattr(auth_client, method)(path, json=payload)
        assert denied.status_code == 403, (path, denied.text)

    _login(auth_client, OWNER)
    body = auth_client.get("/api/app/suqinghe/office").json()
    assert body["can_command"] is True
    decided = auth_client.post(f"/api/app/suqinghe/cards/{ref}/decide", json={"decision": "approve"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["changed"] is True and decided.json()["card"]["decided_via"] == "web"
    late = auth_client.post(f"/api/app/suqinghe/cards/{ref}/decide", json={"decision": "reject", "reason": "晚到的驳回"})
    assert late.status_code == 200 and late.json()["changed"] is False  # 已批过,原样返回
    assert late.json()["card"]["status"] == "approved"
    missing = auth_client.post("/api/app/suqinghe/cards/ffff9/decide", json={"decision": "approve"})
    assert missing.status_code == 404


def test_control_and_instruct(auth_client: TestClient, people) -> None:
    _login(auth_client, OWNER)
    assert auth_client.post("/api/app/suqinghe/control", json={"action": "pause"}).json() == {"paused": True}
    assert auth_client.get("/api/app/suqinghe/office").json()["paused"] is True
    assert auth_client.post("/api/app/suqinghe/control", json={"action": "resume"}).json() == {"paused": False}
    assert auth_client.get("/api/app/suqinghe/office").json()["paused"] is False

    created = auth_client.post("/api/app/suqinghe/instruct", json={"text": "PSPE-001 先别上架"})
    assert created.status_code == 200, created.text
    goal = auth_client.post("/api/app/suqinghe/goals", json={"text": "店里做到 30 个品", "metric": "published_products", "target": 30})
    assert goal.status_code == 200 and goal.json()["metric"] == {"metric": "published_products", "target": 30}
    with without_org_data_isolation(), SessionLocal() as db:
        pending = memory.unhandled_dictations(db)
        assert [row.body for row in pending] == ["PSPE-001 先别上架"]
        memory.mark_handled(db, pending[0], note="记下了")
        db.commit()
        assert memory.unhandled_dictations(db) == []
        assert [m.id for m in memory.relevant(db, "PSPE-001 怎么样")]
    texts = [a["text"] for a in auth_client.get("/api/app/suqinghe/office").json()["activity"]]
    assert any("老板交代" in t for t in texts) and any("新目标" in t for t in texts)


def test_bookshelf_and_calendar_are_readable_by_everyone(auth_client: TestClient, people) -> None:
    from datetime import date

    with without_org_data_isolation(), SessionLocal() as db:
        card = _new_card(db, "shelf")
        cards.decide_card(db, card_id=card.ref, decision="reject", actor=_user(db, people["owner"]), channel="web", reason="PSPE-009 价格太低别上")
        memory.record(db, kind="observation", subject="流量", body="首页跳出率偏高")
        db.add(SqhSnapshot(snapshot_date=date(2026, 10, 22), payload={"headline": "店里已发布 6 个品", "blockers": [{"product": "PSPE-003"}]}))
        db.commit()

    _login(auth_client, REGULAR)
    all_items = auth_client.get("/api/app/suqinghe/memory").json()["items"]
    assert {"suggestion", "decision", "observation"} <= {item["kind"] for item in all_items}
    assert set(all_items[0]) == {"id", "kind", "subject", "body", "refs", "source", "created_at"}

    found = auth_client.get("/api/app/suqinghe/memory", params={"q": "PSPE-009"}).json()["items"]
    assert any("价格太低别上" in item["body"] for item in found)

    only_obs = auth_client.get("/api/app/suqinghe/memory", params={"kind": "observation"}).json()["items"]
    assert only_obs and all(item["kind"] == "observation" for item in only_obs)

    searched_decisions = auth_client.get("/api/app/suqinghe/memory", params={"kind": "decision", "q": "PSPE-009"}).json()["items"]
    assert searched_decisions and all(item["kind"] == "decision" for item in searched_decisions)

    assert auth_client.get("/api/app/suqinghe/memory", params={"kind": "gossip"}).status_code == 422

    listed = auth_client.get("/api/app/suqinghe/snapshots").json()["items"]
    assert listed[0]["date"] == "2026-10-22" and listed[0]["headline"] == "店里已发布 6 个品"
    detail = auth_client.get("/api/app/suqinghe/snapshots/2026-10-22").json()
    assert detail["payload"]["blockers"][0]["product"] == "PSPE-003"
    missing = auth_client.get("/api/app/suqinghe/snapshots/2026-01-01")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "SQH_SNAPSHOT_NOT_FOUND"


# ---------------------------------------------------------------- 一件事一张卡(10-26)


def _morning(monkeypatch: pytest.MonkeyPatch, day: int, *, stale_workers, failing_keys, model_cards) -> dict:
    """跑一次早间流程:快照和模型输出是假的,其余(对账、去重、建卡、记忆)走真库。"""
    from datetime import UTC, datetime

    from backend.app.modules.agent_series.suqinghe import brain, worker_main

    snap = {
        "headline": "测试",
        "products": {"total": 0, "by_stage": {}, "woo_checked": None, "items": []},
        "workers": {"total": 5, "stale": stale_workers} if stale_workers is not None else {"error": "读不到"},
        "keys": {"counts": {}, "failing": [{"name": n, "status": "auth_failed", "reason": "401", "used_by": ["i"]} for n in failing_keys]}
        if failing_keys is not None
        else {"error": "读不到"},
        "content": {"error": "读不到"},
        "approvals": {"pending": 0},
        "goals": [],
    }
    monkeypatch.setattr(worker_main.snapshot, "build_snapshot", lambda db, now=None: snap)
    monkeypatch.setattr(brain, "plan_role", lambda db: "judge")
    monkeypatch.setattr(brain, "_execute", lambda role, messages, timeout: {"plan": f"第 {day} 天的计划", "cards": model_cards})
    with without_org_data_isolation(), SessionLocal() as db:
        return worker_main.run_morning(db, now=datetime(2026, 11, day, 15, 30, tzinfo=UTC))  # 洛杉矶早上


def _plan_cards(db) -> list[SqhCard]:
    return list(db.scalars(select(SqhCard).order_by(SqhCard.id)))


def test_same_issue_gets_one_card_across_days(monkeypatch: pytest.MonkeyPatch, people) -> None:
    """10-23、10-24、10-26 同一把备用钥匙各发了一张卡:去重键里带了日期。现在按快照里那件事去重。"""
    key_card = {"issue": "key:i-spare", "kind": "ops_alert", "title": "I 系列备用 key 被拒", "conclusion": "换不换"}
    worker_card = {"issue": "worker:sm-worker", "kind": "ops_alert", "title": "sm-worker 掉线", "conclusion": "谁去拉起"}
    with without_org_data_isolation(), SessionLocal() as db:
        legacy, _ = cards.create_card(db, dedupe_key="2026-10-24:i_series_backup_key", kind="ops_alert", title="旧规矩发的", conclusion="换不换")
        db.commit()
        legacy_ref = legacy.ref

    # 第 1 天:旧卡合并掉,两件事各一张
    out = _morning(monkeypatch, 2, stale_workers=["sm-worker"], failing_keys=["i-spare"], model_cards=[key_card, worker_card])
    assert out["cards_created"] == 2 and out["settled"]["merged"] == 1
    # 第 2 天:换个说法再发同一件事 → 不建
    again = {**key_card, "title": "I 系列图片备用 key 认证被拒,换不换"}
    out = _morning(monkeypatch, 3, stale_workers=["sm-worker"], failing_keys=["i-spare"], model_cards=[again])
    assert out["cards_created"] == 0
    # 第 3 天:钥匙那一类读不到 → 卡不动(读不到 ≠ 好了)
    out = _morning(monkeypatch, 4, stale_workers=["sm-worker"], failing_keys=None, model_cards=[])
    assert out["settled"]["gone"] == 0

    with without_org_data_isolation(), SessionLocal() as db:
        rows = _plan_cards(db)
        assert [(c.ref == legacy_ref, c.status) for c in rows] == [(True, "expired"), (False, "pending"), (False, "pending")]
        assert rows[0].decision_reason == cards.LEGACY_REASON and rows[0].decided_by_user_id is None
        worker = next(c for c in rows if c.evidence.get("issue") == "worker:sm-worker")
        cards.decide_card(db, card_id=worker.ref, decision="reject", actor=_user(db, people["owner"]), channel="web", reason="sm 先不管")
        db.commit()

    # 第 4 天:钥匙好了 → 那张卡作废;进程还掉线,但老板驳过 → 不再提
    out = _morning(monkeypatch, 5, stale_workers=["sm-worker"], failing_keys=[], model_cards=[worker_card])
    assert out["settled"]["gone"] == 1 and out["cards_created"] == 0
    # 第 5 天:进程好了 → 驳过的那张记一笔了结;第 6 天又掉线 → 算新的一回,可以再发
    out = _morning(monkeypatch, 6, stale_workers=[], failing_keys=[], model_cards=[])
    assert out["settled"]["settled"] == 1
    out = _morning(monkeypatch, 7, stale_workers=["sm-worker"], failing_keys=[], model_cards=[worker_card])
    assert out["cards_created"] == 1

    with without_org_data_isolation(), SessionLocal() as db:
        rows = _plan_cards(db)
        key = next(c for c in rows if c.evidence.get("issue") == "key:i-spare")
        assert key.status == "stale" and key.decision_reason == cards.GONE_REASON
        workers = [c for c in rows if c.evidence.get("issue") == "worker:sm-worker"]
        assert [c.status for c in workers] == ["rejected", "pending"]
        assert workers[0].evidence["settled_on"] == "2026-11-06"
        assert cards.raised_issues(db) == {"worker:sm-worker"}
