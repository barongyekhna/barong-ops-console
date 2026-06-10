# OPS01 Docker Compose Governance Plan

日期：2026-06-10 UTC

## 1. OPS01A 只做什么

OPS01A 只做只读审计和治理方案。

本轮没有安装软件，没有升级 Docker 或 Compose，没有执行 `docker-compose up/down`，
没有执行 `docker compose up/down`，没有停止、重启、删除或重建 production /
staging 容器，没有读取真实 `.env.production` 或 `.env.staging`，没有修改
Nginx 或证书，也没有接真实业务。

## 2. 问题是什么

production 和 staging 现在都能正常访问，但发布 backend/frontend 时反复遇到
Docker Compose v1 的错误：

```text
KeyError: 'ContainerConfig'
```

这不是业务代码错误，也不是登录/API 本身坏了。它发生在发布工具尝试重建或替换
已有容器时，Compose v1 进入了老的 Python 实现路径，去读取新 Docker Engine 或
新镜像元数据里已经不稳定的 `ContainerConfig` 字段。

实际表现是：

- backend/frontend 的新容器发布过程会卡住。
- 已经在跑的旧容器通常还在，所以站点可能仍然可用。
- 手动删除已经停止的目标旧容器后，再用只动目标服务的 `--no-deps --no-build`
  命令创建容器，可以绕过这条失败路径。

## 3. 为什么会反复出现

当前服务器只有 `docker-compose` v1 可用。Compose v1 已经是老工具，它在重建容器
时会尝试合并旧容器、旧镜像和 volume 信息，其中一段逻辑会访问
`ContainerConfig`。新 Docker Engine 和新镜像 metadata 组合下，这个字段可能不在
返回结果里，于是 v1 抛出 `KeyError`。

反复出现在 backend/frontend 发布时，原因是这两个服务经常被重新 build 和
recreate。Postgres 通常不动，所以不常触发。只要旧的 backend/frontend 容器存在，
尤其是有停止态残留时，v1 就可能走“按旧容器信息重建”的路径。

删除已停止的目标容器后能恢复，是因为 Compose 不再需要从那个旧容器读取和合并
metadata，而是按 compose 文件直接创建目标服务容器。

## 4. 当前服务器 Docker / Compose 状态

本轮只读确认到：

- Docker Engine：`29.1.3`
- Docker Client：`29.1.3`
- 系统：Ubuntu 24.04.4 LTS
- `docker-compose` v1：`1.29.2`
- `docker-compose` 路径：`/usr/bin/docker-compose`
- `docker` 路径：`/usr/bin/docker`
- `docker compose` v2：不存在，执行结果是 `docker: unknown command: docker compose`
- Docker CLI plugin 目录：`/usr/libexec/docker/cli-plugins` 只有 `docker-trust`
- `/usr/local/lib/docker/cli-plugins` 和 `/usr/lib/docker/cli-plugins` 当前不存在

结论：当前服务器实际只能使用 Compose v1。项目脚本虽然很多地方写了
`docker compose` 优先、`docker-compose` fallback，但在这台服务器上会落到
`docker-compose` v1。

当前 Barong Ops Console 运行面：

- production frontend：`barong-ops-console-prod_console_frontend_1`，Up，
  `127.0.0.1:3000->3000/tcp`
- production backend：`barong-ops-console-prod_console_backend_1`，Up，
  `127.0.0.1:8000->8000/tcp`
- production postgres：`barong-ops-console-prod_console_postgres_1`，Up healthy，
  只在 Docker 内网暴露 `5432/tcp`
- staging frontend：`barong-ops-console-staging_console_staging_frontend_1`，Up，
  `127.0.0.1:3100->3000/tcp`
- staging backend：`barong-ops-console-staging_console_staging_backend_1`，Up，
  `127.0.0.1:8100->8000/tcp`
- staging postgres：`barong-ops-console-staging_console_staging_postgres_1`，Up
  healthy，只在 Docker 内网暴露 `5432/tcp`

`docker ps -a --filter name=barong-ops-console` 当前没有显示已停止的 Barong Ops
Console 容器。也就是说，人工清理后的当前运行面是干净的；老问题主要发生在发布
过程，不是当前仍有目标 stopped 容器残留。

## 5. 当前项目 Compose 使用情况

脚本扫描结果：

| 文件 | Compose 使用 | 说明 |
| --- | --- | --- |
| `scripts/test_backend_docker.sh` | `docker compose` 优先，fallback `docker-compose`；`build backend`；`run --rm --no-deps backend` | example-only 测试，当前服务器会落到 v1；没有显式 project name |
| `scripts/test_backend_db_docker.sh` | `-p barong-ops-console-f12-test`；`build backend`；`up --detach db`；`run --rm backend`；退出时 `down --volumes --remove-orphans` | example-only 测试 project，会清理自己的测试资源 |
| `scripts/test_frontend_docker.sh` | `-p barong-ops-console-f11-frontend-test`；`build frontend` | example-only frontend build 测试 |
| `scripts/bootstrap_owner_docker.sh` | `COMPOSE_PROJECT_NAME` 默认 `barong-ops-console-example`；`build backend`；`up --detach db`；`run --rm backend` | example-only owner bootstrap |
| `scripts/check_production_deploy_files.sh` | `docker compose` 优先，fallback `docker-compose`；只跑临时目录里的 `config` | 用 `.env.production.example` 替换真实 env，不读取真实 `.env.production` |
| `scripts/check_staging_deploy_files.sh` | `docker compose` 优先，fallback `docker-compose`；只跑临时目录里的 `config` | 用 `.env.staging.example` 复制成临时 env，不读取真实 `.env.staging` |
| `scripts/test_foundation_acceptance.sh` | 调用 Docker 测试脚本，再跑 `docker-compose.example.yml config` | example-only 验收 |
| `scripts/production_smoke_check.sh` | `docker ps --filter name=console_` | 只读检查 |
| `scripts/staging_smoke_check.sh` | `docker ps --filter name=staging` | 只读检查 |
| `scripts/check_dual_env_status.sh` | `docker ps --format ...` | 只读检查 production + staging |

文档和 README 扫描结果：

- `docs/C01_PRODUCTION_DEPLOYMENT.md` 仍保留历史 production 发布命令：
  `build`、`up -d console_postgres`、`run --rm console_backend`、
  `up -d --force-recreate console_backend console_frontend`、`up -d ...`。
  其中 `--force-recreate` 是当前 v1 问题的高风险触发点。
- `docs/C02_STAGING_SETUP.md` 保留历史 staging 启动命令：
  `docker-compose -p barong-ops-console-staging -f docker-compose.staging.yml config`
  和 `up -d --build`。
- `README.md` 的临时 preview / example 章节有 `docker-compose ... up --build`、
  `docker-compose ... down --volumes --remove-orphans`、`docker-compose ...
  config`、`docker compose ... run --rm`、`docker compose ... up --build` 等
  example-only 命令。
- `docs/C03_STAGING_ACCEPTANCE.md` 和 `docs/C04_STAGING_ACCEPTANCE.md` 有历史
  `docker exec` 验收记录。
- 没有发现 `docker logs` 或 Compose `logs` 命令。
- 仓库里发现 `--no-deps`，没有发现 `--no-build`。`--no-build` 是背景里人工恢复
  命令的一部分，不是当前脚本里的固定用法。

production / staging / example project name 状态：

- production 当前容器名显示 project 是 `barong-ops-console-prod`。
- staging 明确使用 `barong-ops-console-staging`。
- example/test 脚本使用 `barong-ops-console-example`、
  `barong-ops-console-f11-frontend-test`、`barong-ops-console-f12-test` 等。
- production 历史文档命令没有全部显式写 `-p barong-ops-console-prod`，后续正式
  发布脚本必须补上。

## 6. 风险分析

`ContainerConfig` 问题对 production 登录/API 的直接影响是发布风险，不是运行时
业务逻辑风险：

- 如果旧容器仍在运行，登录和 API 可能继续正常。
- 如果发布流程先停掉旧容器再触发 v1 错误，就可能造成 frontend/backend 短时不可用。
- 如果误用 `down`，postgres、network、依赖服务都可能被带着处理，风险明显放大。
- 如果 production 发布没有显式 project name，就可能误伤默认 project 或其他同名服务。

不能在 C04E 中途直接升级工具，原因也很直接：

- C04E 是业务功能发布验收，不是部署工具升级窗口。
- Compose v1 到 v2 的行为有差异，需要单独验收 project name、容器名、network、
  volume、env 解析、`depends_on`、`run`、`config` 和 rollback 流程。
- 中途升级会把“业务发布问题”和“部署工具变化问题”混在一起，出问题不好定位。
- production 正常时，不应该为了修发布工具而临时改变生产部署链路。

治理必须单独做，并且先 staging 演练。原因是 staging 可以暴露脚本、project name、
service selector 和 smoke check 的问题，而不会影响 production 登录/API。

## 7. 三种治理方案

### 方案 A：安装或启用 Docker Compose v2

做法：

- 先只读确认 v2 是否已经存在。
- 如果不存在，在单独 OPS01B 安装或启用 Docker Compose v2。
- 发布脚本优先使用 `docker compose`，保留 `docker-compose` v1 fallback。
- 在 staging 先演练 backend/frontend 单服务发布。
- 验证通过后再用于 production。

优点：

- 从根上避开 Compose v1 的 `ContainerConfig` 老 bug。
- 项目脚本已经有 v2 优先、v1 fallback 的习惯，改造成本较低。
- 以后 Docker Engine 继续升级时更稳。

风险：

- 安装或启用 v2 本身是服务器工具变更，不能夹在业务发布中做。
- v2 和 v1 的输出、容器重建判断、wait 参数、project 解析可能有差异，必须先在
  staging 验证。

### 方案 B：不升级工具，只改发布流程

做法：

- 继续使用 Compose v1。
- 禁止 production/staging 发布流程使用 `--force-recreate` 作为默认动作。
- 发布前明确检查目标服务容器状态。
- 如果目标服务存在停止态旧容器，按审批流程只删除目标旧容器，再创建目标服务。
- 命令必须带 project name、compose file 和服务名，只允许 backend/frontend，
  postgres 默认不可重建。

优点：

- 不改变服务器工具链。
- 能解释并规避当前已知绕过方式。

风险：

- 仍然依赖 Compose v1，未来 Docker Engine 或镜像 metadata 变化还可能触发别的问题。
- 删除旧容器这一步如果脚本保护不严，可能误删正在运行的 production 容器。
- 必须把人工兜底流程写得非常硬，否则风险转移到操作习惯上。

### 方案 C：短期保留人工兜底，新增安全发布脚本模板

做法：

- 不立刻安装 v2，也不马上改现有生产流程。
- 新增脚本模板和文档，明确 target env、project name、compose file、service allowlist、
  禁止 `down`、禁止 postgres、禁止无 project name。
- 人工发布遇到 `ContainerConfig` 时按模板执行检查和兜底。

优点：

- 改动最小。
- 适合 OPS01B 之前的短期过渡。

风险：

- 仍然靠人工判断，不能真正消除 v1 问题。
- 反复发布时，故障还会反复出现。
- 不适合作为长期方案。

## 8. 推荐路线

推荐最稳路线是：以方案 A 为主，方案 C 做短期保护，方案 B 只作为 v2 不可用时的
受控 fallback。

具体顺序：

1. OPS01A 只读确认当前确实没有 Compose v2，本轮已经确认。
2. OPS01B 单独处理 Compose v2 安装/启用或安全 fallback 准备，不和业务发布混做。
3. OPS01C 先改造 staging 发布脚本并演练，只允许指定服务，不允许 `down`，postgres
   默认不可重建。
4. OPS01D 再改造 production 发布脚本并演练，必须显式
   `-p barong-ops-console-prod`，必须只动指定 backend/frontend 服务。本项已经完成：
   OPS01D-1 完成 dry-run，OPS01D-2 完成 backend/frontend production 真实演练。
5. OPS01E 更新文档、回滚流程和封板记录。本项已经完成，封板记录见
   `docs/OPS01_SAFE_RELEASE_SEAL.md`。

脚本设计硬规则：

- 默认禁止 `down`。
- production 发布脚本必须明确 project name。
- staging 发布脚本必须明确 project name。
- production 发布脚本必须只动指定服务。
- postgres 默认不可重建。
- 不读取或打印真实 env。
- Nginx 和证书不在 OPS01 里动。
- 不接真实业务。

## 9. 后续任务拆分

OPS01B：Compose v2 安装/启用或安全 fallback 方案准备

- 只处理工具链，不夹带业务发布。
- 如果安装/启用 v2，记录版本、路径、plugin 目录和回滚办法。
- 如果暂时不能装 v2，准备 v1 fallback 的目标容器检查和人工兜底规则。

OPS01B-alt：Compose v1 安全发布脚本准备

- OPS01B 原安装 Compose v2 路线暂时暂停，因为当前 apt 源找不到
  `docker-compose-plugin`。
- 本阶段不升级 Docker，不安装 Compose v2，不添加 Docker 官方 apt 源，也不通过
  `curl` 下载 compose 二进制。
- 当前采用短期稳妥路线：继续基于 `docker-compose` v1.29.2 准备安全发布脚本。
- 新脚本默认 dry-run，只允许明确的 staging/production backend/frontend target，
  禁止 postgres，禁止无 project name，禁止 `down`。
- OPS01B-alt 只准备脚本、runbook 和 dry-run 检查，不真实发布 staging/production，
  不删除、不停止、不重建容器。
- Compose v2 后续可以作为单独工具链任务再评估，但不打断当前项目。

OPS01C：staging 发布脚本改造与演练

- 已使用 OPS01B-alt 的 `scripts/safe_compose_release.sh` 在 staging 真实演练。
- 明确 project：`barong-ops-console-staging`。
- 只允许 `console_staging_backend` / `console_staging_frontend`。
- 禁止 `down`，默认不动 `console_staging_postgres`。
- 演练后运行 staging smoke、production smoke 和 dual-env check。
- 演练记录见 `docs/OPS01_STAGING_SAFE_RELEASE_ACCEPTANCE.md`。

OPS01D：production 发布脚本改造与演练

- OPS01D-1 已完成 production backend/frontend dry-run 和映射复核，归档见
  `docs/OPS01_PRODUCTION_SAFE_RELEASE_DRY_RUN.md`。
- OPS01D-1 没有真实发布 production，没有 build，没有 `up/down`，没有删除、停止、
  重启或重建任何容器。
- OPS01D-2 已完成 production backend/frontend safe release 真实演练，归档见
  `docs/OPS01_PRODUCTION_SAFE_RELEASE_ACCEPTANCE.md`。
- OPS01D-2 两次真实执行都使用 `CONFIRM_SAFE_RELEASE=yes`、
  `CONFIRM_PRODUCTION_RELEASE=yes` 和 `--execute`。
- 明确 project：`barong-ops-console-prod`。
- 只允许 `console_backend` / `console_frontend`。
- 禁止 `down`，默认不动 `console_postgres`。
- production 真实执行必须 double confirmation：
  `CONFIRM_SAFE_RELEASE=yes` 和 `CONFIRM_PRODUCTION_RELEASE=yes`。
- OPS01D-2 已按一次只动一个服务、先 backend 再 frontend 的顺序完成。
- 发布前后都要运行 production smoke、staging smoke 和 dual-env check。
- production backend/frontend 发布后没有触发 `KeyError: 'ContainerConfig'`。
- production backend/frontend rollback tag 已生成。
- production postgres 未被动到，staging 未被动到，Nginx/证书未修改，未接真实业务。

OPS01E：文档和回滚流程封板

- 已更新 production/staging 发布手册和 OPS01 归档文档。
- 已明确当前没有安装 Compose v2，v2 后续单独评估。
- 已明确当前 v1 fallback 路线是 `scripts/safe_compose_release.sh`。
- 已明确 `ContainerConfig` 复发时的处理边界：backend/frontend 用 safe release，
  postgres、Nginx、证书和真实业务不在 OPS01 范围内。
- 已归档最终验证结果，封板记录见 `docs/OPS01_SAFE_RELEASE_SEAL.md`。

## 10. OPS01A 验证

OPS01A 计划完成后需要运行：

```bash
git status --short --untracked-files=all
./scripts/production_smoke_check.sh
./scripts/staging_smoke_check.sh
./scripts/check_dual_env_status.sh
git diff --check -- docs README.md CHANGELOG.md scripts
```

这些验证只读检查运行状态和文档 diff，不安装工具、不升级 Compose、不重启/删除容器、
不读取真实 env、不修改 Nginx/证书、不接真实业务。

## 11. OPS01B-alt 验证

OPS01B-alt 计划完成后需要运行：

```bash
git status --short --untracked-files=all
./scripts/check_safe_release_plan.sh
./scripts/safe_compose_release.sh --env staging --service backend --dry-run
./scripts/safe_compose_release.sh --env staging --service frontend --dry-run
./scripts/safe_compose_release.sh --env production --service backend --dry-run
./scripts/safe_compose_release.sh --env production --service frontend --dry-run
./scripts/production_smoke_check.sh
./scripts/staging_smoke_check.sh
./scripts/check_dual_env_status.sh
git diff --check -- scripts docs README.md CHANGELOG.md
```

这些验证不安装或升级工具，不运行真实发布模式，不读取真实 env，不修改 Nginx/证书，
不接真实业务。`production_smoke_check.sh`、`staging_smoke_check.sh` 和
`check_dual_env_status.sh` 只做只读运行状态检查。

## 12. OPS01C 验证

OPS01C 已在 2026-06-10 UTC 完成 staging safe release 真实演练。

实际执行范围：

- 真实发布 staging backend。
- 真实发布 staging frontend。
- 不发布 production。
- 不停止、删除、重启或重建 staging postgres。
- 不读取或打印真实 env。
- 不修改 Nginx 或证书。
- 不接真实业务。

验证结果：

- `./scripts/check_safe_release_plan.sh`：通过。
- staging backend dry-run：映射为 `staging/backend`，
  service 为 `console_staging_backend`。
- staging frontend dry-run：映射为 `staging/frontend`，
  service 为 `console_staging_frontend`。
- staging backend safe release：通过。
- staging frontend safe release：通过。
- `./scripts/staging_smoke_check.sh`：最终通过。
- `./scripts/production_smoke_check.sh`：最终通过。
- `./scripts/check_dual_env_status.sh`：最终通过。
- rollback tag 已生成：
  `barong-ops-console-staging_console_staging_backend:rollback-20260610100243`
  和
  `barong-ops-console-staging_console_staging_frontend:rollback-20260610100511`。

OPS01C 说明：本次演练证明当前 v1 safe release 流程可以替代
`docker-compose v1 --force-recreate` 的高风险路径。它只删除目标 service 容器，再用
`up -d --no-deps --no-build SERVICE` 创建目标 service，没有触发
`KeyError: 'ContainerConfig'`。

## 13. OPS01D-1 验证

OPS01D-1 已在 2026-06-10 UTC 完成 production dry-run 和安全门禁复核。

实际执行范围：

- 只读检查 production/staging 当前状态。
- dry-run production backend。
- dry-run production frontend。
- 更新文档和 dry-run 输出门禁说明。
- 没有真实发布 production。
- 没有 build、`up/down`、stop、restart、rm 或 recreate 容器。
- 没有读取或打印真实 env。
- 没有修改 Nginx 或证书。
- 没有接真实业务。

production backend dry-run 映射：

- project：`barong-ops-console-prod`
- compose：`docker-compose.production.yml`
- service：`console_backend`
- container：`barong-ops-console-prod_console_backend_1`
- health：`http://127.0.0.1:8000/health`

production frontend dry-run 映射：

- project：`barong-ops-console-prod`
- compose：`docker-compose.production.yml`
- service：`console_frontend`
- container：`barong-ops-console-prod_console_frontend_1`
- health：`https://ops.barongyekhna.com/login`

验证结果：

- `./scripts/check_safe_release_plan.sh`：通过。
- production backend dry-run：映射正确，double confirmation 显示正确。
- production frontend dry-run：映射正确，double confirmation 显示正确。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。

OPS01D-1 后已经完成 OPS01D-2 production safe release 真实演练。OPS01D-2 按先
backend、后 frontend，一次只动一个服务的顺序执行，先打 rollback tag，再等 health
check 和 smoke 通过。OPS01D-2 没有接真实业务。

## 14. OPS01D-2 / OPS01D-3 验证

OPS01D production safe release 真实演练已在 2026-06-10 UTC 完成，OPS01D-3 已做只读
复核和归档。

实际执行范围：

- 真实发布 production backend。
- 真实发布 production frontend。
- 两次都通过 `scripts/safe_compose_release.sh`。
- 两次都使用 `CONFIRM_SAFE_RELEASE=yes`。
- 两次都使用 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 两次都使用 `--execute`。
- 不发布 staging。
- 不停止、删除、重启或重建 production postgres。
- 不停止、删除、重启或重建 staging。
- 不读取或打印真实 env。
- 不修改 Nginx 或证书。
- 不接真实业务。

验证结果：

- production backend safe release：通过。
- production frontend safe release：通过。
- `KeyError: 'ContainerConfig'` 未复现。
- `https://ops.barongyekhna.com/login`：HTTP 200。
- `https://ops.barongyekhna.com/users`：HTTP 200。
- `https://ops.barongyekhna.com/api/backend/health`：`status=ok`，
  `environment=production`。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- production backend rollback tag 已生成：
  `barong-ops-console-prod_console_backend:rollback-20260610103907`。
- production frontend rollback tag 已生成：
  `barong-ops-console-prod_console_frontend:rollback-20260610104306`。

当前仍未安装 Compose v2，仍保留 `docker-compose` v1.29.2。后续 production
backend/frontend 发布应优先使用 `scripts/safe_compose_release.sh`，不要把
`docker-compose --force-recreate` 作为默认发布方式。

## 15. OPS01E 封板

OPS01E 已在 2026-06-10 UTC 完成最终只读复核和文档封板。

本轮复核确认：

- `./scripts/check_safe_release_plan.sh`：通过。
- staging backend dry-run：映射为 `barong-ops-console-staging` /
  `docker-compose.staging.yml` / `console_staging_backend`。
- staging frontend dry-run：映射为 `barong-ops-console-staging` /
  `docker-compose.staging.yml` / `console_staging_frontend`。
- production backend dry-run：映射为 `barong-ops-console-prod` /
  `docker-compose.production.yml` / `console_backend`。
- production frontend dry-run：映射为 `barong-ops-console-prod` /
  `docker-compose.production.yml` / `console_frontend`。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- rollback tag 查询能看到 staging 和 production backend/frontend rollback tag。

OPS01E 没有安装或升级工具，没有执行真实 safe release，没有设置确认变量，没有读取真实
env，没有修改 Nginx/证书，没有接真实业务，也没有 git commit。

OPS01 结论：Docker Compose v1 `ContainerConfig` 问题治理完成。当前不安装 Compose
v2，后续 backend/frontend 发布默认使用 `scripts/safe_compose_release.sh`。下一阶段
回到 C05：权限系统。
