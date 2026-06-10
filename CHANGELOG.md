# Changelog

本项目的重要文档和工程变更记录在此文件中。

## [Unreleased]

### Added

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
