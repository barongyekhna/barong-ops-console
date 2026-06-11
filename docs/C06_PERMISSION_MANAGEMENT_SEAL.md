# C06 Permission Management Seal

日期：2026-06-11 UTC

本文件记录 C06F：用户权限管理系统最终封板归档。

C06F 是文档封板任务，不是功能开发任务、发布任务、真实业务接入任务或 P 系列任务。
本轮不新增 API，不新增 UI，不新增 migration，不发布 staging，不发布 production，不执行
safe release execute，不创建 production 测试账号，不执行 production grant/update/revoke
写入型动态验证，不读取真实 env，不操作 production/staging 容器或数据库，不 psql，不手写
SQL，不 git commit。

## 一、封板结论

C06 用户权限管理系统已完成并封板。

最终结论：

- C06 已完成 owner-only 权限管理闭环。
- C06A 完成用户权限管理方案审计与任务拆分。
- C06B 完成后端 owner-only 权限分配 API。
- C06C 完成前端 User Management 用户权限管理 UI。
- C06D 完成 staging 动态联调验收。
- C06E 完成 production 安全发布归档。
- staging 和 production 已完成对应验收。
- owner 可以通过 User Management 查看、grant、update、revoke explicit permission
  assignments。
- C06 不接真实业务，不进入 P 系列，不接 WooCommerce、n8n 真实业务流、MinIO、
  Filebrowser 或产品页业务模块。
- 下一步应按项目规划进入后续阶段，不在 C06F 中启动。

## 二、C06 完成范围

C06A：用户权限管理审计与方案设计。

- 记录文件：`docs/C06_PERMISSION_MANAGEMENT_PLAN.md`。
- 完成 C05 权限基础、后端 permission resolver、frontend permission UX、User
  Management owner-only 边界和未完成授权能力审计。
- 明确 C06 只做 owner 管理用户 explicit permission assignment，不接真实业务。
- 明确 C06B/C06C/C06D/C06E/C06F 任务拆分。

C06B：后端 owner-only permission assignment API。

- 记录文件：`docs/C06_PERMISSION_BACKEND_ACCESS.md`。
- 新增 assignment list/grant/update/revoke API。
- 所有 C06B API 均为 owner-only。
- 完成 registry key 校验、wildcard 拒绝、owner target 拒绝、duplicate active
  assignment 拒绝、disabled/expired 生效规则、high-risk 确认和 operation_logs 写入。

C06C：前端用户权限管理 UI。

- 记录文件：`docs/C06_PERMISSION_FRONTEND_UI.md`。
- 在 User Management 中新增“权限”入口和“用户权限管理”面板。
- owner 可查看 explicit assignments，可 grant 普通 permission，可 update assignment，
  可 revoke assignment。
- high-risk 权限有二次确认 UI。
- 前端只是 UX，真实安全边界仍以后端 owner-only API 为准。

C06D：staging 联调验收。

- 记录文件：`docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`。
- staging backend/frontend safe release 已完成。
- staging grant/update/revoke 写入型动态流程、`/permissions/me` 生效/移除、
  high-risk 二次确认、operation_logs 和 non-owner 越权拒绝均已验证。

C06E：production 发布归档。

- 记录文件：`docs/C06_PERMISSION_PRODUCTION_RELEASE.md`。
- production backend/frontend safe release 已完成。
- production owner 只读验收完成。
- production 未创建测试账号，未执行 grant/update/revoke 写入型动态验证，以避免污染
  production 权限数据。

## 三、最终后端能力

C06B 后端最终提供以下 owner-only API：

- `GET /permissions/users/{user_id}/assignments`
- `POST /permissions/users/{user_id}/assignments`
- `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`
- `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`

最终后端规则：

- 全部 C06B assignment API 使用 `require_owner()`。
- 不使用 `require_permission("permissions.manage")` 开放 grant/update/revoke。
- `permission_key` 必须来自 enabled `permission_registry`。
- 不允许 wildcard grant。
- 不允许给 owner 创建普通 assignment。
- duplicate active assignment 会被拒绝。
- disabled assignment 不生效。
- expired assignment 不生效。
- registry disabled permission 不生效。
- revoke 是 soft revoke，设置 assignment disabled，不硬删审计历史。
- grant/update/revoke 会写 `operation_logs`。
- high-risk permission grant/update/revoke 需要 reason 和二次确认策略。
- high-risk grant 和 high-risk re-enable 或 scope-changing update 要求
  `confirm_high_risk=true` 和
  `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`。
- `/permissions/me` 会反映 effective permission changes。
- `/users` 仍使用 `require_owner()`，仍 owner-only。
- `/auth/register` 仍不存在，返回 404。
- API 响应不返回 `password_hash`、password、token、secret 或 Authorization header。

## 四、最终前端能力

C06C 前端最终能力：

- User Management 中新增“权限”入口。
- 权限管理入口仅 owner 可见。
- owner 可查看 explicit assignments。
- owner 可 grant 普通 permission。
- owner 可 update assignment。
- owner 可 revoke assignment。
- owner 用户显示 full access，不渲染成普通 assignment。
- permission registry 用于权限选择。
- wildcard `*` 不作为可选 grant。
- high-risk 权限有二次确认 UI。
- 前端传 reason、`confirm_high_risk`、`confirmation_text`，后端记录
  `operation_logs`。
- frontend proxy 精确放行 C06B assignment API，不开放通用 permissions proxy。
- 前端只是 UX，不是安全边界。

保留边界：

- `/users` 导航和页面仍只认 `permissions.is_owner_full_access=true`。
- 普通 non-owner 即使拥有 `users.manage` assignment，也不能看到 User Management。
- `super_admin` 不默认看到 User Management 或权限管理入口。
- 后端 401/403/409/422 和 C06B owner-only API 才是真实授权结果。

## 五、最终权限规则

最终权限规则：

- owner 全局全权限，不依赖 assignment。
- owner 的 `/auth/me` 和 `/permissions/me` 返回 wildcard full access。
- non-owner 通过 explicit assignment 获权。
- `super_admin` 不默认拥有全局权限，也不默认拥有 grant/revoke 能力。
- `role_default_permissions` 不自动生效。
- permission assignment 才是实际授权来源。
- disabled、expired 或 registry disabled assignment 不进入 effective permissions。
- high-risk permission 需要显式确认。
- scope 字段可以保存与展示。
- 完整组织 scope 管理不在 C06 完成。
- company/factory/department scope admin 延后到 C18 或后续组织权限阶段。
- 不允许用 role default、前端状态或本地缓存替代后端 effective permission 判断。

## 六、staging 验收摘要

C06D 已完成。

staging 验收摘要：

- staging backend safe release 完成。
- staging frontend safe release 完成。
- staging 无新增 migration。
- staging Alembic current/head 只读检查为 `c05b_permissions_001 (head)`。
- staging `permission_registry` 曾为空，已按老板批准通过后端 helper 初始化 seed。
- staging registry count 为 18。
- staging owner UI 验收通过。
- staging owner assignment list 验收通过。
- staging grant/update/revoke 动态验证通过。
- staging `/permissions/me` 生效/移除验证通过。
- staging high-risk 二次确认验证通过。
- staging operation_logs 验证通过。
- staging non-owner 越权验证通过。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认 grant/revoke。
- C06D 未读取 env。
- C06D 未操作 postgres 容器。
- C06D 未 psql。
- C06D 未手写 SQL。
- C06D 未接真实业务。

## 七、production 发布摘要

C06E 已完成。

production 发布与验收摘要：

- production backend safe release 完成。
- production frontend safe release 完成。
- production 未执行 Alembic upgrade，因为 C06B/C06C 没有新增 migration。
- production Alembic current/head 保持 `c05b_permissions_001 (head)`。
- production `permission_registry` 发布后为空，已按老板批准通过后端 helper 初始化
  seed，count=18。
- production `/auth/me` owner 验收通过。
- production `/permissions/me` owner 验收通过。
- production `/permissions/registry` owner 验收通过。
- production owner assignment list API 验收通过。
- production frontend C06C UI marker/bundle 验收通过。
- production `/users` 仍 owner-only。
- production `/auth/register` 仍 404。
- production 未创建测试账号。
- production 未执行 grant/update/revoke 写入型动态验证，原因是避免污染生产数据。
- 写入型流程已在 C06D staging 完整验证。
- C06E 未操作 production postgres 容器。
- C06E 未 psql。
- C06E 未手写 SQL。
- C06E 未读取 env。
- C06E 未接真实业务。

## 八、operation_logs 与审计结论

C06 审计结论：

- grant/update/revoke 写 `operation_logs`。
- `operation_logs` 记录 actor。
- `operation_logs` 记录 target。
- `operation_logs` 记录 `permission_key`。
- `operation_logs` 记录 `assignment_id`。
- `operation_logs` 记录 scope。
- `operation_logs` 记录 before/after。
- `operation_logs` 记录 reason。
- `operation_logs` 记录 `risk_level`。
- `operation_logs` 记录 result。
- C06D 已验证 operation_logs 写入。
- C06E production 未做写入型验证以避免污染生产数据。
- 未来如开放非 owner 授权，必须继续保留 `operation_logs` 和高风险确认。

operation log action：

- `permission.assignment.grant`
- `permission.assignment.update`
- `permission.assignment.revoke`

## 九、安全边界

C06F 不发布。

C06 和 C06F 明确不做：

- 不创建真实业务任务。
- 不接 n8n、WooCommerce、P 系列、MinIO、Filebrowser 真实业务流程。
- 不接产品页业务模块。
- 不改变 `/users` owner-only 后端边界。
- 不完整实现组织结构 scope 管理。
- 不让 `super_admin` 默认拥有全局或 grant/revoke 权限。
- 不让 `role_default_permissions` 自动生效。
- 不创建 production 测试账号。
- 不执行 production grant/update/revoke 写入型动态验证。
- 不读取或打印 `.env.production`。
- 不读取或打印 `.env.staging`。
- 不打印 secret、token、password 或 Authorization header。
- 不操作 production/staging postgres 容器。
- 不直接操作 production/staging 数据库。
- 不 psql。
- 不手写 SQL。
- 不新增 migration。
- 不修改 Nginx 或证书。
- 不 git commit。

## 十、未完成范围与后续任务

未完成范围：

- C06 不包含完整 company/factory/department 组织 scope 管理。
- C06 不实现 scoped admin / delegated admin 授权策略。
- C06 不接真实业务模块。
- C06 不接 n8n/P 系列/WooCommerce/MinIO/Filebrowser 真实业务流程。
- C06 不让 `super_admin` 默认拥有 grant/revoke。
- C06 不让 `role_default_permissions` 自动生效。
- C06 不创建 production 测试账号。

后续任务边界：

- C18 或后续：组织/公司/工厂/部门 scope 深化。
- 未来阶段：scope admin / delegated admin 授权策略。
- 未来业务模块接入：必须带 Permission Manifest。
- 未来业务模块菜单策略：业务板块 `show_locked`，管理/系统板块
  `hide_when_denied`。
- 未来 production non-owner 动态验证：需要明确 production 测试账号和老板批准。
- 不在 C06F 中启动真实业务模块。

## 十一、最终验收命令记录

C06F 初始只读审计已执行：

- `git status --short --untracked-files=all`：通过，初始工作区 clean。
- `git log --oneline -12`：通过，HEAD 为
  `f01cb1b docs: add C06E permission production release`。
- HEAD 确认：通过，HEAD 是 `f01cb1b`，包含 C06E commit。
- 已阅读并归纳：
  - `docs/C05_PERMISSION_SYSTEM_SEAL.md`
  - `docs/C06_PERMISSION_MANAGEMENT_PLAN.md`
  - `docs/C06_PERMISSION_BACKEND_ACCESS.md`
  - `docs/C06_PERMISSION_FRONTEND_UI.md`
  - `docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`
  - `docs/C06_PERMISSION_PRODUCTION_RELEASE.md`
- 已查看 C06 当前状态：
  - `README.md`
  - `CHANGELOG.md`
  - `backend/README.md`
  - `frontend/README.md`

C06A-E 最终 commit 链条：

- `98ce194 docs: add C06A permission management plan`
- `ad6e8ae feat: add C06B permission assignment API`
- `7301095 feat: add C06C permission management UI`
- `ba11f2e docs: add C06D permission staging acceptance`
- `f01cb1b docs: add C06E permission production release`

文档完成后执行的最终检查命令和结果：

- `git status --short --untracked-files=all`：通过，显示本轮 C06F 文档变更和新增
  `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`。
- `git diff --check`：通过。
- `frontend npm run verify`：通过，`Frontend foundation checks passed.`。
- `frontend npm run typecheck`：通过。
- `frontend npm run build`：通过，Next.js production build 成功，生成 18 个静态页面。
- `node --test tests/frontend/permissions.test.mjs`：通过，`1 pass`。
- `node --test tests/frontend/permission-management.test.mjs`：通过，`1 pass`。
- C06B 后端 Docker 测试：
  `docker-compose -p barong-ops-console-c06f-test -f docker-compose.example.yml run --rm --no-deps backend python -m pytest tests/backend/test_permission_assignments_api.py`
  普通沙箱内因 Docker socket 权限不足失败；提权后该 `--no-deps` 形式能启动 backend
  测试容器，但未启动 example `db`，因此 7 个用例均因 `db` 主机无法解析产生环境错误。
- C06B 后端 Docker 测试修正为 example DB 依赖形式后通过：
  `docker-compose -p barong-ops-console-c06f-test -f docker-compose.example.yml build backend`，
  `docker-compose -p barong-ops-console-c06f-test -f docker-compose.example.yml up -d db`，
  `docker-compose -p barong-ops-console-c06f-test -f docker-compose.example.yml run --rm backend sh -c "python -m alembic -c backend/alembic.ini upgrade head && python -m pytest tests/backend/test_permission_assignments_api.py"`：
  通过，`7 passed`；测试结束后清理了该 example 项目的临时 db 容器、network 和 volume。
- `./scripts/production_smoke_check.sh`：普通沙箱内 DNS 解析失败；按权限规则提权重跑同一
  只读脚本后通过，`Production smoke check passed for https://ops.barongyekhna.com`。
- `./scripts/staging_smoke_check.sh`：普通沙箱内 Docker socket 权限不足；按权限规则提权重跑
  同一只读脚本后通过，`Staging smoke check passed.`。
- `./scripts/check_dual_env_status.sh`：普通沙箱内 Docker socket 权限不足；按权限规则提权重跑
  同一只读脚本后通过。结果确认 production frontend/backend/postgres 均运行，staging
  frontend/backend/postgres 均运行，host port `5432` 未监听，production smoke 通过，
  staging smoke 通过。
- `./scripts/check_safe_release_plan.sh`：通过，`Safe release plan check passed.`。
- `git status --short --untracked-files=all`：最终状态见本轮报告；仅包含 C06F 文档新增和
  README/CHANGELOG/C06 相关文档更新。

## 十二、C06F 最终结论

C06 用户权限管理系统已封板。

最终保留边界：

- 后端 C06B assignment API 全部 owner-only。
- 前端权限管理入口仍仅 owner 可见。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- owner 仍全局全权限。
- `super_admin` 仍不默认 grant/revoke。
- `role_default_permissions` 仍不自动生效。
- high-risk 二次确认策略保留。
- grant/update/revoke 仍由后端记录 `operation_logs`。
- staging 已完成写入型动态验收。
- production 已完成 C06B/C06C 发布和 owner 只读验收。
- production 未创建测试账号，未执行 grant/update/revoke 写入型动态验证。
- production `permission_registry` 已通过后端 helper 初始化 seed，count=18。
- C06 不接真实业务。
- C06 不进入 P 系列。

完成 C06F 后等待审核，不进入下一阶段，不进入 P 系列，不接真实业务，不发布
staging/production。
