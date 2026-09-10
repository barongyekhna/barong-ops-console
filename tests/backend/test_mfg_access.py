"""M 系列门禁:owner / 制造公司 super_admin / 带权限码的制造公司成员;非 factory 组织看不到。"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.m_series.inventory import service
from backend.app.modules.m_series.inventory.models import (
    MfgBomLine,
    MfgDocCounter,
    MfgDocument,
    MfgItem,
    MfgMovement,
)
from backend.app.services.module_control_center import (
    _module_allowed_for_organization,
)
from backend.app.services.module_registry import (
    FACTORY_ONLY_MODULE_KEYS,
    list_module_manifests,
)

pytestmark = pytest.mark.integration

FACTORY_ORG_ID = "org_" + "a" * 32
STORE_ORG_ID = "org_" + "b" * 32


def _org(org_id: str, org_type: str) -> OrganizationRecord:
    return OrganizationRecord(
        org_id=org_id,
        org_name=f"org-{org_type}",
        org_type=org_type,
        owner_user_id="1",
        status="active",
        metadata_json={},
    )


@pytest.fixture
def db():
    with SessionLocal() as session:
        session.execute(
            delete(OrganizationRecord).where(
                OrganizationRecord.org_id.in_([FACTORY_ORG_ID, STORE_ORG_ID])
            )
        )
        session.commit()
        yield session
        session.execute(
            delete(OrganizationRecord).where(
                OrganizationRecord.org_id.in_([FACTORY_ORG_ID, STORE_ORG_ID])
            )
        )
        session.commit()


def _user(role: str, org: str | None) -> User:
    return User(username=f"u-{role}", password_hash="x", role=role, is_active=True, organization_id=org)


def test_factory_context_requires_exactly_one_factory(db) -> None:
    db.add(_org(STORE_ORG_ID, "store"))
    db.commit()
    with pytest.raises(service.FactoryNotConfigured):
        service.resolve_factory_context(db)
    db.add(_org(FACTORY_ORG_ID, "factory"))
    db.commit()
    ctx = service.resolve_factory_context(db)
    assert ctx.factory_org_id == FACTORY_ORG_ID


def test_role_gate(db) -> None:
    db.add_all([_org(FACTORY_ORG_ID, "factory"), _org(STORE_ORG_ID, "store")])
    db.commit()
    ctx = service.resolve_factory_context(db)
    assert service.user_may_access(_user("owner", None), ctx)
    assert service.user_may_access(_user("super_admin", FACTORY_ORG_ID), ctx)
    assert not service.user_may_access(_user("super_admin", STORE_ORG_ID), ctx)
    assert not service.user_may_access(_user("super_admin", None), ctx)
    # 不带 db 只能走角色硬门:普通角色一律不过
    assert not service.user_may_access(_user("admin", FACTORY_ORG_ID), ctx)
    assert not service.user_may_access(_user("viewer", FACTORY_ORG_ID), ctx)


def test_member_with_permission_code_passes_gate(db) -> None:
    """2026-09-10 拍板:制造公司成员 + 权限页勾了库存权限 → 过门;缺任一条都不过。"""
    from uuid import uuid4

    from backend.app.core.security import hash_password
    from backend.app.models.org_membership import OrgMembershipRecord
    from backend.app.models.permission import UserPermissionAssignment
    from backend.app.services.permission_resolution_cache import clear_permission_ttl_cache
    from backend.app.services.permission_service import upsert_permission_registry

    db.add_all([_org(FACTORY_ORG_ID, "factory"), _org(STORE_ORG_ID, "store")])
    upsert_permission_registry(db)
    helper = User(
        username=f"mfg_helper_{uuid4().hex[:8]}",
        password_hash=hash_password("Mfg-Helper-Test-Only-2026"),
        role="operator",
        is_active=True,
        organization_id=STORE_ORG_ID,
    )
    db.add(helper)
    db.flush()
    db.add(
        OrgMembershipRecord(
            membership_id=f"mem_{uuid4().hex}",
            user_id=str(helper.id),
            org_id=STORE_ORG_ID,
            role="member",
            status="active",
        )
    )
    db.commit()
    ctx = service.resolve_factory_context(db)
    try:
        # 只在贸易公司 → 不过
        assert not service.user_may_access(helper, ctx, db=db)
        # 加进制造公司但没权限码 → 不过
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{uuid4().hex}",
                user_id=str(helper.id),
                org_id=FACTORY_ORG_ID,
                role="member",
                status="active",
            )
        )
        db.commit()
        assert not service.user_may_access(helper, ctx, db=db)
        # 只给 read → 能查不能改
        db.add(
            UserPermissionAssignment(
                user_id=helper.id,
                permission_key=service.PERMISSION_READ,
                scope_type="global",
                scope_key="*",
                granted_by_user_id=helper.id,
                is_enabled=True,
            )
        )
        db.commit()
        clear_permission_ttl_cache()
        assert service.user_may_access(helper, ctx, db=db)
        assert not service.user_may_access(helper, ctx, db=db, action="manage")
        # 给 manage → 都行(manage 蕴含 read)
        db.add(
            UserPermissionAssignment(
                user_id=helper.id,
                permission_key=service.PERMISSION_MANAGE,
                scope_type="global",
                scope_key="*",
                granted_by_user_id=helper.id,
                is_enabled=True,
            )
        )
        db.commit()
        clear_permission_ttl_cache()
        assert service.user_may_access(helper, ctx, db=db, action="manage")
    finally:
        db.execute(delete(UserPermissionAssignment).where(UserPermissionAssignment.user_id == helper.id))
        db.execute(delete(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(helper.id)))
        db.execute(delete(User).where(User.id == helper.id))
        db.commit()


def test_module_only_allowed_for_factory_org() -> None:
    manifest = next(m for m in list_module_manifests() if m.module_key == "mfg.inventory")
    assert manifest.module_key in FACTORY_ONLY_MODULE_KEYS
    assert _module_allowed_for_organization(_org(FACTORY_ORG_ID, "factory"), manifest)
    assert not _module_allowed_for_organization(_org(STORE_ORG_ID, "store"), manifest)


def test_http_gate_owner_and_store_admin(owner_client, db) -> None:
    # owner_client 建的是 store 组织;没有 factory → 503,加上 factory → 200
    response = owner_client.get("/api/app/mfg/stock")
    assert response.status_code == 503
    db.add(_org(FACTORY_ORG_ID, "factory"))
    db.commit()
    response = owner_client.get("/api/app/mfg/stock")
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0}
    response = owner_client.get("/api/app/mfg/context")
    assert response.json()["factory_org_id"] == FACTORY_ORG_ID


def test_http_end_to_end_table_example(owner_client, db) -> None:
    db.add(_org(FACTORY_ORG_ID, "factory"))
    db.commit()

    def post(path, body, expect=201):
        r = owner_client.post(f"/api/app/mfg{path}", json=body)
        assert r.status_code == expect, r.text
        return r.json()

    top = post("/items", {"kind": "part", "code": "TOP", "name": "桌面", "unit": "个"})
    leg = post("/items", {"kind": "part", "code": "LEG", "name": "桌腿", "unit": "条"})
    table = post("/items", {"kind": "product", "code": "TABLE", "name": "桌子", "unit": "套"})
    r = owner_client.put(
        f"/api/app/mfg/items/{table['id']}/bom",
        json={
            "lines": [
                {"part_id": top["id"], "mode": "per_unit", "qty": "1"},
                {"part_id": leg["id"], "mode": "per_unit", "qty": "4"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    post("/documents/receipt", {"lines": [{"item_id": top["id"], "qty": "1000"}, {"item_id": leg["id"], "qty": "800"}]})
    doc = post("/documents/production", {"product_id": table["id"], "qty": "100"})
    assert doc["doc_no"] == "PR-000001"
    conflict = post("/documents/production", {"product_id": table["id"], "qty": "101"}, expect=409)
    assert conflict["detail"]["shortages"][0]["code"] == "LEG"
    post("/documents/shipment", {"product_id": table["id"], "qty": "50"})
    stock = {row["code"]: row["stock"] for row in owner_client.get("/api/app/mfg/stock").json()["items"]}
    assert stock == {"TOP": "900.000", "LEG": "400.000", "TABLE": "50.000"}
    docs = owner_client.get("/api/app/mfg/documents").json()
    assert docs["total"] == 3
    detail = owner_client.get(f"/api/app/mfg/documents/{doc['id']}").json()
    assert len(detail["movements"]) == 3
    preview = owner_client.get(
        "/api/app/mfg/production/preview", params={"product_id": table["id"], "qty": "100"}
    ).json()
    assert preview["feasible"] is True
    with SessionLocal() as s:
        for model in (MfgMovement, MfgDocument, MfgBomLine, MfgItem, MfgDocCounter):
            s.execute(delete(model))
        s.commit()
