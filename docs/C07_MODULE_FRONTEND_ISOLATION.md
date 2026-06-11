# C07C Module Frontend Isolation

日期：2026-06-11 UTC

C07C 在 C07B 后端 Module Manifest / Registry API 已完成后，把前端导航、权限展示和
路由保护接到模块 access state。C07C 只做前端 module-aware navigation / route guard，
不接真实业务，不新增后端 API，不新增 migration，不发布 staging 或 production。

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

## 下一步

建议下一步是 C07D：模块隔离 verify/test 体系。C07D 应继续补自动化校验，确保模块
manifest、navigation、permissions、route namespace、proxy allowlist 和 C05/C06 回归在未来
模块接入时不会漂移。
