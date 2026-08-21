"""幂等建号:NIJING_PASSWORD=... python -m backend.app.modules.agent_series.nijing.bootstrap

建 nijing 用户(viewer、is_bot、挂 factory 组织)+ C19 资料 + 组织成员关系 + agent_registry。
**不授予任何权限码**:她对库存的每一步都以说话人的身份过门,自己不需要、也不该有。
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ....core.security import hash_password
from ....db.session import managed_session
from ....models.c19 import C19ProfileRecord
from ....models.org_membership import OrgMembershipRecord
from ....repositories.operation_logs import create_operation_log
from ....repositories.users import create_user, get_user_by_username
from ....schemas.org_membership import generate_membership_id
from ...c19.identity_sync_service import sync_profile_for_user
from ...m_series.inventory.service import resolve_factory_context
from .agent import ensure_nijing_agent
from .constants import AGENT_BIO, AGENT_DISPLAY_NAME, AGENT_JOB_TITLE, AGENT_USERNAME, PASSWORD_ENV

MIN_PASSWORD_LENGTH = 12
LOCK_ID = 803081893


class BootstrapError(RuntimeError):
    pass


def _ensure_org_membership(db: Session, *, user_id: str, org_id: str) -> None:
    """只给一个组织的 member:_resolve_org 只在成员关系恰好一条时才能无歧义选中。"""
    existing = db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == user_id, OrgMembershipRecord.org_id == org_id
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


def bootstrap(db: Session, *, password: str) -> dict:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise BootstrapError(f"{PASSWORD_ENV} 至少 {MIN_PASSWORD_LENGTH} 位。")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": LOCK_ID})
    try:
        password_hash = hash_password(password)
    except ValueError:
        raise BootstrapError(f"{PASSWORD_ENV} 不满足密码强度要求。") from None

    ctx = resolve_factory_context(db)
    org_id = ctx.factory_org_id

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
    user.is_bot = True
    user.job_title = AGENT_JOB_TITLE
    user.organization_id = org_id
    user.must_change_password = False
    user.is_active = True
    db.add(user)
    db.flush()

    sync_profile_for_user(db, user=user)
    profile = db.get(C19ProfileRecord, user.id)
    if profile is None:
        raise BootstrapError("C19 profile 同步后不存在。")
    profile.display_name = AGENT_DISPLAY_NAME
    profile.bio = AGENT_BIO
    db.add(profile)

    _ensure_org_membership(db, user_id=str(user.id), org_id=org_id)
    agent_created = ensure_nijing_agent(db)

    create_operation_log(
        db,
        actor_type="system",
        actor_id="bot-bootstrap",
        action="agent.bootstrap",
        target_type="user",
        target_id=str(user.id),
        result="success",
        details={"agent": AGENT_USERNAME, "outcome": outcome, "org_id": org_id, "agent_registry_created": agent_created},
    )
    db.commit()
    return {"user_id": user.id, "outcome": outcome, "org_id": org_id, "org_name": ctx.org_name, "agent_registry_created": agent_created}


def main() -> int:
    password = os.getenv(PASSWORD_ENV) or ""
    if not password:
        print(f"{PASSWORD_ENV} is required.", file=sys.stderr)
        return 2
    with managed_session() as db:
        result = bootstrap(db, password=password)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
