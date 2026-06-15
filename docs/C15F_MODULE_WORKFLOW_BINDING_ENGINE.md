# C15F Module Workflow Binding Engine

日期：2026-06-15 UTC

C15F 在 C15A Workflow Registry 之后增加 Module Workflow Binding Engine
（模块工作流绑定引擎）。本阶段只定义 module -> workflow 白名单、绑定状态、
access control、isolation rules 和静态决策；不执行 workflow，不调用 n8n，不调用外部
API，不修改 production/staging，不运行 Docker/pytest，不修改 C15A-E 层实现。

## 1. Module Workflow Binding Model

C15F 的绑定记录形状固定为：

```text
ModuleWorkflowBindingRecord
  module_id: string
  allowed_workflows: tuple[string, ...]
  binding_status: active | read_only | blocked
```

派生规则：

- `module_id` 来自已注册 module manifest。
- `allowed_workflows` 只包含 C15A registry 中同 module 且 `status=active` 的 workflow。
- `binding_status=active` 表示该 module 至少有一个 active workflow。
- `binding_status=read_only` 表示该 module 只有 deprecated workflow。
- `binding_status=blocked` 表示该 module 没有 active/deprecated workflow，或只有
  inactive/error workflow。
- deprecated/inactive/error workflow 保留在 `registered_workflows`、
  `read_only_workflows` 或 `blocked_workflows` 中，但不进入 `allowed_workflows`。

当前默认 C15A 派生结果：

```text
module_id: integration.n8n_test_bridge
allowed_workflows:
  - n8n.workflow.integration.n8n_test_bridge.dispatch.v1
read_only_workflows:
  - n8n.workflow.integration.n8n_test_bridge.legacy.v1
binding_status: active
```

只读 API：

```text
GET /module-workflow-bindings/model
```

## 2. Enforcement Rules

强制规则：

- 未注册 workflow：拒绝。
- 未绑定 workflow：拒绝。
- workflow 不在 module 的 `allowed_workflows` 白名单：拒绝。
- workflow 已注册但不是 active：拒绝。
- module 任意选择 workflow：拒绝。
- 匹配成功只表示 C15F binding validation pass，不授予 runtime execution。

决策 API：

```text
GET /module-workflow-bindings/decision?module_id=...&workflow_id=...
GET /module-workflow-bindings/enforcement
```

典型拒绝码：

```text
c15f_module_workflow_request_invalid
c15f_module_not_registered
c15f_workflow_not_registered
c15f_module_binding_missing
c15f_workflow_not_allowed_for_module
c15f_workflow_binding_not_active
c15f_cross_module_workflow_call_blocked
```

## 3. Access Control System

Access control 固定依赖 C15A：

```text
registry_source = C15A Workflow Registry
whitelist_field = allowed_workflows
module_identifier_field = module_id
workflow_identifier_field = workflow_id
```

规则：

- module 只能访问自身 `allowed_workflows` 中的 workflow。
- workflow 必须存在于 C15A registry。
- module binding 必须是 active。
- 不允许 implicit workflow access。
- 不允许 fallback workflow。
- 不允许 arbitrary workflow selection。
- 不暴露 hidden webhook reference。

只读 API：

```text
GET /module-workflow-bindings/access-control
GET /module-workflow-bindings/validation
```

## 4. Isolation Rules

Isolation rules：

- 一个 workflow 在 C15A 中只属于一个 module。
- C15F `allowed_workflows` 只能包含同一 `module_id` 拥有的 workflow。
- module A workflow 不等于 module B workflow。
- 禁止跨模块 workflow 调用。
- 跨模块请求在 gateway dispatch 之前拒绝。
- runtime workflow reassignment 禁止。

只读 API：

```text
GET /module-workflow-bindings/isolation-rules
```

## 5. C15F Completion Status

Completion API：

```text
GET /module-workflow-bindings/completion-status
```

C15F completed:

- module workflow binding model implemented.
- `module_id` / `allowed_workflows` / `binding_status` implemented.
- Binding enforcement implemented.
- Unbound workflow rejection implemented.
- Arbitrary workflow call rejection implemented.
- C15A registry access control implemented.
- Cross-module isolation implemented.
- Read-only backend API implemented.
- Frontend backend proxy exact GET allowlist updated.
- Static backend/frontend regression tests added but not executed per safety rule.

Safety limits preserved:

- no runtime execution
- no external API call
- no production change
- no staging change
- no docker
- no pytest
- no git commit
- no modification of previous C15A-E layer implementation files

C15F completion status: complete.

## 6. Readiness For C15G

Can proceed to C15G: YES.

Condition:

- C15G must consume C15F binding decisions as validation only.
- C15G must not treat C15F `workflow_access_allowed=true` as direct runtime execution
  permission.
- C15G must preserve C15A as workflow registry source of truth.
- C15G must not introduce cross-module workflow calls, fallback workflow selection,
  external API calls, production/staging changes, Docker, pytest, or git commit unless
  separately approved.
