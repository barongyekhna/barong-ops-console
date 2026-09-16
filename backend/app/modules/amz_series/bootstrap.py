"""幂等建号:``python -m backend.app.modules.amz_series.bootstrap``

一次做完 A0 的组织层:
1. 四家广州公司(org_type=amazon,org_id 钉死在 catalog.py)
2. owner(1)owner 成员关系、王创鑫(2)admin 成员关系,每条都同步 C19 归属投影
3. 五条 amz_stores
4. 王创鑫五店 grant(owner 天然全通,不要行)
5. 四名机器人 amz_a..d:viewer + is_bot + 四组织 member + users.organization_id=龙杰 + C19 资料 + agent_registry
   密码从 AMZ_AGENT_{A..D}_PASSWORD 读;缺哪个就跳过哪个机器人(其余照建)。

不用 organization_lifecycle.create_organization:它要 HTTP AuditContext、每次都 commit、重复即抛;
repository 函数才是能收敛的路。全程 advisory lock,连跑两次结果相同。
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...core.security import hash_password
from ...db.session import managed_session
from ...models.c19 import C19ProfileRecord
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from ...repositories.organizations import create_organization_record
from ...repositories.users import create_user, get_user_by_username
from ...schemas.org_membership import generate_membership_id
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from ...services.module_control_cache_service import refresh_module_control_center_cache_async
from ...services.permission_resolution_cache import clear_permission_ttl_cache
from ..c19.identity_sync_service import sync_affiliation_from_membership, sync_profile_for_user
from .agent import ensure_amz_agents
from .persona import display_name, persona_for
from .catalog import AGENT_HOME_COMPANY, COMPANIES, MANAGER_USER_ID, OWNER_USER_ID, STORES
from .constants import (
    AMAZON_ORG_TYPE,
    EMPLOYEE_PASSWORD_ENVS,
    EMPLOYEE_ROLE_LABELS,
    EMPLOYEE_USERNAMES,
    EMPLOYEES,
    STORE_ROLE_GRANT,
)
from .models import AmzStore, AmzStoreGrant

MIN_PASSWORD_LENGTH = 12
LOCK_ID = 803081894


class BootstrapError(RuntimeError):
    pass


def _ensure_membership(db: Session, *, user: User, org_id: str, role: str) -> OrgMembershipRecord:
    existing = db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == str(user.id), OrgMembershipRecord.org_id == org_id
        )
    )
    if existing is None:
        existing = OrgMembershipRecord(
            membership_id=generate_membership_id(),
            user_id=str(user.id),
            org_id=org_id,
            role=role,
            status="active",
        )
    else:
        existing.role = role
        existing.status = "active"
    db.add(existing)
    db.flush()
    # 通讯录读的是 c19_affiliations 投影,不是 org_memberships;漏这一步 = 「没有加入任何组织」。
    sync_affiliation_from_membership(db, membership=existing, user=user)
    return existing


def _ensure_companies(db: Session, *, owner: User) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for company in COMPANIES:
        org = db.get(OrganizationRecord, company.org_id)
        if org is None:
            create_organization_record(
                db,
                org_id=company.org_id,
                org_name=company.org_name,
                org_type=AMAZON_ORG_TYPE,
                owner_user_id=str(owner.id),
                metadata={"country": "CN", "timezone": "Asia/Shanghai", "custom": {"series": "amz", "short_name": company.short_name}},
            )
            outcomes[company.org_id] = "created"
        else:
            org.org_type = AMAZON_ORG_TYPE
            org.status = "active"
            org.org_name = company.org_name
            org.name = company.org_name
            db.add(org)
            outcomes[company.org_id] = "updated"
        _ensure_membership(db, user=owner, org_id=company.org_id, role="owner")
    return outcomes


def _ensure_stores(db: Session) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for spec in STORES:
        store = db.get(AmzStore, spec.store_code)
        if store is None:
            store = AmzStore(
                store_code=spec.store_code,
                company_org_id=spec.company.org_id,
                company_name=spec.company.org_name,
                display_name=spec.display_name,
                marketplace_id=spec.marketplace_id,
                region=spec.region,
                country=spec.country,
                currency=spec.currency,
                timezone=spec.timezone,
                status="active",
                metadata_json={},
            )
            outcomes[spec.store_code] = "created"
        else:
            store.company_org_id = spec.company.org_id
            store.company_name = spec.company.org_name
            store.display_name = spec.display_name
            store.marketplace_id = spec.marketplace_id
            store.region = spec.region
            store.country = spec.country
            store.currency = spec.currency
            store.status = "active"
            outcomes[spec.store_code] = "updated"
        db.add(store)
    db.flush()
    return outcomes


def _ensure_manager(db: Session, *, manager: User, owner: User) -> None:
    for company in COMPANIES:
        _ensure_membership(db, user=manager, org_id=company.org_id, role="admin")
    for spec in STORES:
        grant = db.get(AmzStoreGrant, (int(manager.id), spec.store_code))
        if grant is None:
            grant = AmzStoreGrant(user_id=int(manager.id), store_code=spec.store_code, role=STORE_ROLE_GRANT, granted_by_user_id=int(owner.id))
        else:
            grant.role = STORE_ROLE_GRANT
        db.add(grant)
    db.flush()


def _ensure_bot(db: Session, *, employee: str, password: str) -> dict:
    username = EMPLOYEE_USERNAMES[employee]
    job_title = EMPLOYEE_ROLE_LABELS[employee]
    try:
        password_hash = hash_password(password)
    except ValueError:
        raise BootstrapError(f"{EMPLOYEE_PASSWORD_ENVS[employee]} 不满足密码强度要求。") from None
    user = get_user_by_username(db, username)
    if user is None:
        user = create_user(
            db,
            username=username,
            password_hash=password_hash,
            role="viewer",
            job_title=job_title,
            organization_id=AGENT_HOME_COMPANY.org_id,
            must_change_password=False,
            is_active=True,
        )
        outcome = "created"
    else:
        user.password_hash = password_hash
        outcome = "updated"
    # role 必须是 viewer 而不是 bot_agent:rbac 把 bot_agent 映射成 ROLE_SYSTEM,连自己的读权限都没了。
    user.role = "viewer"
    user.is_bot = True
    user.job_title = job_title
    user.organization_id = AGENT_HOME_COMPANY.org_id
    user.must_change_password = False
    user.is_active = True
    db.add(user)
    db.flush()

    sync_profile_for_user(db, user=user)
    profile = db.get(C19ProfileRecord, user.id)
    if profile is None:
        raise BootstrapError("C19 profile 同步后不存在。")
    profile.display_name = display_name(employee)
    profile.bio = persona_for(employee).bio
    db.add(profile)

    for company in COMPANIES:
        _ensure_membership(db, user=user, org_id=company.org_id, role="member")
    return {"employee": employee, "user_id": user.id, "outcome": outcome}


def bootstrap(
    db: Session,
    *,
    passwords: dict[str, str],
    owner_user_id: int = OWNER_USER_ID,
    manager_user_id: int = MANAGER_USER_ID,
) -> dict:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": LOCK_ID},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
    with without_org_data_isolation():
        owner = db.get(User, owner_user_id)
        manager = db.get(User, manager_user_id)
        if owner is None:
            raise BootstrapError(f"owner user {owner_user_id} 不存在。")
        if manager is None:
            raise BootstrapError(f"manager user {manager_user_id} 不存在。")

        companies = _ensure_companies(db, owner=owner)
        stores = _ensure_stores(db)
        _ensure_manager(db, manager=manager, owner=owner)

        bots: list[dict] = []
        skipped: list[str] = []
        for employee in EMPLOYEES:
            password = passwords.get(employee, "")
            if len(password) < MIN_PASSWORD_LENGTH:
                skipped.append(employee)
                continue
            bots.append(_ensure_bot(db, employee=employee, password=password))
        agents_created = ensure_amz_agents(db) if bots else []

        create_operation_log(
            db,
            actor_type="system",
            actor_id="amz-bootstrap",
            action="amz.bootstrap",
            target_type="module",
            target_id="amz.ops",
            result="success",
            details={
                "companies": companies,
                "stores": stores,
                "manager_user_id": int(manager.id),
                "bots": bots,
                "bots_skipped_missing_password": skipped,
                "agents_created": agents_created,
            },
        )
        db.commit()
    clear_permission_ttl_cache()
    refresh_module_control_center_cache_async(force=True)
    return {
        "companies": companies,
        "stores": stores,
        "bots": bots,
        "bots_skipped_missing_password": skipped,
        "agents_created": agents_created,
    }


def main() -> int:
    passwords = {employee: os.getenv(EMPLOYEE_PASSWORD_ENVS[employee]) or "" for employee in EMPLOYEES}
    with managed_session() as db:
        result = bootstrap(db, passwords=passwords)
    print(result)
    if result["bots_skipped_missing_password"]:
        print(
            "skipped bots (password env missing or < 12 chars): "
            + ", ".join(result["bots_skipped_missing_password"]),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
