# C03 Staging Acceptance

日期：2026-06-10 UTC

本文件记录 C03D：Owner 创建子账户在 staging 的后半段验收结果。
C03E production 发布已经在 2026-06-10 UTC 完成，production 发布归档见
`docs/C03_PRODUCTION_RELEASE.md`。

## 1. 验收边界

本次只验证 staging 已恢复运行后的功能和隔离状态。

本次没有做：

- 没有 build、recreate、stop、rm 任何 production/staging 容器。
- 没有运行 `docker-compose up` 或 `docker-compose down`。
- 没有修改 Nginx、证书或 production/staging compose 文件。
- 没有读取 `.env.production` 或 `.env.staging` 文件内容。
- 没有打印 password、token 或 secret。
- 没有连接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务。
- 没有 git commit。

## 2. 当前环境确认

只读检查结果：

- `docker ps` 显示 staging frontend、backend、postgres 正常运行，staging
  postgres 为 `healthy`。
- `docker ps` 显示 production frontend、backend、postgres 正常运行，
  production postgres 为 `healthy`。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/check_dual_env_status.sh` 通过。

staging 入口：

- Frontend：`127.0.0.1:3100`
- Backend：`127.0.0.1:8100`
- PostgreSQL：只在 Docker 内网暴露 `5432/tcp`

production smoke 仍通过：

- `https://ops.barongyekhna.com`

## 3. Alembic

在当前 staging backend 容器内执行：

```bash
docker exec -w /app/backend \
  barong-ops-console-staging_console_staging_backend_1 \
  alembic upgrade head
```

结果：通过。

随后执行：

```bash
docker exec -w /app/backend \
  barong-ops-console-staging_console_staging_backend_1 \
  alembic current
```

结果：

```text
f07_core_001 (head)
```

## 4. 用户管理自动验收

验收通过 staging backend HTTP API 完成。owner 登录使用 staging backend
容器运行时配置，不读取真实 env 文件，不输出密码或 token。

测试用户：

- Username：`c03d_test_1781064878`
- User id：`2`
- Role flow：`viewer -> operator -> reviewer`

通过项：

- staging owner 登录成功。
- owner 创建唯一测试用户成功。
- `GET /users` 和 `GET /users/{user_id}` 均不包含 `password_hash`。
- 测试用户可以登录。
- 非 owner 访问 `/users` 返回 `403`。
- owner 将测试用户更新为 `operator` 成功。
- owner 将测试用户更新为 `reviewer` 成功。
- disable 后测试用户不能登录。
- disable 后测试用户已有 token 不能继续访问 `/auth/me`。
- enable 后测试用户可以再次登录。
- reset password 后旧密码登录失败。
- reset password 后新密码登录成功。
- 尝试创建 `role=owner` 被拒绝，返回 `422`。
- `POST /auth/register` 仍返回 `404`。
- `operation_logs` 记录了用户管理动作。
- API 响应和 operation log 检查未发现 password、token、secret 或
  `password_hash` 泄漏。

operation log actions 覆盖：

- `user.create`
- `user.update`
- `user.disable`
- `user.enable`
- `user.reset_password`

同一批日志里也可以看到测试用户登录产生的 `auth.login`。

## 5. 验收后检查

验收后再次运行：

- `./scripts/check_dual_env_status.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。

`./scripts/test_foundation_acceptance.sh` 本轮未执行。原因是该脚本会调用
`docker compose build`、`docker compose up`、`docker compose run --rm` 和
`docker compose down --volumes`，与本轮明确的“不要 build / recreate /
stop / rm 容器、不要 docker-compose up/down”边界冲突。

## 6. 结论

C03D staging 用户管理功能通过本轮验收。

当前结论：

- staging 可用，用户管理 API 和前端入口所在环境可访问。
- staging 测试用户创建、登录、停用、启用、重置密码均通过。
- 非 owner 访问 `/users` 被正确拒绝。
- 公开注册仍不存在。
- operation logs 已验证。
- production smoke 仍正常。
- C03E 已完成 production 用户管理发布验收。
- 真实业务仍未接入。

staging 仍保留为测试服，不复制 staging 测试账号到 production。

## 7. C03E 后续状态

C03E 已把 C03B 后端 `/users` API 和 C03C 前端 `/users` 页面发布到
production：

- production 正式地址：`https://ops.barongyekhna.com/users`
- 未登录访问 production `/api/backend/users` 返回 401。
- production `/api/backend/auth/register` 仍返回 404。
- 当前只支持 `viewer`、`operator`、`reviewer`，不做 `super_admin`。
- 当前不做完整 RBAC。
- 本次没有新增 migration，没有修改 Nginx/证书，没有接真实业务。
- production smoke、staging smoke、dual env check 均通过。

下一步是 C03F：C03 Owner 创建子账户封板。
