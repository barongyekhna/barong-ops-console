# C07C Module Frontend Isolation

日期：2026-06-11 UTC

C07C 在 C07B 后端 Module Manifest / Registry API 已完成后，把前端导航、权限展示和
路由保护接到模块 access state。C07C 只做前端 module-aware navigation / route guard，
不接真实业务，不新增后端 API，不新增 migration，不发布 staging 或 production。

2026-06-11 C07E 补充：staging 模块隔离验收已归档在
`docs/C07_MODULE_STAGING_ACCEPTANCE.md`。C07E 已将本文件记录的 C07C frontend
runtime 通过 safe release 发布到 staging frontend。发布后 `/login` 返回 200，
frontend bundle 命中 `ModuleAccessProvider`、`modules/me`、`admin.users`、
`admin.permissions`、`show_locked`、`Module unavailable`、`No permission`、
`adapter_pending` 等 marker；frontend proxy 对
`/api/backend/modules/registry` 和 `/api/backend/modules/me` 返回 backend 401，对
`/api/backend/modules/not-allowed` 返回 404。C07E 未发布 production，未读取真实 env，
未接 K01/P 系列或真实 provider。

2026-06-12 C07F 补充：production 模块隔离发布已归档在
`docs/C07_MODULE_PRODUCTION_RELEASE.md`。C07F 已将本文件记录的 C07C frontend runtime
通过 OPS01 safe release 发布到 production。production `/modules` 页面返回 200，linked
JS bundle 命中 `ModuleAccessProvider`、`useModuleAccess`、`modules/me`、`admin.users`、
`admin.permissions`、`business.jobs`、`integration.n8n_test_bridge`、`adapter_pending`、
`show_locked` 和 `hide_when_denied` 等 marker；frontend proxy 对
`/api/backend/modules/registry` 和 `/api/backend/modules/me` 返回 backend 401，对
`/api/backend/modules/not-allowed` 返回 404。C07F 未读取真实 env，未操作 postgres，未发布
staging，未接 K01/P 系列或真实业务。

2026-06-12 C07G 补充：C07 模块隔离体系已在
`docs/C07_MODULE_ISOLATION_SEAL.md` 完成最终封板。C07G 确认本文件记录的
ModuleAccessProvider、module-aware navigation、route guard、Module Unavailable / No
Permission 文案和精确 frontend proxy allowlist 已形成 C07 前端最终状态；C07G 未新增 UI、
后端 API、migration 或真实业务接入。

2026-06-11 C07D 补充：模块隔离 verify/test 体系已完成并归档在
`docs/C07_MODULE_ISOLATION_VERIFICATION.md`。C07D 强化
`tests/frontend/module-isolation.test.mjs` 和 `frontend/scripts/verify-foundation.mjs`，
把本文件的 navigation `module_key`、proxy allowlist、safe fallback、business
`show_locked`、admin/system `hide_when_denied`、planned/adapter_pending/unavailable
不可进入、K01/P 系列不接入和 C05/C06 helper 回归固化为自动测试。

## 实现范围

C07C 新增前端模块类型、纯 helper 和 API client：

- `frontend/src/lib/module-registry.ts`
- `frontend/src/lib/module-registry-api.ts`
- `frontend/src/lib/module-notices.ts`
- `frontend/src/components/module-access-provider.tsx`

前端通过现有 restricted same-origin backend proxy 调用：

- `GET /modules/registry`
- `GET /modules/me`

API client 不打印 token、password、secret 或 Authorization header。`/modules/me` 失败时，
前端会标记 `module_access_unknown`，回落到 C05D/C06C 权限导航策略，并额外保证
admin/system 模块不会因为模块 API 失败暴露给 non-owner。

## Proxy allowlist

C07C 只在 frontend backend proxy 精确放行：

- `GET /modules/registry`
- `GET /modules/me`

没有放开 `/modules/*` 通配，没有放开 module API namespace，没有降低 C05/C06 proxy
安全边界。`frontend/scripts/verify-foundation.mjs` 已检查这两个 C07B module registry
路径必须存在于精确 allowlist。

## Module-aware navigation

前端导航项已从短 key 升级为 C07B registry 中的 namespaced `module_key`：

- Dashboard -> `core.dashboard`
- Foundation Demo -> `experimental.foundation_demo`
- n8n Test Bridge -> `integration.n8n_test_bridge`
- Products -> `business.products`
- Modules -> `admin.modules`
- Agents -> `admin.agents`
- Workflows -> `admin.workflows`
- Jobs -> `business.jobs`
- Artifacts -> `business.artifacts`
- Reviews -> `business.reviews`
- Errors -> `system.errors`
- Memory Events -> `system.memory_events`
- User Management -> `admin.users`
- Settings -> `admin.settings`

Permission Management 仍归属 `/users` 内部 panel，不新增独立菜单，但前端显式记录为
`admin.permissions`，并保持 owner-only。

导航规则：

- owner full access 可见 core/admin/system。
- admin/system denied 继续 `hide_when_denied`。
- business denied 继续 `show_locked`。
- `planned`、`adapter_pending`、`unavailable` 显示安全状态 badge，不能触发真实动作。
- 未注册 `module_key` 会被 `assertNavigationModulesRegistered()` 和
  `tests/frontend/module-isolation.test.mjs` 捕获，除非未来显式标记为 core shell exception。

Sidebar 只显示安全状态：`Locked`、`Planned`、`Adapter pending`、`Unavailable`。前端不显示
内部 dependency 细节，不显示 env、secret、token、URL 或凭据。`external_dependencies`
归一化时只保留安全名称，例如 `n8n`、`woocommerce`、`minio`、`filebrowser`、
`ai_provider`。

## Module-aware route guard

C07C 扩展现有 route guard 为 module-aware decision：

- 按 `route_namespace` 匹配，而不是只按精确 pathname。
- 直接访问 hidden admin/system module 时显示无权访问。
- 直接访问 locked business module 时显示无权访问。
- 直接访问 `planned`、`adapter_pending`、`unavailable` module 时显示“模块暂不可用”。
- owner full access 对 available/sealed/enabled 模块通过。
- `planned`、`adapter_pending` 和 `unavailable` 即使 owner 可见，也不能进入真实工作台。

提示文案：

- 标题：`模块暂不可用`
- 内容：`此模块尚未接入执行能力，或当前账号没有访问此模块的权限。如需开通，请联系 Owner。`
- 标题：`无权访问此模块`
- 内容：`当前账号缺少进入该模块所需权限。前端提示仅用于体验，最终权限以后端校验为准。`

前端 route guard 仍只是 UX。最终权限以后端 `require_owner()`、`require_permission()` 和
模块后端校验为准。

## C05/C06 行为保持

C07C 保持 C05/C06 封板边界：

- `/users` 后端仍 owner-only。
- User Management 前端入口仍只对 owner full access 可见。
- Permission Management UI 仍只对 owner 可见。
- C06C 权限管理面板仍在 User Management 内可用。
- business `show_locked` 行为保持。
- admin/system `hide_when_denied` 行为保持。
- No Permission 组件继续可用，并新增 module-aware 文案。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认全局。
- owner full access 继续全局可见。
- `/auth/register` 仍 404。

## 明确不做

C07C 明确不做：

- 不接真实业务模块。
- 不新增 SEO/GEO/K01/P 系列页面或菜单。
- 不接 K01。
- 不接 P01/P02/P03/P04/P05/P06/P07/P08。
- 不接 n8n、WooCommerce、MinIO、Filebrowser。
- 不实现 Module Adapter。
- 不实现 Execution Provider。
- 不实现模块 sandbox。
- 不实现模块开关。
- 不实现审批门。
- 不实现密钥规则。
- 不新增后端 API。
- 不新增 migration。
- 不发布 staging。
- 不发布 production。
- 不执行 safe release。

## 测试

新增 `tests/frontend/module-isolation.test.mjs`，使用 Node 内置 test runner，不新增依赖。
覆盖：

- `/modules/registry` 和 `/modules/me` frontend proxy 精确 allowlist。
- `verify-foundation` 对 C07 module proxy allowlist 的检查。
- owner 可见、admin/system non-owner hidden、business non-owner locked。
- `planned`、`adapter_pending` 不可进入。
- `/modules/me` 缺失时安全降级，不暴露 admin/system 给 non-owner。
- external dependencies 安全名称过滤。
- navigation `module_key` 与 registry mock 对齐。
- User Management / Permission Management owner-only。
- locked、hidden、unavailable、owner route guard decision。
- C05D/C06C 回归假设、`role_default_permissions` 和 `super_admin` 边界。

C07D 已在该文件中继续强化：

- C07B module registry proxy 只能精确允许 `GET /modules/registry` 和
  `GET /modules/me`，并确认 `/permissions/me`、`/permissions/registry` 和 C06B
  assignment API 仍保留。
- User Management 必须映射 `admin.users`，Permission Management 必须映射
  `admin.permissions`。
- unavailable module 必须显示 Module Unavailable decision，不能 enter。
- `/modules/me` 失败或缺失时，non-owner 直接访问 admin/system route 仍是 No
  Permission，不暴露入口。
- wildcard permission 不能绕过 owner-only、hidden、locked 或 module access state。
- Module Unavailable / No Permission 文案不得包含 secret/token/password/env/URL/
  credential/API key。
- business navigation 必须保持 `show_locked`；admin/system navigation 必须保持
  `hide_when_denied`。
- navigation 中不得默认启用 K01、P 系列、WooCommerce、MinIO 或 Filebrowser 菜单。

`frontend/scripts/verify-foundation.mjs` 也在 C07D 中升级为只读 verifier，检查 C07C
helper/provider/test 文件存在、C07 proxy allowlist 精确、没有 `/modules/*` 宽通配、
C05/C06 permission proxy 路径保留，以及没有 live n8n/WooCommerce/MinIO/Filebrowser
action route marker。

## 下一步

C07G 已完成 C07 模块隔离最终封板，记录在 `docs/C07_MODULE_ISOLATION_SEAL.md`。下一步应
进入 C08 Module Adapter，但不得在 C07G 中接 K01/P 系列或真实
n8n/WooCommerce/MinIO/Filebrowser。
