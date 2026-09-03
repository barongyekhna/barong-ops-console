"""建立/更新数字员工账号(第一位:白苏婉 · 内容专员)。

幂等 —— 重复跑只会把账号、显示名、只读权限和 agent 登记补齐到目标状态。
密码每次都按 ``BAISUWAN_PASSWORD`` 重设,因为 worker 要拿它登录,两边必须一致。

    BAISUWAN_PASSWORD=... python -m backend.app.cli.bootstrap_bot

为什么不走 ``POST /users``:``USER_MANAGEMENT_ROLES`` 白名单挡着,而且真正
要写的东西(is_bot、C19 display_name、权限 assignment、agent_registry)分散在
四张表,API 一条都覆盖不了。

为什么 role 是 viewer 而不是 bot_agent:``core/rbac.py`` 把 bot_agent 映射成
ROLE_SYSTEM,只剩 ACTION_INTERNAL —— 她会连自己的 geo.content.read 都用不了。
``is_bot`` 只是标签,鉴权照常走正常那条链。
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..core.security import hash_password
from ..db.session import managed_session
from ..models.c19 import C19ProfileRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..modules.agent_series.baisuwan.agent import ensure_baisuwan_agent
from ..modules.agent_series.baisuwan.constants import (
    AGENT_BIO,
    AGENT_DISPLAY_NAME,
    AGENT_ID,
    AGENT_JOB_TITLE,
    AGENT_PERMISSIONS,
    AGENT_USERNAME,
)
from ..modules.c19.identity_sync_service import sync_profile_for_user
from ..modules.k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
from ..repositories.operation_logs import create_operation_log
from ..repositories.permissions import upsert_user_assignment
from ..schemas.org_membership import generate_membership_id
from ..repositories.users import create_user, get_user_by_username
from ..services.data_isolation import SKIP_ORG_DATA_ISOLATION

BOT_BOOTSTRAP_LOCK_ID = 803081892

MIN_PASSWORD_LENGTH = 12


class BotBootstrapError(RuntimeError):
    pass


def _resolve_org_id(db: Session) -> str:
    """白苏婉挂哪个组织。

    她的 AI 调用复用 K 模块的 key binding,所以默认挂到同一个组织,免得
    出现「人在 A 组织、花的是 B 组织的钱」这种对不上账的情况。
    """
    explicit = (os.getenv("BAISUWAN_ORG_ID") or "").strip()
    if explicit:
        found = db.scalar(
            select(OrganizationRecord.org_id).where(
                OrganizationRecord.org_id == explicit
            )
        )
        if found is None:
            raise BotBootstrapError(f"BAISUWAN_ORG_ID 指向的组织不存在: {explicit}")
        return found

    found = db.scalar(
        select(OrganizationRecord.org_id).where(
            OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME
        )
    )
    if found is None:
        raise BotBootstrapError(
            "找不到默认组织,请显式设置 BAISUWAN_ORG_ID。"
            f"(默认按 org_name={TARGET_ORGANIZATION_NAME} 查找)"
        )
    return found


def _ensure_org_membership(db: Session, *, user_id: str, org_id: str) -> None:
    """把她放进组织 —— 这是能不能读数据的开关,不是锦上添花。

    ``users.organization_id`` 只是一列外键;真正决定请求有没有组织上下文的是
    ``org_memberships``(见 middleware/org_context.py:_resolve_org)。少了这行,
    org_context_middleware 解析不出组织,所有 /api/app/* 一律 403
    「C18H org context is required.」—— 权限给得再对也没用,她连门都进不去。

    刻意只给**一个**组织的 member:``_resolve_org`` 只在成员关系恰好一条时
    才能无歧义地自动选中。多给一个,她就又不知道自己在哪家公司了。
    """
    existing = db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == user_id,
            OrgMembershipRecord.org_id == org_id,
        )
    )
    if existing is not None:
        existing.role = "member"
        existing.status = "active"
        db.add(existing)
    else:
        db.add(
            OrgMembershipRecord(
                membership_id=generate_membership_id(),
                user_id=user_id,
                org_id=org_id,
                role="member",
                status="active",
            )
        )
    db.flush()


def bootstrap_bot(db: Session, *, password: str | None) -> str:
    if not password:
        raise BotBootstrapError("BAISUWAN_PASSWORD is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise BotBootstrapError(
            f"BAISUWAN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters."
        )

    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": BOT_BOOTSTRAP_LOCK_ID},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )

    try:
        password_hash = hash_password(password)
    except ValueError:
        raise BotBootstrapError(
            "BAISUWAN_PASSWORD does not meet security requirements."
        ) from None

    org_id = _resolve_org_id(db)

    user = get_user_by_username(db, AGENT_USERNAME)
    if user is None:
        user = create_user(
            db,
            username=AGENT_USERNAME,
            password_hash=password_hash,
            role="viewer",
            job_title=AGENT_JOB_TITLE,
            organization_id=org_id,
            must_change_password=False,
            is_active=True,
        )
        outcome = "created"
    else:
        user.password_hash = password_hash
        outcome = "updated"

    # 每次都收敛到目标状态:她被停用过、被改过职位、或者是在 is_bot 这列
    # 存在之前建的号,重跑一次就都补回来。
    user.is_bot = True
    user.job_title = AGENT_JOB_TITLE
    user.organization_id = org_id
    user.must_change_password = False
    user.is_active = True
    db.add(user)
    db.flush()

    # C19 身份。sync 只建不覆盖(它不该动用户自己改过的昵称),所以显示名和
    # 简介在这里显式写 —— C19ProfileUpdate 只开放了 avatar_ref,没有别的路。
    sync_profile_for_user(db, user=user)
    profile = db.get(C19ProfileRecord, user.id)
    if profile is None:
        raise BotBootstrapError("C19 profile projection missing after sync.")
    profile.display_name = AGENT_DISPLAY_NAME
    profile.bio = AGENT_BIO
    db.add(profile)

    _ensure_org_membership(db, user_id=str(user.id), org_id=org_id)

    for permission_key in AGENT_PERMISSIONS:
        upsert_user_assignment(
            db,
            user_id=user.id,
            permission_key=permission_key,
            scope_type="global",
            scope_key="*",
            granted_by_user_id=None,
            reason="数字员工白苏婉 · 内容专员(只读)",
            expires_at=None,
        )

    agent_created = ensure_baisuwan_agent(db)

    create_operation_log(
        db,
        actor_type="system",
        actor_id="bot-bootstrap",
        action="agent.bootstrap",
        target_type="user",
        target_id=str(user.id),
        result="success",
        details={
            "outcome": outcome,
            "agent_id": AGENT_ID,
            "username": AGENT_USERNAME,
            "display_name": AGENT_DISPLAY_NAME,
            "org_id": org_id,
            "permissions": list(AGENT_PERMISSIONS),
            "agent_registry_created": agent_created,
        },
    )
    db.commit()
    return outcome


def main() -> int:
    password = os.getenv("BAISUWAN_PASSWORD")
    with managed_session() as db:
        try:
            result = bootstrap_bot(db, password=password)
        except BotBootstrapError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print(f"Bot bootstrap failed: {exc}", file=sys.stderr)
            return 1

    print(f"白苏婉 bootstrap {result}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
