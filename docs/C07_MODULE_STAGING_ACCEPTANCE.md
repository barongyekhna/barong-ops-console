# C07E Module Staging Acceptance

日期：2026-06-11 UTC

C07E 目标是把 C07B 后端 Module Manifest / Module Registry runtime 和 C07C
frontend module-aware navigation / route guard 发布到 staging，并用 C07D
verify/test 规则做 staging 模块隔离验收。

C07E 不进入 C07F，不发布 production，不接 K01/P 系列，不接 n8n、
WooCommerce、MinIO、Filebrowser 或真实业务流程。

## 发布范围

- staging backend：已执行 safe release。
- staging frontend：已执行 safe release。
- production：未发布，仅做只读 smoke。
- Alembic：未执行 upgrade；C07B/C07C/C07D 没有新增 migration。
- staging postgres：未 stop/restart/rm，未重建、删除、清空。
- 数据库：未 psql，未手写 SQL，未直接操作 staging/production DB。
- env：未读取或打印 `.env.staging` / `.env.production`。
- 测试账号和权限 assignment：未创建账号，未 grant/update/revoke staging 或
  production assignment。

## 发布结果

backend release 使用：

```bash
CONFIRM_SAFE_RELEASE=yes ./scripts/safe_compose_release.sh --env staging --service backend --execute
```

结果：成功。脚本 pre-smoke 和 post-smoke 均通过；只替换
`console_staging_backend` 目标容器。

frontend release 首次执行在 Docker build verification stage 失败：
`npm run verify` 找不到 `/tests/frontend/module-isolation.test.mjs`。原因是 C07D
后 `frontend/scripts/verify-foundation.mjs` 会检查 repo-level frontend tests，而
`frontend/Dockerfile` 只复制了 `frontend/`。已修复为在 verification/build stage
复制 `tests/frontend/` 到 `/tests/frontend/`；runtime image 不复制该测试目录。

frontend release 随后使用同一条批准命令重试：

```bash
CONFIRM_SAFE_RELEASE=yes ./scripts/safe_compose_release.sh --env staging --service frontend --execute
```

结果：成功。Docker build 内 `npm run verify`、`npm run typecheck` 和
`npm run build` 通过；脚本 pre-smoke 和 post-smoke 均通过；只替换
`console_staging_frontend` 目标容器。

## Smoke / Status

发布后检查结果：

- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过，只读。
- `./scripts/check_dual_env_status.sh`：通过，只读。
- `./scripts/check_safe_release_plan.sh`：通过，只读。

dual env status 确认 production/staging 端口隔离，staging/production postgres 均未暴露
host 5432。

## Modules API 验收

已动态验证的 staging 未登录状态：

- `GET http://127.0.0.1:8100/modules/registry`：401。
- `GET http://127.0.0.1:8100/modules/me`：401。

owner 动态 API 验收需要 staging owner 登录凭据。本轮未读取 env、未打印 token/password、
未伪造 token、未直接查库，因此未执行以下 live owner 请求：

- owner `GET /modules/registry` 200。
- owner `GET /modules/me` 200。
- owner access state 中 `admin.users` / `admin.permissions` 可见。

C07B/C07D 后端 Docker 最小测试已覆盖同一代码路径：

- `/modules/registry` 和 `/modules/me` 鉴权。
- owner full access 可见 `admin.users` / `admin.permissions`。
- non-owner admin/system hidden。
- business denied `show_locked` / `locked`。
- planned / adapter_pending / unavailable `executable=false`。
- registry 不包含 password_hash 或 secret/token/password/env/provider URL/API key。

## Non-owner 验收

未发现可复用的 active staging-only non-owner 测试账号。C06D 创建的
`c06d_viewer_test_1781168578` 已在 C06D 结束时禁用。本轮按边界没有创建新
staging/production 测试账号，也没有 re-enable 旧账号。

因此 non-owner live login 未执行。non-owner 行为由 C07D Docker tests 和前端
module-isolation tests 验证：

- admin/system 对 non-owner hidden 或不返回。
- business 无权限时 `show_locked` / `locked`。
- `/modules/me` 失败时 frontend fallback 不暴露 admin/system。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认全局。

如后续必须做 live non-owner 登录，需要老板单独批准提供或创建 staging-only 测试账号。

## Frontend 验收

staging frontend 发布后：

- `/login` 返回 200。
- frontend JS bundle marker 命中 `ModuleAccessProvider`、`modules/me`、
  `admin.users`、`admin.permissions`、`show_locked`。
- 多 console route bundle marker 命中 `Module unavailable`、`No permission`、
  `adapter_pending`、`hide_when_denied`、`integration.n8n_test_bridge`、
  `business.products`、`business.jobs`。

frontend module-aware navigation / route guard 由 bundle marker 和 C07D 前端测试共同验收：

- navigation 使用 C07B namespaced `module_key`。
- User Management 映射 `admin.users`，仍 owner-only。
- Permission Management 映射 `admin.permissions`，仍在 `/users` 内 owner-only。
- locked business module 显示 No Permission / locked 语义。
- planned / adapter_pending / unavailable module 显示 Module Unavailable 语义，不进入真实动作。
- No Permission / Module Unavailable 文案不泄露 secret/env/token/password。

## Frontend Proxy Allowlist

发布后 staging frontend proxy 动态状态：

- `GET /api/backend/modules/registry`：401，说明 exact path 已放行并被 backend 鉴权拦截。
- `GET /api/backend/modules/me`：401，说明 exact path 已放行并被 backend 鉴权拦截。
- `GET /api/backend/modules/not-allowed`：404，说明没有危险 `/modules/*` 宽通配。

`frontend/src/app/api/backend/[...path]/route.ts` 仍只精确允许
`modules/registry` 和 `modules/me`，并保留 C05/C06 permission proxy allowlist。

## C05 / C06 回归

发布后 live 未登录回归：

- `GET /auth/me`：401。
- `GET /permissions/me`：401。
- `GET /users`：401。
- `POST /auth/register`：404。

owner C05/C06 live 回归需要 staging owner 登录凭据；本轮未读取 env、未打印
token/password、未伪造 token、未直接查库，因此未执行 live owner `/auth/me`、
`/permissions/me`、`/permissions/registry`、`/permissions/users/{user_id}/assignments`
和 `/users` 请求。

C05/C06 后端 Docker 回归测试通过，覆盖：

- owner full access。
- `/permissions/me`。
- C06B assignment list/grant/update/revoke API。
- `/users` owner-only。
- `/auth/register` 404。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。

## K01 / P 系列 / 真实业务防线

本轮确认：

- K01 未接入 runtime registry 或默认导航。
- P01/P02/P03/P04/P05/P06/P07/P08 未接入 runtime。
- n8n/WooCommerce/MinIO/Filebrowser 未接入真实业务动作。
- `integration.n8n_test_bridge` 保持 integration/test bridge，状态为
  `adapter_pending`，不标记 executable。
- 未创建真实业务任务。
- 未调用外部 provider。
- 未实现 Module Adapter。
- 未实现 Execution Provider。
- 未实现模块 sandbox、模块开关、审批门或密钥规则。

## 本地和 Docker 检查

第一阶段和发布后已运行：

- `git status --short --untracked-files=all`。
- `git log --oneline -15`，确认 HEAD 为 `f8c8c88`，包含 C07D。
- `frontend npm run verify`。
- `frontend npm run typecheck`。
- `frontend npm run build`。
- `node --test tests/frontend/permissions.test.mjs`。
- `node --test tests/frontend/permission-management.test.mjs`。
- `node --test tests/frontend/module-isolation.test.mjs`。
- Docker 后端最小测试：
  `tests/backend/test_modules_registry.py`,
  `tests/backend/test_permissions_api.py`,
  `tests/backend/test_permission_assignments_api.py`，结果 `29 passed`。
- `git diff --check`。
- staging/production smoke、dual env status、safe release plan。

## 验收限制

本轮没有 approved staging owner credentials，也没有 active approved non-owner
test account。因此 owner 和 non-owner live login 请求没有执行。C07E 已完成 staging
backend/frontend 发布、未登录 API、frontend proxy/bundle、smoke/status 和本地/Docker
contract 验收；完整 owner/non-owner live API 证据需要老板提供凭据或单独批准
staging-only 测试账号后补充。

## 下一步

C07F production 模块隔离发布归档已完成，记录见
`docs/C07_MODULE_PRODUCTION_RELEASE.md`。C07F 未获得 approved production owner/non-owner
auth material，因此 production owner/non-owner live login 仍未执行；相关规则由 C07D
tests 和本 C07E staging 验收共同作为依据。下一步是 C07G：C07 模块隔离封板；C07G 仍不得
接 K01/P 系列或真实业务。
