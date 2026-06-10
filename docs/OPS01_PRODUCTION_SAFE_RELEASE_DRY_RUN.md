# OPS01D-1 Production Safe Release Dry-Run

日期：2026-06-10 UTC

本文件记录 OPS01D-1：基于 OPS01C 已经在 staging 真实演练通过的
`scripts/safe_compose_release.sh`，对 production backend/frontend 做 dry-run、
映射复核、风险检查和文档准备。

## 1. 这次只做什么

OPS01D-1 只做 dry-run 和只读检查，没有真实发布 production。

本轮没有做这些事：

- 没有执行 `CONFIRM_SAFE_RELEASE=yes`。
- 没有执行 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 没有运行 safe release 的真实 `--execute` 发布模式。
- 没有 build。
- 没有执行 `docker-compose up/down` 或 `docker compose up/down`。
- 没有 stop、restart、rm、recreate production 或 staging 容器。
- 没有操作 production/staging postgres。
- 没有读取或打印 `.env.production` / `.env.staging` 内容。
- 没有修改 Nginx 或证书。
- 没有 reload/restart Nginx。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务任务。
- 没有 git commit。

这次的目的很简单：先确认脚本指向的 production 映射是对的，安全门禁还在，当前
production/staging 都正常。真正的 production 演练留到 OPS01D-2。

## 2. 当前只读检查结果

本轮执行并确认：

- `git status --short --untracked-files=all`：开始时工作区干净。
- `git log --oneline --max-count=8`：最新提交为
  `de2bcb3 docs: archive OPS01C staging safe release rehearsal`。
- `./scripts/check_safe_release_plan.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- production `docker ps` 只读列表显示 frontend/backend/postgres 都在运行，
  production postgres 为 healthy，只暴露 Docker 内网 `5432/tcp`。
- staging `docker ps` 只读列表显示 frontend/backend/postgres 都在运行，
  staging postgres 为 healthy，只暴露 Docker 内网 `5432/tcp`。

production 当前对外入口仍是：

- frontend health：`https://ops.barongyekhna.com/login`
- backend health：`http://127.0.0.1:8000/health`

staging 仍只走本机测试端口，没有对公网单独开放 staging。

## 3. 为什么 production 多一个确认变量

staging 真实执行只需要：

```bash
CONFIRM_SAFE_RELEASE=yes
```

production 真实执行必须同时需要：

```bash
CONFIRM_SAFE_RELEASE=yes
CONFIRM_PRODUCTION_RELEASE=yes
```

原因是 production 是正式入口。`CONFIRM_SAFE_RELEASE=yes` 只能说明操作者知道自己要
运行真实 release；`CONFIRM_PRODUCTION_RELEASE=yes` 再额外确认“这次目标就是
production”。这样可以降低把 staging 操作习惯误带到 production 的风险。

OPS01D-1 没有设置这两个变量，所以本轮不可能触发真实 production release。

## 4. Production Backend Dry-Run 映射

执行：

```bash
./scripts/safe_compose_release.sh --env production --service backend --dry-run
```

复核结果：

- `env=production`
- `service=backend`
- `project=barong-ops-console-prod`
- `compose=docker-compose.production.yml`
- `compose_service=console_backend`
- `container=barong-ops-console-prod_console_backend_1`
- `health=http://127.0.0.1:8000/health`
- dry-run 输出明确 production 真实执行需要
  `CONFIRM_SAFE_RELEASE=yes` 和 `CONFIRM_PRODUCTION_RELEASE=yes`。
- dry-run 输出明确 postgres target 被禁止。
- dry-run 输出明确 `down` 被禁止。
- dry-run 输出明确 dry-run 不会真实执行 build、tag、rm、up、smoke 或 health check。

backend dry-run 只是打印计划，没有执行 build、没有删除容器、没有创建容器。

## 5. Production Frontend Dry-Run 映射

执行：

```bash
./scripts/safe_compose_release.sh --env production --service frontend --dry-run
```

复核结果：

- `env=production`
- `service=frontend`
- `project=barong-ops-console-prod`
- `compose=docker-compose.production.yml`
- `compose_service=console_frontend`
- `container=barong-ops-console-prod_console_frontend_1`
- `health=https://ops.barongyekhna.com/login`
- dry-run 输出明确 production 真实执行需要
  `CONFIRM_SAFE_RELEASE=yes` 和 `CONFIRM_PRODUCTION_RELEASE=yes`。
- dry-run 输出明确 postgres target 被禁止。
- dry-run 输出明确 `down` 被禁止。
- dry-run 输出明确 dry-run 不会真实执行 build、tag、rm、up、smoke 或 health check。

frontend dry-run 只是打印计划，没有执行 build、没有删除容器、没有创建容器。

## 6. 为什么 postgres 被禁止

OPS01 的 safe release 只解决 backend/frontend 发布时绕开
`docker-compose` v1 `ContainerConfig` 风险的问题。

Postgres 是数据库，不能当成普通应用容器随手重建。误动 postgres 可能影响数据、
连接、volume 和可恢复性，所以脚本只允许 `backend` / `frontend`，明确拒绝
`postgres`、`console_postgres` 和 `console_staging_postgres`。

OPS01D-1 没有操作 production 或 staging 数据库。

## 7. 为什么 down 被禁止

`down` 的风险太大。它可能处理整个 Compose project 的容器、network，甚至在某些
命令参数下带到 volume。OPS01 的目标是“一次只动一个服务”，所以 safe release
真实流程只允许目标 backend 或 frontend 容器被替换，不允许使用 `down`。

OPS01D-1 只做 dry-run，本轮连目标容器也没有实际删除或重建。

## 8. 为什么必须明确 project name

production project 是：

```text
barong-ops-console-prod
```

staging project 是：

```text
barong-ops-console-staging
```

如果 Compose 命令不显式带 `-p project`，Compose 会根据目录名推导 project name。
这会带来误伤风险：可能找错容器、建出另一套名字相近的容器，或者影响默认 project。

所以 safe release 的所有 Compose v1 命令都必须同时写清楚：

```text
docker-compose -p PROJECT -f COMPOSE ...
```

OPS01D-1 复核到 production dry-run 中的 would-run 命令都带
`-p barong-ops-console-prod -f docker-compose.production.yml`。

## 9. 安全门禁复核

本轮复核到脚本仍满足：

- 默认模式是 dry-run。
- 真实执行必须显式加 `--execute`。
- production 真实执行必须同时设置
  `CONFIRM_SAFE_RELEASE=yes` 和 `CONFIRM_PRODUCTION_RELEASE=yes`。
- staging 真实执行只需要设置 `CONFIRM_SAFE_RELEASE=yes`。
- env 只允许 `staging` / `production`。
- target service 只允许 `backend` / `frontend`。
- postgres target 被拒绝。
- 所有 Compose v1 命令必须带 `-p project` 和 `-f compose`。
- 脚本不包含 `docker-compose down`。
- 脚本不包含 `docker stop` 或 `docker restart`。
- 脚本不使用无 project name 的 Compose `up`。

本轮还增强了 dry-run 输出和 `check_safe_release_plan.sh`，让这些门禁在 production
dry-run 中直接可见，并被检查脚本覆盖。

## 10. OPS01D-2 下一步

OPS01D-2 才能做 production safe release 真实演练。进入 OPS01D-2 前仍然不接真实
业务。

OPS01D-2 必须遵守：

- 先跑 production/staging smoke 和 dual-env check。
- 先打 rollback tag，保留发布前正在运行的目标镜像引用。
- 一次只动一个服务。
- 顺序必须先 backend，再 frontend。
- backend 通过 health check 和 smoke 后，才允许进入 frontend。
- production 真实执行必须同时设置
  `CONFIRM_SAFE_RELEASE=yes` 和 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 仍然禁止 postgres、禁止 `down`、禁止读取真实 env、禁止修改 Nginx/证书、禁止接
  真实业务。

## 11. 结论

OPS01D-1 通过。

production backend/frontend safe release dry-run 映射正确，double confirmation
门禁存在，postgres target 被禁止，`down` 被禁止，production/staging smoke 和
dual-env check 均通过。

当前还没有真实发布 production。下一步是 OPS01D-2：按 backend 再 frontend 的顺序
做 production safe release 真实演练。
