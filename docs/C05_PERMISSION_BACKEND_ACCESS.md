# C05 Permission Backend Access

日期：2026-06-10 UTC

本文件记录 C05C：后端权限 dependency、`/auth/me.permissions` 合同和只读
permissions API。

C05C 只做后端权限判断、当前用户权限返回、只读权限目录 API 和测试。不做前端 UI，不做权限管理页面，
不部署 staging/production，不接真实业务。

## 只读审计结论

### 当前 `/auth/me`

`GET /auth/me` 在 `backend/app/api/routes/auth.py`。C05C 之前它返回
`AuthenticatedUser`：

- `id`
- `username`
- `role`
- `is_active`
- `last_login_at`

当前 `users` 表和 auth schema 没有 `email` 字段，所以 C05C 不新增 `email`。
`UserResponse` 用于 `/users`，字段是 `id`、`username`、`role`、`is_active`、
`last_login_at`、`created_at`、`updated_at`。

C05C 适合在 `/auth/me` 上追加 `permissions`，因为旧字段保持原样，前端读取旧字段不会失效。
为了不改变 login response，C05C 新增 `AuthenticatedUserWithPermissions`，只用于
`GET /auth/me`；`POST /auth/login` 里的 `user` 仍使用原 `AuthenticatedUser`。

### 当前 dependency

`get_current_user()` 在 `backend/app/api/deps.py` 中校验 Bearer token、token secret、
token `sub`、token role 与数据库 role 一致、用户存在且 `is_active=true`。

`require_owner()` 依赖 `get_current_user()`，然后用 `is_owner_role(user.role)` 判断 owner。
不是 owner 时返回 403：`Owner role required.`

C05C 新增的 `require_permission()` 与 `require_owner()` 并列存在，不修改
`require_owner()`，因此不会破坏当前 `/users`。

### 当前 route 注册方式

当前 FastAPI app 在 `backend/app/main.py` 中逐个 import router，并调用
`app.include_router(...)`。C05C 按同一风格新增
`backend/app/api/routes/permissions.py`，注册：

- `GET /permissions/me`
- `GET /permissions/registry`

## `require_permission()` 用法

位置：`backend/app/api/deps.py`

用法示例：

```python
from fastapi import Depends

from ..deps import require_permission


def route(
    user = Depends(require_permission("jobs.read")),
):
    ...


def scoped_route(
    user = Depends(
        require_permission(
            "jobs.read",
            scope_type="company",
            scope_key="independent_site",
        )
    ),
):
    ...
```

行为：

- 未登录仍由 `get_current_user()` 返回 401。
- `role=owner` 在 dependency 层直接通过，不查询 assignment，不受 scope 限制。
- 非 owner 调用 `PermissionService.user_has_permission()`。
- 非 owner 只有 enabled、未过期、permission registry enabled、scope 匹配的
  `user_permission_assignments` 才能通过。
- 无权限返回 403，detail 形如 `Missing permission: users.manage`。
- `super_admin` 不特殊处理，不默认全局全权限。

## Owner wildcard 规则

Owner 是全局最高权限者：

- 拥有所有公司、所有工厂、所有组织、所有板块、所有权限。
- 不需要逐条 `user_permission_assignments`。
- 不受 `scope_type` / `scope_key` 限制。

C05C 的 API 合同对 owner 使用 wildcard：

```json
{
  "is_owner_full_access": true,
  "permission_keys": ["*"],
  "assignments": [],
  "scope_summary": []
}
```

这样 owner 的 `/auth/me` 和 `/permissions/me` 不依赖 registry 是否已经 seed。
C05B 的底层 `resolve_effective_permissions()` 仍可列出当前 registry 权限点，供服务层测试和后续管理端使用。

## `/auth/me.permissions`

C05C 后 `GET /auth/me` 保留旧字段，并追加：

```json
{
  "id": 1,
  "username": "owner",
  "role": "owner",
  "is_active": true,
  "last_login_at": null,
  "permissions": {
    "is_owner_full_access": true,
    "permission_keys": ["*"],
    "assignments": [],
    "scope_summary": []
  }
}
```

非 owner 只返回 explicit assignment 生效后的权限：

```json
{
  "permissions": {
    "is_owner_full_access": false,
    "permission_keys": ["artifacts.read", "jobs.read"],
    "assignments": [
      {
        "permission_key": "jobs.read",
        "scope_type": "global",
        "scope_key": "*"
      }
    ],
    "scope_summary": [
      {
        "scope_type": "global",
        "scope_key": "*",
        "permission_keys": ["artifacts.read", "jobs.read"]
      }
    ]
  }
}
```

`role_default_permissions` 不会自动进入 `permission_keys`、`assignments` 或
`scope_summary`。

响应不返回 `password_hash`，不返回 token、secret、password。

## `/permissions/me`

`GET /permissions/me` 当前登录用户可访问，用于查看自己的 effective permissions。

返回结构：

```json
{
  "user_id": 1,
  "role": "owner",
  "permissions": {
    "is_owner_full_access": true,
    "permission_keys": ["*"],
    "assignments": [],
    "scope_summary": []
  }
}
```

Owner 返回 wildcard。非 owner 返回 enabled、未过期、scope 生效的 assignment。

## `/permissions/registry`

`GET /permissions/registry` 是只读权限目录 API。

访问规则：

- owner 直接可访问。
- 非 owner 必须拥有 `permissions.read`。
- 无 `permissions.read` 返回 403。

返回现有 enabled `permission_registry` 列表，使用项目现有 `ListResponse` 包装：

```json
{
  "items": [],
  "count": 0,
  "limit": 100,
  "offset": 0
}
```

C05C 不在 app startup 自动写库，也不在 registry route 隐式 seed。测试和后续明确管理流程可以调用
`upsert_permission_registry()`，该 helper 是幂等的。

## 为什么 `/users` 仍 owner-only

C05C 的目标是接入权限 dependency 和只读权限合同，不改变真实业务或管理行为。

当前 `/users` 全部路由仍使用 `require_owner()`：

- `GET /users`
- `POST /users`
- `GET /users/roles`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`
- `POST /users/{user_id}/reset-password`
- `POST /users/{user_id}/disable`
- `POST /users/{user_id}/enable`

C05D 已承接前端权限感知，但没有把 `/users` 从 owner-only 升级到 `users.manage`。原因是后端
真实安全边界仍是 `require_owner()`；前端不能提前让普通 `users.manage` 非 owner 看到 User
Management。后续如需改变 `/users` 授权，必须作为 C06 或独立后端任务处理。

## 为什么 role defaults 暂不自动生效

`role_default_permissions` 是建议模板，不是授权事实。

C05C 继续保证：

- `super_admin` 不因为 role default 获得全局权限。
- `viewer`、`operator`、`reviewer` 不因为 role default 自动获权。
- 非 owner 的有效权限只来自 `user_permission_assignments`。

后续权限管理 UI 可以把 role defaults 作为创建 assignment 的建议，但必须由 owner 或被授权管理者明确确认。

## C05D 承接说明

C05D 已做：

- 前端读取 `/auth/me.permissions`，但仍以后端 403 作为安全边界。
- 企业管理菜单按权限隐藏，业务板块无权限显示清晰提示。
- User Management 前端入口只在 owner full access 时可见。
- 普通非 owner 即使拥有 `users.manage` assignment，C05D 也不显示 `/users` 入口，因为后端
  `/users` 仍是 owner-only。

C05D 没有做：

- 没有把 `/users` 从 `require_owner()` 升级为 `require_permission("users.manage")`。
- 没有决定 `GET /users/roles` 使用 `roles.read` 还是 `users.manage`。
- 没有增加权限管理 UI 或 grant/revoke API。
- 没有部署 staging 或 production。

后续如果要开放 User Management，必须先做后端任务并完成 staging 验收。

## C05E staging 验收

C05E 已在 staging 完成权限后端联调验收，记录见
`docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`。

验收结论：

- staging backend 已通过 OPS01 safe release 使用当前 C05B/C05C 代码。
- staging Alembic 当前版本为 `c05b_permissions_001 (head)`。
- owner `GET /auth/me` 返回 `permissions`，且
  `is_owner_full_access=true`、`permission_keys=["*"]`。
- owner `GET /permissions/me` 返回 wildcard full access。
- owner `GET /permissions/registry` 返回 200 和 list response 结构。
- 临时 staging-only `viewer` non-owner 无 wildcard、无 assignment。
- non-owner `GET /permissions/me` 返回 200，`is_owner_full_access=false`。
- non-owner `GET /permissions/registry` 返回 403，因为没有 `permissions.read`。
- non-owner `GET /users` 返回 403，确认 `/users` 仍是后端 owner-only。
- 未登录 `/auth/me`、`/permissions/me`、`/users` 均返回 401。
- `/auth/register` 仍返回 404。
- 本轮未新增 grant/revoke API，未新增权限管理 UI，未发布 production，未接真实业务。

## 安全边界

C05C 不做这些事：

- 不读取或修改真实 `.env.production` / `.env.staging`。
- 不创建 production/staging 真实用户。
- 不操作 production/staging 数据库真实数据。
- 不部署 staging 或 production。
- 不修改前端 UI。
- 不新增 grant/revoke API。
- 不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 不创建真实业务任务。
- 不执行 git commit。
