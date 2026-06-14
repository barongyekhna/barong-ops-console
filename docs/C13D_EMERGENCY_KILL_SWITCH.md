# C13D Emergency Kill Switch

日期：2026-06-14 UTC

C13D 是极简全局一票否决系统。它只定义并实现 `global_kill_switch`
布尔开关，不扩展 governance system，不新增 override 机制，不修改 C13C policy
engine 规则，不设计新的 execution flow。

## 1. Kill Switch Implementation

新增实现：

- `backend/app/schemas/emergency_kill_switch.py`
- `backend/app/services/emergency_kill_switch.py`
- `backend/app/services/module_switch_runtime_gate.py`
- `backend/app/services/module_switch_policy_engine.py`
- `tests/backend/test_module_switch_runtime_gate.py`

状态模型：

```text
global_kill_switch = TRUE | FALSE
```

默认值：

```text
global_kill_switch = FALSE
```

授权规则：

```text
only system_owner may toggle global_kill_switch
```

当前系统角色中，`system_owner` 对应现有 `owner` role。非 owner 调用
`set_global_kill_switch(...)` 会得到 `system_owner_required`。

## 2. Block Flow Definition

当 `global_kill_switch = TRUE`：

```text
C13D Emergency Kill Switch
  -> block C08 module resolution
  -> block C12 approval request creation
  -> block C09 execution request contract generation
  -> block C10 sandbox entry
  -> block C13B module switch runtime gate
  -> block C13C policy evaluation / effective registry generation
```

Block decision：

```text
state = GLOBAL_KILL_SWITCH
switch_status = OFF
enforcement_result = BLOCKED
reason = global_kill_switch_enabled
execution_chain_stopped = true
approval_request_allowed = false
execution_request_allowed = false
sandbox_entry_allowed = false
```

## 3. System Override Rule

`global_kill_switch = TRUE` ignores all module switch states:

```text
module ON  -> BLOCKED
module OFF -> BLOCKED
missing   -> BLOCKED
invalid   -> BLOCKED
```

This is not a module override mechanism. There is no force-ON, force-OFF,
bypass-policy, partial freeze, consistency layer, registry override, or policy
engine mutation in C13D.

## 4. Safety Boundary

C13D keeps the existing safety boundary:

- no runtime execution
- no external API
- no production or staging change
- no docker
- no pytest execution in this task
- no git commit
- no new API route
- no database migration
- no approval bypass
- no sandbox unlock
- no C13C group / batch / inheritance / dependency policy rule change

## 5. C13D Completion Status

C13D completed:

- `global_kill_switch = TRUE/FALSE` state implemented.
- TRUE blocks C08 / C09 / C10 / C12 through the existing C13B entry gate.
- TRUE blocks C13B and C13C before module switch / policy decisions continue.
- TRUE ignores all module switch states.
- Toggle authorization is restricted to system owner / existing owner role.
- No governance expansion, override mechanism, C13C policy rule change,
  consistency layer, or execution flow design was added.

可以进入 C13E，前提是 C13E 明确范围，并继续保持 no execution / no external API /
no production or staging change 边界。
