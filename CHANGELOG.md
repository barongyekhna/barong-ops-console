# Changelog

本项目的重要文档和工程变更记录在此文件中。

## [Unreleased]

### Added

- C05B：新增后端权限数据模型与 migration `c05b_permissions_001`，创建
  `permission_registry`、`user_permission_assignments`、`role_default_permissions`
  三张表；新增 SQLAlchemy models、Pydantic schemas、permission seed 常量、
  registry upsert、assignment grant/revoke/disable、role default storage、owner
  全局 resolver、非 owner scoped assignment 查询服务和权限测试；本轮不新增公开 API，
  不替换 `require_owner()`，不修改前端 UI，不发布 staging/production，不接真实业务。
- C05B：新增 `docs/C05_PERMISSION_DATA_MODEL.md`，记录 registry 与 assignment 的区别、
  owner 为什么不需要逐条 assignment、`super_admin` 为什么不能默认全局、role defaults
  当前不自动生效、scope 第一版预留和 C05C/C05D 下一步。
- C05A：新增 `docs/C05_PERMISSION_SYSTEM_PLAN.md`，开始权限系统阶段，只做现状审计和设计方案；文档记录当前 owner 判断、`require_owner`、`/users` owner-only、`/auth/me` 返回字段、静态前端菜单、当前没有真实 user permission/scope assignment，并提出 Permission Registry、User Permission Assignment、Role Default Permissions、Permission Scope、Module Permission Manifest、第一批基础权限点、业务/管理菜单策略、migration 判断和 C05B-C05H 后续拆分；本轮不实现功能、不新增 migration、不部署、不修改 production/staging、不接真实业务。
- OPS01E：新增 `docs/OPS01_SAFE_RELEASE_SEAL.md`，归档 Docker Compose v1 `ContainerConfig` 问题治理最终封板结论；本轮只做只读复核和文档封板，确认 safe release plan check 通过、staging/production backend/frontend 四个 dry-run 映射正确、production/staging smoke 和 dual-env status 通过、rollback tag 存在；本轮没有安装或升级工具，没有执行真实 release，没有设置确认变量，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务，没有 git commit。
- OPS01D-3：新增 `docs/OPS01_PRODUCTION_SAFE_RELEASE_ACCEPTANCE.md`，归档 production backend/frontend safe release 真实演练结果；OPS01D-2 已使用 `scripts/safe_compose_release.sh` 先后完成 production backend 和 production frontend 真实发布，两次都使用 `CONFIRM_SAFE_RELEASE=yes`、`CONFIRM_PRODUCTION_RELEASE=yes` 和 `--execute`，均未触发 `docker-compose` v1 `KeyError: 'ContainerConfig'`，已生成 production backend/frontend rollback tag，production smoke、staging smoke 和 dual-env status 均通过；本轮 OPS01D-3 只做只读复核和文档归档，没有重新发布、重建、停止或删除容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01D-1：新增 `docs/OPS01_PRODUCTION_SAFE_RELEASE_DRY_RUN.md`，归档 production backend/frontend safe release dry-run、映射复核和安全门禁检查；本轮确认 production/staging smoke 和 dual-env status 通过，production backend 映射到 `barong-ops-console-prod_console_backend_1` / `http://127.0.0.1:8000/health`，production frontend 映射到 `barong-ops-console-prod_console_frontend_1` / `https://ops.barongyekhna.com/login`；本轮没有真实发布 production，没有 build、up/down、停止、删除、重建容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01C：新增 `docs/OPS01_STAGING_SAFE_RELEASE_ACCEPTANCE.md`，归档 staging safe release 真实演练结果；本轮使用 `scripts/safe_compose_release.sh` 分别发布 staging backend 和 staging frontend，绕开 `docker-compose` v1 `--force-recreate` 的 `ContainerConfig` 风险路径，生成 staging backend/frontend rollback tag，确认 staging smoke、production smoke 和 dual-env status 均通过；本轮未发布 production，未停止/删除/重建 staging postgres，未读取真实 env，未修改 Nginx/证书，未接真实业务。
- OPS01B-alt：新增 `scripts/safe_compose_release.sh`、`scripts/check_safe_release_plan.sh` 和 `docs/OPS01_SAFE_RELEASE_RUNBOOK.md`，准备基于当前 `docker-compose` v1.29.2 的短期安全发布流程；脚本默认 dry-run，真实执行必须显式 `--execute` 和确认变量，只允许 staging/production 的 backend/frontend，禁止 postgres，所有 `docker-compose` 调用必须带 project name 和 compose file。本阶段只做脚本、文档和 dry-run 检查，没有真实发布 staging/production，没有删除、停止、重建容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01A：新增 `docs/OPS01_DOCKER_COMPOSE_GOVERNANCE_PLAN.md`，用大白话归档 Docker / Compose 当前状态、项目脚本 Compose 用法扫描、`docker-compose` v1 `KeyError: 'ContainerConfig'` 根因判断、三种治理方案对比、推荐 staging-first 路线、绝对禁止项和 OPS01B-OPS01E 后续拆分；本轮只做只读审计和文档方案，不安装/升级工具，不重启/删除/重建 production/staging 容器，不读取真实 env，不修改 Nginx/证书，不接真实业务。
- C04F：新增 `docs/C04_ROLE_SYSTEM_SEAL.md`，归档角色体系总封板结论，记录 C04 已完成、标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent` 已统一、当前可创建角色仅 `viewer` / `operator` / `reviewer`、`owner` / `super_admin` / `module_admin` / `bot_agent` 仍为 reserved、C04 不做完整 RBAC、C05 才做权限系统、production `/users` 返回 200、未登录 `/api/backend/users/roles` 和 `/api/backend/users` 返回 401、`/api/backend/auth/register` 仍返回 404，以及本轮未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C04E：新增 `docs/C04_PRODUCTION_RELEASE.md`，归档角色目录 UI production 发布后的只读验收结果，记录 C04B 后端角色目录和 C04C 前端角色目录 UI 已进入 production、`https://ops.barongyekhna.com/users` 可用、未登录 `/api/backend/users/roles` 返回 401、创建用户下拉只允许 `viewer` / `operator` / `reviewer`、`owner` / `super_admin` / `module_admin` / `bot_agent` 仍为 reserved、C04 不做完整 RBAC、C05 才做权限系统，以及本轮未新增 migration、未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C04D：新增 `docs/C04_STAGING_ACCEPTANCE.md`，归档 staging 角色目录 UI/API 验收结果，记录 `/users/roles` owner-only 行为、标准角色和可创建角色目录、reserved roles 拒绝矩阵、staging 页面检查、operation logs 验证、production 仍正常，以及本轮未读取真实 env、未 build/recreate/stop/rm 容器、未执行 `docker-compose up/down`、未修改 Nginx/证书、未接真实业务。
- C04C：前端 User Management 页面新增角色目录说明区，显示 “Current assignable roles” 的 `viewer` / `operator` / `reviewer`，以及 “Reserved roles, not assignable in C04” 的 `owner` / `super_admin` / `module_admin` / `bot_agent`，并明确完整 RBAC 留到 C05。
- C04C：`frontend/src/lib/users-api.ts` 新增 role metadata 类型和 `listUserRoles()`，通过 `/api/backend/users/roles` 调用 C04B 的 owner-only `GET /users/roles`，保留 token 不打印和用户管理错误提示。
- C04B：新增 `backend/app/core/roles.py`，统一定义标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent`、当前 `/users` 可创建角色 `viewer` / `operator` / `reviewer`、不可创建角色 `owner` / `super_admin` / `module_admin` / `bot_agent`、role normalize/validation helper 和角色展示 metadata。
- C04B：新增 owner-only `GET /users/roles`，返回当前用户管理可创建角色和标准角色目录；不可创建角色只展示为 `assignable=false`，不开放选择或放权。
- C04B：新增 `tests/backend/test_roles.py` 并扩展用户管理测试，覆盖标准角色、可创建/不可创建角色、大小写和空格 normalize、创建/PATCH role 拒绝矩阵、非 owner 禁止访问、`/auth/register` 404、API 不返回 `password_hash` 和 operation logs。
- C04A：新增 `docs/C04_ROLE_SYSTEM_PLAN.md`，开始角色体系阶段，记录现有 role 使用方式审计、标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent` 的边界、role 与 job_title/department/permissions/module access 的区别、C04 与 C05 的分工、migration 判断、风险分析和 C04B-C04F 后续任务拆分；本阶段只设计不实现，不接真实业务。
- C03F：新增 `docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md`，归档 C03 Owner 创建子账户最终封板结论，记录 production `/users` 已可用、未登录 `/api/backend/users` 返回 401、`/auth/register` 仍返回 404、production/staging/dual env check 通过、当前只支持 owner 管理 `viewer`/`operator`/`reviewer` 子账户，并明确 `super_admin`、完整 RBAC、模块权限、邮件邀请、密码找回和真实业务接入留到后续 C04/C05 或单独任务。
- C03E：新增 `docs/C03_PRODUCTION_RELEASE.md`，归档 production 用户管理发布验收结果，记录 C03B 后端 `/users` API 和 C03C 前端 `/users` 页面已进入 production、`https://ops.barongyekhna.com/users` 可用、未登录 `/api/backend/users` 返回 401、`/auth/register` 仍返回 404、production/staging/dual env check 通过，以及本轮未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C03D：新增 `docs/C03_STAGING_ACCEPTANCE.md`，归档 staging 用户管理验收结果，记录测试用户 `c03d_test_<timestamp>` 的创建、登录、停用、启用、重置密码、非 owner 403、`role=owner` 拒绝、`/auth/register` 404、operation logs 验证和 production smoke 仍正常。
- C03C：新增受保护的 `/users` 前端用户管理页面和 System 导航入口，支持用户列表、创建 `viewer`/`operator`/`reviewer`、查看详情、更新基础 role、停用、启用和重置子账户密码；页面明确是内部账号管理，不是公开注册。
- C03C：新增 `frontend/src/lib/users-api.ts` 前端用户管理 API client，接入现有 token 和 `/api/backend` 代理，补充 401/403/409/422 友好错误提示，避免打印 password/token。
- C03C：前端 API proxy 精确放行 owner-only `/users` 相关 GET/POST/PATCH 路径，并继续不暴露通用写代理、不转发危险 headers、不破坏 `/auth`、`/health`、F10/F11/F12 代理。
- C03B：新增 owner-only `/users` 后端用户管理 API，支持列表、创建、详情、更新、停用、启用和重置子账户密码；只允许创建 `viewer`、`operator`、`reviewer` 子账户，不允许创建 `owner`。
- C03B：新增用户管理 schema、repository、service、router 和数据库集成测试，覆盖非 owner 登录、`/auth/me`、`/users` 401/403、重复 username、弱密码、禁用用户、密码重置、禁止 owner 自停用和 operation logs。
- C03A：新增 `docs/C03_OWNER_ACCOUNT_MANAGEMENT_PLAN.md`，用大白话记录现有 users/auth/frontend 鉴权审计、当前 owner-only 限制、C03 账号管理边界、后端 API 草案、前端页面草案、安全规则、migration 判断、staging-first 发布流程和 C03B-C03F 任务拆分；本阶段只设计不实现。
- C02F：新增 `docs/C02_ENVIRONMENT_ISOLATION_SEAL.md`，用大白话归档 C02 最终结论、C02A-C02F 完成清单、production/staging 当前状态、隔离规则、发布原则、n8n/workflow 未来原则、安全禁止项、剩余风险和 C02 封板结论。
- C02E：新增 `docs/C02_ENVIRONMENT_ISOLATION_ACCEPTANCE.md`，归档 production/staging 最终只读验收结果、双环境隔离证据、脚本结果、compose config 安全临时 env 方法、真实业务边界、剩余风险和 C02F 封板下一步。
- C02D：新增 `docs/C02_DUAL_ENV_OPERATIONS.md`，用大白话说明 production/staging 双环境当前运行状态、端口/容器/volume/network/env 隔离、发布原则、数据边界、n8n workflow 未来版本化要求、只读安全命令和危险命令。
- C02D：新增 `scripts/check_dual_env_status.sh`，只读检查 Git 状态、真实 env Git ignore、production/staging 容器状态、端口隔离、console Postgres 暴露面以及 production/staging smoke endpoint，不读取真实 env，不修改服务。
- C02C：记录 staging 已在服务器本机启动，frontend 为 `127.0.0.1:3100`，backend 为 `127.0.0.1:8100`，postgres 为 Docker 内网 `5432/tcp` 且 healthy，staging owner 已初始化并完成后端登录链路测试。
- C02B：新增 `docker-compose.staging.yml`、`.env.staging.example`、staging 静态检查脚本和 staging smoke check 模板，只准备测试服施工图，不启动服务。
- C02B：新增 `docs/C02_STAGING_SETUP.md`，说明 staging 与 production 的端口、命名、env、volume、network 隔离，以及 C02C 才能创建真实 `.env.staging` 和启动 staging。
- C01C：新增 `docs/C01_PRODUCTION_ACCEPTANCE.md`，归档 `https://ops.barongyekhna.com` production 验收证据、证书状态、Nginx/容器暴露面、非集成边界、已知风险和 C01 封板结论。
- C01C：补齐 production smoke check，覆盖 HTTPS login、HTTPS backend health proxy、HTTP 到 HTTPS 跳转和 `docker ps` 状态检查，不读取 `.env.production`，不修改任何服务。
- C01B-1：新增 `docker-compose.production.yml`、`.env.production.example`、Nginx 模板、production 部署文档和静态部署文件检查脚本，准备 `ops.barongyekhna.com` 正式部署文件。
- C01B-1：新增 production smoke check 脚本，用于部署后人工验收登录页/API 可达性，不包含凭证、不触发业务动作。
- F13：新增第一代空地基统一验收脚本与封板报告，覆盖后端、数据库迁移、owner 认证、F10/F11/F12 API、前端 required routes/build、Compose config、diff 和安全边界扫描。
- F13：补齐 foundation/demo 阶段说明、example-only 临时登录预览、安全启动方式、环境变量密钥规则、剩余风险和下一阶段接入边界。
- F12：新增 owner-only `POST /n8n-test/run`、公开但 callback header 鉴权的 `POST /n8n-test/callback`、owner-only `GET /n8n-test/latest`，完成 Console 与 n8n test webhook 闭环。
- F12：新增 `n8n_test_bridge` / `n8n_test_agent` / `n8n_test_webhook_workflow` demo Registry、test Job、callback Job Events、demo Artifact / Review / Memory Event、System Error 与 Operation Logs。
- F12：新增受保护的 `/n8n-test` 页面、Run n8n Test 按钮、waiting callback 自动轮询、latest event / artifact / review / memory / error 展示及 test-only 安全提示。
- F12：新增 webhook 未配置、mock HTTP payload、HTTP failure、callback secret 缺失/错误/正确、demo terminal status、敏感信息隔离和无真实集成测试。
- F11：新增 owner-only `POST /foundation-demo/run` 与 `GET /foundation-demo/latest`，完成 Module / Agent / Workflow / Job / Job Events / Artifact / Review / Memory Event / Operation Logs 演习闭环。
- F11：新增受保护的 Foundation Demo 前端页面、运行按钮、latest 状态展示及明确的 demo-only 外部系统隔离提示。
- F11：新增闭环幂等 Registry、新 Job、多步事件、metadata-only Artifact、pending demo Review、无模型 Memory Event、事务回滚与 failure 审计测试。
- F10：新增 owner-only Registry、Job / Job Event、Artifact、Review、System Error、Memory Event、Context Packet 基础 API，以及只读 Memory Summary / Operation Log API。
- F10：所有基础写入与 `operation_logs` 审计在同一事务提交，并新增 demo 状态、敏感字段、外部 URL、重复键和引用完整性校验。
- F10：Modules、Agents、Workflows、Jobs、Artifacts、Reviews、Errors、Memory Events 前端页面接入真实只读列表，提供 loading、error、empty 和简易卡片状态。
- F10：新增 Registry、Jobs、Artifact / Review / Error、Memory / Operation Log 数据库集成测试及无外部 HTTP 客户端边界检查。
- F09：新增 Next.js / React / TypeScript 前端空壳、`/login`、Dashboard、基础导航和结构化空状态页面。
- F09：新增基于 F08 `login`、`me`、`logout` 认证 API 的前端登录状态、401 清理、受保护路由和退出流程。
- F09：新增 frontend Dockerfile、固定依赖 lockfile、前端 route/safety 验证、TypeScript 检查和 production build 脚本。
- F08：新增 Argon2id 密码哈希、JWT token、owner 幂等初始化 CLI 与 example Docker 脚本。
- F08：新增 `POST /auth/login`、`POST /auth/logout`、`GET /auth/me` 和认证 operation logs。
- F08：新增密码安全、owner bootstrap、登录失败统一响应、停用用户、当前用户和退出审计测试。
- F07：新增 14 张核心空地基表的 SQLAlchemy 模型与单一 Alembic migration。
- F07：新增 schema metadata、字段、主键、稳定业务 ID 唯一约束和 migration 无 seed 测试。
- F07：数据库 Docker 验证脚本新增 migration upgrade、downgrade、再次 upgrade 的完整验证。
- F06：新增 PostgreSQL、SQLAlchemy 与 Alembic 迁移机制骨架，metadata 和 migration versions 保持为空。
- F06：新增 example-only PostgreSQL Compose 服务、数据库配置测试和隔离 Docker 验证脚本。
- F05B：新增后端 Docker 隔离测试脚本和可复现的健康检查验证方式。
- F05：新增 FastAPI / Python 后端空骨架、非敏感应用配置和 `GET /health`。
- F05：新增后端 Dockerfile、示例 Compose 配置和健康检查测试。
- F04：新增架构、模块合同、API 边界、数据库 Schema、认证、n8n 集成、固定任务序列和 Codex 施工规则文档。
- 新增 `docs/FOUNDATION_BLUEPRINT_V1_1.md`，同步 Barong Ops Console 空地基 V1.1 基线。
- 将登录认证、`owner` 初始化账号、受保护页面、用户表和密码哈希存储纳入空地基范围。
- 明确 Registry、Job、Artifact、Review、Memory Event、Operation Log、核心表、技术路线、施工顺序和最终验收标准。

### Changed

- C05B：README、backend README 和 C05 权限系统计划更新为后端权限数据地基已实现；当前仍不暴露
  `/auth/me.permissions`，不增加 permission API，不修改前端权限菜单，不把 `/users` 从
  `require_owner` 切到 `users.manage`，C05C/C05D 继续处理正式 enforcement 和 UI 接入。
- C05A：README、backend README、frontend README 和 C04 角色体系封板文档更新为 C05 权限系统已开始；说明 C05 目标是权限基础设施而不是业务模块接入，当前仍未接真实业务，`super_admin` 仍不是全局 owner，C05B 如实现 User Permission Assignment 和 Permission Registry 应 staging-first 新增 migration。
- OPS01E：README、OPS01 safe release runbook、OPS01 Docker Compose governance plan、OPS01 production acceptance、OPS01 production dry-run 归档和 OPS01 staging acceptance 归档更新为 OPS01 已封板；文档明确当前仍未安装 Compose v2，后续 backend/frontend 发布默认使用 `scripts/safe_compose_release.sh`，不再默认使用 `docker-compose --force-recreate`，下一阶段回到 C05 权限系统。
- OPS01D-3：README、OPS01 safe release runbook、OPS01 Docker Compose governance plan、OPS01 production dry-run 归档和 OPS01 staging acceptance 归档更新为 production safe release 真实演练已完成；文档明确 backend/frontend 都已在 production 演练成功，`ContainerConfig` 问题未复现，当前仍未安装 Compose v2，仍保留 `docker-compose` v1.29.2，但后续 production backend/frontend 发布应优先使用 `scripts/safe_compose_release.sh`，不要把 `docker-compose --force-recreate` 作为默认发布方式；后来 OPS01E 做安全发布流程封板。
- OPS01D-1：`scripts/safe_compose_release.sh` 的 dry-run 输出现在显式打印 `env=...`、`project=...`、`compose=...`、`container=...`、`health=...` 和安全门禁；`scripts/check_safe_release_plan.sh` 增强为检查默认 dry-run、production double confirmation、staging 单确认、env/service allowlist、postgres 拒绝、禁止 `down`、禁止 `docker stop/restart`、所有 Compose v1 命令带 project name。README、OPS01 runbook、OPS01 governance plan 和 OPS01C staging acceptance 当时同步为 OPS01D-1 已完成 production dry-run、production 尚未真实发布、下一步 OPS01D-2 才做 production safe release 真实演练。
- OPS01C：README、OPS01 safe release runbook 和 OPS01 Docker Compose governance plan 更新为 staging safe release 演练已完成；文档明确 OPS01C 只动 staging backend/frontend，staging postgres 和 production 未被发布或重建，rollback tag 只作为后续人工回滚参考，本阶段不执行 rollback，下一步 OPS01D 再治理 production safe release 演练和发布流程。
- OPS01B-alt：OPS01 Docker Compose 治理说明更新为 Compose v2 安装路线暂因 apt 找不到 `docker-compose-plugin` 暂停，当前采用短期 B-alt 路线准备安全发布脚本；Compose v2 后续可以单独评估，但不打断当前项目。README 同步说明新增 safe release runbook 和 dry-run script，当前还没有真实使用脚本发布 staging/production，下一步 OPS01C 是 staging 演练。
- OPS01A：README 更新为 OPS01 已开始，目标是治理 Docker Compose v1 `ContainerConfig` 发布问题；当前只做审计方案，不改运行环境，后续先 OPS01B 处理 Compose v2 或安全 fallback，再 staging-first 演练发布脚本，最后才进入 production。
- C04F：README、backend README、frontend README、C04 角色计划、C04 staging 验收文档和 C04 production 发布文档更新为 C04 已封板；production 已有角色目录 UI，当前仍不做完整 RBAC，不给 `super_admin` 放权，C05 才做 permissions / RBAC；C04 后先做 OPS01：Docker Compose v1 `ContainerConfig` 问题治理。
- C04E：README、backend README、frontend README、C04 角色计划和 C04 staging 验收文档更新为 production 角色目录发布已完成；production `/users` 页面已经使用角色目录 UI，当前仍不做 `super_admin` 放权、不做完整 RBAC，下一步为 C04F 角色体系封板。
- C04D：README、backend README、frontend README 和 C04 角色计划当时更新为 staging 角色目录 UI/API 已验收通过，C04 仍不做完整 RBAC、不创建 production 用户、不接真实业务。
- C04C：创建用户和详情页 managed role 下拉改为由 `/users/roles` 返回的 `assignable=true` 角色生成，并在前端安全过滤为 `viewer` / `operator` / `reviewer`；`owner`、`super_admin`、`module_admin`、`bot_agent` 不可选择。
- C04C：前端 API proxy 最小放行 `GET /api/backend/users/roles`，不破坏 `/health`、`/auth` 和既有 `/users` list/create/detail/update/disable/enable/reset-password 路径。
- C04C：README、frontend README、C03 封板文档和 C04 角色计划更新为前端已使用后端角色目录；本阶段不做完整 RBAC、不部署 staging/production、不创建真实用户、不接真实业务，下一步为 C04D staging 验收角色目录 UI。
- C04B：`backend/app/schemas/user.py` 和 `backend/app/services/user_management_service.py` 改为调用统一 `validate_assignable_user_role`；创建和更新用户 role 仍只允许 `viewer` / `operator` / `reviewer`，继续拒绝 `owner` / `super_admin` / `module_admin` / `bot_agent`。
- C04B：`backend/app/api/deps.py` 的 owner-only 判断改为 `is_owner_role` helper，不改变 `/users` 权限结果；`super_admin`、`module_admin`、`bot_agent` 只定义不放权，完整权限系统仍留给 C05。
- C04B：README、backend README、C03 封板文档和 C04 角色计划更新为 C04B 后端角色常量与统一校验已落地；本阶段不新增 migration、不部署 staging、不发布 production、不接真实业务。
- C04A：README、backend README、frontend README 和 C03 封板文档更新为 C04 已开始，明确 C04 是角色体系、不是完整权限系统；C05 才做 permissions、module access 和角色权限绑定；当前仍不读取真实 env、不创建真实用户、不操作 production/staging 数据库、不改容器、不改 Nginx/证书、不接真实业务。
- C03F：README、backend README、frontend README、C03 计划文档、C03D staging 验收文档和 C03E production 发布文档更新为 C03 已封板、User Management 已进入 production、C03 不包含 `super_admin` 或完整 RBAC，下一阶段为 C04：角色体系。
- C03E：README、backend README、frontend README、C03 计划文档和 C03D staging 验收文档更新为 production 用户管理发布已完成，`/users` 页面已在 production 可用；当前仍不做 `super_admin`、完整 RBAC 或真实业务接入，后续由 C03F 完成封板。
- C03D：README、backend README、frontend README 和 C03 计划文档当时更新为 C03D staging 已验收通过、production 用户管理发布进入 C03E、真实业务仍未接入；本轮未读取真实 env 文件、未打印 secret、未修改 Nginx/证书、未重启或删除容器。
- C03C：`frontend/scripts/verify-foundation.mjs` 纳入 `/users` route、用户管理 API 连接、PATCH proxy 和无公开注册检查；README/frontend README/C03 文档当时更新为 C03C 代码完成状态，后续 C03D 再更新为 staging 已验收。
- C03B：拆分 `get_current_user` 和 `require_owner`；`get_current_user` 只验证 token、用户存在、active 状态和 token role 与数据库 role 一致，`require_owner` 负责 `/users` owner-only 授权。
- C03B：`/auth/login` 和 `/auth/me` 不再要求用户必须是 `owner`；active 非 owner 子账户可以登录并读取当前用户信息，inactive 用户仍被拒绝。公开注册继续不存在。
- C03B：`scripts/test_backend_db_docker.sh` 纳入 `tests/backend/test_user_management_api.py`，确保 example/test 数据库测试覆盖用户管理 API；本阶段不新增 migration、不做前端页面、不做完整 RBAC、不接真实业务。
- C03A：README 补充 C03 owner 创建子账户阶段说明，明确 C03A 只做审计和设计，不新增 migration、不创建用户、不改 production/staging 容器、不接真实业务。
- C02F：README、backend/frontend README、C02A-C02E 文档和双环境运维文档更新为 C02 已封板，production/staging 双环境隔离体系完成，当前仍未接真实业务，下一阶段为 C03：Owner 创建子账户。
- C02E：README、backend/frontend README、`docs/C02_DUAL_ENV_OPERATIONS.md`、`docs/C02_STAGING_SETUP.md` 和 `docs/C02_ENVIRONMENT_ISOLATION_PLAN.md` 更新为 production/staging 双环境最终验收完成、两套环境均可用、当前仍未接真实业务模块、下一步 C02F 环境隔离封板。
- C02D：README、backend/frontend README、`docs/C02_STAGING_SETUP.md` 和 `docs/C02_ENVIRONMENT_ISOLATION_PLAN.md` 更新为 C02C 已完成 staging 本机启动、C02D 只补双环境只读运维检查、staging 仍不暴露公网、下一步 C02E/C02F 做最终验收与封板。
- C02B：README、backend/frontend README、C02A 隔离方案和 F13 验收脚本补充 staging 施工图说明；`.gitignore` 明确忽略真实 `.env.staging`，但保留 `.env.staging.example` 可提交。
- C01C：README、backend/frontend README 和部署检查脚本更新为 C01 production 已上线封板状态，明确当前仍是 foundation/console 阶段，下一阶段为 C02 生产/测试环境分离。
- C01C：`scripts/check_production_deploy_files.sh` 不再创建、覆盖、读取或要求移动真实 `.env.production`；compose 静态验证改用临时目录中的 `.env.production.example`。
- C01B-1：F13 验收脚本允许仓库存在 `docker-compose.production.yml`，继续禁止未审查的额外 Compose 文件。
- C01B-1：README、backend/frontend README 补充 production 部署文件边界，明确真实 `.env.production`、证书、Nginx 安装和业务接入均不在本阶段执行。
- F13：前端 foundation verifier 现在显式检查根路由、受保护 layout 和 auth guard；修正后端 README 中仅适用于 F08 当时状态的“无前端登录页”表述。
- F13：确认不新增 migration、依赖或真实业务接入，不修改生产 Compose，不创建真实产品任务，并保持 F12 网络能力仅限显式配置的 test/demo webhook。
- F12：example 配置新增 `N8N_TEST_WEBHOOK_URL`、`N8N_TEST_CALLBACK_SECRET`、`N8N_TEST_REQUEST_TIMEOUT_SECONDS`；URL 默认空并安全失败，示例值仅使用 `example.invalid`。
- F12：数据库 Docker 测试纳入 n8n test bridge API/回调鉴权/审计/失败测试；前端验证纳入 `/n8n-test` 路由、精确 API 代理及 test bridge only 文案。
- F11：数据库 Docker 测试纳入 Foundation Demo API/事务/失败回滚/敏感信息/无外部客户端测试，前端验证纳入 demo 页面和精确 API 代理检查。
- F11：README 明确演习闭环不接真实 n8n、WooCommerce、MinIO/Filebrowser、P 系列或真实业务任务，且不新增 migration。
- F10：数据库 Docker 验证脚本纳入全部 F10 API 测试；前端 foundation 校验要求八个只读 API 接线并阻止外部集成引用。
- F10：README 明确基础 API 仅登记 foundation/demo 数据，不触发真实工作流、不调用模型、不上传文件、不创建真实产品或业务任务。
- F09：example Compose 新增仅依赖 backend 的 frontend 服务，绑定 `127.0.0.1:3000`，不依赖外部业务服务。
- F09：README 明确第一版没有公开注册，除 `/login` 外页面受保护，前端仍不接真实业务模块或外部系统。
- F08：数据库 Docker 验证覆盖认证测试和 owner CLI，并继续执行 migration upgrade、downgrade、再次 upgrade 和清理。
- F08：README 明确第一版禁止公开注册，前端登录页留到 F09，example secret/password 不得用于生产。
- F07：Alembic metadata 现在加载全部核心空地基模型；`/health` 仍不声称已检查数据库。
- F07：README 明确认证、owner 初始化、业务 API、前端和真实业务仍未实现，认证基础留到 F08。
- F06：示例后端通过 `DATABASE_URL` 指向示例数据库；`/health` 仍不检查数据库连接，核心业务表留到 F07。
- F05B：固定后端 Python 直接和传递依赖版本，并调整示例镜像以非 root 用户运行后端和 `pytest`，不依赖系统 Python 环境。
- F05B：示例 Compose 继续仅包含 backend，明确不使用生产路径、真实密钥、数据库或外部服务。
- F04：将空地基工程约束拆分为可独立审查和后续实现引用的专题合同，并固定 F04 至 F13 任务代号。
- 明确第一版禁止公开注册，除 `/login` 外的控制台页面默认要求登录。
- 明确 n8n 仅作为通过 Adapter / Webhook 接入的执行引擎。
- 明确“先地基后业务、先注册后运行、先测试后生产、先 artifact 后下游、先审核后高风险动作、先日志后成功”的施工原则。
- 补充生产环境保护、真实系统隔离、禁止 silent success 和禁止自动跨越人工审核的约束。
