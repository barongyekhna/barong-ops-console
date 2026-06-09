# C02 Staging Setup

日期：2026-06-09 UTC

## 0. C02C/C02D 当前状态

C02C 已经完成 staging 本机启动：

- staging frontend 已运行在 `127.0.0.1:3100`。
- staging backend 已运行在 `127.0.0.1:8100`。
- staging postgres 已运行并保持 `healthy`，只在 Docker 内网暴露 `5432/tcp`。
- staging owner 已初始化，后端登录链路已测试通过。
- staging 暂不暴露公网。

C02D 只补双环境运维文档、只读状态检查脚本和安全边界说明。C02D 不启动、
停止、重启或删除任何 production/staging 容器，不读取真实 env，不修改
Nginx，不申请证书，也不接真实业务。

## 1. 这是什么

staging 是测试服，不是正式服。

production 是现在已经上线的正式入口：
`https://ops.barongyekhna.com`。正式服给老板和以后真实业务使用，不能拿来试
新功能、试 migration、试 owner 初始化，也不能随便接 webhook。

staging 是以后用来试代码、试数据库迁移、试脚本流程、试登录和 smoke check
的隔离环境。它应该坏在测试服里，不能影响 production。

C02B 当时只准备施工图：

- 新增 staging compose。
- 新增 `.env.staging.example`。
- 新增静态检查脚本。
- 新增 smoke check 模板。
- 更新文档。

C02C 后，staging 已经在本机端口启动。C02D 仍然不修改 production，不改
Nginx，不申请证书，也不接真实业务。

## 2. staging 和 production 的区别

production 当前使用：

- project：`barong-ops-console-prod`。
- frontend：`127.0.0.1:3000`。
- backend：`127.0.0.1:8000`。
- postgres：只在 Docker 内网，宿主机不暴露 `5432`。
- network：`barong-ops-console-prod`。
- volume：`console_postgres_data`。
- env：服务器本地 `.env.production`。

staging 当前使用：

- project：`barong-ops-console-staging`。
- frontend：`127.0.0.1:3100`。
- backend：`127.0.0.1:8100`。
- postgres：只在 Docker 内网，宿主机不暴露 `5432`。
- network：`barong-ops-console-staging`。
- volume：`console_staging_postgres_data`。
- env：服务器本地 `.env.staging`。

staging 的 service 名是：

- `console_staging_postgres`
- `console_staging_backend`
- `console_staging_frontend`

当前真实容器名是：

- `barong-ops-console-staging_console_staging_frontend_1`
- `barong-ops-console-staging_console_staging_backend_1`
- `barong-ops-console-staging_console_staging_postgres_1`

这些名字故意和 production、n8n、MinIO、Filebrowser、Baisuwan agent、
SerpBear 分开。

## 3. C02C 怎么创建真实 .env.staging

C02C 已经在服务器本地创建真实 `.env.staging`。本节保留的是历史操作边界，
不是 C02D 要执行的步骤。

C02B 只提交 `.env.staging.example`，里面全是占位值。真实 `.env.staging`
只能在服务器本地创建，不能提交 Git，也不能打印到日志或工单里。

C02C 才能做这一步：

```bash
cp .env.staging.example .env.staging
chmod 600 .env.staging
```

然后只在服务器本地编辑 `.env.staging`：

- `APP_ENV` 保持 `staging`。
- `POSTGRES_PASSWORD` 换成 staging 专用随机值，不能和 production 相同。
- `DATABASE_URL` 里的密码要和 `POSTGRES_PASSWORD` 匹配，特殊字符要 URL
  encode，host 必须是 `console_staging_postgres`。
- `AUTH_TOKEN_SECRET` 换成 staging 专用随机值，不能复制 production。
- `OWNER_USERNAME` 和 `OWNER_PASSWORD` 使用 staging 测试账号。
- `BACKEND_API_URL` 保持 `http://console_staging_backend:8000`。
- `NEXT_PUBLIC_API_BASE_URL` 使用 staging 访问入口。
- `N8N_TEST_WEBHOOK_URL` 默认留空。
- `N8N_TEST_CALLBACK_SECRET` 默认留空。

staging owner 不能使用 production owner 密码。原因很直接：测试服经常会被
重建、试错、截图或多人协作；如果复用 production 密码，测试服出问题就会把
正式 owner 一起暴露。

## 4. C02C 怎么启动 staging

C02C 已经完成 staging 启动。本节保留的是历史操作记录，C02D 不运行这些
命令。C02C 在确认 `.env.staging` 已经准备好之后，才可以使用显式 project
name 启动 staging：

```bash
docker-compose -p barong-ops-console-staging \
  -f docker-compose.staging.yml config

docker-compose -p barong-ops-console-staging \
  -f docker-compose.staging.yml up -d --build
```

不要省略 `-p barong-ops-console-staging`。不要对 production project 执行
`up`、`down`、`restart` 或 `rm`。C02D 阶段也不要为了复查而重新执行这些
启动类命令。

staging postgres 不暴露宿主机端口。backend 只绑定
`127.0.0.1:8100`，frontend 只绑定 `127.0.0.1:3100`。

## 5. 为什么不能接真实业务

staging 是测试服，数据可以随时被清理或重建。它不能接：

- 真实 n8n workflow。
- 真实 P 系列任务。
- WooCommerce。
- MinIO。
- Filebrowser。
- 真实商品、订单、素材或业务任务。

如果 staging 打到真实 webhook，就可能把测试数据当成真实业务执行；如果接到
真实存储或真实电商系统，就可能污染 production 数据。C02B/C02C/C02D 都只允许
foundation/demo 验证。

## 6. 静态检查怎么跑

C02B 新增的静态检查只看文件，不启动容器，不要求真实 `.env.staging` 存在，
也不读取 `.env.production`：

```bash
./scripts/check_staging_deploy_files.sh
```

它会检查：

- staging compose 和 env example 是否存在。
- `.gitignore` 是否忽略真实 `.env.staging`。
- frontend/backend 端口是否是 `127.0.0.1:3100` 和 `127.0.0.1:8100`。
- postgres 是否没有宿主机端口。
- service、network、volume 是否使用 staging 命名。
- staging 文件是否没有 production 域名、production project、真实 webhook
  URL。
- compose config 是否能在安全临时目录里通过。

脚本开头会明确输出：

```text
C02B static check only, no services started.
```

## 7. smoke check 怎么跑

`scripts/staging_smoke_check.sh` 是 staging 已经启动之后才用的只读检查。
C02C 已经启动 staging，所以 C02D 可以运行它做只读验收；但不要为了复查而
执行任何启动、停止或重启命令。

staging 启动后运行：

```bash
./scripts/staging_smoke_check.sh
```

它会检查：

- `http://127.0.0.1:3100/login`
- `http://127.0.0.1:3100/api/backend/health`
- `http://127.0.0.1:8100/health`
- `docker ps` 里的 staging 容器、端口和 postgres 暴露面

如果 staging 还没启动，脚本会提示：

```text
staging is not running yet
```

它不会读取 `.env.production`，不会读取 `.env.staging` 内容，也不会修改任何
服务。

## 8. C02D 双环境总检查

C02D 新增一个 production + staging 总检查脚本：

```bash
./scripts/check_dual_env_status.sh
```

它会检查：

- `git status`。
- `.env.production` 和 `.env.staging` 是否被 Git 忽略。
- production/staging 容器是否按预期运行。
- production 使用 `127.0.0.1:3000` 和 `127.0.0.1:8000`。
- staging 使用 `127.0.0.1:3100` 和 `127.0.0.1:8100`。
- console postgres 都不暴露宿主机 PostgreSQL 端口。
- production 和 staging smoke endpoint 是否返回正常。

如果 staging 未运行，脚本只提示：

```text
staging is not running yet
```

它不会建议 `up`、`restart`、`down` 之类危险命令。

## 9. 未来域名

如果以后要开放 `staging.ops.barongyekhna.com`，必须单独做 DNS、Nginx、
HTTPS、访问控制和 smoke check。C02D 不做这些事。
