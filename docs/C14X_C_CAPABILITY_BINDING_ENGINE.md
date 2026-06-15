# C14X-C Capability Binding Engine

日期：2026-06-15 UTC

C14X-C 在 C14X-A AI Execution Binding Registry 和 C14X-B Model Lock System 之后增加
Capability Binding Engine（能力绑定引擎）。本阶段只定义静态 capability routing、
capability -> model mapping、module capability binding rules、validation 和 integration；
不执行 AI，不调用模型，不调用外部 API，不修改 production 或 staging，不运行 Docker/pytest，
不提交 git commit。

## 1. Capability Routing Model

C14X-C 支持的 capability 集合固定为：

```text
serp
reasoning
writing
embedding
```

每条显式 capability route 必须完整绑定：

```text
CapabilityBindingRecord
  capability: serp | reasoning | writing | embedding
  key: string
  model: string
  module: string
  status: draft | active | disabled | deprecated
```

实现位置：

- `backend/app/schemas/capability_binding.py`
- `backend/app/core/capability_bindings.py`
- `backend/app/services/capability_binding_engine.py`
- `backend/app/api/routes/capability_bindings.py`

默认注册表：

```text
CAPABILITY_BINDINGS_V1 = ()
MODULE_CAPABILITY_BINDINGS_V1 = ()
```

默认状态没有 capability route、没有 capability -> model mapping、没有 module capability
grant，因为 C14X-A/C14X-B 默认也没有 AI binding 或 model lock。
未绑定 capability 的行为固定为 `reject_without_fallback`。

只读 routing API：

```text
GET /capability-bindings/routing-model
```

返回 route path：

```text
routing_path = (capability, key, model, module)
execution_allowed = false
```

## 2. Capability To Model Mapping

C14X-C 的 capability -> model mapping 必须来自显式 C14X-C record，并且必须同时满足：

```text
CapabilityBindingRecord.key == AIExecutionBindingRecord.key
CapabilityBindingRecord.model == AIExecutionBindingRecord.model
CapabilityBindingRecord.capability == AIExecutionBindingRecord.capability
CapabilityBindingRecord.module == AIExecutionBindingRecord.module
CapabilityBindingRecord.key == ModelLockRegistryRecord.key_id
CapabilityBindingRecord.model == ModelLockRegistryRecord.model_id
```

规则：

- capability 不允许 auto-switch model。
- capability 不允许 fallback 到其他 capability。
- capability 不允许 fallback 到其他 model。
- capability 不允许 auto routing。
- model 必须尊重 C14X-B locked model。
- C14X-B validation pass 只表示校验通过，不授予 runtime execution。

只读 mapping API：

```text
GET /capability-bindings/model-mapping
```

## 3. Module Capability Binding Rules

Module binding 结构：

```text
ModuleCapabilityBindingRecord
  module: string
  allowed_capabilities: tuple[serp | reasoning | writing | embedding]
  status: active | disabled
```

规则：

- module -> capability 必须显式声明。
- 没有 module binding 时不允许 implicit access。
- active module binding 中声明的 capability 必须有对应 C14X-C capability route。
- 同一个 capability 不允许出现在多个 module binding 中，避免 capability drift。
- route 的 module 必须在 active module binding 中显式允许该 capability。

只读 module binding API：

```text
GET /capability-bindings/module-bindings
```

## 4. Enforcement Strategy

请求校验逻辑：

```text
declared capability + key + requested model + module
-> exact C14X-C capability binding lookup by capability
-> require key/model/module to match C14X-A binding
-> require model to match C14X-B locked model
-> require module to explicitly allow capability
-> missing or mismatch => reject without fallback
-> match => validation pass only, no runtime execution grant
```

强制拒绝：

- missing capability binding。
- missing C14X-B model lock。
- C14X-A/C14X-C key/model/capability/module/status mismatch。
- C14X-B/C14X-C model mismatch。
- missing active module capability binding。
- module binding does not allow capability。
- orphan module capability binding。
- duplicate capability route。
- duplicate capability across module bindings。

只读 enforcement/validation API：

```text
GET /capability-bindings/enforcement
GET /capability-bindings/validation
GET /capability-bindings/request-validation
GET /capability-bindings/integration
GET /capability-bindings/completion-status
```

Frontend backend proxy 只精确放行上述 GET path，不开放 wildcard、POST/PATCH/DELETE 或
execute/run/invoke/sync path。

## 5. C14X-C Completion Status

C14X-C completed:

- Capability routing model implemented.
- Capability -> model mapping implemented.
- Module capability binding rules implemented.
- Strict enforcement implemented.
- No capability drift validation implemented.
- No auto routing validation implemented.
- No fallback capability/model validation implemented.
- C14X-A registry integration implemented.
- C14X-B model lock integration implemented.
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

C14X-C completion status: complete.

## 6. Readiness For C14X-D

Can proceed to C14X-D: YES.

Condition:

- C14X-D must remain downstream of C14X-A/C14X-B/C14X-C.
- C14X-D must not treat capability binding validation as runtime execution permission.
- C14X-D must not introduce auto routing, fallback capability/model selection, runtime model
  switching, model invocation, external API calls, production/staging changes, Docker,
  pytest, or git commit unless separately approved.
