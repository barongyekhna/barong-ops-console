# C05 Permission Staging Acceptance

日期：2026-06-11 UTC

本文件记录 C05E：权限系统在 staging 环境的联调验收结果。

C05E 只做 staging 验收和归档。它不新增业务功能，不新增 grant/revoke API，不新增
权限分配 UI，不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或产品页业务模块，
也不发布 production。

C05G 已引用本文件作为 C05 staging 验收依据，并在
`docs/C05_PERMISSION_SYSTEM_SEAL.md` 中完成 C05 权限系统最终封板。

## 1. 验收目标

C05E 验证 C05B/C05C/C05D 的权限系统闭环：

- C05B 权限表 migration 已进入 staging。
- C05C 后端 `/auth/me.permissions`、`GET /permissions/me`、
  `GET /permissions/registry` 在 staging 可用。
- C05D 前端权限感知、导航策略和无权访问提示符合设计。
- `/users` 后端仍保持 owner-only。
- 普通 non-owner 用户没有 wildcard 权限，不能访问 `/users`。
- 前端权限只作为 UX，真实安全边界仍以后端 401/403 为准。

## 2. C05A/B/C/D 承接关系

- C05A 完成权限系统审计和设计方案，记录 role、permission、scope、
  assignment 的分工。
- C05B 新增 `permission_registry`、`user_permission_assignments`、
  `role_default_permissions` 三张权限表和服务层权限查询地基。
- C05C 接入 `require_permission()`、`/auth/me.permissions`、
  `GET /permissions/me` 和 `GET /permissions/registry`，并保持 `/users`
  owner-only。
- C05D 接入前端权限感知：business 板块 `show_locked`，admin/system
  板块 `hide_when_denied`，直接访问无权页面显示“无权访问此板块”，
  User Management 只对 owner full access 可见。

## 3. 发布和 migration 状态

只读探测发现 staging 发布前：

- `GET http://127.0.0.1:8100/permissions/me` 返回 `404`。
- `GET http://127.0.0.1:8100/permissions/registry` 返回 `404`。

这说明 staging 尚未包含 C05C 当前后端路由，因此 C05E 按批准执行了 staging
backend/frontend 安全发布。

执行范围：

- 已执行 staging backend safe release。
- 已在 staging backend 容器内执行 Alembic `upgrade head`。
- 已执行 staging frontend safe release。
- Alembic 当前版本确认为 `c05b_permissions_001 (head)`。

未执行事项：

- 未发布 production。
- 未操作 production 容器或 production 数据库。
- 未停止、重启、删除或重建 staging postgres 容器。
- 未直接连接或操作 staging postgres。
- 未读取或打印 `.env.staging` / `.env.production`。
- 未执行 `docker-compose down`。
- 未接真实业务。
- 未新增 grant/revoke API 或 UI。
- 未 git commit。

## 4. Owner API 验收

owner 验收使用 staging backend 容器运行时配置登录。未读取真实 env 文件，未输出
password、token 或 Authorization header。

结果：

- owner login：`200`。
- owner `GET /auth/me`：`200`。
- `/auth/me` 包含 `permissions`：是。
- `/auth/me.permissions.is_owner_full_access`：`true`。
- `/auth/me.permissions.permission_keys`：`["*"]`。
- `/auth/me` 未泄漏 `password`、`password_hash`、`token`、`secret`、
  `access_token` 字段。
- owner `GET /permissions/me`：`200`。
- `/permissions/me.permissions.is_owner_full_access`：`true`。
- `/permissions/me.permissions.permission_keys`：`["*"]`。
- owner `GET /permissions/registry`：`200`，返回 `items` 数组和 `count`
  整数字段。
- owner `GET /users`：`200`，响应为 list 结构，未泄漏 `password_hash`。

说明：C05C 不在 app startup 自动 seed `permission_registry`，也不在 registry
route 隐式 seed。C05E 验证的是 staging route、认证、响应结构和 owner wildcard
合同可用。

## 5. Non-owner API 验收

按老板批准，本轮通过 owner-only `/users` API 在 staging 创建了一个临时
staging-only `viewer` 测试账号，账号名前缀为 `c05e_non_owner_`。

创建边界：

- 只创建一个临时普通测试账号。
- role 使用 `viewer`。
- 未授予任何 permission assignment。
- 未重置或修改已有 non-owner 用户。
- 未打印测试账号 password、token 或 Authorization header。

结果：

- 临时 viewer 创建：`201`。
- 创建响应 role：`viewer`。
- 创建响应 `is_active`：`true`。
- 创建响应未泄漏 `password_hash`。
- non-owner 通过 staging frontend proxy `/api/backend/auth/login` 登录：`200`。
- non-owner 通过 staging frontend proxy `GET /api/backend/auth/me`：`200`。
- frontend proxy `/auth/me` 包含 `permissions`：是。
- frontend proxy `/auth/me.role`：`viewer`。
- frontend proxy `/auth/me.permissions.is_owner_full_access`：`false`。
- frontend proxy `/auth/me.permissions.permission_keys` 不包含 `*`。
- frontend proxy `/auth/me.permissions.permission_keys` 数量：`0`。
- non-owner 直接访问 staging backend `GET /auth/me`：`200`。
- backend `/auth/me.permissions.is_owner_full_access`：`false`。
- backend `/auth/me.permissions.permission_keys` 不包含 `*`。
- backend `/auth/me.permissions.permission_keys` 数量：`0`。
- non-owner `GET /permissions/me`：`200`。
- `/permissions/me.permissions.is_owner_full_access`：`false`。
- `/permissions/me.permissions.permission_keys` 不包含 `*`。
- `/permissions/me.permissions.permission_keys` 数量：`0`。
- `/permissions/me.permissions.assignments` 数量：`0`。
- non-owner `GET /permissions/registry`：`403`，因为没有 `permissions.read`。
- non-owner `GET /users`：`403`。
- 以上 non-owner 响应均未泄漏 `password_hash`。

结论：

- non-owner 没有 owner wildcard。
- role 本身不会自动放权。
- `role_default_permissions` 不会自动成为 effective permissions。
- `/users` 后端仍 owner-only。
- `/permissions/registry` 对非 owner 仍由 `permissions.read` 保护。

## 6. 前端权限 UX 验收

当前执行环境没有可用的 Chromium/Playwright 浏览器工具，因此 C05E 做了两层前端验收：

- 通过 staging frontend proxy 完成 non-owner 登录和 `/auth/me` 动态请求，确认
  staging frontend 能读取当前用户 permissions。
- 使用 C05D 前端权限 helper 对 non-owner 的空权限响应做导航和 route guard 决策验证。

helper 验证结果：

- `frontend_user_management_visible=false`。
- `frontend_user_management_can_access=false`。
- `frontend_business_jobs_visible=true`。
- `frontend_business_jobs_locked=true`。
- `frontend_admin_modules_visible=false`。
- `frontend_direct_users_denied_notice_expected=true`。
- `frontend_direct_jobs_denied_notice_expected=true`。

结论：

- User Management 对 non-owner 隐藏。
- admin/system 模块无权限时隐藏入口。
- business 模块无权限时保持可见但 locked。
- 直接访问无权路由时会显示“无权访问此板块”。
- 前端只是 UX；后端 403 仍是 `/users` 和 `/permissions/registry` 的真实安全边界。

## 7. 未登录和注册边界

发布和 non-owner 验收后再次确认：

- 未登录 `GET /auth/me`：`401`。
- 未登录 `GET /permissions/me`：`401`。
- 未登录 `GET /users`：`401`。
- `POST /auth/register`：`404`。

## 8. Smoke 和状态检查

C05E 执行和复核的检查结果：

- `git status --short --untracked-files=all`：验收前为 clean；文档更新前仍为 clean。
- `git log --oneline -5`：HEAD 为 `f302926 feat: add C05D frontend permission access`。
- `npm run typecheck`：通过。
- `npm run build`：通过。
- `npm run verify`：通过。
- `node --test tests/frontend/permissions.test.mjs`：通过。
- 后端权限最小测试：
  `tests/backend/test_permissions_api.py tests/backend/test_permissions_service.py tests/backend/test_permission_migration.py`
  通过，`17 passed`。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。
- `git diff --check`：发布前通过；文档完成后再次复跑通过。

发布后状态：

- staging frontend 运行在 `127.0.0.1:3100`。
- staging backend 运行在 `127.0.0.1:8100`。
- staging postgres healthy，只暴露 Docker 内网 `5432/tcp`。
- production frontend/backend/postgres 仍运行且 smoke 通过。
- production postgres 未暴露宿主机 `5432`。

## 9. 安全边界结论

C05E 已确认：

- 没有读取或打印 `.env.staging`。
- 没有读取或打印 `.env.production`。
- 没有打印 password、token、secret 或 Authorization header。
- 没有操作 production 数据库。
- 没有操作 production 容器。
- 没有发布 production。
- 没有停止、重启、删除或重建 staging postgres 容器。
- 没有直接操作 staging postgres。
- 仅通过批准的 Alembic migration 修改 staging schema。
- 仅通过批准的 owner-only `/users` API 创建一个 staging-only viewer 测试账号。
- 没有授予任何 permission assignment。
- 没有接真实业务。
- 没有新增 grant/revoke 权限管理页面。
- 没有新增 grant/revoke API。
- 没有 git commit。

## 10. C05E 结论

C05E staging 联调验收通过。

通过项：

- staging backend/frontend 已使用当前 C05B/C05C/C05D 代码完成联调。
- staging 权限 migration 已应用到 `c05b_permissions_001 (head)`。
- `/auth/me` 在 staging 返回 permissions 字段。
- `GET /permissions/me` 在 staging 可用。
- `GET /permissions/registry` 在 staging 可用。
- owner 返回 full access wildcard。
- owner 可访问 `/users`。
- non-owner 无 wildcard，无 assignment。
- non-owner 不能访问 `/users`。
- non-owner 不能读取 `/permissions/registry`。
- User Management 对 non-owner 隐藏。
- 业务模块对无权限用户为 locked / 无权访问提示策略。
- admin/system 模块无权限时隐藏入口。
- `/users` 后端仍 owner-only。
- `super_admin` 不默认全局权限的规则由本地后端权限测试覆盖。
- `role_default_permissions` 不自动生效的规则由本地后端权限测试和本轮 viewer 空权限响应共同覆盖。
- production 未发布且 smoke 通过。

未做项：

- 未做 grant/revoke 权限管理页面。
- 未做 grant/revoke API。
- 未接真实业务模块。
- 未发布 production。
- 未验证“有 explicit business permission 的 non-owner 可访问业务模块”，因为本轮边界明确测试账号不授予任何额外 permission assignment。

下一步：

- C05F：production 发布归档已经完成，记录见
  `docs/C05_PERMISSION_PRODUCTION_RELEASE.md`。C05F 按 OPS01 safe release 机制发布
  production backend/frontend，并在 production backend 容器内执行 Alembic `upgrade head`。
- C05G：C05 权限系统封板已完成，记录见
  `docs/C05_PERMISSION_SYSTEM_SEAL.md`。C05G 只归档最终安全边界、未做范围和后续业务模块
  接入规则，不进入 P 系列，不接真实业务。
