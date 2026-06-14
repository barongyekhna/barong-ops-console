# C14X-A AI Execution Binding Registry

日期：2026-06-14 UTC

C14X-A 是 C14 完整封板之后的独立 AI Execution Binding Registry（AI 执行绑定注册系统）。
它引用 C14 的安全边界，但不重新打开 C14A-C14G，不修改 `docs/C14_FINAL_STATE.json`，
不新增 C14 sub-module。

本阶段只定义 AI routing path registry、binding rules、flow mapping 和 UI inspection
model；registry 本身不执行 AI，不选择模型，不调用模型，不调用外部 API，不修改
production/staging。

## 1. Binding Registry Structure

核心结构：

```text
AIExecutionBindingRecord
  key: string
  model: string
  capability: serp | reasoning | writing | embedding
  module: string
  status: draft | active | disabled | deprecated
```

实现位置：

- `backend/app/schemas/ai_execution_binding.py`
- `backend/app/core/ai_execution_bindings.py`
- `backend/app/services/ai_execution_binding_registry.py`
- `backend/app/api/routes/ai_execution_bindings.py`

默认注册表：

```text
AI_EXECUTION_BINDINGS_V1 = ()
```

默认状态没有 AI model binding，没有 active route，没有 runtime grant。

每条 binding record 同时固定以下安全字段：

- `explicit_binding_required = true`
- `one_to_one_binding_required = true`
- `key_to_model_fixed = true`
- `model_to_capability_fixed = true`
- `capability_to_module_fixed = true`
- `automatic_model_selection_allowed = false`
- `fallback_routing_allowed = false`
- `implicit_execution_routing_allowed = false`
- `registry_executes_ai = false`
- `runtime_execution_allowed = false`
- `model_invocation_allowed = false`
- `external_api_call_allowed = false`
- `production_change_allowed = false`

## 2. Binding Rule Model

C14X-A 强制 1:1:1:1 binding：

```text
key -> model -> capability -> module
```

规则：

- `key` 在 registry 内唯一。
- `model` 在 registry 内唯一。
- `capability` 在 registry 内唯一。
- `module` 在 registry 内唯一。
- `key -> model` 固定绑定，不允许同一个 key 指向多个 model。
- `model -> capability` 固定绑定，不允许同一个 model 承载多个 capability binding。
- `capability -> module` 固定绑定，不允许 capability 自动漂移到其他 module。

禁止项：

- 自动选择模型。
- fallback routing。
- implicit execution routing。
- 未注册 module binding。
- 在 binding record 中携带 endpoint、token、credential、Authorization、URL 或其他
  runtime-sensitive value。

Registry behavior：

- binding creation = explicit only。
- binding update = manual override only。
- binding deletion = controlled operation only。
- C14X-A 不开放 POST/PATCH/DELETE API；本轮只读。

## 3. Execution Flow Mapping

C14X-A flow mapping：

```text
UI exact binding key inspection
-> C14X-A registry exact key lookup
-> fixed key -> model -> capability -> module path
-> stop before any runtime execution boundary
```

关键约束：

- registry only defines routing path。
- registry does not execute AI。
- registry does not invoke model。
- registry does not call external API。
- registry does not create C09 execution request。
- registry does not enter C10 sandbox。
- missing key 不触发 fallback。
- disabled/deprecated/draft binding 不触发替代 model 或替代 module。

只读 flow API：

```text
GET /ai-execution-bindings/execution-flow
```

返回 route path：

```text
key
model
capability
module
status
routing_path = (key, model, capability, module)
execution_allowed = false
```

## 4. UI To Registry Interaction Model

UI 只允许 inspection：

```text
GET /ai-execution-bindings/registry
GET /ai-execution-bindings/rules
GET /ai-execution-bindings/execution-flow
GET /ai-execution-bindings/validation
GET /ai-execution-bindings/ui-interaction
GET /ai-execution-bindings/completion-status
```

Frontend backend proxy 只精确放行上述 GET path，不开放 wildcard。

UI interaction rules：

- lookup mode = exact binding key only。
- create/update/delete surface = not exposed in UI。
- UI 不选择 model。
- UI 不发起 execution。
- UI 不触发 provider call。
- UI 不写 registry。
- UI 不做 fallback route suggestion。

## 5. C14X-A Completion Status

C14X-A completed:

- Binding registry structure implemented.
- Binding rule model implemented.
- 1:1:1:1 binding validation implemented.
- Execution flow mapping implemented.
- UI -> registry interaction model implemented.
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

C14X-A completion status: complete.

## 6. Readiness For C14X-B

Can proceed to C14X-B: YES.

Condition:

- C14X-B must remain downstream of this registry contract.
- C14X-B must not introduce automatic model selection, fallback routing, implicit execution
  routing, runtime model invocation, external API calls, production/staging changes, Docker,
  pytest, or git commit unless separately approved.
