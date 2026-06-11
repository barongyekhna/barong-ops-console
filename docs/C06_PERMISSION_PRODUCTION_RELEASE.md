# C06 Permission Production Release

日期：2026-06-11 UTC

本文件记录 C06E：production 权限管理安全发布和归档验收。

C06E 的目标是把 C06B 后端 owner-only permission assignment API 和 C06C 前端
User Management 权限管理 UI 安全发布到 production，并完成只读为主的 production
验收归档。C06E 不是功能开发任务，不接 WooCommerce、n8n 真实业务流、MinIO、
Filebrowser、产品页业务模块或 P 系列。

## 1. 发布范围

发布内容：

- production backend：包含 C06B
  `/permissions/users/{user_id}/assignments` owner-only list/grant/update/revoke
  API。
- production frontend：包含 C06C User Management 内“权限”入口和“用户权限管理”
  UI。

未发布内容：

- 不发布 staging。staging 只做 smoke/status 只读验证。
- 不发布 postgres。
- 不新增 migration。
- 不接真实业务。

## 2. 发布前预检

发布前只读预检结果：

- `git status --short --untracked-files=all`：clean。
- `git log --oneline -12`：HEAD 为
  `ba11f2e docs: add C06D permission staging acceptance`。
- 当前 HEAD 包含 C06D。
- `frontend npm run verify`：通过。
- `frontend npm run typecheck`：通过。
- `frontend npm run build`：通过。
- `node --test tests/frontend/permissions.test.mjs`：通过。
- `node --test tests/frontend/permission-management.test.mjs`：通过。
- C06B backend assignment API Docker 测试
  `tests/backend/test_permission_assignments_api.py`：通过，`7 passed`。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。
- `git diff --check`：通过。
- production Alembic 只读检查：
  `current` 和 `heads` 均为 `c05b_permissions_001 (head)`。

发布前 production 只读探测：

- backend 直连 `GET /permissions/users/1/assignments` 未登录返回 `404`，
  说明 production backend 尚未包含 C06B。
- frontend `/users` 返回 `200`。
- production C06C bundle marker 未找到，说明 production frontend 尚未包含 C06C。
- 未登录 `/auth/me`、`/permissions/me`、`/users` 返回 `401`。
- `/auth/register` 返回 `404`。

## 3. Production backend release

已按 OPS01 safe release 执行 production backend release：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes \
  ./scripts/safe_compose_release.sh --env production --service backend --execute
```

结果：

- pre-smoke 通过。
- backend image build 通过。
- safe release 只删除并重建目标容器
  `barong-ops-console-prod_console_backend_1`。
- rollback tag：
  `barong-ops-console-prod_console_backend:rollback-20260611095626`。
- health check `http://127.0.0.1:8000/health` 通过。
- post-smoke 通过。
- 未操作 production postgres 容器。

## 4. Production frontend release

已按 OPS01 safe release 执行 production frontend release：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes \
  ./scripts/safe_compose_release.sh --env production --service frontend --execute
```

结果：

- pre-smoke 通过。
- frontend image build、`npm run verify`、`npm run typecheck`、`next build` 均通过。
- safe release 只删除并重建目标容器
  `barong-ops-console-prod_console_frontend_1`。
- rollback tag：
  `barong-ops-console-prod_console_frontend:rollback-20260611095830`。
- health check `https://ops.barongyekhna.com/login` 通过。
- post-smoke 通过。
- 未操作 production postgres 容器。

## 5. Alembic / DB

C06B/C06C 没有新增 migration。C06E 未执行 production Alembic upgrade。

production Alembic 只读结果：

- `alembic current`：`c05b_permissions_001 (head)`。
- `alembic heads`：`c05b_permissions_001 (head)`。

本轮没有直接连接 production postgres，没有 psql，没有手写 SQL，没有新增 migration，
没有停止、重启、删除或重建 production postgres。

## 6. Permission registry seed

发布后 owner `GET /permissions/registry` 首次验收返回：

- status：`200`。
- `items`：数组。
- `count=0`。

按 C06E 边界，本轮立即暂停，没有擅自 seed，没有 psql，没有查 DB，没有写 DB。随后老板
单独批准一次性初始化 production `permission_registry` seed，限定只能在 production
backend 容器内通过现有后端应用层 helper `upsert_permission_registry()` 执行。

已执行：

- 在 `barong-ops-console-prod_console_backend_1` 内调用现有
  `upsert_permission_registry()`。
- helper 返回 `permission_registry_seed_upsert_count=18`。
- seed 包含普通权限 `jobs.read`。
- seed 包含 high-risk 权限 `permissions.manage`。

本次 seed 只写入 `permission_registry` 系统权限点，没有写
`user_permission_assignments`，没有写 `role_default_permissions`，没有 grant/update/revoke
任何 production 用户权限，没有创建 production 测试账号。

## 7. Owner API 验收

owner 验收使用 production backend 容器运行时配置登录。未读取 `.env.production` 或
`.env.staging` 文件，未输出 password、token、secret 或 Authorization header。

backend 直连验收：

- owner login：`200`。
- owner `GET /auth/me`：`200`。
- `/auth/me` 包含 `permissions`：是。
- `/auth/me.permissions.is_owner_full_access`：`true`。
- `/auth/me.permissions.permission_keys` 包含 wildcard：是。
- owner `GET /permissions/me`：`200`。
- `/permissions/me.permissions.is_owner_full_access`：`true`。
- `/permissions/me.permissions.permission_keys` 包含 wildcard：是。
- owner `GET /permissions/registry`：`200`。
- `/permissions/registry.items` 为数组：是。
- `/permissions/registry.count=18`。
- registry 非空：是。
- registry 包含普通权限 `jobs.read`：是。
- registry 包含 high-risk 权限：是。
- owner `GET /permissions/users/{owner_id}/assignments`：`200`。
- assignment list 返回数组：是。
- owner target `is_owner_full_access=true`：是。
- assignment list 合理为空：`count=0`。
- owner `GET /users`：`200`。
- `/users.items` 为数组：是。
- `/users` count：`1`。
- `/users` 未泄漏 `password_hash`：是。

frontend proxy 验收：

- owner `GET /api/backend/auth/me`：`200`。
- owner `GET /api/backend/permissions/me`：`200`。
- owner `GET /api/backend/permissions/registry`：`200`。
- registry 非空：是。
- owner `GET /api/backend/permissions/users/{owner_id}/assignments`：`200`。
- owner `GET /api/backend/users`：`200`。
- proxy `/users` 未泄漏 `password_hash`：是。

未登录和注册边界：

- backend 未登录 `GET /auth/me`：`401`。
- backend 未登录 `GET /permissions/me`：`401`。
- backend 未登录 `GET /users`：`401`。
- backend `GET /auth/register`：`404`。
- proxy 未登录 `GET /api/backend/auth/me`：`401`。
- proxy 未登录 `GET /api/backend/permissions/me`：`401`。
- proxy 未登录 `GET /api/backend/users`：`401`。
- proxy `GET /api/backend/auth/register`：`404`。

## 8. Frontend C06C UI 验收

production frontend 验收：

- production `/login`：production smoke 通过。
- production `/users`：`200`。
- production `/users` linked JS bundle 包含 C06C marker。
- matched marker：`C06C permissions`。
- matched script：`_next/static/chunks/01c0972jz5tri.js`。
- owner 通过 frontend proxy 可读取 `/auth/me`、`/permissions/registry`、
  `/permissions/users/{owner_id}/assignments` 和 `/users`。

本机没有 Chromium/Google Chrome，Node 环境也没有 Playwright 包，因此没有执行真实浏览器
DOM 截图验收。本轮使用 production `/users` 页面、published JS bundle marker、owner
frontend proxy API 和本地前端测试共同确认 C06C UI 已进入 production。

User Management 仍仅 owner 可见：

- 前端 `/users` 仍是 owner-only route。
- C06C 权限入口只在 owner-only User Management 内显示。
- `/users` 后端仍使用 `require_owner()`，不是 `require_permission("users.manage")`。
- 前端只是 UX；后端 owner-only API 才是安全边界。

## 9. Non-owner / 写入型动态验证

C06E production 没有执行 non-owner 动态 grant/update/revoke 验证。

原因：

- 没有老板明确指定的 production non-owner 测试账号。
- C06E 禁止创建 production 测试账号。
- C06E 禁止重置 production 用户密码。
- C06E 禁止修改已有 production 用户权限 assignment，除非另行明确批准。
- 避免污染 production 权限数据。

non-owner 和写入型动态验证已在 C06D staging 完整通过。C06E production 仅做 owner
只读验收、registry seed 初始化和边界验证。

## 10. operation_logs

C06E production 没有执行 grant/update/revoke，因此没有新增 production
`permission.assignment.*` operation log 写入验收。

operation_logs 写入已在 C06D staging 动态验收通过：

- `permission.assignment.grant`
- `permission.assignment.update`
- `permission.assignment.revoke`
- 普通和 high-risk 成功/失败路径

C06E 避免在 production 写入 assignment 变更，避免污染正式权限数据。

## 11. 保留边界

C06E 保留以下边界：

- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认拥有 grant/revoke。
- C06B assignment API 仍使用 `require_owner()`。
- 前端权限管理只是 UX，不能替代后端 owner-only 安全边界。
- 未创建 production 测试账号。
- 未重置 production 用户密码。
- 未执行 production grant/update/revoke 动态写入验收。
- 未读取 `.env.production` 或 `.env.staging`。
- 未打印 secret、token、password 或 Authorization header。
- 未操作 production postgres 容器。
- 未直接操作 production DB。
- 未发布 staging。
- 未接真实业务。
- 未进入 P 系列。
- 未 git commit。

## 12. Smoke / status

发布后和 seed 后均完成只读检查：

- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。

dual env 状态：

- production frontend：`127.0.0.1:3000->3000/tcp`。
- production backend：`127.0.0.1:8000->8000/tcp`。
- production postgres：healthy，只暴露 Docker 内网 `5432/tcp`。
- staging frontend：`127.0.0.1:3100->3000/tcp`。
- staging backend：`127.0.0.1:8100->8000/tcp`。
- staging postgres：healthy，只暴露 Docker 内网 `5432/tcp`。
- host port `5432` 未监听。

staging smoke 通过，说明 staging 未受 production 发布影响。

## 13. 结论

C06E production 发布归档通过。

结论：

- production backend 已发布包含 C06B 的当前代码。
- production frontend 已发布包含 C06C 的当前代码。
- production `/permissions/users/{user_id}/assignments` owner 可访问。
- production User Management 中 C06C 权限管理 UI bundle/marker 存在。
- production owner 可查看 permission registry。
- production registry 初始为空；经老板单独批准，已通过后端应用层 helper 初始化
  `permission_registry` seed，count 为 18。
- production owner 可打开 User Management 对应 API 和页面。
- `/users` 后端仍 owner-only。
- `/auth/register` 仍 404。
- 未登录 `/auth/me`、`/permissions/me`、`/users` 仍 401。
- non-owner production 动态验证未执行，原因是无明确测试账号且禁止创建/污染生产数据。
- production grant/update/revoke 动态写入验收未执行，C06D staging 已完整验证。
- production smoke、staging smoke、dual env status、safe release plan 均通过。
- staging 未受影响。
- 未接真实业务。
- C06F 已完成 C06 用户权限管理封板，见
  `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`。

C06E production 发布归档结果已纳入 C06F 最终封板归档。
