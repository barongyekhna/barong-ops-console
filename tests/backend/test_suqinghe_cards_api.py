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
