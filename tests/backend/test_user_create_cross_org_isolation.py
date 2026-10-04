"""owner 人在 A 组织,给 B 组织建号/挪人/注册机器人——不许被 C18G 误伤。

2026-10-04 事故:owner 删掉王维后重建,连续三次 422「提交的内容不符合要求」。
真因是组织表自带 org_id 列,被数据隔离层按「当前所在组织」过滤;
目标组织 ≠ 当前组织时 get_organization 返回 None → 误报「组织不存在」。
生产把 422 原因消毒成一句通用中文,页面上看不出来。

这里把隔离上下文显式设成 A 组织,确认对 B 组织的操作都能走通,
同时真不存在的组织仍然被拒。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.org_membership import OrgMemberAddRequest
from backend.app.schemas.user import BotCreate, UserCreate, UserUpdate
from backend.app.services.auth_service import AuditContext
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
    without_org_data_isolation,
)
from backend.app.services.org_membership_service import (
    OrgMembershipConflictError,
    add_org_member,
)
from backend.app.services.user_management_service import (
    UserOrganizationNotFoundError,
    create_bot_user,
    create_managed_user,
    update_managed_user,
)
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

# 用了 TestClient 夹具,不显式标注会被自动归到 system(两条 CI 通道都不跑)。
pytestmark = pytest.mark.integration

OTHER_ORG_ID = "org_22222222222222222222222222222222"
MISSING_ORG_ID = "org_99999999999999999999999999999999"
AUDIT = AuditContext("cross-org-test", None, None)


def _owner_in_default_org(owner_client: TestClient) -> int:
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.role == "owner"))
        assert owner is not None
        db.add(
            OrganizationRecord(
                org_id=OTHER_ORG_ID,
                org_name="Other Test Org",
                org_type="factory",
                owner_user_id=str(owner.id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()
        return owner.id


def _scoped_to_default_org(owner_id: int):
    return org_data_isolation_context(
        OrgDataIsolationUserContext(
            org_id=DEFAULT_TEST_ORG_DB_ID,
            user_id=str(owner_id),
            role="owner",
            source="test",
        )
    )


def test_owner_creates_user_in_other_org_while_scoped_to_own_org(
    owner_client: TestClient,
) -> None:
    owner_id = _owner_in_default_org(owner_client)
    with SessionLocal() as db, _scoped_to_default_org(owner_id):
        owner = db.get(User, owner_id)
        user, _ = create_managed_user(
            db,
            payload=UserCreate(
                username="王维", role="super_admin", organization_id=OTHER_ORG_ID
            ),
            actor=owner,
            audit=AUDIT,
        )
        # 路由紧接着补成员关系,同样要跨组织走通。
        try:
            with without_org_data_isolation():
                add_org_member(
                    db,
                    org_id=OTHER_ORG_ID,
                    payload=OrgMemberAddRequest(user_id=str(user.id), role="admin"),
                    actor=owner,
                    audit=AUDIT,
                )
        except OrgMembershipConflictError:
            pass
        assert user.organization_id == OTHER_ORG_ID
        user_id = user.id

    with SessionLocal() as db:
        membership = db.scalar(
            select(OrgMembershipRecord).where(
                OrgMembershipRecord.user_id == str(user_id),
                OrgMembershipRecord.org_id == OTHER_ORG_ID,
            )
        )
        assert membership is not None


def test_create_still_rejects_missing_org_while_scoped(
    owner_client: TestClient,
) -> None:
    owner_id = _owner_in_default_org(owner_client)
    with SessionLocal() as db, _scoped_to_default_org(owner_id):
        owner = db.get(User, owner_id)
        with pytest.raises(UserOrganizationNotFoundError):
            create_managed_user(
                db,
                payload=UserCreate(
                    username="ghost_org_user",
                    role="viewer",
                    organization_id=MISSING_ORG_ID,
                ),
                actor=owner,
                audit=AUDIT,
            )


def test_owner_moves_user_to_other_org_while_scoped_to_own_org(
    owner_client: TestClient,
) -> None:
    owner_id = _owner_in_default_org(owner_client)
    with SessionLocal() as db, _scoped_to_default_org(owner_id):
        owner = db.get(User, owner_id)
        user, _ = create_managed_user(
            db,
            payload=UserCreate(
                username="mover", role="viewer", organization_id=DEFAULT_TEST_ORG_DB_ID
            ),
            actor=owner,
            audit=AUDIT,
        )
        moved = update_managed_user(
            db,
            user_id=user.id,
            payload=UserUpdate(organization_id=OTHER_ORG_ID),
            actor=owner,
            audit=AUDIT,
        )
        assert moved.organization_id == OTHER_ORG_ID


def test_owner_registers_bot_in_other_org_while_scoped_to_own_org(
    owner_client: TestClient,
) -> None:
    owner_id = _owner_in_default_org(owner_client)
    with SessionLocal() as db, _scoped_to_default_org(owner_id):
        owner = db.get(User, owner_id)
        bot = create_bot_user(
            db,
            payload=BotCreate(
                username="cross_org_bot",
                display_name="跨组织机器人",
                job_title="测试",
                organization_id=OTHER_ORG_ID,
                password="example-only-bot-password",
            ),
            actor=owner,
            audit=AUDIT,
        )
        bot_id = bot.id

    with SessionLocal() as db:
        membership = db.scalar(
            select(OrgMembershipRecord).where(
                OrgMembershipRecord.user_id == str(bot_id),
                OrgMembershipRecord.org_id == OTHER_ORG_ID,
            )
        )
        assert membership is not None
