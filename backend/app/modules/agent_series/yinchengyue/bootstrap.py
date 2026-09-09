"""收敛登记:python -m backend.app.modules.agent_series.yinchengyue.bootstrap [--with-user]

按 2026-08-22 的规矩,机器人的**身份**(users / c19_profiles / org_memberships)在控制台
「用户管理 → 注册机器人」里建,这里不建号。默认只把 agent_registry 收敛到位。

加 ``--with-user`` 时,对**已经存在**的 yinchengyue 账号做幂等修补:is_bot、岗位、简介、
显示名、贸易公司的成员关系(只此一条,多一条整站 403)。账号不存在就报错退出,不代建。
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ....db.session import managed_session
from ....models.c19 import C19ProfileRecord
from ....models.org_membership import OrgMembershipRecord
from ....models.organization import OrganizationRecord
from ....repositories.operation_logs import create_operation_log
from ....repositories.users import get_user_by_username
from ....schemas.org_membership import generate_membership_id
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...c19.identity_sync_service import sync_affiliation_from_membership, sync_profile_for_user
from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
from .agent import ensure_yinchengyue_agent
from .constants import AGENT_BIO, AGENT_DISPLAY_NAME, AGENT_JOB_TITLE, AGENT_USERNAME

LOCK_ID = 803081894


class BootstrapError(RuntimeError):
    pass


def resolve_trade_org_id(db: Session) -> str:
    explicit = (os.getenv("YINCHENGYUE_ORG_ID") or "").strip()
    if explicit:
        found = db.scalar(select(OrganizationRecord.org_id).where(OrganizationRecord.org_id == explicit), execution_options=SKIP_ORG_DATA_ISOLATION)
        if found is None:
            raise BootstrapError(f"YINCHENGYUE_ORG_ID 指向的组织不存在: {explicit}")
        return str(found)
    found = db.scalar(select(OrganizationRecord.org_id).where(OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME), execution_options=SKIP_ORG_DATA_ISOLATION)
    if found is None:
        raise BootstrapError(f"找不到贸易公司组织(org_name={TARGET_ORGANIZATION_NAME}),请显式设置 YINCHENGYUE_ORG_ID。")
    return str(found)


def _ensure_single_membership(db: Session, *, user, org_id: str) -> None:
    """只留贸易公司这一条 member 关系(多一条整站 403),并同步到 C19 的组织投影(通讯录显示的是它)。"""
    user_id = str(user.id)
    rows = list(db.scalars(select(OrgMembershipRecord).where(OrgMembershipRecord.user_id == user_id), execution_options=SKIP_ORG_DATA_ISOLATION))
    kept = None
    for row in rows:
        if row.org_id == org_id and kept is None:
            kept = row
            row.role = "member"
            row.status = "active"
            db.add(row)
        else:
            db.delete(row)
    if kept is None:
        kept = OrgMembershipRecord(membership_id=generate_membership_id(), user_id=user_id, org_id=org_id, role="member", status="active")
        db.add(kept)
    db.flush()
    sync_affiliation_from_membership(db, membership=kept, user=user)


def converge_registry(db: Session) -> dict:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": LOCK_ID}, execution_options=SKIP_ORG_DATA_ISOLATION)
    created = ensure_yinchengyue_agent(db)
    db.commit()
    return {"agent_registry_created": created}


def repair_identity(db: Session) -> dict:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": LOCK_ID}, execution_options=SKIP_ORG_DATA_ISOLATION)
    user = get_user_by_username(db, AGENT_USERNAME)
    if user is None:
        raise BootstrapError(f"账号 {AGENT_USERNAME} 不存在:请先在控制台「用户管理 → 注册机器人」里建号。")
    org_id = resolve_trade_org_id(db)
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

    _ensure_single_membership(db, user=user, org_id=org_id)
    created = ensure_yinchengyue_agent(db)
    create_operation_log(
        db,
        actor_type="system",
        actor_id="bot-bootstrap",
        action="agent.bootstrap",
        target_type="user",
        target_id=str(user.id),
        result="success",
        details={"agent": AGENT_USERNAME, "outcome": "repaired", "org_id": org_id, "agent_registry_created": created},
    )
    db.commit()
    return {"user_id": user.id, "org_id": org_id, "agent_registry_created": created}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    with managed_session() as db:
        result = repair_identity(db) if "--with-user" in args else converge_registry(db)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
