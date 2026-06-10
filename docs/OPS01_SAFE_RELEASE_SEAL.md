# OPS01 Safe Release Seal

日期：2026-06-10 UTC

本文件是 OPS01E 的最终封板记录。OPS01E 只做只读复核和文档封板，没有安装工具，
没有升级 Docker，没有重建容器，没有停止或删除容器，没有真实发布，没有读取真实
env，没有修改 Nginx 或证书，也没有接真实业务。

## 一、OPS01 最终结论

OPS01 的目标是治理 Docker Compose v1 `KeyError: 'ContainerConfig'` 这个发布老问题。
这个目标已经完成。

当前结论很简单：

- 当前服务器仍然使用 `docker-compose` v1.29.2。
- 当前没有安装 Docker Compose v2。
- 当前不改 Docker apt 源，不下载 Compose 二进制，不升级 Docker。
- 当前采用 `scripts/safe_compose_release.sh` 这条 safe release 路线。
- staging backend/frontend 已经真实演练通过。
- production backend/frontend 已经 dry-run 复核并真实演练通过。
- 后续 backend/frontend 发布优先使用 `scripts/safe_compose_release.sh`。
- 后续不再把 `docker-compose --force-recreate` 当作 backend/frontend 默认发布方式。

OPS01E 本轮只复核这些结论并补齐文档，没有执行真实 release。

## 二、问题根因

问题根因不是业务代码，也不是登录页或 API 坏了。

当前服务器上的 `docker-compose` 是 v1.29.2。这个老版本在 recreate 旧容器时，会读取
旧容器和新镜像 metadata 里的 `ContainerConfig` 字段。新版 Docker / 新镜像 metadata
里这个字段不稳定，Compose v1 读不到时就会抛：

```text
KeyError: 'ContainerConfig'
```

这个问题反复出现在 backend/frontend 发布时，因为 backend/frontend 会频繁替换旧容器。
如果继续使用 `--force-recreate`，Compose v1 就容易再次走到这条失败路径。

## 三、已完成清单

OPS01 已按下面顺序完成：

- OPS01A：完成 Docker Compose v1 `ContainerConfig` 问题只读审计与治理方案。
- OPS01B：Compose v2 安装路线因 apt 源没有 `docker-compose-plugin` 候选包而暂停。
- OPS01B-alt：新增 `scripts/safe_compose_release.sh` 和
  `scripts/check_safe_release_plan.sh`，准备 v1 safe release 路线。
- OPS01C：staging backend/frontend safe release 真实演练成功。
- OPS01D-1：production backend/frontend safe release dry-run 与映射复核成功。
- OPS01D-2：production backend/frontend safe release 真实演练成功。
- OPS01D-3：production safe release 归档完成。
- OPS01E：最终只读复核和文档封板完成。

## 四、safe release 标准流程

后续 backend/frontend 发布的标准流程是：

1. 跑目标环境 pre smoke check。
2. build 目标 service 镜像。
3. 给当前正在运行的目标 service 镜像打 rollback tag。
4. 只移除目标 backend/frontend 容器。
5. 用下面这种形式创建目标 service：

```bash
docker-compose -p PROJECT -f COMPOSE up -d --no-deps --no-build SERVICE
```

6. 等目标 health check 通过。
7. 跑目标环境 post smoke check。
8. 跑 dual env check，确认 production 和 staging 都正常。

这个流程的核心是一次只动一个 backend/frontend 服务，不走 `--force-recreate`，不带着
postgres 或其他依赖服务一起动。

## 五、安全门禁

safe release 的安全门禁必须继续保留：

- 默认是 dry-run。
- staging 真实执行必须设置 `CONFIRM_SAFE_RELEASE=yes`。
- production 真实执行必须同时设置：
  - `CONFIRM_SAFE_RELEASE=yes`
  - `CONFIRM_PRODUCTION_RELEASE=yes`
- `postgres` target 禁止。
- `docker-compose down` 禁止。
- `docker stop` / `docker restart` 禁止。
- 无 project name 的 Compose 命令禁止。
- 所有 Compose v1 命令必须显式带 `-p PROJECT` 和 `-f COMPOSE`。
- 每次真实发布前都必须先 dry-run，确认 env、project、compose file、service、
  container 和 health URL 映射正确。

## 六、适用范围

OPS01 safe release 只适用于：

- staging backend
- staging frontend
- production backend
- production frontend

## 七、不适用范围

OPS01 safe release 不适用于：

- postgres
- Nginx
- HTTPS / certbot
- MinIO / Filebrowser
- n8n
- WooCommerce
- P 系列真实业务

这些对象如果以后要变更，必须另开任务、重新定义范围和验收标准。

## 八、rollback tag

rollback tag 的作用是保留“发布前正在跑的那版镜像”的明确引用。它是恢复参考，不是
自动回滚机制。

OPS01C 和 OPS01D-2 已生成 backend/frontend rollback tag。OPS01E 只确认 rollback tag
存在，没有执行 rollback。

本阶段确认到的关键 rollback tag 包括：

- `barong-ops-console-staging_console_staging_backend:rollback-20260610100243`
- `barong-ops-console-staging_console_staging_frontend:rollback-20260610100511`
- `barong-ops-console-prod_console_backend:rollback-20260610103907`
- `barong-ops-console-prod_console_frontend:rollback-20260610104306`

后续如果真的需要 rollback，必须单独开任务，先 staging，再 production；不能在普通
发布任务里临时决定回滚。

## 九、后续建议

后续可以单独评估 Docker Compose v2 和 Docker 官方 apt 源，但这不属于 OPS01E，也不
阻塞当前主线。

当前 C04 已封板，OPS01 已封板。下一阶段应回到 C05：权限系统。后续 C05/C06 等阶段
如果需要发布 backend/frontend，应使用 `scripts/safe_compose_release.sh`，不要默认
使用 `docker-compose --force-recreate`。

## 十、OPS01 封板结论

OPS01 已完成。

Docker Compose v1 `ContainerConfig` 老问题已经有稳定治理流程：backend/frontend 发布
走 safe release，默认 dry-run，真实执行受确认变量保护，一次只动一个服务，postgres
禁止作为 target，production 必须 double confirmation。

OPS01E 最终只读复核结果：

- `./scripts/check_safe_release_plan.sh`：通过。
- staging backend dry-run：映射正确。
- staging frontend dry-run：映射正确。
- production backend dry-run：映射正确。
- production frontend dry-run：映射正确。
- `./scripts/production_smoke_check.sh`：通过。
- `./scripts/staging_smoke_check.sh`：通过。
- `./scripts/check_dual_env_status.sh`：通过。
- rollback tag：存在。
- 本轮没有真实 release。

最终结论：后续不再把 `docker-compose --force-recreate` 作为 backend/frontend 默认发布
方式；C05 及后续 backend/frontend 发布优先使用 `scripts/safe_compose_release.sh`。
