# C13C Module Switch Policy Layer

日期：2026-06-14 UTC

C13C 在 C13A/C13B 基础上构建 Module Switch Policy System。范围限定为
只读静态 policy model、dependency graph、cascading rules、group/batch switch
evaluation、inheritance policy，以及将 C13B runtime gate 的默认 registry 来源切换为
policy engine 的 effective registry。

本阶段不新增 API、migration、frontend runtime UI、provider 调用、sandbox 能力、队列、
worker、webhook、operation log 写入、staging/production 操作或 git commit。

## 1. Policy Engine Design

新增实现：

- `backend/app/schemas/module_switch.py`
- `backend/app/core/module_switches.py`
- `backend/app/services/module_switch_policy_engine.py`
- `tests/backend/test_module_switch_runtime_gate.py`

Policy engine:

```text
ModuleSwitchPolicyEngine
  input:
    ModuleSwitchRegistryRecord[]
    ModuleSwitchDependencyRule[]
    ModuleSwitchGroupPolicy[]
    ModuleSwitchInheritancePolicy[]
    optional ModuleSwitchGroupSwitchRequest[]
    optional ModuleSwitchBatchSwitchRequest[]

  output:
    ModuleSwitchPolicyEvaluation[]
    effective ModuleSwitchRegistryRecord[]
```

Evaluation order:

```text
1. load module registry records
2. apply inherited group default policy
3. apply group switch requests
4. apply batch module switch requests
5. fail-close invalid or missing module records
6. apply dependency cascade recursively
7. emit effective registry for C13B runtime gate
```

Design boundaries:

- Policy engine is read-only and in-memory.
- Group/batch requests are evaluation inputs only; they do not persist or mutate runtime state.
- C13B runtime gate public methods remain unchanged.
- Allowed still means "may continue to C12"; it does not approve or execute.
- Blocked still means no C12 approval request, no C09 execution request, no C10 sandbox entry.

## 2. Dependency Graph Model

新增 `ModuleSwitchDependencyRule`:

```text
parent_module_key
child_module_key
parent_off_behavior = disable_child
recursive = true
reason
```

C13C dependency graph:

| Parent | Child | Rule |
| --- | --- | --- |
| `admin.users` | `admin.permissions` | User management OFF disables permission management. |
| `admin.modules` | `admin.agents` | Module registry OFF disables agent registry. |
| `admin.modules` | `admin.workflows` | Module registry OFF disables workflow registry. |
| `business.jobs` | `experimental.foundation_demo` | Jobs OFF disables foundation demo. |
| `business.jobs` | `integration.n8n_test_bridge` | Jobs OFF disables n8n test bridge. |
| `business.jobs` | `business.artifacts` | Jobs OFF disables artifacts. |
| `business.jobs` | `business.reviews` | Jobs OFF disables reviews. |
| `system.operation_logs` | `system.errors` | Operation logs OFF disables error review. |
| `system.operation_logs` | `system.memory_events` | Operation logs OFF disables memory event review. |

ON/OFF dependency rules:

```text
parent ON:
  child evaluates its own module/group/batch/inheritance policy

parent OFF / DEPRECATED / MAINTENANCE / missing / invalid:
  child effective state becomes OFF
  child enabled becomes false
  child disabled_reason records safe dependency summary
```

Dependency cascade always runs after module, group, batch and inheritance logic.
This makes dependency OFF the final safety constraint.

## 3. Cascading Behavior Rules

C13C cascade behavior:

- Parent OFF disables direct children.
- Recursive cascade is enabled for every dependency rule.
- A child disabled by cascade becomes a parent for its own children.
- A child cannot override a parent-disabled state.
- Batch/group ON cannot re-enable a child when an upstream parent is OFF.
- Cycles are guarded by visited edges; repeated edges do not loop indefinitely.
- Missing or invalid parent records are treated as OFF and cascade to children.

Example:

```text
admin.users OFF
  -> admin.permissions OFF
    -> admin.settings OFF, if that recursive edge exists in policy input
```

## 4. Group Switch Logic

新增 `ModuleSwitchGroupPolicy`:

```text
group_key
module_keys
default_state
disabled_reason
batch_control_supported = true
```

C13C default groups:

- Category groups: `category.core`, `category.admin`, `category.system`,
  `category.business`, `category.integration`, `category.experimental`
- Navigation groups: `navigation.overview`, `navigation.system`,
  `navigation.registry`, `navigation.operations`, `navigation.governance`

Group switch control:

```text
ModuleSwitchGroupSwitchRequest(group_key, state, disabled_reason)
  -> applies requested state to all modules in group
  -> no persistence
  -> no runtime mutation
  -> no provider/sandbox/API side effect
```

Batch switch control:

```text
ModuleSwitchBatchSwitchRequest(module_keys, state, disabled_reason)
  -> applies requested state to listed modules
  -> unknown module targets are rejected
  -> no persistence
  -> no runtime mutation
```

Precedence:

```text
group default < group switch < batch module switch < invalid/missing fail-close < dependency cascade
```

## 5. Inheritance Policy

新增 `ModuleSwitchInheritancePolicy`:

```text
module_key
group_keys
policy_mode = inherit | override
parent_off_overrides_module = true
```

Inheritance logic:

- `inherit`: module may inherit non-ON group default when its direct state is ON.
- `override`: module direct switch record overrides group default policy.
- Group switch and batch switch are explicit evaluation requests and can set module state.
- Parent OFF cascade always overrides inherited, group, batch and module state.
- `parent_off_overrides_module=true` is mandatory in C13C.

Default policy:

- Most modules use `inherit` from category and navigation groups.
- `core.dashboard` and `system.operation_logs` use `override` for group default policy.
- No default group is OFF in C13C, so existing C13B all-registered-modules-ON behavior remains unchanged.

## 6. Safety Rules

C13C guarantees:

- no execution
- no runtime state mutation
- no C09 provider modification
- no C10 sandbox modification
- no external provider call
- no queue / worker / webhook / callback
- no approval bypass
- no approval persistence change
- no execution request generation change beyond existing C13B gate boundary
- no sandbox unlock
- no production or staging change
- no API or migration
- no git commit

Implementation boundary:

- C13C modified only C13 module switch schema/core/service/test/doc surfaces.
- C09/C10 files were not modified.
- Runtime gate still fail-closes missing, duplicate or invalid switch records.
- Effective registry records continue to use `enabled == (state == "ON")`.

## 7. Verification

新增 focused tests:

- recursive dependency cascade
- group switch batch control
- inherit vs override logic
- default effective registry still covers all C07 module keys

Runtime/test/deploy commands were not executed for this stage because C13C
safety explicitly requires no execution. No docker, pytest, dev server,
provider call, staging or production command was run.

## 8. C13C Completion Status

C13C completed:

- policy engine design: completed
- dependency graph model: completed
- ON/OFF dependency rules: completed
- cascading behavior rules: completed
- group switch logic: completed
- batch module switch logic: completed
- inheritance policy: completed
- safety constraints: completed

可以进入 C13D，前提是 C13D 继续明确范围。如果 C13D 要引入 API、持久化 switch
mutation、UI control、audit write 或 production/staging 操作，必须单独授权并重新定义
safety boundary。
