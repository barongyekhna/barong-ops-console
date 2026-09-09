"""用户管理:注册机器人 + 彻底删除账号(只删已停用、非 owner、无业务记录引用)。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.c19 import C19ProfileRecord
from backend.app.models.c19 import C19AffiliationRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from tests.backend.conftest import DEFAULT_TEST_ORG_DB_ID

pytestmark = pytest.mark.integration

BOT = {
    "username": "testbot",
    "display_name": "测试机器人",
    "job_title": "测试员",
    "organization_id": DEFAULT_TEST_ORG_DB_ID,
    "bio": "只在测试里出现",
    "password": "test-bot-password-123",
}


def test_register_bot_then_purge(owner_client) -> None:
    r = owner_client.post("/api/app/users/bots", json=BOT)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_bot"] is True and body["role"] == "viewer" and body["job_title"] == "测试员"
    assert body["organization_id"] == DEFAULT_TEST_ORG_DB_ID
    bot_id = body["id"]
    with SessionLocal() as db:
        profile = db.get(C19ProfileRecord, bot_id)
        assert profile is not None and profile.display_name == "测试机器人" and profile.bio == "只在测试里出现"
        assert db.scalar(select(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(bot_id))) is not None
        # 通讯录「所属组织」读的是 C19 投影表;注册时必须一并同步,否则显示「没有加入任何组织」。
        affiliation = db.scalar(select(C19AffiliationRecord).where(C19AffiliationRecord.user_id == bot_id))
        assert affiliation is not None and affiliation.status == "active"
    # 重名拒绝
    assert owner_client.post("/api/app/users/bots", json=BOT).status_code == 409
    # 密码太短 / 用户名不合法 → 422
    assert owner_client.post("/api/app/users/bots", json={**BOT, "username": "bot2", "password": "short"}).status_code == 422
    assert owner_client.post("/api/app/users/bots", json={**BOT, "username": "Bad Name"}).status_code == 422

    # 活着的不能删 → 先停用 → 删
    assert owner_client.delete(f"/api/app/users/{bot_id}").status_code == 409
    assert owner_client.post(f"/api/app/users/{bot_id}/disable").status_code == 200
    r = owner_client.delete(f"/api/app/users/{bot_id}")
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["org_memberships"] == 1
    with SessionLocal() as db:
        assert db.get(User, bot_id) is None
        assert db.get(C19ProfileRecord, bot_id) is None
        assert db.scalar(select(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(bot_id))) is None
    assert owner_client.delete(f"/api/app/users/{bot_id}").status_code == 404


def test_purge_refuses_owner_and_self(owner_client) -> None:
    me = owner_client.get("/api/public/auth/me").json()
    my_id = me["id"] if "id" in me else me["user"]["id"]
    assert owner_client.delete(f"/api/app/users/{my_id}").status_code == 409

