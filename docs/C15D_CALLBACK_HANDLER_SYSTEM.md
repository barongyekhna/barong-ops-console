# C15D Callback Handler System

## Scope

C15D implements the n8n callback handling boundary for
barong-ops-console. It receives signed callbacks, binds them to the original
C15C execution request by `context_id`, updates local execution status, stores
workflow output and metadata, and prepares standardized module notification
results.

C15D does not trigger n8n execution, does not call external APIs, does not
invoke AI models, does not change staging or production, does not run
Docker/pytest, and does not commit git changes.

## 1. Callback Handler Design

Callback entrypoint:

```text
POST /callback-handler/receiver
```

Accepted callback payload:

```json
{
  "module": "string",
  "workflow_id": "string",
  "context_id": "ctx.c15c.<16 hex chars>",
  "status": "pending | running | success | failed",
  "output": {},
  "execution_metadata": {},
  "timestamp": "ISO-8601 string"
}
```

Receiver flow:

```text
n8n webhook callback
-> C15D Callback Receiver
-> C15B HMAC-SHA256 signature verification
-> C15D Context Binding System
-> C15D Execution Status Manager
-> C15D Result Storage
-> C15D Module Notification System
```

The receiver uses the C15B signing secret and `X-Barong-Gateway-Signature`
header. The callback payload is canonicalized as sorted JSON and signed with
HMAC-SHA256. Missing, invalid, or stale signatures are rejected before context
binding.

Inspection API:

```text
GET /callback-handler/design
```

## 2. Context Binding Logic

C15D binds only C15C `ExecutionPayloadStandardRequest` records:

```text
context_id -> C15C ExecutionPayloadStandardRequest
```

Binding API:

```text
POST /callback-handler/context-bindings
```

Rules:

- `context_id` is the lookup key.
- `context_id` must match `^ctx\.c15c\.[0-9a-f]{16}$`.
- The context must already be bound before a callback can be accepted.
- The callback `module` must match the bound C15C request.
- The callback `workflow_id` must match the bound C15C request.
- Rebinding the same `context_id` to a different request is rejected.
- Unknown context callbacks are rejected.

Inspection API:

```text
GET /callback-handler/context-binding
```

## 3. Status Management System

Allowed statuses:

```text
pending
running
success
failed
```

Allowed transitions:

```text
pending -> pending | running | success | failed
running -> running | success | failed
success -> success
failed  -> failed
```

`success` and `failed` are terminal. Repeated terminal callbacks with the same
status are treated as idempotent returns. Terminal status changes such as
`success -> failed` are rejected.

Inspection API:

```text
GET /callback-handler/status-management
```

## 4. Result Storage Model

C15D stores callback results in the local in-memory contract store keyed by
`context_id`. This keeps C15D within the no-migration/no-environment-change
boundary while defining the storage contract for a later persistence step.

Stored fields:

```text
workflow_output
execution_metadata
created_at
updated_at
started_at
completed_at
callbacks_received
```

Result lookup API:

```text
GET /callback-handler/results/{context_id}
```

Stored output and metadata reject credentials, direct webhook references, URLs,
authorization values, tokens, secrets, and runtime access markers.

Inspection API:

```text
GET /callback-handler/result-storage
```

## 5. Module Notification System

C15D prepares an in-process module notification contract and returns the
standardized result in the callback response. It does not call module HTTP APIs
or trigger follow-up execution.

Supported notification families:

```text
K
P
SEO
```

Current family mapping:

- `business.products` and product/P-prefixed modules map to `P`.
- `seo.*` and `business.seo.*` modules map to `SEO`.
- `k.*` and `business.k.*` modules map to `K`.
- Other modules return `generic` while preserving the same standardized result
  shape.

Inspection API:

```text
GET /callback-handler/module-notifications
```

## 6. Completion Status

C15D is complete:

- Callback receiver: implemented.
- Payload validation: implemented.
- C15B signature verification reuse: implemented.
- Context binding by `context_id`: implemented.
- C15C execution request binding: implemented.
- Execution status manager: implemented.
- Result storage model: implemented.
- Module notification contract: implemented.
- Runtime execution trigger: not performed.
- n8n dispatch: not performed.
- External API call: not performed.
- Production/staging change: not performed.
- Docker/pytest/git commit: not performed.

Completion API:

```text
GET /callback-handler/completion-status
```

Can proceed to C15E: yes.
