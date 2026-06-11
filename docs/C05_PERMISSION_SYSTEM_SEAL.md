# C05 Permission System Seal

日期：2026-06-11 UTC

本文件记录 C05G：C05 权限系统最终封板。

C05G 是文档封板任务，不是功能开发、权限分配页面、grant/revoke API、staging
发布、production 发布或真实业务接入任务。本轮只归档 C05A-F 的完成范围、最终
权限模型、安全边界、生产状态和后续接入规则。

## 一、封板结论

C05 权限系统已完成并封板。

最终结论：

- C05 已形成完整闭环：设计、数据模型、后端 enforcement、前端权限感知、
  staging 验收、production 发布归档和最终封板记录均已完成。
- staging 和 production 已完成验收。
- production 已发布 C05 权限系统，并通过 owner 验收。
- 下一步不接真实业务，不进入 P 系列。后续应按计划进入 C06，或先做 C18/
  组织权限深化与业务模块接入前置规划。

## 二、C05 完成范围

C05A：权限审计与方案。

- 完成现有 auth、role、User Management、frontend navigation 和测试文档审计。
- 明确 role、permission、scope、assignment 的分工。
- 明确 Permission Registry、User Permission Assignment、Role Default
  Permissions、Permission Scope 和 Module Permission Manifest 概念。
- 明确业务菜单 `show_locked`、管理/系统菜单 `hide_when_denied`。
- 记录文件：`docs/C05_PERMISSION_SYSTEM_PLAN.md`。

C05B：权限数据模型与 migration。

- 新增 `permission_registry`。
- 新增 `user_permission_assignments`。
- 新增 `role_default_permissions`。
- 新增 Alembic migration `c05b_permissions_001`。
- 新增权限 seed/upsert、assignment 查询服务、owner 全局 resolver 和测试。
- 记录文件：`docs/C05_PERMISSION_DATA_MODEL.md`。

C05C：后端权限依赖与 API。

- 新增 `require_permission()`。
- `GET /auth/me` 追加 `permissions`。
- 新增 `GET /permissions/me`。
- 新增 `GET /permissions/registry`。
- `/users` 仍保持 `require_owner()`。
- 未新增 grant/revoke API。
- 记录文件：`docs/C05_PERMISSION_BACKEND_ACCESS.md`。

C05D：前端权限感知与访问提示。

- 前端读取 `/auth/me.permissions`。
- 新增 `hasPermission`、`isOwnerFullAccess`、`canAccessModule` 等 helper。
- 业务板块无权限时 `show_locked`。
- 管理/系统板块无权限时 `hide_when_denied`。
- 新增无权访问提示和基础 route guard。
- User Management 仅 owner full access 可见。
- 记录文件：`docs/C05_PERMISSION_FRONTEND_ACCESS.md`。

C05E：staging 联调验收。

- staging backend/frontend safe release 已完成。
- staging Alembic `upgrade head` 已完成。
- owner 验收通过。
- non-owner staging 动态验收通过。
- `/users` 仍 owner-only。
- 未读取真实 env，未接真实业务。
- 记录文件：`docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`。

C05F：production 发布归档。

- production backend safe release 已完成。
- production Alembic `upgrade head` 已完成。
- production frontend safe release 已完成。
- production owner API 和 frontend 权限 UX 验收通过。
- frontend proxy allowlist 已补齐 `/permissions/me` 和 `/permissions/registry`。
- production non-owner 动态 UI 未验证，原因是没有现成生产 non-owner 账号和密码，
  且 C05F 不创建 production 测试账号。
- 未操作 production postgres 容器，未读取真实 env，未接真实业务。
- 记录文件：`docs/C05_PERMISSION_PRODUCTION_RELEASE.md`。

## 三、最终权限模型

- Role 只是基础身份，不等于实际授权。
- Permission Assignment 才是非 owner 用户实际授权来源。
- Owner 拥有全局全权限，不需要逐条 assignment。
- `super_admin` 不默认拥有全局权限，也不会因为 role 自动获得管理能力。
- `role_default_permissions` 是建议默认权限模板，不自动生效，不进入 effective
  permissions。
- Scope 已预留 `global`、`company`、`factory`、`department`、`organization`、
  `module`，但完整组织/公司/工厂/部门管理不在 C05 完成。
- Permission Registry 是系统权限点来源，记录系统承认哪些稳定 permission keys。
- Module Permission Manifest 是未来业务模块注册要求。未来模块必须声明权限点，
  再写入 Permission Registry，由后续授权流程分配给用户。

## 四、后端最终状态

- `require_permission()` 已完成。
- owner 在 dependency 层直接通过，不受 assignment 或 scope 限制。
- 非 owner 基于 enabled、未过期、registry enabled、scope 匹配的 assignment 判断。
- `GET /auth/me` 已返回 `permissions`。
- `GET /permissions/me` 可用。
- `GET /permissions/registry` 可用。
- `/users` 仍使用 `require_owner()`，仍是后端 owner-only。
- `/auth/register` 仍返回 404。
- `/auth/me`、`/permissions/me`、`/permissions/registry`、`/users` 响应不返回
  `password_hash`。
- grant/revoke API 未做。

## 五、前端最终状态

- 前端读取 `/auth/me` 或 `/permissions/me` 的 permissions 合同。
- `hasPermission`、`isOwnerFullAccess`、`canAccessModule` 等 helper 已完成。
- 业务模块采用 `show_locked`。
- 管理/系统模块采用 `hide_when_denied`。
- User Management 仅 owner full access 可见。
- 无权访问提示已完成。
- 直接访问受保护页面会安全降级或显示无权访问提示。
- 前端权限只是 UX，不是安全边界。真实授权结果以后端 401/403 和
  `require_permission()` / `require_owner()` 为准。

## 六、staging 验收摘要

C05E 已完成。

验收摘要：

- staging backend safe release 已完成。
- staging frontend safe release 已完成。
- staging Alembic `upgrade head` 已完成，当前版本为 `c05b_permissions_001 (head)`。
- owner `/auth/me` 和 `/permissions/me` 返回 full access wildcard。
- owner `/permissions/registry` 返回 200 和 list response 结构。
- staging non-owner 动态验收通过：无 wildcard、无 assignment、`/permissions/me`
  返回 200、`/permissions/registry` 返回 403、`/users` 返回 403。
- User Management 对 non-owner 隐藏。
- admin/system 入口无权限隐藏。
- business 入口无权限 locked。
- 直接访问无权 route 会显示无权访问提示。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- 未读取 `.env.staging` 或 `.env.production`。
- 未接真实业务。

## 七、production 发布摘要

C05F 已完成。

发布与验收摘要：

- production backend safe release 已完成。
- production Alembic `upgrade head` 已完成，当前版本为 `c05b_permissions_001 (head)`。
- production frontend safe release 已完成。
- production `/auth/me` 验收通过。
- production `/permissions/me` 验收通过。
- production `/permissions/registry` 验收通过。
- owner full access 验证通过，permission wildcard 验证通过。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- frontend proxy allowlist 已修复 `/permissions/me` 和 `/permissions/registry`。
- production non-owner 动态 UI 未验证，原因是没有现成生产 non-owner 账号和密码，
  且 C05F 不创建 production 测试账号。
- 未操作 production postgres 容器。
- 未直接操作 production 数据库。
- 未读取 `.env.production` 或 `.env.staging`。
- 未接真实业务。

## 八、安全边界

C05G 不发布 staging 或 production。

C05 和 C05G 明确不做：

- 不创建真实业务任务。
- 不接 n8n、WooCommerce、P 系列、MinIO、Filebrowser 真实业务流程。
- 不做权限分配页面。
- 不做 grant/revoke API。
- 不改变 `/users` owner-only 后端边界。
- 不完整实现组织结构 scope 管理。
- 不创建 production 测试账号。
- 不读取或打印 `.env.production`。
- 不读取或打印 `.env.staging`。
- 不打印 secret、token、password 或 Authorization header。
- 不操作 production/staging postgres 容器。
- 不直接操作 production/staging 数据库。
- 不修改 Nginx 或证书。

## 九、后续任务

C06：用户权限管理页面。

- 新增 grant/revoke API。
- 新增权限分配 UI。
- 权限变更写入 operation_logs。
- 高风险权限需要二次确认。
- 如需开放 User Management，必须先正式改变后端 `/users` 授权边界并完成验收。

C18 或后续组织权限阶段：

- 深化 company/factory/department/organization scope。
- 建立组织、公司、工厂、部门实体和 scope 管理。
- 明确 scoped super_admin、module_admin 和业务域授权边界。

业务模块接入前置要求：

- 必须带 Permission Manifest。
- 必须注册稳定 permission keys。
- 后端 API 必须接入对应 `require_permission()`。
- 业务板块菜单必须遵循 `show_locked`。
- 管理/系统板块菜单必须遵循 `hide_when_denied`。
- 真实业务模块不要在 C05G 中启动。

## 十、最终验收命令记录

C05G 本轮只读审计已执行：

- `git status --short --untracked-files=all`：通过，初始工作区 clean。
- `git log --oneline -10`：通过，提交链包含 C05A-F。
- `git rev-parse --short HEAD`：通过，HEAD 为 `50e2358`。

C05A-F 最终 commit 链条：

- `1e6dbc3 docs: add C05A permission system plan`
- `9e75e84 feat: add C05B permission data model`
- `544efdb feat: add C05C permission backend access`
- `f302926 feat: add C05D frontend permission access`
- `ac41ffd docs: add C05E permission staging acceptance`
- `50e2358 fix: allow C05 permission proxy and archive production release`

文档完成后执行的最终检查命令和结果：

- `git status --short --untracked-files=all`：通过，显示本轮 C05G 文档变更。
- `git diff --check`：通过。
- `npm run verify`：通过，`Frontend foundation checks passed.`。
- `npm run typecheck`：通过。
- `npm run build`：通过，Next.js production build 成功，生成 18 个静态页面。
- `node --test tests/frontend/permissions.test.mjs`：通过，`1 pass`。
- `pytest tests/backend/test_permissions_api.py tests/backend/test_permissions_service.py
  tests/backend/test_permission_migration.py`：当前环境不可运行，`pytest` 命令不存在。
- `python -m pytest tests/backend/test_permissions_api.py tests/backend/test_permissions_service.py
  tests/backend/test_permission_migration.py`：当前环境不可运行，`python` 命令不存在。
- `python3 -m pytest tests/backend/test_permissions_api.py tests/backend/test_permissions_service.py
  tests/backend/test_permission_migration.py`：当前环境不可运行，系统 Python 缺少 `pytest` 模块。
- `./scripts/production_smoke_check.sh`：普通沙箱内 DNS 解析失败；按权限规则 escalated
  重跑同一只读命令后通过，`Production smoke check passed for https://ops.barongyekhna.com`。
- `./scripts/staging_smoke_check.sh`：普通沙箱内 Docker socket 权限不足；按权限规则 escalated
  重跑同一只读命令后通过，`Staging smoke check passed.`。
- `./scripts/check_dual_env_status.sh`：普通沙箱内 Docker socket 权限不足；按权限规则 escalated
  重跑同一只读命令后通过。结果确认 production/staging frontend/backend/postgres 均运行，
  host port `5432` 未监听，production smoke 通过，staging smoke 通过。
- `./scripts/check_safe_release_plan.sh`：通过，`Safe release plan check passed.`。
- `git status --short --untracked-files=all`：最终状态见本轮报告；仅包含 C05G 文档新增和
  C05 文档引用更新。

## 十一、C05G 最终结论

C05 权限系统已封板。

最终保留边界：

- `/users` 后端仍 owner-only。
- User Management 前端仍仅 owner full access 可见。
- owner 仍全局全权限。
- `super_admin` 仍不默认全局权限。
- `role_default_permissions` 仍不自动生效。
- 前端权限仍只是 UX。
- 后端 `require_permission()` 和 `require_owner()` 仍是真实安全边界。
- C05 不包含 grant/revoke 权限管理页面。
- C05 不包含权限分配 UI。
- C05 不包含完整组织/公司/工厂/部门 scope 管理。
- C05 不接真实业务模块。
- C05 不接 n8n、P 系列、WooCommerce、MinIO、Filebrowser 真实业务流程。

完成 C05G 后等待审核，不进入 C06，不进入 P 系列，不接真实业务，不发布
staging/production。
