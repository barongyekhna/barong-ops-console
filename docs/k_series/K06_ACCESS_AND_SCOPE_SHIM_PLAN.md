# K06 Access And Scope Shim Plan

Status: K06A access/scope design draft, pending owner review.

Date: 2026-06-12.

## 1. 当前现实

- 正式 scope 未完成。
- C07/C08/C13/C18 还没有全部完成。
- K 系列必须 `scope-adapter-pending`。
- K 系列必须使用 K Scope Shim。
- K 系列不能自己发明永久 scope。
- K 系列不能修改 core auth / permission / users / roles / organizations /
  scope runtime。

Temporary shim fields remain:

```text
workspace_key = default_independent_store
business_context = independent_store
scope_mode = adapter_pending
```

## 2. K Scope Shim

Future function draft:

```text
require_k_product_knowledge_access(current_user, action)
```

Recommended inputs:

- `current_user`: authenticated backend user from the existing dependency
  style.
- `action`: one of `read`, `create`, `update`, `archive`,
  `attributes.manage`, `keywords.manage`, or `risk_terms.manage`.
- Future optional context: `product_id`, `workspace_key`, `business_context`,
  `scope_mode`.

Recommended behavior:

- If K feature flag disabled, return 404 by default to keep dormant K API
  hidden. A 403 response may be used if the owner prefers explicit denial.
- If formal C scope adapter does not exist, fallback to owner or K-prefixed
  permission.
- If formal C scope adapter exists, future K25/K26 can replace the fallback
  branch with the official adapter.
- Owner role may pass the fallback check, following current backend owner
  behavior.
- Non-owner users must have the matching K-prefixed permission.
- All product queries must be constrained by `workspace_key`,
  `business_context`, and `scope_mode`.
- The default adapter-pending scope is:

```text
workspace_key = default_independent_store
business_context = independent_store
scope_mode = adapter_pending
```

Required action-to-permission mapping:

| Action | Permission key |
| --- | --- |
| `read` | `k.product_knowledge.read` |
| `create` | `k.product_knowledge.create` |
| `update` | `k.product_knowledge.update` |
| `archive` | `k.product_knowledge.archive` |
| `attributes.manage` | `k.product_knowledge.attributes.manage` |
| `keywords.manage` | `k.product_knowledge.keywords.manage` |
| `risk_terms.manage` | `k.product_knowledge.risk_terms.manage` |

Rules:

- Do not modify core auth/permission runtime.
- Do not alter `users`, `roles`, `permissions`, `organizations`, or formal
  scope tables.
- Do not create a K-only permanent scope system.
- Do not bypass the shim for direct repository or service access.
- Do not widen access with generic permissions such as `product.read` or
  `admin.product.*`.

## 3. Feature flag

Recommended flag:

```text
K_PRODUCT_KNOWLEDGE_ENABLED=false
```

Rules:

- Default is false.
- K06B must not read production or staging env.
- K06B must not enable K API by default.
- K06B must not expose a frontend menu.
- K06B must not connect staging or production.

Observed backend config style:

- `backend/app/core/config.py` uses pydantic settings through `Settings` and
  `get_settings()`.
- No K feature flag exists in the current read-only scan.

K06B implementation recommendation:

- If owner approval limits K06B to the K module path, define a K-local
  `feature_flags.py` default that returns disabled and document the future
  config binding.
- If the owner explicitly approves a config touchpoint, use the existing
  `Settings` style and add a default-false boolean. This must still avoid
  reading production/staging env files.

## 4. 未来接正式 C adapter 的替换点

Future K25/K26 replacement points:

- Replace `scope_shim.py` fallback logic with the official C scope adapter once
  C18 is complete and approved.
- Replace hard-coded adapter-pending values with official workspace,
  organization, or module scope values after formal scope is available.
- Replace K-local permission fallback with official module permission
  resolution after C07/C08/C13 are complete and approved.
- Register K permissions through the official module/permission registry only
  after the relevant C gates and owner approval.
- Keep K table queries scoped by the official adapter fields after migration
  strategy is reviewed.
- Keep `operation_logs` table structure unchanged. Any audit display integration
  waits for C17/K21.
- Keep provider secret access out of K scope shim. Live provider secrets wait
  for C14/C09/K27 and owner approval.
