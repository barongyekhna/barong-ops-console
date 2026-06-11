# C06D Permission Staging Acceptance

日期：2026-06-11 UTC

## 1. 目标

C06D 将 C06B 后端 owner-only permission assignment API 和 C06C 前端 User
Management 权限管理 UI 发布到 staging，并完成 staging 联调验收。

C06D 只做 staging 验收，不进入 C06E production 发布，不进入 P 系列，不接
WooCommerce、n8n 真实业务流、MinIO、Filebrowser、产品页或真实业务模块。

## 2. 发布范围

本轮只执行 staging backend/frontend safe release：

- staging backend：`console_staging_backend`
- staging frontend：`console_staging_frontend`

执行结果：

- staging backend safe release：成功，发布后 staging smoke 通过。
- staging frontend safe release：成功，发布后 staging smoke 通过。
- production：未发布。
- Alembic：未执行 upgrade。只读检查显示 current/head 均为
  `c05b_permissions_001 (head)`。
- staging postgres 容器：未 stop/restart/rm，未重建，未清空。
- staging 数据库：未直接 psql，未手写 SQL。
- env：未读取或打印 `.env.staging` / `.env.production`。
- secrets：未打印 password、token、Authorization header 或 secret。
- git commit：未执行。

## 3. Registry Seed 处理

发布后首次动态验收发现：

- owner `GET /permissions/registry` 返回 `200`。
- 但 `items=[]`，无法满足 C06D “permission_key 必须来自
  `/permissions/registry`” 的 grant 验收要求。

经老板批准，本轮在 staging backend 容器内调用现有后端应用层 helper
`upsert_permission_registry()` 初始化 `permission_registry` 系统权限点 seed。

执行边界：

- 只写入 `permission_registry` 系统权限点 seed。
- 未直接连接 postgres。
- 未手写 SQL。
- 未新增 migration。
- 未操作 staging postgres 容器。
- 未读取或打印 env。
- 未影响 production。

结果：

- `permission_registry_seed_count=18`。
- owner `GET /permissions/registry` 返回 `200`。
- registry count：`18`。
- 普通 permission 可用：`artifacts.read`。
- high-risk permission 可用：`jobs.manage`。

## 4. 发布后只读检查

发布后检查结果：

- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过，只读。
- `./scripts/check_dual_env_status.sh`：通过，只读。
- `./scripts/check_safe_release_plan.sh`：通过，只读。
- staging backend assignment route 未登录返回 `401`，确认 C06B 路由已发布。
- staging `/users` 页面返回 `200`。
- staging frontend 已发布 C06C bundle，公开构建产物包含：
  `C06C permissions`、`Grant permission`、`Explicit assignments`、
  `CONFIRM_HIGH_RISK_PERMISSION`、`Permission key 来自`。

说明：本机没有 Playwright/Puppeteer 或 Chromium 可执行文件，未做浏览器截图级
点击验收。UI 验收依据为 staging frontend proxy 登录链路、已发布 bundle 标识和
本地前端测试。

## 5. Owner UI / Proxy 验收

owner 通过 staging frontend proxy 验证：

- frontend proxy owner login：`200`。
- frontend proxy owner `GET /auth/me`：`200`。
- owner `permissions.is_owner_full_access`：`true`。
- frontend proxy owner `GET /permissions/registry`：`200`。
- frontend proxy registry count：`18`。

User Management 权限入口验收：

- `/users` 页面已发布并返回 `200`。
- 已发布 bundle 包含 C06C 权限管理面板和 high-risk 二次确认标识。
- 本地 `tests/frontend/permission-management.test.mjs` 覆盖 owner 可见权限入口、
  non-owner 不可见、owner target full access、空状态、grant/update/revoke 和
  high-risk 前端阻断逻辑。

## 6. Assignment List 验收

通过 C06B API 完成：

- owner `GET /permissions/users/{owner_id}/assignments`：`200`。
- owner target 返回 `is_owner_full_access=true`。
- owner target `assignments=[]`，不把 owner 渲染成普通 assignment。
- 创建 staging-only viewer 测试账号：
  `c06d_viewer_test_1781168578`。
- owner `GET /permissions/users/{viewer_id}/assignments`：`200`。
- 初始 explicit assignments：空列表。
- 测试账号密码未打印。

测试结束后已通过 owner-only `/users/{user_id}/disable` 禁用该 staging-only
测试账号。

## 7. 普通 Permission Grant / Update / Revoke

普通 permission 使用 registry 中的 `artifacts.read`，所有变更都通过 C06B API
完成，未直接写 `user_permission_assignments`。

grant：

- owner `POST /permissions/users/{viewer_id}/assignments`：`201`。
- assignment effective：`true`。
- assignment list 刷新后包含该 assignment。
- non-owner `GET /permissions/me` 包含 `artifacts.read`。
- operation log action：`permission.assignment.grant`，result：`success`。

update：

- owner `PATCH /permissions/users/{viewer_id}/assignments/{assignment_id}`
  设置 `enabled=false` 并更新 scope/reason：`200`。
- assignment 显示 disabled。
- non-owner `GET /permissions/me` 不再包含 `artifacts.read`。
- owner 再次 update re-enable 并改回 global scope：`200`。
- non-owner `GET /permissions/me` 再次包含 `artifacts.read`。
- operation log action：`permission.assignment.update`，result：`success`。

revoke：

- owner `DELETE /permissions/users/{viewer_id}/assignments/{assignment_id}`：
  `200`。
- revoke 语义为 soft revoke，assignment disabled。
- non-owner `GET /permissions/me` 不再包含 `artifacts.read`。
- operation log action：`permission.assignment.revoke`，result：`success`。

## 8. High-Risk Permission 验收

high-risk permission 使用 registry 中的 `jobs.manage`。

阻断验证：

- 缺少 reason：`400`。
- 缺少 `confirm_high_risk` / confirmation text：`400`。
- confirmation text 不是 `CONFIRM_HIGH_RISK_PERMISSION`：`400`。

成功 grant：

- 带 reason、`confirm_high_risk=true`、
  `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`：`201`。
- operation log action：`permission.assignment.grant`，result：`success`。

revoke：

- high-risk revoke 缺少 reason：`400`。
- high-risk revoke 带 reason：`200`。
- operation log action：`permission.assignment.revoke`，result：`success`。
- 测试结束后 high-risk assignment 已 revoke，non-owner `/permissions/me`
  不再包含 `jobs.manage`。

operation_logs 只读汇总：

- `permission.assignment.grant success=2`。
- `permission.assignment.update success=2`。
- `permission.assignment.revoke success=2`。
- `permission.assignment.grant failure=3`。
- `permission.assignment.revoke failure=1`。
- high-risk failure 日志记录 `jobs.manage` 且 `high_risk=true`。

## 9. Non-owner 越权验证

使用 staging-only viewer 测试账号验证：

- non-owner `GET /permissions/users/{viewer_id}/assignments`：`403`。
- non-owner `POST /permissions/users/{viewer_id}/assignments`：`403`。
- non-owner `PATCH /permissions/users/{viewer_id}/assignments/{assignment_id}`：
  `403`。
- non-owner `DELETE /permissions/users/{viewer_id}/assignments/{assignment_id}`：
  `403`。
- non-owner `GET /users`：`403`。
- non-owner `GET /permissions/registry`：`403`，未授予 `permissions.read`。
- frontend proxy non-owner `GET /auth/me`：`200`，但
  `permissions.is_owner_full_access=false`。

## 10. 保留 C05/C06 安全结论

- `/users` 仍是后端 owner-only。
- 未登录 `/auth/me`：`401`。
- 未登录 `/permissions/me`：`401`。
- 未登录 `/users`：`401`。
- `/auth/register`：`404`。
- `role_default_permissions` 不自动生效；测试账号初始
  `/permissions/me.permission_keys` 为空。
- `super_admin` 不默认 grant/revoke；`/users` 创建 `super_admin` 被拒绝，返回
  `422`。C06B 后端测试继续覆盖 `super_admin` 不能 list/grant/update/revoke。
- 前端只是 UX；后端 `require_owner()` 和 C06B owner-only API 是安全边界。
- 未接真实业务。

## 11. 测试账号

本轮创建 staging-only 临时 viewer 测试账号：

- username：`c06d_viewer_test_1781168578`
- role：`viewer`
- 创建方式：owner-only `/users` API
- 用途：仅 staging C06D 验收
- 密码：未输出
- token / Authorization header：未输出
- 测试结束状态：已 disable

该账号未用于 production。

## 12. 最终结论

C06D staging 发布和动态验收通过。

已验证 C06B/C06C 在 staging 上共同满足：

- owner 能查看 explicit assignments。
- owner 能通过 UI/API 所需路径 grant/update/revoke 普通 permission。
- `/permissions/me` 能反映 grant/update/revoke 后的 effective permission 变化。
- high-risk permission 缺少 reason/confirmation 被阻断。
- high-risk permission 带确认可 grant，且测试结束后已 revoke。
- grant/update/revoke 均写 operation_logs。
- non-owner 不能越权访问 assignment 管理 API。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认 grant/revoke。
- production 未在 C06D 发布，production smoke 仍通过。后续 C06E 已完成 production
  发布归档，见 `docs/C06_PERMISSION_PRODUCTION_RELEASE.md`。
- C06F 已完成 C06 用户权限管理封板，见
  `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`。

C06D staging 验收结果已纳入 C06F 最终封板归档。
