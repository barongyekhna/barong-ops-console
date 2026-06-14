# C12C Approval Workflow Engine

日期：2026-06-14 UTC

C12C 在 C12A `ApprovalRequest` schema 和 C12B `ApprovalRuleEngine` 之后新增
Approval Workflow Engine。本阶段只做内存 workflow state transition，不执行 sandbox，
不触发 C09 execution，不写 DB，不新增 API，不调用 external API，不修改 production /
staging，不 git commit。

## 1. Workflow Engine Implementation

新增：

- `backend/app/services/approval_workflow_engine.py`
- `ApprovalWorkflowEngine.create_workflow(request) -> ApprovalWorkflow`
- `ApprovalWorkflowEngine.apply_decision(decision) -> ApprovalWorkflow`
- `ApprovalWorkflowEngine.update_state(target_state, decision=decision) -> ApprovalWorkflow`

更新：

- `backend/app/schemas/approval.py`
  - 新增 `ApprovalWorkflow`
  - 新增 `ApprovalWorkflowHistoryEntry`
  - 新增 `ApprovalWorkflowState`
  - 新增 `ApprovalWorkflowEvent`
  - `ApprovalStatusTraceEntry` 增加 `decision_source`

`create_workflow(request)` 接收 C12A `ApprovalRequest` 或可验证为该 schema 的 mapping。
它只把已存在的 execution request 语义映射到 C12 workflow，不创建、不提交、不运行 C09
execution。

创建流程：

```text
ApprovalRequest(status=pending)
  -> create ApprovalWorkflow(state=pending)
  -> record execution_request_triggered history
  -> call C12B ApprovalRuleEngine.evaluate(request)
  -> apply_decision(decision)
```

`apply_decision(decision)` 接收 C12B 或人工审批产生的 `ApprovalDecision`。如果 decision
为 `pending`，workflow 保持 pending 并记录 `c12b_decision_recorded`；如果 decision 为
终态，则走 `update_state()`。

`update_state(target_state, decision=decision)` 是唯一状态变更入口。它校验状态、校验
transition rule、校验 decision status 与目标状态一致、更新 `ApprovalRequest.status`、追加
`status_trace`，并追加 workflow history。

## 2. State Machine Definition

状态：

```text
pending
approved
rejected
auto_approved
```

初始状态：

```text
pending
```

终态：

```text
approved
rejected
auto_approved
```

允许状态变更：

```text
pending -> approved
pending -> rejected
pending -> auto_approved
```

不允许：

- `approved` / `rejected` / `auto_approved` 之后再次变更。
- `pending -> pending` 作为状态变更。
- 任意未知状态。

`pending` decision 不是状态变更，只是 decision history record。

## 3. Transition Rules

- 新 workflow 必须从 `ApprovalRequest.status == pending` 创建。
- 创建 workflow 时追加 `request_created` trace。
- C12B 输出 `auto_approved` 时执行 `pending -> auto_approved`。
- C12B 输出 `rejected` 时执行 `pending -> rejected`，例如 request/context snapshot identity
  drift。
- 人工审批输出 `approved` 时执行 `pending -> approved`。
- 人工审批输出 `rejected` 时执行 `pending -> rejected`。
- 终态 workflow 收到任何新 decision 都抛出 `ApprovalWorkflowTransitionError`。

## 4. Event Flow

Execution request trigger:

```text
execution request context
  -> C12A ApprovalRequest
  -> ApprovalWorkflowEngine.create_workflow()
  -> ApprovalWorkflow(state=pending)
```

C12B decision update:

```text
ApprovalWorkflow(state=pending)
  -> ApprovalRuleEngine.evaluate(ApprovalRequest)
  -> ApprovalDecision
  -> ApprovalWorkflowEngine.apply_decision()
  -> update_state() when decision is terminal
```

History tracking:

- `ApprovalWorkflow.history` records event, state change, timestamp, decision status,
  decision source, actor id, and reason.
- `ApprovalRequest.status_trace` records request-level state changes and decision source.
- `pending` C12B decision is recorded in workflow history with `state_changed=false` and does
  not append request-level status trace.

## 5. Integration Rules

C12A integration:

- Workflow input is `ApprovalRequest`.
- Workflow output is `ApprovalWorkflow`, containing the updated `ApprovalRequest`.
- Request status and trace are updated through schema copies, not in-place mutation.

C12B integration:

- `create_workflow()` calls `ApprovalRuleEngine.evaluate()`.
- `apply_decision()` accepts `ApprovalDecision`.
- C12B remains a pure evaluator; C12C owns state transition.

Safety boundary:

- No C09 execution provider call.
- No C10 sandbox runtime or bridge call.
- No external API call.
- No database write.
- No operation log write.
- No production or staging mutation.
- No runtime action execution.

## 6. C12C Completion Status

C12C completed as an in-memory workflow engine with state machine, transition rules, event flow,
history tracking, and C12A/C12B integration.

可以进入 C12D。C12D 的合理范围是审批持久化/API/权限边界设计，必须继续显式声明是否写
DB、是否写 operation log、reviewer 权限如何校验，以及 C09/C10 仍如何保持阻断。
