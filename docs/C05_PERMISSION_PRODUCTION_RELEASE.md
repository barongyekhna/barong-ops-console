# C05 Permission Production Release

日期：2026-06-11 UTC

本文件记录 C05F：权限系统 production 安全发布和 production 归档验收。

C05F 不是功能开发任务，不是 staging 验收任务，也不是真实业务接入任务。本轮只把
C05B/C05C/C05D/C05E 已完成的权限系统结果安全发布到 production，并完成验收归档。

C05G 已引用本文件作为 C05 production 发布和验收依据，并在
`docs/C05_PERMISSION_SYSTEM_SEAL.md` 中完成 C05 权限系统最终封板。

## 1. C05F 目标

C05F 的目标是把 C05 权限系统发布到 production：

- C05B 权限表 migration。
- C05C 后端权限 dependency、`/auth/me.permissions`、`GET /permissions/me`、
  `GET /permissions/registry`。
- C05D 前端权限感知、导航策略和无权访问提示。
- C05E staging 验收归档结论。

发布和验收严格遵守 OPS01 safe release 治理：

- production 发布使用 `scripts/safe_compose_release.sh`。
- 不使用 `docker-compose down`。
- 不使用 `docker-compose --force-recreate`。
- 不停止、重启、删除或重建 production postgres。
- production 只发布 backend/frontend。
- production DB schema 只通过 production backend 容器内 Alembic `upgrade head`
  应用 migration。
- 不直接连接 production postgres 手工改表。
- 不读取或打印 `.env.production` / `.env.staging`。
- 不打印 secret、token、password 或 Authorization header。
- 不接真实业务。
- 不新增 grant/revoke API 或权限分配页面。
- 不 git commit。

## 2. C05A/B/C/D/E 承接关系

- C05A 完成权限系统现状审计和设计方案。
- C05B 新增 `permission_registry`、`user_permission_assignments`、
  `role_default_permissions` 三张权限表和权限服务地基。
- C05C 接入后端 `require_permission()`、`/auth/me.permissions`、
  `GET /permissions/me`、`GET /permissions/registry`，并保持 `/users` owner-only。
- C05D 接入前端权限感知，business 板块 `show_locked`，admin/system 板块
  `hide_when_denied`，User Management 只对 owner full access 可见。
- C05E 在 staging 完成 backend/frontend safe release、Alembic `upgrade head` 和
  owner/non-owner 验收，确认权限闭环可用。

## 3. 发布前只读预检

发布前只读预检结果：

- `git status --short --untracked-files=all`：clean。
- `git log --oneline -8`：HEAD 为
  `ac41ffd docs: add C05E permission staging acceptance`。
- `ac41ffd` ancestor 检查：通过，当前 HEAD 就是 `ac41ffd`。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。
- `npm run typecheck`：通过。
- `npm run verify`：通过。
- `npm run build`：通过。
- `node --test tests/frontend/permissions.test.mjs`：通过。
- 后端权限最小测试：
  `tests/backend/test_permissions_api.py tests/backend/test_permissions_service.py tests/backend/test_permission_migration.py`
  通过，`17 passed`。
- `git diff --check`：通过。

发布前 production 只读 API 状态：

- 未登录 `/auth/me`：401。
- 未登录 `/permissions/me`：404。
- 未登录 `/permissions/registry`：404。
- 未登录 `/users`：401。
- `/auth/register`：404。
- `/login`：200。

发布前两个 permissions endpoint 为 404，说明 production backend 尚未包含 C05C。

## 4. Production backend release 结果

已执行 production backend safe release：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes \
  ./scripts/safe_compose_release.sh --env production --service backend --execute
```

结果：

- pre-smoke 通过。
- backend image build 通过。
- safe release 只删除并重建目标容器
  `barong-ops-console-prod_console_backend_1`。
- rollback tag 已生成：
  `barong-ops-console-prod_console_backend:rollback-20260611034216`。
- health check `http://127.0.0.1:8000/health` 通过。
- post-smoke 通过。
- 未操作 production postgres 容器。

## 5. Production Alembic migration 结果

已在新的 production backend 容器内执行：

```bash
docker exec -w /app barong-ops-console-prod_console_backend_1 \
  python -m alembic -c backend/alembic.ini upgrade head
```

结果：

- Alembic 执行：
  `Running upgrade f07_core_001 -> c05b_permissions_001, create permission tables`。
- `alembic current`：`c05b_permissions_001 (head)`。
- `alembic heads`：`c05b_permissions_001 (head)`。

本轮没有直接连接 production postgres，没有手工改表，没有停止、重启、删除或重建
production postgres。

## 6. Production frontend release 结果

已执行 production frontend safe release。首次 release 后发现 frontend proxy allowlist
没有放行 C05C 的两个只读 permissions 路径：

- `GET /api/backend/permissions/me`
- `GET /api/backend/permissions/registry`

当时 production backend 直连已正确返回 401，但 frontend proxy 仍返回 404。为完成 C05F
外部 API 验收，本轮做了最小集成修复：

- `frontend/src/app/api/backend/[...path]/route.ts` 放行上述两个 GET permissions 路径。
- `frontend/scripts/verify-foundation.mjs` 增加防回归检查。

该修复没有新增 grant/revoke API，没有新增权限分配页面，没有改变后端权限模型。

修复后重新执行 production frontend safe release：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes \
  ./scripts/safe_compose_release.sh --env production --service frontend --execute
```

最终结果：

- pre-smoke 通过。
- frontend image build、verify、typecheck、Next build 均通过。
- safe release 只删除并重建目标容器
  `barong-ops-console-prod_console_frontend_1`。
- final rollback tag 已生成：
  `barong-ops-console-prod_console_frontend:rollback-20260611043513`。
- health check `https://ops.barongyekhna.com/login` 通过。
- post-smoke 通过。
- 未操作 production postgres 容器。

## 7. Production API 验收结果

owner 验收使用 production backend 容器运行时配置登录。未读取真实 env 文件，未输出
password、token 或 Authorization header。

frontend proxy 和 backend 直连的 owner 验收结果一致：

- owner login：200。
- owner `GET /auth/me`：200。
- `/auth/me` 包含 `permissions`：是。
- `/auth/me.permissions.is_owner_full_access`：`true`。
- `/auth/me.permissions.permission_keys` 包含 wildcard：是。
- owner `GET /permissions/me`：200。
- `/permissions/me.permissions.is_owner_full_access`：`true`。
- `/permissions/me.permissions.permission_keys` 包含 wildcard：是。
- owner `GET /permissions/registry`：200。
- `/permissions/registry` 返回 list response 结构，`items` 为数组，`count` 为整数。
- owner `GET /users`：200。
- `/users` 返回 list response 结构，未泄漏 `password_hash`。
- owner 响应未泄漏 `password`、`password_hash`、`token`、`secret`、`access_token`
  字段。

未登录和注册边界：

- 未登录 `GET /api/backend/auth/me`：401。
- 未登录 `GET /api/backend/permissions/me`：401。
- 未登录 `GET /api/backend/permissions/registry`：401。
- 未登录 `GET /api/backend/users`：401。
- `GET /api/backend/auth/register`：404。

说明：C05C 不在 app startup 自动 seed `permission_registry`，也不在 registry route
隐式 seed。production `/permissions/registry` 本轮验收重点是 route、认证和响应结构可用。

## 8. Production frontend 权限 UI 验收结果

frontend 验收结果：

- production `/login` 页面返回 200。
- production `/users` 页面返回 200。
- owner 通过 production frontend proxy `GET /auth/me` 返回 permissions。
- owner permissions 为 full access，且包含 wildcard。
- 使用 C05D 前端权限 helper 验证 owner permissions 后：
  - `frontend_user_management_visible=true`。
  - `frontend_user_management_can_access=true`。
  - `frontend_user_management_locked=false`。

当前执行环境没有 Chromium/Playwright 浏览器工具，因此没有做真实浏览器 DOM 截图验收。
本轮使用 production frontend proxy 动态认证结果和 C05D helper 验证 User Management 对 owner
可见可访问。

## 9. `/users` 仍 owner-only

生产验收确认：

- owner `GET /users`：200。
- 未登录 `GET /users`：401。
- `/users` 响应不返回 `password_hash`。

本轮没有把 `/users` 从 `require_owner()` 改成 `require_permission("users.manage")`。
User Management 后端真实安全边界仍是 owner-only。前端 User Management 也仍只对
`permissions.is_owner_full_access=true` 的 owner 可见。

## 10. Non-owner production 验收说明

本轮没有创建 production non-owner 测试账号。

原因：

- C05F 是 production 发布归档，不创建生产测试账号。
- 没有使用现成 non-owner production 账号和密码。
- 不读取或打印真实 env。
- 不产生真实业务或账号数据。

non-owner 动态验收已在 C05E staging 完成。production 本轮只记录 non-owner 动态验证未执行，
原因是没有现成可用账号且禁止创建 production 测试账号。

## 11. Smoke 和状态检查

发布后最终检查：

- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。

dual env 最终状态：

- production frontend：`127.0.0.1:3000->3000/tcp`。
- production backend：`127.0.0.1:8000->8000/tcp`。
- production postgres：healthy，只暴露 Docker 内网 `5432/tcp`。
- staging frontend：`127.0.0.1:3100->3000/tcp`。
- staging backend：`127.0.0.1:8100->8000/tcp`。
- staging postgres：healthy，只暴露 Docker 内网 `5432/tcp`。
- host port `5432` 未监听。

staging smoke 通过，说明 staging 未受 production 发布影响。

## 12. 本轮没有做什么

本轮没有：

- 没有发布 staging。
- 没有操作 production postgres 容器。
- 没有停止、重启、删除或重建 production postgres。
- 没有直接连接 production postgres 手工改表。
- 没有读取或打印 `.env.production`。
- 没有读取或打印 `.env.staging`。
- 没有打印 secret、token、password 或 Authorization header。
- 没有创建 production 测试账号。
- 没有接 WooCommerce、n8n 真实业务流、MinIO、Filebrowser 或产品页业务模块。
- 没有创建真实业务任务。
- 没有新增 grant/revoke API。
- 没有新增 grant/revoke 权限管理页面。
- 没有做权限分配页面。
- 没有 git commit。

## 13. C05F 结论

C05F production 发布归档通过。

结论：

- production backend 已发布到 C05 权限系统代码。
- production Alembic 已升级到 `c05b_permissions_001 (head)`。
- production frontend 已发布到 C05 权限系统代码，并补齐 permissions proxy allowlist。
- production `/auth/me` 已返回 permissions。
- production `/permissions/me` 可用。
- production `/permissions/registry` 可用。
- owner full access 和 wildcard 已验证。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- production smoke 通过。
- staging smoke 通过。
- dual env status 通过。
- safe release plan 通过。
- staging 未受影响。
- 未接真实业务。

下一步：C05G 已完成 C05 权限系统封板，记录见
`docs/C05_PERMISSION_SYSTEM_SEAL.md`。后续进入 C06 或 C18/业务模块接入前置规划，不进入
P 系列，不在 C05G 中接真实业务。
