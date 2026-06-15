# C14X-D Module Allocation System

日期：2026-06-15 UTC

C14X-D 在 C14X-C Capability Binding Engine 之前增加 Module Allocation System（模块能力
分配系统）。本阶段只定义静态 module allocation registry、capability assignment model、
module categories、capability budget system、enforcement rules 和 integration flow；
不执行 AI，不调用模型，不调用外部 API，不修改 production 或 staging，不运行 Docker/pytest，
不提交 git commit。

## 1. Module Allocation Registry Design

核心结构：

```text
ModuleAllocationRecord
  module_id: K-series | P-series | SEO | BS
  allowed_capabilities: tuple[serp | reasoning | writing | embedding]
  bound_key: string
  bound_model: string
  status: draft | active | disabled | deprecated
  capability_budgets: tuple[ModuleCapabilityBudget]
```

预算结构：

```text
ModuleCapabilityBudget
  capability: serp | reasoning | writing | embedding
  max_units_per_request: finite integer
  max_units_per_window: finite integer
  window_seconds: finite integer
```

实现位置：

- `backend/app/schemas/module_allocation.py`
- `backend/app/core/module_allocations.py`
- `backend/app/services/module_allocation_system.py`
- `backend/app/api/routes/module_allocations.py`

默认注册表：

```text
MODULE_ALLOCATIONS_V1 = ()
```

默认状态没有 module allocation、没有 active AI access、没有 runtime grant，因为
C14X-A/B/C 默认也没有 active AI execution route。

只读 registry API：

```text
GET /module-allocations/registry
```

## 2. Capability Assignment Model

C14X-D 强制：

```text
module_id -> allowed_capabilities -> bound_key -> bound_model -> finite budget
```

规则：

- capability 必须显式分配给 module。
- 未分配 capability 不允许 implicit access。
- 不存在 shared capability pool；active allocation 中同一个 capability 不允许跨 module
  共享。
- bound key 和 bound model 必须显式声明。
- allocation validation pass 只表示 C14X-D 检查通过，不授予 runtime execution。

只读 assignment API：

```text
GET /module-allocations/assignment-model
```

## 3. Module Categories

C14X-D 定义四类 module category template：

```text
K-series -> writing + reasoning
P-series -> writing
SEO      -> serp + reasoning
BS       -> serp + reasoning + writing + embedding
```

category template 只定义上限，不自动授予能力。实际可用 capability 仍必须出现在
`ModuleAllocationRecord.allowed_capabilities` 中，并且必须有对应 finite budget。

只读 categories API：

```text
GET /module-allocations/categories
```

## 4. Capability Budget System

每个 module capability 必须有有限预算：

- `max_units_per_request`
- `max_units_per_window`
- `window_seconds`

规则：

- 每个 assigned capability 必须有且只能有一个 budget。
- budget capability 必须属于该 module allocation 的 `allowed_capabilities`。
- `max_units_per_request` 不能大于 `max_units_per_window`。
- request usage 超出 per-request limit 时拒绝。
- request usage 超出 window 剩余额度时拒绝。
- 不存在 unlimited AI access。

只读 budget API：

```text
GET /module-allocations/budget-system
```

## 5. Enforcement Rules

请求校验逻辑：

```text
declared module_id + capability + key + requested model + usage units
-> exact C14X-D allocation lookup by module_id
-> require allocation status active
-> require capability explicitly assigned to module
-> require key/model to match bound_key/bound_model
-> require finite budget to cover requested usage
-> missing/mismatch/budget exceeded => reject without fallback
-> match => pass context to C14X-C routing only, no runtime execution grant
```

强制拒绝：

- missing active module allocation。
- capability not assigned to module。
- capability assigned to more than one active module。
- module category capability violation。
- missing/duplicate capability budget。
- budget request limit exceeded。
- budget window exceeded。
- bound key mismatch。
- bound model mismatch。
- implicit capability access。
- shared capability pool。
- unlimited AI access。

只读 enforcement/validation API：

```text
GET /module-allocations/enforcement
GET /module-allocations/validation
GET /module-allocations/request-validation
GET /module-allocations/completion-status
```

Frontend backend proxy 只精确放行上述 GET path，不开放 wildcard、POST/PATCH/DELETE 或
execute/run/invoke/sync path。

## 6. Integration Flow

C14X-D 的集成顺序固定为：

```text
Module
  -> C14X-D allocation check
  -> C14X-C routing
  -> C14X-B model lock
  -> C09 execution
  -> C10 sandbox
```

只读 integration API：

```text
GET /module-allocations/integration-flow
```

C14X-D 不调用 C09，不进入 C10，不执行 AI，不调用模型。C14X-D allocation pass 只是
进入 C14X-C routing 前的静态治理检查。

## 7. C14X-D Completion Status

C14X-D completed:

- Module allocation registry structure implemented.
- Capability assignment model implemented.
- K-series / P-series / SEO / BS category rules implemented.
- Per-module finite capability budget system implemented.
- Strict enforcement rules implemented.
- No implicit capability access validation implemented.
- No shared capability pool validation implemented.
- No unlimited AI access validation implemented.
- Module -> C14X-D -> C14X-C -> C14X-B -> C09 -> C10 integration flow defined.
- Read-only backend API implemented.
- Frontend proxy exact GET allowlist updated.
- Static backend/frontend regression tests added but not executed per safety rule.

Safety limits preserved:

- no runtime execution
- no model invocation
- no external API call
- no production change
- no staging change
- no docker
- no pytest
- no git commit

C14X-D completion status: complete.

## 8. Readiness For C14X-E

Can proceed to C14X-E: YES.

Condition:

- C14X-E must remain downstream of C14X-D/C14X-C/C14X-B.
- C14X-E must not treat module allocation validation as runtime execution permission.
- C14X-E must not introduce implicit capability access, shared capability pools, unlimited
  AI access, auto routing, fallback capability/model selection, runtime model invocation,
  external API calls, production/staging changes, Docker, pytest, or git commit unless
  separately approved.
