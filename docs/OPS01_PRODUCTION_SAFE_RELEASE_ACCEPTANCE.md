# OPS01D Production Safe Release Acceptance

日期：2026-06-10 UTC

本文件是 OPS01D-3 的归档记录。OPS01D-2 已经手动完成 production backend 和
production frontend 的 safe release 真实演练；OPS01D-3 只做只读复核、文档归档和
最终记录。

OPS01D-3 没有重新发布、没有重新 build、没有停止、删除或重建任何 production /
staging 容器。

## 1. OPS01D-2 演练了什么

OPS01D-2 演练的是：在 production 上不用
`docker-compose --force-recreate`，改用 `scripts/safe_compose_release.sh` 一次只发布
一个服务。

实际顺序是：

1. production backend safe release。
2. production frontend safe release。

两次真实执行都使用了同一套门禁：

```bash
CONFIRM_SAFE_RELEASE=yes
CONFIRM_PRODUCTION_RELEASE=yes
./scripts/safe_compose_release.sh --env production --service <backend|frontend> --execute
```

这说明操作者明确确认了两件事：这次是真发布，而且目标是 production。

## 2. 为什么这一步重要

production 现在是正式入口。发布 backend/frontend 时不能靠临场手动拆命令，也不能
继续使用已知有风险的 `--force-recreate` 路径。

OPS01D-2 的意义是把 staging 已经演练过的 safe release 流程放到 production 真实跑
一遍，确认它能在正式环境完成 backend/frontend 发布，同时不动 postgres、不影响
staging、不修改 Nginx/证书、不接真实业务。

OPS01D-3 的意义是把这件事记录清楚，方便 OPS01E 做安全发布流程封板。OPS01E 现已
完成，封板记录见 `docs/OPS01_SAFE_RELEASE_SEAL.md`。

## 3. ContainerConfig 问题是什么

当前服务器仍然使用 `docker-compose` v1.29.2。这个老版本在强制重建已有容器时，
可能会读取旧容器和镜像 metadata 里的 `ContainerConfig` 字段。

在当前 Docker Engine 和镜像 metadata 组合下，这个字段不稳定。结果就是发布时可能
抛出：

```text
KeyError: 'ContainerConfig'
```

这个错误不是业务代码坏了，也不是登录页或 API 本身坏了。它是 Compose v1 的发布
工具路径问题。风险点在于：如果发布动作已经影响了目标容器，再遇到这个错误，就可能
让 backend/frontend 发布卡住。

## 4. safe release 如何绕开 force-recreate

`scripts/safe_compose_release.sh` 不走 `--force-recreate`。它把发布拆成更明确的步骤：

1. 先跑目标环境 smoke。
2. build 目标 service 镜像。
3. 给当前正在运行的目标 service 镜像打 rollback tag。
4. 只移除目标 service 容器。
5. 用
   `docker-compose -p PROJECT -f COMPOSE up -d --no-deps --no-build SERVICE`
   创建目标 service。
6. 等目标 health 通过。
7. 再跑目标环境 smoke。

这样 Compose v1 不需要按旧容器做强制重建，也不会顺手动 postgres 或其他依赖服务。

## 5. Production backend 结果

production backend safe release 已真实执行成功。

确认结果：

- 使用 `scripts/safe_compose_release.sh` 执行。
- 使用 `CONFIRM_SAFE_RELEASE=yes`。
- 使用 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 使用 `--execute`。
- 没有触发 `KeyError: 'ContainerConfig'`。
- release 后 `http://127.0.0.1:8000/health` 正常。
- release 后 `https://ops.barongyekhna.com/api/backend/health` 正常。
- 已生成 production backend rollback tag：
  `barong-ops-console-prod_console_backend:rollback-20260610103907`。

OPS01D-3 复核时，production backend 容器仍为 Up，host 端口仍是
`127.0.0.1:8000->8000/tcp`。

## 6. Production frontend 结果

production frontend safe release 已真实执行成功。

确认结果：

- 使用 `scripts/safe_compose_release.sh` 执行。
- 使用 `CONFIRM_SAFE_RELEASE=yes`。
- 使用 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 使用 `--execute`。
- 没有触发 `KeyError: 'ContainerConfig'`。
- release 后 `https://ops.barongyekhna.com/login` 返回 200。
- release 后 `https://ops.barongyekhna.com/users` 返回 200。
- release 后 `https://ops.barongyekhna.com/api/backend/health` 正常。
- 已生成 production frontend rollback tag：
  `barong-ops-console-prod_console_frontend:rollback-20260610104306`。

OPS01D-3 复核时，production frontend 容器仍为 Up，host 端口仍是
`127.0.0.1:3000->3000/tcp`。

## 7. OPS01D-3 只读复核结果

OPS01D-3 只做复核，没有再执行 release。

本轮确认：

- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- `https://ops.barongyekhna.com/login`：HTTP 200。
- `https://ops.barongyekhna.com/users`：HTTP 200。
- `https://ops.barongyekhna.com/api/backend/health`：返回 `status=ok`，
  `environment=production`。
- production frontend/backend/postgres 都在运行。
- production postgres 仍为 healthy，只暴露 Docker 内网 `5432/tcp`。
- staging frontend/backend/postgres 都在运行。
- staging postgres 仍为 healthy，只暴露 Docker 内网 `5432/tcp`。
- rollback tag 查询能看到 production backend/frontend rollback tag。

production 当前运行面：

- `barong-ops-console-prod_console_frontend_1`：Up，
  `127.0.0.1:3000->3000/tcp`。
- `barong-ops-console-prod_console_backend_1`：Up，
  `127.0.0.1:8000->8000/tcp`。
- `barong-ops-console-prod_console_postgres_1`：Up healthy，`5432/tcp` 只在容器网络。

staging 当前运行面：

- `barong-ops-console-staging_console_staging_frontend_1`：Up，
  `127.0.0.1:3100->3000/tcp`。
- `barong-ops-console-staging_console_staging_backend_1`：Up，
  `127.0.0.1:8100->8000/tcp`。
- `barong-ops-console-staging_console_staging_postgres_1`：Up healthy，
  `5432/tcp` 只在容器网络。

## 8. 没有动哪些东西

OPS01D-2/OPS01D-3 的边界仍然很清楚：

- production postgres 未被动到。
- staging 未被发布、停止、删除、重启或重建。
- staging postgres 未被动到。
- Nginx 未修改。
- HTTPS 证书未修改。
- 没有 reload/restart Nginx。
- 没有读取或打印 `.env.production`。
- 没有读取或打印 `.env.staging`。
- 没有接真实 n8n。
- 没有接 P 系列。
- 没有接 WooCommerce。
- 没有接 MinIO。
- 没有接 Filebrowser。
- 没有创建真实业务任务。

## 9. 当前 Compose 状态

当前仍未安装 Docker Compose v2。

服务器仍保留 `docker-compose` v1.29.2。短期发布 backend/frontend 时，优先使用
`scripts/safe_compose_release.sh`。不要再把
`docker-compose --force-recreate` 当作 backend/frontend 的默认 production 发布方式。

Compose v2 可以后续单独评估，但不影响 OPS01D 的结论：当前 v1 safe release 流程已经
在 staging 和 production 都真实演练通过。

## 10. 结论

OPS01D production safe release 真实演练通过。

结论：

- production backend safe release 真实执行成功。
- production frontend safe release 真实执行成功。
- 两次都使用 double confirmation 和 `--execute`。
- 两次都通过 `scripts/safe_compose_release.sh`。
- 两次都没有触发 `docker-compose` v1 `KeyError: 'ContainerConfig'`。
- production backend/frontend rollback tag 已生成。
- production smoke 通过。
- staging smoke 通过。
- dual env check 通过。
- production postgres 未被动到。
- staging 未被动到。
- Nginx/证书未修改。
- 未接真实业务。

OPS01E 已完成安全发布流程封板：safe release 流程、rollback tag 说明、
`ContainerConfig` 复发处理边界和 production 发布手册已经整理成最终版本。

当前仍未安装 Compose v2。后续 production backend/frontend 发布继续优先使用
`scripts/safe_compose_release.sh`，不要把 `docker-compose --force-recreate` 作为默认
发布方式。OPS01 封板后，下一阶段回到 C05：权限系统。
