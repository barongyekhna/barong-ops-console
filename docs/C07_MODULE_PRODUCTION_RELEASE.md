# C07F Module Production Release

C07F 目标是把 C07B 后端 Module Manifest / Module Registry runtime 和 C07C
frontend module-aware navigation / route guard 安全发布到 production，并完成
production 发布归档验收。

C07F 是 production 发布归档任务，不是新功能开发任务。本轮没有进入 K01，没有进入 P
系列，没有接 n8n、WooCommerce、MinIO、Filebrowser 或真实业务流程，没有新增 API、
UI、migration、Module Adapter、Execution Provider、模块沙箱、模块开关、审批门或密钥规则。

## 发布范围

- production backend：通过 OPS01 safe release 发布 `console_backend`。
- production frontend：通过 OPS01 safe release 发布 `console_frontend`。
- Alembic：未执行 upgrade。C07B/C07C/C07D/C07E 没有新增 migration，production
  `current` 和 `heads` 均为 `c05b_permissions_001 (head)`。
- production postgres：未 stop/restart/rm，未重建、删除、清空，未暴露 host 5432。
- staging：未发布，只做 smoke/status 只读验证。
- env：未读取或打印 `.env.production`、`.env.staging`。
- 数据库：未 psql，未手写 SQL，未直接操作 production/staging DB。
- 权限数据：未创建 production/staging 测试账号，未 grant/update/revoke assignment。

## 发布执行

本轮使用 OPS01 safe release 机制，且只执行老板批准的两个 production 命令。

### Backend

执行：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes ./scripts/safe_compose_release.sh --env production --service backend --execute
```

结果：

- pre production smoke 通过。
- backend image build 成功。
- 只移除并重建 `barong-ops-console-prod_console_backend_1` 目标容器。
- rollback tag：`barong-ops-console-prod_console_backend:rollback-20260612015341`。
- backend health `http://127.0.0.1:8000/health` 通过。
- post production smoke 通过。

### Frontend

执行：

```bash
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes ./scripts/safe_compose_release.sh --env production --service frontend --execute
```

结果：

- pre production smoke 通过。
- frontend image build 成功，Docker build 内 `npm run verify`、`npm run typecheck`、
  `npm run build` 均通过。
- 只移除并重建 `barong-ops-console-prod_console_frontend_1` 目标容器。
- rollback tag：`barong-ops-console-prod_console_frontend:rollback-20260612015621`。
- frontend health `https://ops.barongyekhna.com/login` 通过。
- post production smoke 通过。

## 基础验收

发布后只读检查结果：

- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过，只读，未启动或发布 staging。
- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/check_safe_release_plan.sh`：通过。

dual env status 显示：

- production frontend：`127.0.0.1:3000->3000/tcp`。
- production backend：`127.0.0.1:8000->8000/tcp`。
- production postgres：`Up ... (healthy)|5432/tcp`，无 host PostgreSQL port。
- staging frontend/backend/postgres 正常运行。
- host port 5432 未监听。

## Modules API 验收

未登录 production backend direct：

- `GET http://127.0.0.1:8000/modules/registry`：401。
- `GET http://127.0.0.1:8000/modules/me`：401。

production backend 容器内 C07B 关键文件已存在，且 hash 与当前 workspace 一致：

- `/app/backend/app/api/routes/modules.py`
- `/app/backend/app/services/module_registry.py`
- `/app/backend/app/core/modules.py`
- `/app/backend/app/schemas/module.py`

production owner live API 验收限制：

- 本轮没有 approved production owner auth material。
- 未伪造 token，未读取 env，未直接查库。
- 未执行 owner live `/modules/registry`、`/modules/me`、`/auth/me`、
  `/permissions/me`、`/permissions/registry`、assignment list 或 `/users` 请求。
- owner full access、admin.users/admin.permissions 可见、registry items 非空、owner
  module access state 由 C07D Docker tests 和 C07E staging 验收覆盖。

production non-owner live API 验收限制：

- 本轮没有 approved production non-owner 测试账号。
- 未创建 production 测试账号，未重置密码，未修改权限 assignment。
- non-owner admin/system hidden、business locked/show_locked、`super_admin` 不默认全局、
  `role_default_permissions` 不自动生效由 C07D Docker/Node tests 和 C07E staging
  验收覆盖。

## Frontend Proxy 验收

production frontend proxy 未登录：

- `GET https://ops.barongyekhna.com/api/backend/modules/registry`：401。
- `GET https://ops.barongyekhna.com/api/backend/modules/me`：401。
- `GET https://ops.barongyekhna.com/api/backend/modules/not-allowed`：404。

结论：

- `/api/backend/modules/registry` 和 `/api/backend/modules/me` exact allowlist 生效。
- 没有危险 `/modules/*` 宽通配。
- C05/C06 permission proxy allowlist 未被移除。

## Frontend Bundle 验收

production `/modules` 页面返回 200，linked JS bundle 命中 C07C module-aware marker：

- `ModuleAccessProvider`
- `useModuleAccess`
- `/modules/me`
- `module_access_unknown`
- `admin.users`
- `admin.permissions`
- `business.jobs`
- `core.dashboard`
- `integration.n8n_test_bridge`
- `adapter_pending`
- `show_locked`
- `hide_when_denied`
- `模块暂不可用`
- `无权访问此模块`

production bundle 没有命中 K01/P 系列/WooCommerce/MinIO/Filebrowser 默认导航 marker：

- `k01`
- `product_knowledge`
- `p01`-`p08`
- `p_series`
- `woocommerce`
- `minio`
- `filebrowser`

## Module Access 行为依据

business `show_locked` / `locked`：

- C07D 后端测试要求 business manifest `denied_behavior="show_locked"`。
- C07D 前端测试确认 business denied fallback visible + locked。
- production bundle 包含 `show_locked`、`business.jobs`、locked badge 和 No Permission
  route decision 代码。

admin/system `hide_when_denied`：

- C07D 后端测试要求 admin/system manifest `denied_behavior="hide_when_denied"`。
- C07D 前端测试确认 non-owner admin/system hidden，`/modules/me` 失败 fallback 也不暴露
  admin/system。
- production bundle 包含 `hide_when_denied`、`admin.users`、`admin.permissions`。

planned / adapter_pending / unavailable 防误执行：

- C07D 后端测试确认这些状态 `executable=false`。
- C07D 前端测试确认 route decision 为 `module_unavailable` 且 `canEnter=false`。
- production bundle 包含 `adapter_pending`、Module Unavailable 文案和
  `integration.n8n_test_bridge`。
- C07F 未新增 create/run/publish 真实业务 action。

registry 安全内容：

- owner live registry 因无 approved owner auth material 未直接读取。
- C07D 后端测试覆盖 registry 序列化不包含 secret/token/password/env/provider URL/API key。
- production bundle 和 docs 只暴露安全状态名称，不包含真实 provider URL、webhook secret
  或 API key。

## C05 / C06 回归

production live 未登录回归：

- `GET /auth/me`：401。
- `GET /permissions/me`：401。
- `GET /users`：401。
- `POST /auth/register`：404。

`/users` 后端仍 owner-only：

- production 未登录 `/users` 返回 401。
- C07D 后端测试确认 non-owner `/users` 返回 403。
- C06B assignment API 仍 owner-only；本轮未执行 production grant/update/revoke。

C05/C06 owner live 回归限制：

- 本轮没有 approved production owner auth material。
- 未执行 owner `/auth/me`、`/permissions/me`、`/permissions/registry`、
  `/permissions/users/{user_id}/assignments` 或 `/users` live 请求。
- C07D Docker 后端测试覆盖 `/permissions/me`、C06B assignment API、`/users` owner-only、
  `/auth/register` 404、`super_admin` 不默认全局、`role_default_permissions` 不自动生效。
- C07E staging 已完成同一 C07 runtime 的 safe release、proxy/bundle/API 未登录验收和
  staging smoke/status 验收。

## K01 / P 系列 / 真实业务防线

本轮确认：

- K01 未接入 runtime。
- K01 未默认出现在 production navigation 中。
- P01/P02/P03/P04/P05/P06/P07/P08 未接入 runtime。
- n8n/WooCommerce/MinIO/Filebrowser 未接入真实动作。
- `integration.n8n_test_bridge` 保持 test/integration/adapter_pending，不标记 executable。
- 未创建真实业务任务。
- 未调用外部 provider。
- 未实现 Module Adapter。
- 未实现 Execution Provider。
- 未实现模块 sandbox、模块开关、审批门或密钥规则。

## 本地和 Docker 检查

C07F 第一阶段和发布后已运行：

- `git status --short --untracked-files=all`。
- `git log --oneline -15`，确认 HEAD 为 `0ae9c43`，包含 C07E。
- `frontend npm run verify`。
- `frontend npm run typecheck`。
- `frontend npm run build`。
- `node --test tests/frontend/permissions.test.mjs`。
- `node --test tests/frontend/permission-management.test.mjs`。
- `node --test tests/frontend/module-isolation.test.mjs`。
- Docker 后端最小测试：
  `tests/backend/test_modules_registry.py`,
  `tests/backend/test_permissions_api.py`,
  `tests/backend/test_permission_assignments_api.py`,
  `tests/backend/test_user_management_api.py`，结果 `47 passed`。
- `git diff --check`。
- `./scripts/production_smoke_check.sh`。
- `./scripts/staging_smoke_check.sh`。
- `./scripts/check_dual_env_status.sh`。
- `./scripts/check_safe_release_plan.sh`。

文档更新后最终检查已再次运行，frontend verify/typecheck/build、三组 frontend Node
tests、Docker 后端最小测试、`git diff --check`、production/staging smoke、dual env
status 和 safe release plan 均通过。

## 结论

C07F 已完成 production backend/frontend safe release 和 production 发布归档验收。

本轮没有执行 Alembic upgrade，没有操作 production/staging postgres 容器，没有直接操作数据库，
没有读取真实 env，没有发布 staging，没有创建测试账号，没有修改权限 assignment，没有接 K01/P
系列或真实业务。

下一步建议：C07G 模块隔离封板。
