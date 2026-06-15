# C15C Execution Payload Standardization

## Scope

C15C defines the Execution Payload Standardization Layer for module workflow
requests. It converts module-specific request shapes into one standard payload
contract, attaches workflow metadata from C15A, attaches execution metadata from
C14X, standardizes context identifiers, and stops before any runtime execution
boundary.

C15C does not call n8n, does not call C15B ingress, does not invoke AI models,
does not call external APIs, does not change staging or production, does not run
Docker/pytest, and does not commit git changes.

## 1. Payload Standardization Model

The standard request schema is:

```json
{
  "module": "string",
  "task": "string",
  "context_id": "ctx.c15c.<16 hex chars>",
  "workflow_id": "string",
  "execution": {
    "capability": "serp | reasoning | writing | embedding",
    "model": "string",
    "key_id": "string"
  },
  "payload": {},
  "timestamp": "ISO-8601 string"
}
```

Implementation:

- `backend/app/schemas/execution_payload_standardization.py`
- `ExecutionPayloadStandardRequest`
- `ExecutionPayloadMetadata`

Rules:

- Top-level extra fields are forbidden in the standardized request.
- Caller-supplied execution metadata is rejected.
- `execution.capability`, `execution.model`, and `execution.key_id` must be
  attached from C14X.
- Payload credential fields, webhook fields, URL fields, authorization fields,
  token fields, and direct runtime references are rejected.

Inspection API:

```text
GET /payload-standardization/model
```

## 2. Normalization Engine Design

The normalization engine accepts module request aliases:

```text
module: module | module_key
task: task | action | operation
context: context_id | contextId | correlation_id | trace_id | context
payload: payload or residual module-specific fields
timestamp: supplied timestamp or generated UTC timestamp
workflow_id: optional verification hint, never a C15A bypass
```

Normalization flow:

```text
module-specific request
-> normalize module/task/payload
-> standardize context_id
-> attach workflow_id through C15A
-> attach execution metadata through C14X
-> validate standard request schema
-> return accepted/rejected normalization result
```

Implementation:

- `backend/app/services/execution_payload_standardization.py`
- `normalize_execution_payload_request`
- `standardize_context_id`

Inspection and validation API:

```text
GET  /payload-standardization/normalization-engine
POST /payload-standardization/normalize
```

`POST /payload-standardization/normalize` returns a normalization decision only.
It does not dispatch C15B, does not resolve real n8n URLs, does not invoke
models, and does not call external APIs.

## 3. Context Standard Rules

All normalized requests use:

```text
ctx.c15c.<16 lowercase hex chars>
```

Rules:

- Module-specific context formats are not preserved in the standardized request.
- Already-standard C15C context IDs are preserved.
- Legacy or module-specific context values are hashed with module, task, raw
  context, and timestamp.
- Raw context values are not returned.
- Traceability is carried by `ExecutionPayloadTraceChain`:

```text
module -> task -> context_id -> workflow_id -> capability -> model -> key_id
```

Inspection API:

```text
GET /payload-standardization/context-rules
```

## 4. Workflow Mapping Integration

C15C uses C15A as the workflow source of truth:

```text
module -> active workflow_id
```

Validation rules:

- Workflow must exist in C15A.
- Workflow must be explicitly bound to the requested module.
- Workflow status must be `active`.
- Unregistered, unbound, inactive, deprecated, and error workflows are rejected.
- If multiple active workflows exist and no safe explicit workflow hint is
  provided, C15C rejects instead of guessing.
- Hidden n8n webhook references are not exposed by C15C.

Inspection API:

```text
GET /payload-standardization/workflow-mapping
```

## 5. C14X Execution Metadata Integration

C15C attaches execution metadata from C14X capability routing:

```text
capability -> key -> model -> module
```

Output mapping:

```text
execution.capability = C14X capability
execution.model      = C14X locked model reference
execution.key_id     = C14X binding key
```

Default C14X registries are empty, so default runtime-bound normalization is
rejected with a clear missing C14X execution metadata reason. This preserves the
C14X rule that no AI model binding or runtime route exists by default.

## 6. Completion Status

C15C is complete:

- Payload standardization model: implemented.
- Normalization engine design: implemented.
- Context standard rules: implemented.
- Workflow mapping integration with C15A: implemented.
- Execution metadata integration with C14X: implemented.
- Invalid mapping rejection: implemented.
- Runtime execution: not performed.
- n8n dispatch: not performed.
- AI model invocation: not performed.
- External API call: not performed.
- Production/staging change: not performed.
- Docker/pytest/git commit: not performed.

Completion API:

```text
GET /payload-standardization/completion-status
```

Can proceed to C15D: yes.

C15D can consume the standardized request contract and trace chain, but must not
treat C15C normalization as runtime execution permission.
