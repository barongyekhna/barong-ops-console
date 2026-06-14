# C14E Dependency Binding Rules Layer

日期：2026-06-14 UTC

C14E 在 C14D External Dependency Governance Layer 之后新增 Dependency Binding
Rules Layer（依赖绑定规则层）。本阶段只建立 module、capability、external service
之间的静态 contract、validation、inspection 和 audit 模型；不执行 runtime，不调用外部
API，不读取 secret，不修改 staging/production。

## 1. Binding Model Design

C14E 新增 Module -> Service binding：

```text
ModuleServiceBinding
  module_key
  service_id
  binding_status: active | restricted | disabled
  allowed_capabilities: serp | reasoning | writing | embedding
```

实现位置：

- `backend/app/schemas/dependency_binding.py`
- `backend/app/core/dependency_bindings.py`
- `backend/app/services/dependency_binding_rules.py`
- `backend/app/api/routes/external_dependencies.py`

默认绑定：

```text
integration.n8n_test_bridge -> n8n
  binding_status = disabled
  allowed_capabilities = []
```

该默认记录只表示“显式声明并禁用”。它不会注册 n8n，不会授予能力，不会连接服务。
C14D 的 external service registry 仍保持默认空注册表。

## 2. Capability Mapping System

C14E 定义固定能力集合：

```text
serp
reasoning
writing
embedding
```

能力授权必须同时满足三层声明：

```text
ModuleCapabilityBinding
  module_key
  allowed_capabilities
  binding_status

ServiceCapabilityMapping
  service_id
  capabilities
  binding_status

ModuleServiceBinding
  module_key
  service_id
  allowed_capabilities
  binding_status
```

任何一层缺失、disabled、能力不相交、service 未注册或 service 状态不满足要求，均不会形成
可用 graph edge。

默认 capability mapping：

```text
integration.n8n_test_bridge.allowed_capabilities = []
n8n.capabilities = []
```

因此默认状态没有 `serp/reasoning/writing/embedding` 任一能力被授予。

## 3. Dependency Graph Structure

C14E dependency graph 模型：

```text
module -> capability -> external service
```

Graph snapshot 包含：

- module nodes：module key、declared service ids、allowed capabilities、binding status。
- capability nodes：固定 C14E capability 集合及引用计数。
- service nodes：service id、C14D 注册状态、service status、trust level、service capabilities。
- edges：module + capability + service 的显式绑定边。
- validation：当前规则集校验结果。

只读 inspection API：

```text
GET /external-dependencies/binding-rules
GET /external-dependencies/dependency-graph
GET /external-dependencies/binding-validation
GET /external-dependencies/binding-audit
```

Frontend backend proxy 只精确放行上述 GET 路径，不开放 wildcard。

## 4. Validation Rules

C14E validation 强制：

- module 必须先在 C07 module manifest 声明 external dependency。
- adapter dependency 必须属于自己的 module，且必须被 module manifest 声明。
- 每个声明的 module external dependency 都必须有显式 ModuleServiceBinding。
- module 使用 service capability 前，必须有 ModuleCapabilityBinding。
- service 被用于 capability 前，必须有 ServiceCapabilityMapping。
- active/restricted binding 必须声明至少一个 capability。
- disabled binding 不允许授予 capability。
- active/restricted binding 必须指向已注册 service。
- active binding 要求 service status 为 active。
- restricted binding 不允许指向 suspended/quarantined service。
- capability 必须同时存在于 module allowed capabilities 和 service capability mapping。
- graph edge 只能从同一 module 的显式 binding 生成，禁止跨 module 泄漏。

Validation output：

```text
DependencyBindingValidationResult
  valid
  issues[]
  module_service_binding_count
  module_capability_binding_count
  service_capability_mapping_count
  graph_edge_count
```

Audit output：

```text
DependencyBindingAuditEntry
  audit_id
  module_key
  service_id
  capability
  binding_status
  decision: allow | restrict | block
  reason
```

默认 n8n 绑定的 audit decision 为 `block`，reason 为
`c14e_module_service_binding_disabled`。

## 5. Safety Rules

C14E 固定安全边界：

- no runtime execution
- no external API call
- no provider endpoint call
- no secret read/write
- no implicit provider usage
- no cross-module binding leakage
- no production change
- no staging change
- no docker
- no pytest executed in this task
- no git commit

本阶段新增的是 contract-only read model。没有新增 POST、PATCH、DELETE、run、execute、
sync、register、approve 或 provider action endpoint。

## 6. C14E Completion Status

C14E completed:

- Module -> Service binding model implemented.
- Capability binding model implemented for `serp/reasoning/writing/embedding`.
- Service capability mapping model implemented.
- Default explicit disabled binding for `integration.n8n_test_bridge -> n8n` added.
- Dependency graph model implemented.
- Validation rules implemented for explicit binding、no implicit provider usage and no
  cross-module binding leakage.
- Read-only inspection/audit APIs added.
- Frontend proxy exact GET allowlist updated.
- Static regression tests added but not executed per safety rule.

C14E completion status: complete.

Readiness for C14F: YES, if C14F remains contract-only or receives separate approval
before any runtime execution, external API integration, staging/production change, docker,
pytest, or git commit activity.
