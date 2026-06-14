# C12D Approval Persistence + API + Permission Boundary

日期：2026-06-14 UTC

C12D 将 C12A-C12C 的内存审批系统扩展为可持久化、可 API 访问、带权限边界的审批服务。
本阶段仍不执行 action，不调用 C09 execution provider，不调用 C10 sandbox，不接外部 provider，
不修改 production/staging，不运行 docker / pytest，不 git commit。

## 1. Persistence Implementation

新增 ORM model:

- `backend/app/models/approval.py`
  - `ApprovalRequestRecord`
  - `ApprovalWorkflowRecord`
  - `ApprovalDecisionRecord`

新增 migration:

- `backend/alembic/versions/20260614_01_create_approval_tables.py`

新增 repository:

- `backend/app/repositories/approvals.py`
  - `ApprovalRepository`
  - `WorkflowRepository`
  - `DecisionRepository`

Repository 支持：

- `save`
- `load`
- `query`

持久化策略：

- 常用查询字段拆成列：`approval_id`、`execution_id`、`status`、`requester_id`、`state` 等。
- 完整 C12A/C12C 对象以 JSON payload 保存：
  - `request_payload`
  - `workflow_payload`
  - `decision_payload`
- 读取时恢复为 `ApprovalRequest`、`ApprovalWorkflow`、`ApprovalDecision` schema。

## 2. API Endpoints

新增 router:

- `backend/app/api/routes/approval.py`

已挂载到:

- `backend/app/main.py`

Endpoints:

```text
POST /approval/request
GET  /approval/{id}
POST /approval/{id}/approve
POST /approval/{id}/reject
GET  /approval/list
```

API 输入规则：

- 调用方不能提交 `requester_id`、`reviewer_id`、`status`。
- `requester_id` 从当前认证用户派生。
- `reviewer_id` 只在人工 approve/reject 时由服务层写入。
- 调用方不能通过 context facts 覆盖 `requester_role` / `actor_role`。

## 3. Permission Boundary Model

实现位置:

- `backend/app/services/approval_service.py`

C12D actor boundary:

| C12D role | 权限 |
| --- | --- |
| `owner` | full access: request/read/list/approve/reject/auto_approve |
| `admin` | read/list/approve/reject |
| `user` | request only |
| `system` | auto_approve only |

Role mapping:

- `owner` -> `owner`
- `admin` / `super_admin` / `module_admin` -> `admin`
- `system` / `bot_agent` -> `system`
- others -> `user`

`system` actor 只能持久化最终状态为 `auto_approved` 的请求；如果 C12B/C12C 结果不是
`auto_approved`，服务层拒绝保存。

## 4. System Integration Flow

Request flow:

```text
POST /approval/request
  -> authenticate user
  -> normalize C12D actor role
  -> enforce request / auto_approve boundary
  -> build C12A ApprovalRequest
  -> C12C ApprovalWorkflowEngine.create_workflow()
  -> C12B ApprovalRuleEngine.evaluate()
  -> persist ApprovalRequestRecord
  -> persist ApprovalWorkflowRecord
  -> persist ApprovalDecisionRecord for C12B decision
```

Manual approve/reject flow:

```text
POST /approval/{id}/approve or /reject
  -> authenticate user
  -> normalize C12D actor role
  -> enforce owner/admin approve/reject boundary
  -> load ApprovalWorkflow from persistence
  -> ApprovalWorkflowEngine.load_workflow()
  -> ApprovalWorkflowEngine.apply_decision()
  -> persist updated ApprovalRequestRecord
  -> persist updated ApprovalWorkflowRecord
  -> persist manual ApprovalDecisionRecord
```

Read/list flow:

```text
GET /approval/{id} or /approval/list
  -> authenticate user
  -> owner/admin read/list boundary
  -> load persisted request/workflow/decisions
  -> return C12 schema payload plus C12D safety boundary
```

## 5. Safety Constraints

C12D guarantees:

- no execution
- no C09 provider call
- no C10 sandbox call
- no external provider call
- no action dispatch
- no queue / worker / webhook / callback
- no permission bypass

Approval status is persistence/audit state only. `approved` or `auto_approved` does not trigger
runtime execution and does not unlock C09/C10 execution in this stage.

## 6. C12E Readiness

可以进入 C12E。

C12E 的合理范围可以是：

- frontend approval console
- audit/operation-log integration
- C09 blocked approval state lookup integration
- approval expiry / revocation policy

C12E 仍必须单独授权；C12D 不授权 runtime execution、sandbox execution、production gateway
exposure 或外部 provider 接入。
