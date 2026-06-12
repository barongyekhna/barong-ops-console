# K06D Router Registration Decision Gate

Status: K06D router registration decision gate draft, pending owner review.

Date: 2026-06-12.

## 1. 当前决策

K router 暂不注册，除非老板明确批准 K06F。

Current default decision:

- Keep `backend/app/modules/k_series/product_knowledge/router.py` unregistered.
- Do not modify `backend/app/main.py`.
- Do not add K to any core router registry.
- Do not expose K frontend navigation.
- Keep K API disabled by default.

## 2. 为什么暂不注册

- 注册 router 可能需要改 `backend/app/main.py` 或 core router registry。
- 这会进入总控 runtime 接入点，而不再只是 dormant module skeleton。
- C08 Module Adapter may not be complete or confirmed for K runtime registration.
- C13 module switches / feature flag enforcement may not be complete or confirmed.
- C18 formal scope may not be complete or confirmed.
- K 当前 API 默认 disabled，但 route 一旦注册就可能成为外部可达路径。
- Even a disabled route increases the surface that must be covered by feature flag, permission, scope, module switch, proxy, and rollback rules.
- K permission keys are currently module-local constants and are not confirmed as formally registered permissions.
- K Scope Shim is a temporary adapter-pending boundary, not formal C18 scope.
- Current `backend/app/main.py` uses explicit router includes, so route registration is a concrete runtime change requiring approval.

## 3. K06F 允许条件

K06F can register the router only if all conditions are true:

- K06D reviewed.
- K06E tests pass.
- Owner explicitly approves route registration.
- C07 module isolation registration pattern confirmed.
- C08/C13 status reviewed.
- C18 status reviewed if any scope behavior is affected.
- API remains disabled by default.
- No frontend menu exposure.
- No live provider.
- No n8n.
- No staging/production.
- No production or staging env read.
- Permission behavior remains default-deny for non-owner users unless formally approved.
- Module switch / feature flag behavior is consistent with the approved C pattern.
- Rollback plan exists.

## 4. K06F 最小允许改动候选

The following files are future candidates only and require owner approval before any edit:

- `backend/app/main.py` or existing router registry, requires owner approval.
- `backend/app/core/config.py` if feature flag must use core config, requires owner approval.
- `backend/app/core/permissions.py` if permission registry must include K permissions, requires owner approval.
- Any C module registry file, requires owner approval.
- Any module manifest / registry source used by C07/C08/C13, requires owner approval.

If owner approval is not explicit, K06F must not touch these files.

## 5. K06F 禁止事项

- 不正式 scope 接入。
- 不 frontend menu。
- 不 live provider。
- 不 n8n。
- 不 staging/production。
- 不绕过 feature flag。
- 不默认开放给所有用户。
- 不放开 frontend proxy 通配。
- 不修改 P-series workflow JSON。
- 不修改 n8n draft lane。
- 不读取 production/staging env。
- 不连接 DeepSeek、OpenAI、Claude、SERP、WooCommerce、Google Sheets、WeCom、MinIO、Filebrowser 或任何 live service。
- 不修改 users / roles / permissions / organizations / operation_logs table structure。
