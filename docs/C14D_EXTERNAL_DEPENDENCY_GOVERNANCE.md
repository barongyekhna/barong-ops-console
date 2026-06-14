# C14D External Dependency Governance Layer

日期：2026-06-14 UTC

C14D 在 C14A Secret Classification、C14B Secret Storage Policy 和 C14C Secret
Access Control 的基础上，定义并实现 External Dependency Governance Layer
（外部依赖治理层）。本阶段只做动态注册、信任评估、policy 决策、unknown service
quarantine proposal、dependency binding 和 execution gate 合同；不接真实外部 API，
不读取 secret，不执行 runtime，不修改 production/staging。

## 1. External Service Registry Design

C14D 新增动态外部服务注册合同：

```text
ExternalService
  service_id: string
  service_type: ai_api | automation | payment | storage | custom | unknown
  status: active | suspended | quarantined | pending
  trust_level: high | medium | low | untrusted
  metadata: object
```

实现位置：

- `backend/app/schemas/external_dependency.py`
- `backend/app/core/external_dependencies.py`
- `backend/app/services/external_dependency_governance.py`
- `backend/app/api/routes/external_dependencies.py`

注册规则：

- C14D 默认 registry 为空：`EXTERNAL_SERVICE_REGISTRY_V1 = ()`。
- C14D 不内置 n8n、AI、payment、storage 或任何 provider allowlist。
- 动态注册数据必须从受控 registry source 进入
  `validate_external_service_registry()`。
- `service_id` 只校验安全命名格式和敏感片段，不校验 provider 名单。
- 未注册服务不会被静态拒绝，而是进入 C14D unknown service quarantine flow。

为避免 C14D 前置层截断 unknown service，本轮同步调整：

- C07 `ModuleManifestV1.external_dependencies` 改为动态安全 key 校验。
- C08 `ModuleAdapterDependencyDeclaration.dependency_key` 改为动态安全 key 校验。
- frontend adapter normalizer 不再使用静态服务名集合。

## 2. Trust Evaluation Model

C14D 新增动态信任评估：

```text
evaluate_external_service_trust(service, context)
  -> dynamic_trust_score: 0..100
  -> dynamic_trust_level: high | medium | low | untrusted
  -> access_recommendation: allow | restrict | quarantine
```

输入因素：

- usage history：`total_calls`、`successful_calls`
- module sensitivity：`module_sensitivity`
- risk context：`risk_level`
- past violations：`past_violations`
- approval outcomes：`approval_requests`、`approved_requests`、
  `approval_rejections`
- current service status：`active`、`pending`、`suspended`、`quarantined`
- configured trust level：初始信任等级只作为评分输入，不作为最终结论

信任等级不是固定配置。最终访问建议由 score、status、risk、approval 和 violations
共同决定：

- `allow`：高分、active、无 policy/risk 阻断。
- `restrict`：中低分、pending、或上下文风险需要收紧。
- `quarantine`：untrusted、quarantined、严重低分或 unknown。

## 3. Policy Decision Engine

C14D 新增 policy 决策：

```text
PolicyDecision
  service_id
  module
  action
  context
  decision: allow | deny | quarantine | require_approval
  reason
```

决策规则：

- default deny：没有 explicit policy 时，已注册服务也 `deny`。
- unknown service：`quarantine`，并生成 registration proposal。
- suspended service：`deny`。
- quarantined service：`quarantine`。
- high-risk / critical context：`require_approval`，必须交给 C12。
- trust below policy minimum：`require_approval`。
- policy explicit deny：`deny`。
- policy explicit allow 仍必须同时满足 status、trust、risk 和 context。

C14D policy selector 支持 `service_id` 或 `service_type`。这些 selector 是动态
policy data，不是代码里的 service allowlist。核心代码不内置任何 provider 名单。

## 4. Unknown Service Flow

当 C14D 检测到未注册外部服务：

1. 不允许直接执行。
2. `PolicyDecision.decision = quarantine`。
3. `reason = c14d_unknown_service_quarantined`。
4. `registration_required = true`。
5. `quarantine_required = true`。
6. 生成 `ExternalServiceRegistrationProposal`。
7. proposal 通过只读 API 暴露给 C14 UI：
   `GET /external-dependencies/proposals`。
8. 等待人工或系统审批；C14D 本轮不开放注册/审批写接口。

Registration proposal 只包含安全 metadata：

```text
proposal_id
service_id
service_type = unknown
status = quarantined
source_module
source_adapter
source_action
detection_context
ui_surface = c14_external_provider_control_panel
```

proposal 不包含 secret、token、endpoint、provider URL、Authorization header 或 raw
payload。

## 5. Dependency Binding Rules

模块与外部服务绑定必须满足：

- module/adapter 必须显式声明 dependency intent。
- service 必须已注册，或以 unknown/pending 进入 proposal flow。
- `ExternalDependencyPolicy` 必须允许 module + action + service/service_type。
- trust evaluation 必须达到 policy 要求。
- high-risk、critical、low-trust、restrict recommendation 或 policy 要求时，必须
  `require_approval` 并等待 C12。
- C14D binding 不读取 secret，不解析 credential，不创建外部调用。

只读 binding 汇总 API：

```text
GET /external-dependencies/bindings
```

返回每个声明依赖的：

- module
- adapter
- action
- service_id
- service_registered
- service_status
- trust_level
- binding_status
- policy_decision
- requires_c12_approval

## 6. Execution Gate Integration Point

C14D 作为 external dependency control layer 插入 C09 之前：

```text
C08 -> C13 -> C12 -> C14 -> C09 -> C10
```

实现点：

- `ExternalDependencyGate.check()`
- `C14D_GATE = ExternalDependencyGate()`
- `ExecutionFlowGate._c14_block_reason()`
- `ExecutionFlowGateDecision.c14_allowed`
- `ExecutionFlowGateDecision.c14_external_dependency_bypass_blocked`

C13E 当前执行链路：

```text
C08 adapter/action binding
-> C12 approval requirement
-> C14D external dependency policy/trust/context gate
-> C09 provider contract binding and no-execute state
-> C10 sandbox entry state
```

`ExecutionRequestContractV1` validation 仍通过 `C13E_GATE.check()` 统一进入 gate。
C14D 不修改 execution request，不创建 execution request，不触发 C09 provider，不进入
C10 runtime。

## 7. Safety Rules

C14D 固定安全边界：

- no hardcoded service/provider allowlist
- no runtime execution
- no direct external API call
- no provider endpoint call
- no secret read/write
- no secret leakage from C14A-C14C
- no C09 direct secret access
- no C10 raw secret injection
- no production changes
- no staging changes
- no docker
- no pytest executed in this task
- no git commit

只读 API：

```text
GET /external-dependencies/registry
GET /external-dependencies/proposals
GET /external-dependencies/bindings
```

未新增 POST/PATCH/DELETE registration、approval、execute、sync 或 provider call API。

## 8. C14D Completion Status

C14D completed:

- ExternalService dynamic registry contract implemented.
- Default registry and policy set are empty; no built-in provider allowlist exists.
- C07/C08 dependency declarations now accept dynamic safe dependency keys.
- Trust evaluation model implemented from usage history、module sensitivity、
  risk context、past violations and approval outcomes.
- Policy decision engine implemented with default deny, explicit policy only,
  unknown quarantine and high-risk C12 approval requirement.
- Unknown service registration proposal flow implemented and exposed for C14 UI.
- Dependency binding read model implemented.
- Execution gate integration inserted before C09 through C13E.
- Frontend backend proxy exposes only exact GET C14D read paths.
- Static regression tests were added/updated, but not executed per task safety rule.

C14D completion status: complete.

Readiness for C14E: YES, if C14E remains a separately approved task and does not treat
C14D as authorization to connect live providers, read secrets, create runtime execution,
modify production/staging, or bypass C12 approval for high-risk external dependency use.
