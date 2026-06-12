# C07 Module Isolation Seal

日期：2026-06-12 UTC

本文件记录 C07G：C07 模块隔离体系最终封板归档。

C07G 是文档封板任务，不是功能开发任务、发布任务、真实业务接入任务或后续模块开发任务。
本轮不新增 API，不新增 UI，不新增 migration，不修改 runtime 代码，不发布 staging，不发布
production，不执行 safe release，不读取真实 env，不操作 production/staging 容器或数据库，
不 psql，不手写 SQL，不创建测试账号，不创建真实业务任务，不 git commit。

## 一、封板结论

C07 模块隔离体系已完成并封板。

最终结论：

- C07A 完成模块隔离审计与方案设计。
- C07B 完成后端 Module Manifest v1、Module Registry、`GET /modules/registry` 和
  `GET /modules/me`。
- C07C 完成前端 module-aware navigation、route guard、ModuleAccessProvider 和
  Module Unavailable / No Permission 提示。
- C07D 完成模块隔离 verify/test 体系。
- C07E 完成 staging 模块隔离验收。
- C07F 完成 production 模块隔离发布归档。
- staging 和 production 已完成对应验收。
- 后端 module registry 已上线 production。
- 前端 module-aware navigation / route guard 已上线 production。
- C07 完成模块隔离基础闭环。
- C07 不接真实业务，不进入 K01，不进入 P 系列。
- 下一步应进入 C08 Module Adapter，但不在 C07G 中启动。

## 二、C07 完成范围

C07A：模块隔离审计与方案设计。

- 记录文件：`docs/C07_MODULE_ISOLATION_PLAN.md`。
- 完成 C05/C06 权限基础、当前导航、route、backend router、frontend proxy 和测试体系审计。
- 定义模块、Module Manifest v1、Permission Manifest、route/API namespace、external
  dependencies、denied/unavailable behavior、status/lifecycle、K01 未来接入边界和 C07 与后续
  C08/C09/C10/C13/C15/C18 的分工。

C07B：后端 Module Manifest v1 / Module Registry 基础。

- 记录文件：`docs/C07_MODULE_REGISTRY_BACKEND.md`。
- 新增静态代码内 module registry、Module Manifest v1 schema、registry validation 和 module
  access state 计算。
- 新增 authenticated `GET /modules/registry` 和 `GET /modules/me`。
- 未新增 migration，未接真实业务。

C07C：前端 module-aware navigation / route guard。

- 记录文件：`docs/C07_MODULE_FRONTEND_ISOLATION.md`。
- 新增前端 module registry/access helper、module registry API client、ModuleAccessProvider、
  module-aware sidebar 和 route guard。
- frontend proxy 只精确放行 `/api/backend/modules/registry` 和 `/api/backend/modules/me`。
- 未新增后端 API，未接真实业务。

C07D：模块隔离 verify/test 体系。

- 记录文件：`docs/C07_MODULE_ISOLATION_VERIFICATION.md`。
- 强化后端 module registry tests、前端 Node tests 和 `frontend/scripts/verify-foundation.mjs`。
- 将 manifest 完整性、module_key、permission、proxy allowlist、business/admin/system 行为、
  不可执行状态、K01/P 系列不接入和 C05/C06 回归固化为自动检查。

C07E：staging 模块隔离验收。

- 记录文件：`docs/C07_MODULE_STAGING_ACCEPTANCE.md`。
- staging backend/frontend safe release 已完成。
- staging 未执行 Alembic，未读取 env，未操作 postgres，未接真实业务。

C07F：production 模块隔离发布归档。

- 记录文件：`docs/C07_MODULE_PRODUCTION_RELEASE.md`。
- production backend/frontend safe release 已完成。
- production 未执行 Alembic，未读取 env，未操作 postgres，未接真实业务。

## 三、最终模块定义

模块不是按钮，不是 helper，也不是一段可复用代码。

模块是有独立页面入口、权限、路由、API namespace、状态和可能外部依赖的功能板块。模块必须能
回答它的稳定 `module_key`、展示名称、分类、状态、生命周期、权限声明、页面入口、API 边界、
导航策略、不可用策略、外部依赖、执行要求、数据边界、验收要求和文档来源。

示例模块：

- `core.dashboard`
- `admin.users`
- `admin.permissions`
- `business.jobs`
- `business.products`
- `integration.n8n_test_bridge`
- future K01 product knowledge，未来建议 key 为 `k01.product_knowledge`

最终规则：

- 新模块必须通过 Module Manifest 注册。
- 没有 manifest 的模块不能进入正式导航。
- 没有 permission declaration 的模块不能绕过 C05/C06 权限系统。
- 没有 route namespace / api namespace 的模块不能随意挂载。
- business 模块无权限时默认 `show_locked` / `locked`。
- admin/system 模块无权限时默认 `hide_when_denied` / `hidden`。
- `planned`、`adapter_pending`、`unavailable` 模块不可 executable。

## 四、Module Manifest v1 最终状态

Module Manifest v1 最终字段：

- `module_key`
- `display_name`
- `description`
- `category`
- `status`
- `lifecycle`
- `route_namespace`
- `api_namespace`
- `navigation`
- `required_permissions`
- `permission_manifest`
- `denied_behavior`
- `unavailable_behavior`
- `external_dependencies`
- `execution_provider_required`
- `module_adapter_required`
- `sandbox_required`
- `feature_flag_key`
- `audit_log_actions`
- `operation_log_policy`
- `allowed_scope_types`
- `data_boundary`
- `release_requirements`
- `staging_acceptance_required`
- `production_release_required`
- `docs_path`

最终规则：

- `module_key` 发布后应稳定，不随 UI 文案、客户名、环境名或临时项目名变化。
- permission keys 必须可追踪，并可注册到 `permission_registry`。
- `required_permissions` 必须能追溯到同模块 `permission_manifest`。
- `external_dependencies` 只声明安全依赖名，例如 `n8n`、`woocommerce`、`minio`、
  `filebrowser`、`ai_provider`，不包含 secret、token、password、env、Authorization
  header、provider URL、webhook URL、API key 或 credential。
- `planned`、`adapter_pending`、`unavailable` 不可 executable。
- C07 只声明 `execution_provider_required`、`module_adapter_required`、`sandbox_required` 和
  `feature_flag_key`，不实现对应能力。

## 五、最终后端状态

后端最终状态：

- 后端已提供静态 module registry。
- 后端已提供 Module Manifest v1 schema。
- 后端已提供 module access state 计算。
- `GET /modules/registry` 已实现。
- `GET /modules/me` 已实现。
- 两个 API 均要求登录。
- 未登录返回 401。
- owner full access 可见 admin/system。
- non-owner admin/system hidden 或不返回。
- business 无权限 `locked` / `show_locked`。
- `planned`、`adapter_pending`、`unavailable` 不可 executable。
- registry 不返回 secret、token、password、env、Authorization header、provider URL、webhook
  URL、API key 或 credential。
- `admin.users` 和 `admin.permissions` 继续 owner-only。
- `/users` 后端仍 owner-only。
- `/auth/register` 仍 404。
- C07B 没有新增 migration。
- C07B 没有接真实业务。

后端上线状态：

- staging 已在 C07E 发布并验收。
- production 已在 C07F 发布并归档。
- production 后端 module registry runtime 已上线。

## 六、最终前端状态

前端最终状态：

- 前端已实现 module registry/access helper。
- 前端已实现 module registry API client。
- 前端已实现 ModuleAccessProvider。
- 前端 navigation 已绑定 `module_key`。
- 前端 route guard 已支持 module access state。
- Module Unavailable / No Permission 文案已完成。
- frontend proxy 精确放行 `/api/backend/modules/registry` 和 `/api/backend/modules/me`。
- frontend proxy 不放开危险 `/modules/*` 宽通配。
- business 模块无权限保持 `show_locked`。
- admin/system 模块无权限保持 `hide_when_denied`。
- `planned`、`adapter_pending`、`unavailable` 显示不可用，不触发真实动作。
- User Management 仍 owner-only。
- Permission Management 仍 owner-only。
- C07C 没有新增后端 API。
- C07C 没有接真实业务。

前端上线状态：

- staging 已在 C07E 发布并验收。
- production 已在 C07F 发布并归档。
- production 前端 module-aware navigation / route guard 已上线。

## 七、verify/test 体系最终状态

C07D 已把模块隔离规则固化进后端测试、前端 Node 测试和只读 verifier。

后端测试入口：

- `tests/backend/test_modules_registry.py`

前端测试入口：

- `tests/frontend/module-isolation.test.mjs`
- `tests/frontend/permissions.test.mjs`
- `tests/frontend/permission-management.test.mjs`
- `frontend/scripts/verify-foundation.mjs`

校验点包括：

- `module_key` 唯一。
- manifest 字段完整。
- `category`、`status`、`denied_behavior` 合法。
- business `show_locked`。
- admin/system `hide_when_denied`。
- `planned`、`adapter_pending`、`unavailable` 不可 executable。
- `external_dependencies` 不泄漏 secret、env、token、password、credential、provider URL 或 API key。
- proxy allowlist 不放宽。
- navigation item 必须有 `module_key` 或明确 core exception。
- K01/P 系列不能默认启用。
- `integration.n8n_test_bridge` 只能保持 test-only / adapter_pending。
- User Management 和 Permission Management 仍 owner-only。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- C05/C06 回归不破坏。

## 八、staging 验收摘要

C07E 已完成。

staging 验收摘要：

- staging backend safe release 完成。
- staging frontend safe release 完成。
- staging 未执行 Alembic。
- staging `/modules/registry` 和 `/modules/me` 未登录 401。
- staging frontend proxy `/api/backend/modules/registry` 和 `/api/backend/modules/me` allowlist 生效。
- staging proxy 未放开 `/modules/*` 宽通配。
- staging bundle marker 命中 C07C module-aware 代码。
- C05/C06 回归通过。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- owner/non-owner live login 限制如 C07E 文档所述：没有 approved staging owner credentials，
  也没有 active approved non-owner test account，因此未执行 live owner/non-owner login；相关规则由
  C07D Docker/Node tests 覆盖。
- 未读取 env。
- 未操作 postgres 容器。
- 未接 K01/P 系列/真实业务。

## 九、production 发布摘要

C07F 已完成。

production 发布摘要：

- production backend safe release 完成。
- production frontend safe release 完成。
- production 未执行 Alembic。
- production `/modules/registry` 和 `/modules/me` 未登录 401。
- production frontend proxy `/api/backend/modules/registry` 和 `/api/backend/modules/me` allowlist
  生效。
- production proxy 未放开 `/modules/*` 宽通配。
- production bundle marker 命中 C07C module-aware 代码。
- production C05/C06 未登录基线保持：
  - `/auth/me` 401
  - `/permissions/me` 401
  - `/users` 401
  - `/auth/register` 404
- owner/non-owner live login 未执行，原因是没有 approved production auth material；未伪造
  token、未读 env、未查库、未创建测试账号、未改 assignment。
- production 未接 K01/P 系列/真实业务。
- 未操作 production postgres 容器。
- 未 psql。
- 未手写 SQL。
- 未读取 env。

## 十、K01 与 C07 的最终关系

K01 是未来业务模块，不是 C07。

最终关系：

- C07 不开发 K01。
- C07 不创建 K01 真实业务能力。
- C07 为 K01 未来接入提供模块隔离规则。
- K01 未来必须通过 Module Manifest 声明：
  - `module_key`
  - permissions
  - route namespace
  - API namespace
  - external dependencies
  - status / lifecycle
  - feature flag / adapter_pending
- K01 在未正式接入前必须保持 `adapter_pending` / disabled-by-default / hidden navigation。
- K01 不占 C 系列编号。
- K01 不重写 C07。
- K01 不绕过 C08/C13/C18。
- K01 后续只能作为 `adapter_pending` / disabled-by-default / hidden navigation 的未来业务模块接入，
  不能抢 C07/C08/C13/C18 的职责。

## 十一、P 系列与 C07 的最终关系

P 系列是 n8n 工作流，不是 C07。

最终关系：

- C07 不接 P 系列。
- C07 不直接调用 P 系列 workflow。
- 未来 P 系列如果进入控制台，必须作为模块或模块下 execution capability 接入。
- 未来 P 系列必须遵守 Permission Manifest、module registry、Execution Provider 和 n8n 接入规范。
- C15 才定义 n8n 接入规范。
- C09 才定义 Execution Provider。
- C07 不创建 P 系列真实业务任务。

## 十二、C07 与后续阶段边界

后续阶段边界：

- C08 Module Adapter：模块如何接入控制台，不在 C07 做。
- C09 Execution Provider：模块如何执行任务，不在 C07 做。
- C10 模块沙箱：模块运行隔离，不在 C07 做。
- C11 模块验收标准：模块上线验收标准，不在 C07 完整实现。
- C12 审批门：模块动作审批，不在 C07 做。
- C13 模块开关：模块启停治理，不在 C07 做。
- C14 密钥规则：provider secrets，不在 C07 做。
- C15 n8n 接入规范：不在 C07 做。
- C18 组织结构：完整 company/factory/department scope，不在 C07 做。

C07 只完成模块隔离基础闭环，不替代后续阶段。

## 十三、安全边界

C07G 不发布 staging 或 production。

C07 和 C07G 明确不做：

- 不创建真实业务任务。
- 不接 n8n/WooCommerce/P 系列/MinIO/Filebrowser。
- 不接 K01。
- 不修改核心权限模型。
- 不改变 `/users` owner-only 后端边界。
- 不创建 production/staging 测试账号。
- 不执行 grant/update/revoke assignment。
- 不新增 migration。
- 不读 env。
- 不操作数据库。
- 不操作 production/staging postgres 容器。
- 不 psql。
- 不手写 SQL。
- 不新增后端 API。
- 不新增前端 UI。
- 不修改 runtime 代码。
- 不替代 C08/C09/C10/C13/C15/C18。

## 十四、未完成范围与后续任务

未完成范围：

- C08：Module Adapter。
- C09：Execution Provider。
- C10：模块沙箱。
- C11：模块验收标准。
- C12：审批门。
- C13：模块开关。
- C14：密钥规则。
- C15：n8n 接入规范。
- C16：正式网页安全检查。
- C17：审计日志页面。
- C18：组织结构。
- C19：内部通讯预留。
- C20：最终封板。

真实业务模块不要在 C07G 中启动。下一步建议进入 C08 Module Adapter，但必须由老板审核后单独启动。

## 十五、最终验收命令记录

C07G 初始只读审计已执行：

- `git status --short --untracked-files=all`：通过，初始工作区 clean。
- `git log --oneline -18`：通过，HEAD 为 `ace9112 docs: add C07F module production release`，
  最近提交链包含 C07A-F、C06F 和 C05G。
- HEAD 确认：通过，当前 HEAD 是 `ace9112`，即 C07F commit。
- 已阅读并归纳：
  - `docs/C05_PERMISSION_SYSTEM_SEAL.md`
  - `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`
  - `docs/C07_MODULE_ISOLATION_PLAN.md`
  - `docs/C07_MODULE_REGISTRY_BACKEND.md`
  - `docs/C07_MODULE_FRONTEND_ISOLATION.md`
  - `docs/C07_MODULE_ISOLATION_VERIFICATION.md`
  - `docs/C07_MODULE_STAGING_ACCEPTANCE.md`
  - `docs/C07_MODULE_PRODUCTION_RELEASE.md`
- 已查看 C07 当前状态：
  - `README.md`
  - `CHANGELOG.md`
  - `backend/README.md`
  - `frontend/README.md`

C07A-F 最终 commit 链条：

- `f5925ed docs: add C07A module isolation plan`
- `32f1454 feat: add C07B module registry backend`
- `f59ae65 feat: add C07C module-aware frontend isolation`
- `f8c8c88 test: add C07D module isolation verification`
- `0ae9c43 docs: add C07E module staging acceptance`
- `ace9112 docs: add C07F module production release`

文档完成后执行的最终检查命令和结果：

- `git status --short --untracked-files=all`：通过，显示本轮 C07G 文档变更和新增
  `docs/C07_MODULE_ISOLATION_SEAL.md`。
- `git diff --check`：通过。
- `frontend npm run verify`：通过，`Frontend foundation checks passed.`。
- `frontend npm run typecheck`：通过。
- `frontend npm run build`：通过，Next.js production build 成功，生成 18 个静态页面。
- `node --test tests/frontend/permissions.test.mjs`：通过，`1 pass`。
- `node --test tests/frontend/permission-management.test.mjs`：通过，`1 pass`。
- `node --test tests/frontend/module-isolation.test.mjs`：通过，`1 pass`。
- 后端 C07B/C07D module registry 最小测试和 C05/C06 权限回归最小测试：
  - 普通沙箱执行
    `docker-compose -p barong-ops-console-c07g-test -f docker-compose.example.yml build backend`
    因 Docker socket 权限不足失败。
  - 按权限规则提权后，example backend image build 通过。
  - `docker-compose -p barong-ops-console-c07g-test -f docker-compose.example.yml up -d db`：
    通过，仅启动 C07G example project 的测试 DB。
  - `docker-compose -p barong-ops-console-c07g-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini upgrade head`：
    通过，仅作用于 C07G example DB，升级到现有 `c05b_permissions_001`。
  - `docker-compose -p barong-ops-console-c07g-test -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_modules_registry.py tests/backend/test_permissions_api.py tests/backend/test_permission_assignments_api.py tests/backend/test_user_management_api.py`：
    通过，`47 passed`。
  - `docker-compose -p barong-ops-console-c07g-test -f docker-compose.example.yml down --volumes --remove-orphans`：
    通过，仅清理 C07G example project 的临时容器、network 和 volume。
- `./scripts/production_smoke_check.sh`：
  - 普通沙箱内 DNS 解析失败，`Could not resolve host: ops.barongyekhna.com`。
  - 按权限规则提权重跑同一只读命令后通过，`Production smoke check passed for https://ops.barongyekhna.com`。
- `./scripts/staging_smoke_check.sh`：
  - 普通沙箱内 Docker socket 权限不足。
  - 按权限规则提权重跑同一只读命令后通过，`Staging smoke check passed.`。
- `./scripts/check_dual_env_status.sh`：
  - 普通沙箱内 Docker socket 权限不足。
  - 按权限规则提权重跑同一只读命令后通过，确认 production/staging frontend/backend/postgres 均运行，
    host port `5432` 未监听，production smoke 通过，staging smoke 通过。
- `./scripts/check_safe_release_plan.sh`：通过，`Safe release plan check passed.`。
- 最终 `git status --short --untracked-files=all`：仅包含 C07G 文档新增和
  README/CHANGELOG/C07 相关文档更新：
  - `M CHANGELOG.md`
  - `M README.md`
  - `M backend/README.md`
  - `M docs/C07_MODULE_FRONTEND_ISOLATION.md`
  - `M docs/C07_MODULE_ISOLATION_PLAN.md`
  - `M docs/C07_MODULE_ISOLATION_VERIFICATION.md`
  - `M docs/C07_MODULE_PRODUCTION_RELEASE.md`
  - `M docs/C07_MODULE_REGISTRY_BACKEND.md`
  - `M docs/C07_MODULE_STAGING_ACCEPTANCE.md`
  - `M frontend/README.md`
  - `?? docs/C07_MODULE_ISOLATION_SEAL.md`

## 十六、C07G 最终结论

C07 模块隔离体系已封板。

最终保留边界：

- `/modules/registry` 和 `/modules/me` 均要求登录，未登录为 401。
- frontend proxy 精确放行 `/api/backend/modules/registry` 和 `/api/backend/modules/me`。
- frontend proxy 不放开危险 `/modules/*` 宽通配。
- business 模块无权限 `show_locked` / `locked`。
- admin/system 模块无权限 `hide_when_denied` / `hidden`。
- `planned`、`adapter_pending`、`unavailable` 模块不可 executable。
- User Management 仍 owner-only。
- Permission Management 仍 owner-only。
- `/users` 后端仍 owner-only。
- `/auth/register` 仍 404。
- C05 权限系统未被破坏。
- C06 用户权限管理未被破坏。
- C07 未接 K01。
- C07 未接 P 系列。
- C07 未接 n8n/WooCommerce/MinIO/Filebrowser 真实业务。
- C07 未创建真实业务任务。
- C07 未实现 Module Adapter。
- C07 未实现 Execution Provider。
- C07 未实现模块沙箱。
- C07 未实现模块开关。
- C07 未实现审批门。
- C07 未实现密钥规则。
- C07 未实现 n8n 接入规范。

完成 C07G 后等待老板审核，不进入 C08，不进入 K01，不进入 P 系列，不接真实业务，不发布
staging/production。
