# OPS01C Staging Safe Release Acceptance

日期：2026-06-10 UTC

本文件记录 OPS01C：在 staging 测试服真实演练 safe release 流程。

这次只演练 `scripts/safe_compose_release.sh` 对 staging backend 和 staging
frontend 的发布方式，目的是验证它能替代以前容易触发
`docker-compose` v1 `--force-recreate` 的发布动作，绕开
`KeyError: 'ContainerConfig'` 老问题。

## 1. 本轮边界

本轮只允许操作 staging backend 和 staging frontend。

实际遵守情况：

- 没有执行 production safe release。
- 没有执行 production `docker-compose up/down`。
- 没有 stop、restart、rm 任何 production 容器。
- 没有 stop、restart、rm staging postgres。
- 没有删除 staging volume 或 network。
- 没有读取或打印 `.env.production` / `.env.staging` 内容。
- 没有打印 secret、token、password 或 Authorization header。
- 没有修改 Nginx 或证书。
- 没有 reload/restart Nginx。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务任务。
- 没有新增 migration。
- 没有 git commit。

production 相关动作只做只读 smoke/status 检查，用来确认 staging 演练没有影响
production。

## 2. 为什么只在 staging 演练

当前 production 正常可用，不能拿 production 去试发布工具链。

staging 和 production 的服务形态一致，但 staging 只绑定本机测试端口：

- staging frontend：`127.0.0.1:3100`
- staging backend：`127.0.0.1:8100`
- staging postgres：只在 Docker 内网暴露 `5432/tcp`

所以 OPS01C 先在 staging 演练 backend/frontend 单服务发布。只有 staging 通过后，
OPS01D 才能进入 production safe release 演练和流程治理。

## 3. safe release 怎么绕开 ContainerConfig

老问题出现在 `docker-compose` v1 强制重建已有容器时。v1 会读取旧容器和镜像
metadata，遇到新 Docker Engine 或新镜像 metadata 时可能读不到
`ContainerConfig`，于是抛：

```text
KeyError: 'ContainerConfig'
```

safe release 脚本不走 `--force-recreate`。它把流程拆开：

1. 先跑目标环境 smoke。
2. build 目标 service 镜像。
3. 给当前正在运行的目标 service 镜像打 rollback tag。
4. 只删除目标 service 容器。
5. 用 `docker-compose -p PROJECT -f COMPOSE up -d --no-deps --no-build SERVICE`
   创建目标 service。
6. 等目标 health 通过。
7. 再跑目标环境 smoke。

这样 Compose v1 不需要按旧容器执行强制重建，也不会带着 postgres 或其他依赖一起动。

## 4. 演练前检查

演练前执行并确认：

- `git status --short --untracked-files=all`：干净。
- `git log --oneline --max-count=8`：最新提交为
  `1e6d686 OPS01B-alt add safe compose v1 release dry-run`。
- `./scripts/check_safe_release_plan.sh`：通过。
- `./scripts/safe_compose_release.sh --env staging --service backend --dry-run`：
  显示 `mapping: staging/backend`，目标 service 是 `console_staging_backend`。
- `./scripts/safe_compose_release.sh --env staging --service frontend --dry-run`：
  显示 `mapping: staging/frontend`，目标 service 是 `console_staging_frontend`。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。

演练前容器状态确认：

- staging frontend 运行中，绑定 `127.0.0.1:3100->3000/tcp`。
- staging backend 运行中，绑定 `127.0.0.1:8100->8000/tcp`。
- staging postgres 运行中且 healthy，只暴露 Docker 内网 `5432/tcp`。
- production frontend/backend/postgres 均运行中。
- production postgres healthy，只暴露 Docker 内网 `5432/tcp`。

## 5. Staging Backend Safe Release

实际执行命令：

```bash
CONFIRM_SAFE_RELEASE=yes \
./scripts/safe_compose_release.sh --env staging --service backend --execute
```

说明：当前脚本默认 dry-run，真实执行必须显式加 `--execute`。

结果：

- pre staging smoke 通过。
- backend 镜像 build 成功。
- 生成 rollback tag：
  `barong-ops-console-staging_console_staging_backend:rollback-20260610100243`。
- 脚本只删除目标容器
  `barong-ops-console-staging_console_staging_backend_1`。
- 脚本用 Compose v1 创建目标 service：
  `docker-compose -p barong-ops-console-staging -f docker-compose.staging.yml up -d --no-deps --no-build console_staging_backend`。
- backend health 最终通过。
- post staging smoke 通过。

发布后验证：

- `http://127.0.0.1:8100/health` 返回 `status=ok`，`environment=staging`。
- `http://127.0.0.1:3100/api/backend/health` 返回 `status=ok`，
  `environment=staging`。
- staging backend 容器 Up。
- staging frontend 没有被重建，只作为 smoke/proxy 被只读访问。
- staging postgres 仍 healthy，运行时间保持约 20 小时，未被重建。
- production smoke 通过。

## 6. Staging Frontend Safe Release

实际执行命令：

```bash
CONFIRM_SAFE_RELEASE=yes \
./scripts/safe_compose_release.sh --env staging --service frontend --execute
```

结果：

- pre staging smoke 通过。
- frontend 镜像 build 成功。
- 生成 rollback tag：
  `barong-ops-console-staging_console_staging_frontend:rollback-20260610100511`。
- 脚本只删除目标容器
  `barong-ops-console-staging_console_staging_frontend_1`。
- 脚本用 Compose v1 创建目标 service：
  `docker-compose -p barong-ops-console-staging -f docker-compose.staging.yml up -d --no-deps --no-build console_staging_frontend`。
- frontend `/login` health 最终通过。
- post staging smoke 通过。

发布后验证：

- `http://127.0.0.1:3100/login` 返回 `200`。
- `http://127.0.0.1:3100/users` 返回 `200`。
- `http://127.0.0.1:3100/api/backend/health` 返回 `status=ok`，
  `environment=staging`。
- staging frontend 容器 Up。
- staging backend 没有被重建，只作为反代 health 目标被只读访问。
- staging postgres 仍 healthy，运行时间保持约 20 小时，未被重建。
- production smoke 通过。

## 7. 最终复核

最终再次执行：

- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- staging `docker ps`：frontend/backend Up，postgres Up healthy。
- production `docker ps`：frontend/backend Up，postgres Up healthy。

最终 rollback tag 查询包含：

- `barong-ops-console-staging_console_staging_backend:rollback-20260610100243`
- `barong-ops-console-staging_console_staging_frontend:rollback-20260610100511`

本阶段只确认 rollback tag 已生成。rollback tag 的作用是保留发布前正在跑的镜像引用，
方便后续人工回滚时有明确对象。本阶段不执行 rollback。

## 8. 结论

OPS01C staging safe release 演练通过。

结论：

- safe release 脚本已经真实发布 staging backend。
- safe release 脚本已经真实发布 staging frontend。
- 两次发布都绕开了 `--force-recreate`。
- 两次发布都没有触发 `KeyError: 'ContainerConfig'`。
- 两次发布都只删除并重建目标 staging service 容器。
- staging postgres 没有被删除、停止、重启或重建。
- production 没有被发布、停止、重启、删除或重建。
- staging smoke 通过。
- production smoke 通过。
- rollback tag 已生成。
- 没有读取真实 env。
- 没有修改 Nginx 或证书。
- 没有接真实业务。

下一步 OPS01D：基于 OPS01C 结果，治理 production safe release 演练/发布流程。
OPS01D 必须先 dry-run，必须显式确认 production 映射和 project name，必须继续禁止
postgres、禁止 `down`、禁止读取真实 env、禁止接真实业务。
