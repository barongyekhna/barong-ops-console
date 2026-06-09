# C02 Environment Isolation Plan

审计日期：2026-06-09 UTC

## 1. 本文件说什么

C02A 只做两件事：

- 只读审计当前 production，也就是正式服。
- 设计 staging/test，也就是测试服、PBE 的隔离方案。

C02A 不创建测试服，不启动新容器，不改 production，不配置 DNS，不改
Nginx，不申请证书，也不接任何真实业务。

production 是正式服，当前域名是 `https://ops.barongyekhna.com`。以后真实
P 系列、真实 n8n workflow、WooCommerce、MinIO、Filebrowser 只能在明确审
核后的正式任务里接入，不能在 C02A 接入。

staging 是测试服。它用来试新功能、试 migration、试 owner 初始化、试脚本
流程。测试服必须和正式服隔离，不能共用数据库、volume、密钥、真实业务回调
或真实业务账号。

不能直接在 production 测新功能，原因很简单：production 是老板和以后真实业
务要用的正式入口。直接在 production 测功能，可能会改正式数据、覆盖正式
owner、打到真实 webhook、占用正式端口，或者让正式服务停掉。测试服就是为了
把这些风险挡在正式服外面。

C02C 后的当前状态：staging 已经在服务器本机端口启动，owner 已初始化，后端
登录链路已测试通过。C02D 不再接真实业务功能，只补双环境运维文档、只读状态
检查脚本和安全边界说明。

## 2. production 当前状态

本次只读检查确认：

- production frontend 容器：`barong-ops-console-prod_console_frontend_1`。
- production backend 容器：`barong-ops-console-prod_console_backend_1`。
- production postgres 容器：`barong-ops-console-prod_console_postgres_1`。
- production network：`barong-ops-console-prod`。
- production volume：`console_postgres_data`。
- frontend 端口：宿主机 `127.0.0.1:3000` 绑定到容器 `3000/tcp`。
- backend 端口：宿主机 `127.0.0.1:8000` 绑定到容器 `8000/tcp`。
- postgres 只显示容器内 `5432/tcp`，没有绑定宿主机 `5432`。
- `https://ops.barongyekhna.com/login` 返回 `HTTP/2 200`。
- `https://ops.barongyekhna.com/api/backend/health` 返回 `status=ok`，
  `environment=production`，`external_services=not_connected`。
- `http://ops.barongyekhna.com/login` 返回 `301` 到
  `https://ops.barongyekhna.com/login`。
- 证书列表里已有 `ops.barongyekhna.com` 证书，当前有效。
- `nginx -t` 通过。它仍报告已有 n8n 相关 warning，但 Nginx 配置测试结果是
  successful；本阶段没有修改这些站点。
- `docker-compose.production.yml` 结构正常。因为它引用真实
  `.env.production`，本次只在安全临时目录中把 env 文件替换为
  `.env.production.example` 后运行 `docker-compose -f docker-compose.production.yml config`。
- 开始写本文档前，`git status --short --untracked-files=all` 为空，仓库是
  干净的。

本次没有读取或打印 `.env.production`，也没有修改 `.env.production`。

## 3. example/test 当前状态

`docker-compose.example.yml` 现在是本地/example 测试入口，不是 production
入口。它定义：

- `db`：临时 Postgres，使用 example 数据库名、用户名和密码。
- `backend`：连接 compose 内部 `db:5432`。
- `frontend`：连接 compose 内部 `backend:8000`，浏览器侧默认指向
  `http://localhost:8000`。

example compose 不读取 `.env.production`，也不使用 production network
`barong-ops-console-prod` 或 production volume `console_postgres_data`。
所以它不会直接污染 production 数据库。

需要注意的是，example compose 的 frontend/backend 端口仍是
`127.0.0.1:3000` 和 `127.0.0.1:8000`。production 已经占用这两个端口。以后
不能把 example 当 staging 直接长期运行；如果直接 `up`，大概率会和 production
端口冲突。

`scripts/test_foundation_acceptance.sh` 当前仍只使用
`docker-compose.example.yml` 做测试入口。它会调用：

- `scripts/test_backend_docker.sh`：build backend，并用 example compose
  `run --rm --no-deps backend` 跑健康测试；它没有显式 project name，但不会
  启动 production，也不会读取 `.env.production`。
- `scripts/test_backend_db_docker.sh`：使用显式 project
  `barong-ops-console-f12-test`，启动临时 `db`，跑 migration 和 backend
  数据库测试，结束时 `down --volumes --remove-orphans` 清理自己的测试资源。
- `scripts/test_frontend_docker.sh`：使用显式 project
  `barong-ops-console-f11-frontend-test`，build frontend。

当前测试脚本没有发现会主动误碰 production 的行为。风险点是命令习惯：后续不
应该允许没有显式 project name 的 `docker-compose up/down`，也不应该允许
staging 脚本读取 `.env.production`。

## 4. staging 推荐架构

staging 是测试服，不是正式服。建议它以后独立为一个 compose project：

- compose project：`barong-ops-console-staging`。
- frontend：测试服 Next.js runtime。
- backend：测试服 FastAPI runtime。
- postgres：测试服独立 Postgres。
- network：测试服独立 Docker network。
- volume：测试服独立 Postgres volume。
- env：测试服独立 `.env.staging`。

未来可以预留域名：

- `staging.ops.barongyekhna.com`

C02A 不配置这个域名，不写 Nginx，不申请证书。未来如果要开放公网测试服，应
该单独做 DNS、Nginx、HTTPS、访问控制和 smoke check。

## 5. 端口规划

当前端口状态：

- `127.0.0.1:3000` 已被 production frontend 使用。
- `127.0.0.1:8000` 已被 production backend 使用。
- `127.0.0.1:3100` 已被 staging frontend 使用。
- `127.0.0.1:8100` 已被 staging backend 使用。
- console production/staging postgres 都只显示 Docker 内网 `5432/tcp`，不暴露
  宿主机 PostgreSQL 端口。

staging 当前使用：

- staging frontend：`127.0.0.1:3100:3000`。
- staging backend：`127.0.0.1:8100:8000`。
- staging postgres：不暴露宿主机端口，只在 staging Docker network 内部使用
  `5432/tcp`。

如果未来重新规划 staging 端口，备选是：

- frontend 备选：`127.0.0.1:3101`，再不行用 `127.0.0.1:3200`。
- backend 备选：`127.0.0.1:8101`，再不行用 `127.0.0.1:8200`。
- postgres 仍不暴露宿主机端口。

## 6. 命名隔离

建议 staging 命名规范：

- compose project：`barong-ops-console-staging`。
- service names：
  - `console_staging_frontend`
  - `console_staging_backend`
  - `console_staging_postgres`
- Compose 默认容器名会是：
  - `barong-ops-console-staging_console_staging_frontend_1`
  - `barong-ops-console-staging_console_staging_backend_1`
  - `barong-ops-console-staging_console_staging_postgres_1`
- network：`barong-ops-console-staging`。
- volume：`console_staging_postgres_data`。
- env 文件：
  - `.env.staging`
  - `.env.staging.example`

不建议 staging 复用 production 的 service 名、network 名、volume 名或 env 文件
名。

## 7. 数据和密钥隔离

staging 必须满足这些规则：

- production DB 和 staging DB 绝不共用。
- staging 使用独立 Postgres container。
- staging 使用独立 volume：`console_staging_postgres_data`。
- staging owner 是测试账号，不能使用 production owner 密码。
- staging 的 `AUTH_TOKEN_SECRET` 独立生成，不能复制 production secret。
- staging 的 `N8N_TEST_WEBHOOK_URL` 默认空。
- staging 不接真实 n8n webhook。
- staging 不接 WooCommerce。
- staging 不接 MinIO。
- staging 不接 Filebrowser。
- staging 不创建真实业务任务。

production 的 `.env.production` 只能给 production 使用。staging 的
`.env.staging` 只能给 staging 使用。两个环境的 secret、owner 密码、数据库
URL、token secret 都不能交叉复制。

## 8. 命令安全规则

后续脚本和手工命令建议统一遵守：

- production 脚本名称必须带 `production`。
- staging 脚本名称必须带 `staging`。
- 所有脚本开头必须打印当前 target environment，例如
  `target environment: staging`。
- dangerous 命令必须要求显式 project name。
- 禁止无 project name 的 `docker-compose up`。
- 禁止无 project name 的 `docker-compose down`。
- staging 脚本不能读取 `.env.production`。
- production 脚本不能读取 `.env.staging`。
- production compose 命令必须显式使用 production project。
- staging compose 命令必须显式使用 `barong-ops-console-staging`。
- smoke check 只能检查自己的目标环境，不能跨环境复用 env 文件。
- 打印日志时不能输出 secret、token、password 或完整数据库连接串。

建议后续脚本里加入硬性检查：

- 如果 target 是 `production`，只允许 `.env.production`。
- 如果 target 是 `staging`，只允许 `.env.staging`。
- 如果 compose project 为空，直接失败。
- 如果 staging 端口配置成 `3000` 或 `8000`，直接失败。
- 如果 staging Postgres 配置了宿主机 `5432`，直接失败。

## 9. C02A-C02F 当前计划

当前 C02 任务状态：

- C02A：完成 production 只读审计和 staging/test 隔离方案。
- C02B：完成 staging compose、`.env.staging.example`、静态检查和 smoke check
  模板，不启动服务。
- C02C：已在服务器本地创建 `.env.staging`，启动 staging
  postgres/backend/frontend，初始化 staging owner，并测试后端登录链路。
- C02D：补双环境运维手册、只读状态检查脚本和安全边界说明，不接任何真实业务
  功能。
- C02E / C02F：环境隔离最终验收与封板。
- 未来可选：单独配置 `staging.ops.barongyekhna.com`、DNS、Nginx、HTTPS 和访问
  控制。

C02D 仍不应该接真实业务。真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser
接入要等单独阶段。

## 10. C02B-C02D 文件清单

C02B 在 C02A 隔离方案基础上准备这些文件：

- `docker-compose.staging.yml`：staging compose 施工图。
- `.env.staging.example`：placeholder-only staging env 模板。
- `scripts/check_staging_deploy_files.sh`：只做静态检查，不读取真实 env，不启动
  服务。
- `scripts/staging_smoke_check.sh`：staging 启动后使用的只读 smoke check。
- `docs/C02_STAGING_SETUP.md`：测试服创建、启动和边界说明。

C02D 补充这些文件：

- `docs/C02_DUAL_ENV_OPERATIONS.md`：production/staging 双环境运维手册。
- `scripts/check_dual_env_status.sh`：production + staging 双环境只读状态检查。

C02D 不读取或修改 `.env.production` / `.env.staging`，不启动、停止、重启或
删除容器，不修改 Nginx 或证书，不接真实业务。

## 11. C02A-C02D 结论

C02A-C02D 当前结论：

- production 当前正常运行。
- production frontend/backend 只绑定本机端口，由 Nginx 通过 HTTPS 对外服务。
- production postgres 没有暴露宿主机 PostgreSQL 端口。
- production 证书存在且 HTTPS 正常。
- staging 当前在服务器本机运行，frontend/backend 绑定 `127.0.0.1:3100` 和
  `127.0.0.1:8100`。
- staging postgres 没有暴露宿主机 PostgreSQL 端口。
- staging 暂不暴露公网。
- 当前 external services 是 `not_connected`，符合还没有接真实业务的状态。
- production 和 staging 使用独立 project、独立端口、独立 network、独立
  volume、独立 env、独立 owner 和独立 secret。
- production 数据库和 staging 数据库绝不共用，测试数据不能复制到 production。
- C02D 只补运维文档和只读检查，没有读取或修改真实 env，没有启动、停止、重启
  或删除容器，没有修改 Nginx 或证书，没有接任何真实业务。
