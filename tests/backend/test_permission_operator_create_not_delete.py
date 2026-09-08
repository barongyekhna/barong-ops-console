"""operator 拿到 K「新建」但没拿到「归档/删除」时，后端必须真的拦住删除。

这条测试走的是和生产验收完全相同的路径：owner 通过用户管理 API 建 operator
→ 首登改密 → owner 通过授权 API 只给 read + create → operator 建产品成功
→ operator 删除 / 归档 / 更新全部 403 → owner 回读产品仍在。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.services.permission_service import upsert_permission_registry

OWNER_PASSWORD = "Perm-Tree-Owner-Test-Only-2026"
OPERATOR_PASSWORD = "Perm-Tree-Operator-Test-Only-2026"
CATEGORY_ID = "perm-tree-leaf-pumps"
K_READ = "k.product_knowledge.read"
K_CREATE = "k.product_knowledge.create"
K_UPDATE = "k.product_knowledge.update"
K_ARCHIVE = "k.product_knowledge.archive"


def _seed_owner_with_org(*, with_second_org: bool = False) -> tuple[str, str, int]:
    """在任何 HTTP 请求之前把组织和跨组织员工直接种进库。
    请求内的 ORM 查询被 data_isolation 限定在当前组织上下文，所以另一组织的
    东西不能靠 API 建。返回 (owner用户名, 组织A, 组织B里员工的 user_id 或 0)。"""
    username = f"perm_tree_owner_{uuid4().hex[:10]}"
    org_id = f"org_{uuid4().hex}"
    other_org = f"org_{uuid4().hex}" if with_second_org else ""
    other_operator_id = 0
    with SessionLocal() as db:
        upsert_permission_registry(db)
        user = User(
            username=username,
            password_hash=hash_password(OWNER_PASSWORD),
            role="owner",
            is_active=True,
            organization_id=org_id,
        )
        db.add(user)
        db.flush()
        db.add(
            OrganizationRecord(
                org_id=org_id,
                org_name="权限树测试组织",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
        )
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{uuid4().hex}",
                user_id=str(user.id),
                org_id=org_id,
                role="owner",
                status="active",
            )
        )
        if other_org:
            db.add(
                OrganizationRecord(
                    org_id=other_org,
                    org_name="权限树测试组织B",
                    org_type="factory",
                    owner_user_id=str(user.id),
                    status="active",
                    metadata_json={},
                )
            )
            db.flush()
            other_operator = User(
                username=f"perm_tree_cross_{uuid4().hex[:8]}",
                password_hash=hash_password(OPERATOR_PASSWORD),
                role="operator",
                is_active=True,
                organization_id=other_org,
            )
            db.add(other_operator)
            db.flush()
            db.add(
                OrgMembershipRecord(
                    membership_id=f"mem_{uuid4().hex}",
                    user_id=str(other_operator.id),
                    org_id=other_org,
                    role="member",
                    status="active",
                )
            )
            db.flush()
            other_operator_id = other_operator.id
        db.execute(
            text(
                "INSERT INTO k_category_google "
                "(id, name, full_path, parent_id, level, is_leaf) "
                "VALUES (:id, :name, :path, NULL, 1, true) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": CATEGORY_ID,
                "name": "Permission Tree Pumps",
                "path": "Business & Industrial > Permission Tree Pumps",
            },
        )
        db.commit()
    return username, org_id, other_operator_id


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"x-session-token": response.json()["session_token"]}


@pytest.mark.integration
def test_operator_with_create_but_not_archive_cannot_delete_k_product(
    auth_client: TestClient,
) -> None:
    owner_username, org_id, _unused = _seed_owner_with_org()
    owner = _login(auth_client, owner_username, OWNER_PASSWORD)

    # 1. owner 通过用户管理 API 建 operator（单组织成员关系由路由自动挂）。
    operator_username = f"perm_tree_operator_{uuid4().hex[:8]}"
    created = auth_client.post(
        "/api/app/users",
        headers=owner,
        json={
            "username": operator_username,
            "role": "operator",
            "organization_id": org_id,
            "job_title": "权限树验收",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    operator_id = created.json()["id"]
    initial_password = created.json()["initial_password"]
    assert initial_password

    # 2. 首登要求改密；改完才能碰业务接口。
    first_login = auth_client.post(
        "/api/public/auth/login",
        json={"username": operator_username, "password": initial_password},
    )
    assert first_login.status_code == 200, first_login.text
    assert first_login.json()["require_password_change"] is True
    temp_headers = {"x-session-token": first_login.json()["session_token"]}
    changed = auth_client.post(
        "/api/public/auth/change-password",
        headers=temp_headers,
        json={
            "current_password": initial_password,
            "new_password": OPERATOR_PASSWORD,
        },
    )
    assert changed.status_code == 200, changed.text
    operator = _login(auth_client, operator_username, OPERATOR_PASSWORD)

    # 3. 零权限时连读都不行。
    denied_read = auth_client.get("/api/app/k/products", headers=operator)
    assert denied_read.status_code == 403, denied_read.text

    # 4. owner 只授 read + create（与权限树「保存」发出的请求一致）。
    for key in (K_READ, K_CREATE):
        granted = auth_client.post(
            f"/api/app/permissions/users/{operator_id}/assignments",
            headers=owner,
            json={
                "permission_key": key,
                "reason": "Permission center assignment update.",
                "scope_type": "global",
                "scope_key": "*",
            },
        )
        assert granted.status_code == 201, granted.text

    me = auth_client.get("/api/app/permissions/me", headers=operator)
    assert me.status_code == 200, me.text
    assert set(me.json()["permission_keys"]) == {K_READ, K_CREATE}

    # 5. operator 能建产品。
    created_product = auth_client.post(
        "/api/app/k/products",
        headers=operator,
        json={
            "raw_input_text": "permission tree probe product",
            "category_id": CATEGORY_ID,
            "source_system": "manual",
        },
    )
    assert created_product.status_code == 201, created_product.text
    product_id = created_product.json()["id"]
    product_key = created_product.json().get("product_key") or created_product.json().get("sku")
    assert product_key

    # 6. 删除 / 归档 / 更新全部被后端拦住。
    deleted = auth_client.request(
        "DELETE",
        f"/api/app/k/products/{product_id}",
        headers=operator,
        json={"product_key": product_key},
    )
    assert deleted.status_code == 403, deleted.text
    assert deleted.json()["detail"] == f"Missing permission: {K_ARCHIVE}"

    archived = auth_client.post(
        f"/api/app/k/products/{product_id}/archive",
        headers=operator,
        json={"reason": "probe"},
    )
    assert archived.status_code == 403, archived.text
    assert archived.json()["detail"] == f"Missing permission: {K_ARCHIVE}"

    updated = auth_client.patch(
        f"/api/app/k/products/{product_id}",
        headers=operator,
        json={"raw_input_text": "should not be allowed"},
    )
    assert updated.status_code == 403, updated.text
    assert updated.json()["detail"] == f"Missing permission: {K_UPDATE}"

    # 7. 产品确实还在，并且没被归档。
    still_there = auth_client.get(f"/api/app/k/products/{product_id}", headers=owner)
    assert still_there.status_code == 200, still_there.text
    assert still_there.json()["product_status"] != "archived"
    assert still_there.json()["raw_input_text"] == "permission tree probe product"

    # 8. 数据库里只有 read/create 两行生效，没有 archive 行。
    with SessionLocal() as db:
        rows = [
            (row.permission_key, bool(row.is_enabled))
            for row in db.scalars(
                select(UserPermissionAssignment).where(
                    UserPermissionAssignment.user_id == operator_id
                )
            )
        ]
    enabled_keys = {key for key, enabled in rows if enabled}
    assert enabled_keys == {K_READ, K_CREATE}
    assert all(key != K_ARCHIVE for key, _enabled in rows)


@pytest.mark.integration
def test_super_admin_has_all_feature_keys_and_can_grant_within_own_org_only(
    auth_client: TestClient,
) -> None:
    owner_username, org_id, other_operator_id = _seed_owner_with_org(
        with_second_org=True
    )
    owner = _login(auth_client, owner_username, OWNER_PASSWORD)

    def create_user(username: str, role: str, organization_id: str) -> tuple[int, dict[str, str]]:
        created = auth_client.post(
            "/api/app/users",
            headers=owner,
            json={
                "username": username,
                "role": role,
                "organization_id": organization_id,
                "job_title": "权限树验收",
                "is_active": True,
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        first = auth_client.post(
            "/api/public/auth/login",
            json={"username": username, "password": body["initial_password"]},
        )
        assert first.status_code == 200, first.text
        changed = auth_client.post(
            "/api/public/auth/change-password",
            headers={"x-session-token": first.json()["session_token"]},
            json={
                "current_password": body["initial_password"],
                "new_password": OPERATOR_PASSWORD,
            },
        )
        assert changed.status_code == 200, changed.text
        return body["id"], _login(auth_client, username, OPERATOR_PASSWORD)

    suffix = uuid4().hex[:8]
    super_admin_id, super_admin = create_user(f"pt_sa_{suffix}", "super_admin", org_id)
    operator_id, operator = create_user(f"pt_op_{suffix}", "operator", org_id)

    # 另一个组织里的普通员工已在 seed 阶段直接入库，用来证明跨组织被拒。
    assert other_operator_id > 0

    # 1. 超管对本组织拥有注册表里全部功能键（最高权限）。
    me = auth_client.get("/api/app/permissions/me", headers=super_admin)
    assert me.status_code == 200, me.text
    keys = set(me.json()["permission_keys"])
    assert {K_READ, K_CREATE, K_UPDATE, K_ARCHIVE, "f.enrichment.read"}.issubset(keys)
    k_list = auth_client.get("/api/app/k/products", headers=super_admin)
    assert k_list.status_code == 200, k_list.text

    # 2. 超管能给本组织普通员工授权、列出并撤销。
    granted = auth_client.post(
        f"/api/app/permissions/users/{operator_id}/assignments",
        headers=super_admin,
        json={
            "permission_key": K_READ,
            "reason": "Permission center assignment update.",
            "scope_type": "global",
            "scope_key": "*",
        },
    )
    assert granted.status_code == 201, granted.text
    assignment_id = granted.json()["assignment"]["id"]
    listed = auth_client.get(
        f"/api/app/permissions/users/{operator_id}/assignments", headers=super_admin
    )
    assert listed.status_code == 200, listed.text
    assert [a["permission_key"] for a in listed.json()["assignments"] if a["enabled"]] == [K_READ]
    op_me = auth_client.get("/api/app/permissions/me", headers=operator)
    assert set(op_me.json()["permission_keys"]) == {K_READ}
    revoked = auth_client.request(
        "DELETE",
        f"/api/app/permissions/users/{operator_id}/assignments/{assignment_id}",
        headers=super_admin,
        json={"reason": "Permission center assignment update."},
    )
    assert revoked.status_code == 200, revoked.text

    # 3. 跨组织员工、以及另一位管理员 —— 超管都不能碰。
    cross = auth_client.post(
        f"/api/app/permissions/users/{other_operator_id}/assignments",
        headers=super_admin,
        json={"permission_key": K_READ, "reason": "blocked", "scope_type": "global", "scope_key": "*"},
    )
    assert cross.status_code == 403, cross.text
    self_grant = auth_client.post(
        f"/api/app/permissions/users/{super_admin_id}/assignments",
        headers=super_admin,
        json={"permission_key": K_READ, "reason": "blocked", "scope_type": "global", "scope_key": "*"},
    )
    assert self_grant.status_code == 403, self_grant.text
