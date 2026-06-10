# C04D Staging Acceptance

日期：2026-06-10 UTC

本文件记录 C04D：部署到 staging 测试服验收角色目录 UI 的后半段验收结果。

本轮不恢复旧状态。staging backend/frontend 已由人工安全恢复后，本轮只在现有
运行中的 staging/prod 服务上做验收和文档归档。

## 1. 边界

本轮遵守以下边界：

- 没有 build、recreate、stop、rm 任何 production/staging 容器。
- 没有执行 `docker-compose up/down`。
- 没有修改 Nginx、证书或 compose 文件。
- 没有读取 `.env.production` 或 `.env.staging` 文件内容。
- 没有打印 password、token、secret 或 Authorization header。
- 没有创建 production 用户。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务。
- 没有 git commit。

## 2. 只读环境状态

`docker ps` 显示：

- staging frontend：`barong-ops-console-staging_console_staging_frontend_1`
  运行中，绑定 `127.0.0.1:3100->3000/tcp`。
- staging backend：`barong-ops-console-staging_console_staging_backend_1`
  运行中，绑定 `127.0.0.1:8100->8000/tcp`。
- staging postgres：`barong-ops-console-staging_console_staging_postgres_1`
  运行中且 healthy，只暴露 Docker 内网 `5432/tcp`。
- production frontend/backend/postgres 均运行中。
- production postgres healthy，且 console Postgres 未暴露宿主机 5432。

验收前只读检查：

- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。

## 3. Staging Migration

在当前 staging backend 容器内执行：

```bash
docker exec barong-ops-console-staging_console_staging_backend_1 \
  python -m alembic -c backend/alembic.ini upgrade head
```

结果：成功，无错误输出。

随后执行：

```bash
docker exec barong-ops-console-staging_console_staging_backend_1 \
  python -m alembic -c backend/alembic.ini current
```

结果：

```text
f07_core_001 (head)
```

## 4. 角色目录 API 验收

验收通过 staging backend HTTP API 完成。owner 登录使用 staging backend 容器运行时
配置，不读取真实 env 文件，不输出密码或 token。

测试账号前缀：

- `c04d_role_1781078011_37cba9`

通过项：

- staging owner 登录成功。
- owner `GET /users/roles` 返回 `200`。
- `standard_roles` 包含并按当前目录返回：
  `owner`、`super_admin`、`module_admin`、`operator`、`reviewer`、`viewer`、
  `bot_agent`。
- `assignable_roles` 只包含 `viewer`、`operator`、`reviewer`。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 均为 `assignable=false`。
- 未登录 `GET /users/roles` 返回 `401`。
- 非 owner `GET /users/roles` 返回 `403`。
- 创建 `viewer`、`operator`、`reviewer` 均成功，返回 `201`。
- 创建 `owner`、`super_admin`、`module_admin`、`bot_agent` 均被拒绝，
  返回 `422`。
- `PATCH /users/{user_id}` 改成 `viewer`、`operator`、`reviewer` 均成功，
  返回 `200`。
- `PATCH /users/{user_id}` 改成 `owner`、`super_admin`、`module_admin`、
  `bot_agent` 均被拒绝，返回 `422`。
- `POST /auth/register` 仍返回 `404`。
- `/operation-logs` 可见本轮测试用户相关 `user.create` 和 `user.update`
  用户管理记录；同批日志也包含测试用户登录产生的 `auth.login`。

本轮 API 验收输出只包含状态码、角色名和测试账号前缀，未输出密码、token、
secret 或 Authorization header。

## 5. Staging 页面验收

staging 页面检查：

- `http://127.0.0.1:3100/login` 返回 `200`。
- `http://127.0.0.1:3100/users` 返回 `200`。
- `http://127.0.0.1:3100/api/backend/health` 返回 staging backend health，
  其中 `environment` 为 `staging`。

源码、构建产物和 API 结果共同确认：

- `frontend/src/lib/users-api.ts` 通过 `listUserRoles()` 调用 `/users/roles`。
- `frontend/src/components/user-management-panel.tsx` 的创建用户下拉和详情页
  managed role 下拉来自 `roleCatalog.assignable_roles`，并经过
  `isManagedUserRole()` 安全白名单过滤。
- 本轮 staging API 返回的 `assignable_roles` 只有 `viewer`、`operator`、
  `reviewer`，因此创建用户下拉只展示这三个角色。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 通过
  “Reserved roles, not assignable in C04” 区域展示为 reserved，不进入可选项。
- staging frontend 容器中的 `.next` 构建产物包含 `/users/roles`、角色目录加载
  提示和 reserved role UI 文案。

## 6. 验收后检查

验收后再次运行：

- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。

`./scripts/test_foundation_acceptance.sh` 本轮未执行。原因是该脚本内部会调用
`docker compose build`、`docker compose up`、`docker compose run --rm` 和
`docker compose down --volumes`，与本轮明确的“不要 build / recreate / stop /
rm 容器、不要 docker-compose up/down”边界冲突。

## 7. 结论

C04D staging 角色目录 UI 和 API 验收通过。

结论：

- 本轮没有重新部署、重启、删除或重建 production/staging 容器。
- 本轮只在已恢复运行的 staging 上创建测试账号并验收角色目录。
- production smoke 在验收前后均通过，production 仍正常。
- `/users/roles` owner-only 行为正确。
- `viewer`、`operator`、`reviewer` 是当前 C04 唯一可创建/可选择角色。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 保持 reserved，不可创建，
  不可 PATCH 分配。
- `/auth/register` 仍不存在。
- User Management 页面使用后端角色目录，不再依赖硬编码可见角色作为唯一来源。
- C04 仍不做完整 RBAC，不给 `super_admin`、`module_admin` 或 `bot_agent`
  实际权限，不接真实业务。

## 8. C04E production 发布状态

C04E 已在 2026-06-10 UTC 由人工完成 production 发布，并在
`docs/C04_PRODUCTION_RELEASE.md` 中归档只读验收结果。

当前 production 状态：

- C04B 后端角色目录已进入 production。
- C04C 前端角色目录 UI 已进入 production。
- production `/users` 页面可用。
- 未登录访问 production `/api/backend/users/roles` 返回 401。
- 创建用户下拉仍只允许 `viewer`、`operator`、`reviewer`。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 仍是 reserved，不可创建、
  不可选择。
- 当前不做 `super_admin` 放权。
- 当前不做完整 RBAC。
- production smoke、staging smoke、dual env check 均通过。
- staging 仍保留为测试服。

下一步是 C04F：角色体系总封板。
