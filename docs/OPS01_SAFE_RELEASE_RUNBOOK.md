# OPS01 Safe Release Runbook

日期：2026-06-10 UTC

## 1. 这份 runbook 解决什么

当前服务器短期内继续使用 Ubuntu `docker.io` 自带的 Docker Engine 和
`docker-compose` v1.29.2。OPS01B 原本想安装 Compose v2，但当前 apt 源找不到
`docker-compose-plugin`，不能在业务发布过程中临时改系统源、下载二进制或升级
Docker。

所以 OPS01B-alt 先做一件更稳的事：把已经人工验证过的绕过流程写成安全脚本和
检查脚本。OPS01B-alt 只准备，不真实发布 staging 或 production。

OPS01C 已经在 staging 真实演练 backend 和 frontend safe release。演练记录见
`docs/OPS01_STAGING_SAFE_RELEASE_ACCEPTANCE.md`。

OPS01D-1 已经对 production backend/frontend 完成 safe release dry-run 和映射
复核。归档见 `docs/OPS01_PRODUCTION_SAFE_RELEASE_DRY_RUN.md`。OPS01D-1 没有真实
发布 production。

OPS01D-2 已经对 production backend 和 production frontend 完成 safe release 真实
演练。归档见 `docs/OPS01_PRODUCTION_SAFE_RELEASE_ACCEPTANCE.md`。两次 production
执行都使用 `CONFIRM_SAFE_RELEASE=yes`、`CONFIRM_PRODUCTION_RELEASE=yes` 和
`--execute`，都通过 `scripts/safe_compose_release.sh`，没有触发
`KeyError: 'ContainerConfig'`。

OPS01B-alt 阶段没有删除容器、没有重建容器、没有启动发布、没有读取真实 env、
没有修改 Nginx 或证书。OPS01C 只删除并重建 staging backend/frontend 目标容器，
没有动 staging postgres，也没有动 production。OPS01D-2 只发布 production
backend/frontend 目标容器，没有动 production postgres，没有动 staging，没有修改
Nginx/证书，也没有接真实业务。

OPS01E 已完成最终只读复核和封板，封板记录见
`docs/OPS01_SAFE_RELEASE_SEAL.md`。OPS01E 没有执行真实 release，也没有安装 Compose
v2。OPS01 封板后，backend/frontend 发布默认走
`scripts/safe_compose_release.sh`，下一阶段回到 C05 权限系统。

## 2. 为什么不用 --force-recreate

`--force-recreate` 会强迫 Compose 按旧容器信息重建服务。当前服务器只有
`docker-compose` v1，这个老版本在重建 backend/frontend 时多次触发：

```text
KeyError: 'ContainerConfig'
```

这类错误发生在发布工具层，不代表业务代码坏了。问题是 Compose v1 在处理旧容器和
新镜像 metadata 时，会去读 `ContainerConfig`。新 Docker Engine 或新镜像返回的
metadata 里这个字段不稳定，于是 v1 抛错。

如果发布流程已经影响了目标容器，再遇到这个错误，就可能让 backend/frontend 发布
卡住。因此现在不再把 `--force-recreate` 作为 backend/frontend 的安全发布方式。

## 3. 为什么现在不安装 Compose v2

当前事实是：

- Docker Engine 来自 Ubuntu `docker.io`。
- `docker-compose` v1 是 1.29.2。
- `docker compose` v2 不存在。
- apt 当前找不到 `docker-compose-plugin`。

要安装 Compose v2，可能需要改 apt 源、安装 Docker 官方源或下载二进制。那些都是
服务器工具链变更，应该单独评估和演练，不能混进当前发布风险治理里。

Compose v2 后续可以继续评估，但它不阻塞当前 safe release 流程，也不阻塞 C05 主线。

## 4. safe release 脚本目标

`scripts/safe_compose_release.sh` 的目标是把允许的发布范围写死：

- 只允许 `staging` 或 `production`。
- 只允许 `backend` 或 `frontend`。
- 禁止 `postgres` 作为 target。
- 所有 `docker-compose` 命令必须带 `-p PROJECT` 和 `-f COMPOSE`。
- 默认永远是 dry-run。
- 真实执行必须显式加 `--execute`。
- 真实执行必须设置 `CONFIRM_SAFE_RELEASE=yes`。
- production 真实执行还必须设置 `CONFIRM_PRODUCTION_RELEASE=yes`。

真实执行流程设计为：

1. 跑目标环境 pre smoke check。
2. build 目标服务镜像。
3. 给当前正在运行的目标服务镜像打 rollback tag。
4. 只移除目标服务容器。
5. 用 `docker-compose -p PROJECT -f COMPOSE up -d --no-deps --no-build SERVICE`
   创建目标服务。
6. 等目标健康检查通过。
7. 跑目标环境 post smoke check。

OPS01B-alt 只验证 dry-run 和静态检查，不执行真实发布流程。

## 5. dry-run 怎么用

先跑总检查：

```bash
./scripts/check_safe_release_plan.sh
```

分别看四个允许 target 的计划：

```bash
./scripts/safe_compose_release.sh --env staging --service backend --dry-run
./scripts/safe_compose_release.sh --env staging --service frontend --dry-run
./scripts/safe_compose_release.sh --env production --service backend --dry-run
./scripts/safe_compose_release.sh --env production --service frontend --dry-run
```

dry-run 只打印映射和将来会执行的步骤，不会 build、不会删除容器、不会执行
`docker-compose up`。production dry-run 会额外打印 double confirmation 门禁：
真实执行必须同时有 `CONFIRM_SAFE_RELEASE=yes` 和
`CONFIRM_PRODUCTION_RELEASE=yes`。

## 6. staging 后续怎么演练

OPS01C 已经按下面顺序在 staging 做完真实演练：

1. 先确认 production smoke、staging smoke、dual-env status 都通过。
2. 先选 staging backend，执行 dry-run，确认 project、compose file、service、
   container、health URL 都正确。
3. 设置 `CONFIRM_SAFE_RELEASE=yes`，只对 staging backend 执行 `--execute`。
4. 发布后跑 staging smoke 和 dual-env status。
5. backend 通过后，再按同样方式演练 staging frontend。

OPS01C 没有跳过 smoke check，没有碰 postgres，没有改 Nginx/证书，没有接真实
业务。结果是 staging backend 和 staging frontend safe release 都通过，production
smoke 仍通过。

## 7. OPS01C 演练结果

2026-06-10 UTC，OPS01C 在 staging 完成真实演练：

- staging backend safe release 通过。
- staging frontend safe release 通过。
- 两次发布都没有使用 `--force-recreate`。
- 两次发布都只删除并重建目标 staging service 容器。
- staging postgres 仍 healthy，未被停止、删除、重启或重建。
- production 只做 smoke/status 只读检查，未被发布或重建。
- staging smoke、production smoke、dual-env status 最终都通过。
- 已生成 staging rollback tag：
  `barong-ops-console-staging_console_staging_backend:rollback-20260610100243`
  和
  `barong-ops-console-staging_console_staging_frontend:rollback-20260610100511`。

## 8. production 后续怎么使用

OPS01D 已经用于 production 真实演练。production 使用前必须已经完成 OPS01C staging
演练和 OPS01D-1 production dry-run。OPS01D-2 已经按 backend 再 frontend 的顺序完成
真实演练。

production 真实执行需要两个确认变量：

```bash
CONFIRM_SAFE_RELEASE=yes \
CONFIRM_PRODUCTION_RELEASE=yes \
./scripts/safe_compose_release.sh --env production --service backend --execute
```

production frontend 同理。后续所有 production backend/frontend 发布都应该优先使用
`scripts/safe_compose_release.sh`，而不是
`docker-compose --force-recreate`。每次真实发布前仍必须先 dry-run，确认映射仍然是：

- project：`barong-ops-console-prod`
- compose：`docker-compose.production.yml`
- backend service：`console_backend`
- frontend service：`console_frontend`
- backend container：`barong-ops-console-prod_console_backend_1`
- frontend container：`barong-ops-console-prod_console_frontend_1`

production 发布必须一次只动一个服务，先有 rollback tag，再等 health check 和 smoke
通过。OPS01D 不能绕过 staging，不能在不确认 project name 的情况下运行。

OPS01D-2 的 production 演练结果：

- production backend safe release 通过。
- production frontend safe release 通过。
- 两次都使用 double confirmation 和 `--execute`。
- 两次都没有触发 `KeyError: 'ContainerConfig'`。
- production smoke、staging smoke 和 dual-env check 都通过。
- production postgres 未被动到。
- staging 未被动到。

## 9. rollback tag 的意义

发布前脚本会把当前正在运行的目标服务镜像打一个 rollback tag，例如：

```text
barong-ops-console-prod_console_backend:rollback-YYYYmmddHHMMSS
```

它的意义是保留“发布前正在跑的那版镜像”的明确引用。这样如果新镜像发布后健康检查
不过，后续人工回滚时能知道上一版镜像是哪一个。

OPS01B-alt 只准备这个机制，不实际打 tag。OPS01C 已经在 staging backend/frontend
演练中生成 rollback tag。OPS01D-2 已经在 production backend/frontend 演练中生成
rollback tag：

- `barong-ops-console-prod_console_backend:rollback-20260610103907`
- `barong-ops-console-prod_console_frontend:rollback-20260610104306`

本阶段只确认 tag 存在，不执行 rollback。

## 10. 绝对禁止项

这些规则在 OPS01B-alt、OPS01C、OPS01D 都必须遵守：

- 不允许 `down`。
- 不允许动 postgres。
- 不允许无 project name 的 `docker-compose`。
- 不允许绕过 safe release 流程直接操作 production。
- 不允许跳过 staging。
- 不允许读取或打印 `.env.production` / `.env.staging`。
- 不允许修改 Nginx 或证书。
- 不允许接真实业务。

## 11. 阶段边界

OPS01B-alt 只完成脚本、文档和 dry-run 检查。

OPS01C 已完成 staging 真实演练。

OPS01D-1 已完成 production dry-run。

OPS01D-2 已完成 production 真实演练，且使用了 double confirmation。

OPS01D-3 已完成只读复核和归档。

OPS01E 已完成最终封板。当前仍未安装 Compose v2；后续 backend/frontend 发布优先使用
`scripts/safe_compose_release.sh`，不再默认使用
`docker-compose --force-recreate`。下一阶段回到 C05：权限系统。
