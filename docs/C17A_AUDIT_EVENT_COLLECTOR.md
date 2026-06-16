# C17A Audit Event Collector

## 1. Event Schema Definition

Canonical schema: `backend/app/schemas/event_collector.py::AuditEvent`.

```json
{
  "event_id": "uuid",
  "timestamp": "ISO8601",
  "event_type": "string",
  "module": "C13 | C14 | C15 | C16 | Pxx | system",
  "action": "string",
  "context_id": "string",
  "user_id": "string | null",
  "product_key": "string | null",
  "workflow_id": "string | null",
  "source": "frontend | backend | n8n | ai | system",
  "status": "success | failed | pending",
  "latency_ms": 0,
  "payload": {},
  "metadata": {}
}
```

Implementation rules:

- `event_id` is generated with UUID.
- `timestamp` is UTC ISO8601.
- `context_id` is inherited from `X-Request-ID`, `X-Trace-ID`, webhook payload context, or generated per request.
- `payload` and `metadata` are sanitized before entering the buffer or structured logger.
- The collector is append-only and does not write a new database table in C17A.

## 2. Event Capture Middleware

Middleware: `backend/app/middleware/event_collector.py::capture_audit_events`.

Captured events:

- `api.request.received`: before route execution.
- `api.response.completed`: after response or exception.

Behavior:

- Sets `request.state.context_id`.
- Sets response headers `X-Request-ID` and `X-Trace-ID`.
- Preserves downstream `context_id` changes from webhook/callback payloads.
- Emits asynchronously through `backend/app/services/event_collector.py::EventEmitter`.
- Stores recent events in an in-memory buffer and writes structured JSON to logger `barong.audit_events`.

## 3. Hook Injection Map

| Layer | Hook point | Event types | Code |
| --- | --- | --- | --- |
| API | request before/after | `api.request.received`, `api.response.completed` | `middleware/event_collector.py` |
| Auth | login/logout/session validation | `auth.login`, `auth.logout`, `auth.session.validate` | `services/auth_service.py`, `api/deps.py` |
| RBAC | dependency checks and internal checks | `rbac.check`, `rbac.permission_check`, `rbac.internal_check` | `api/deps.py` |
| Control-plane | boundary entry/exit | `control_plane.entry`, `control_plane.exit` | `main.py` |
| Webhook gateway | C15B ingress/egress | `webhook.gateway.ingress`, `webhook.gateway.egress` | `api/routes/webhook_gateway.py` |
| n8n trigger | C15C standardized request | `n8n.workflow.trigger` | `services/execution_payload_standardization.py` |
| n8n execution | C15D context bind/callback | `workflow.execution.start`, `workflow.execution.status`, `workflow.execution.end` | `services/callback_handler.py` |
| n8n test bridge | mock trigger/start/end | `n8n.workflow.trigger`, `workflow.execution.start`, `n8n.workflow.dispatch`, `workflow.execution.end` | `services/n8n_test_service.py` |
| Failure handling | C15H failure/retry/timeout/replay | `workflow.failure`, `workflow.retry`, `workflow.timeout` | `services/failure_handling.py` |
| AI prompt layer | C14X-E prompt input/output | `ai.llm.request`, `ai.llm.response` | `services/execution_prompt_generator.py` |
| AI clients | DeepSeek/GPT/4sapi client wrappers | `ai.llm.request`, `ai.llm.response` | `services/event_collector.py::record_llm_request/response` |
| File metadata | artifact registry read/write | `file.read`, `file.write` | `repositories/artifacts.py` |
| FileBrowser | future read/write/delete adapter | `file.read`, `file.write`, `file.delete` | `services/event_collector.py::record_filebrowser_operation` |
| MinIO | future upload/download adapter | `file.upload`, `file.download` | `services/event_collector.py::record_minio_operation` |
| Product knowledge | memory/context packet read/write | `product_knowledge.read`, `product_knowledge.write` | `repositories/memory.py` |
| Category tree | module registry/manifests | `category_tree.read`, `category_tree.update` | `repositories/registry.py`, `services/module_registry.py` |
| Logs | operation log read/write | `log.read`, `log.write` | `repositories/operation_logs.py` |

## 4. Context ID Propagation Design

Propagation path:

`frontend -> backend middleware -> auth/RBAC -> control-plane -> C15 gateway -> n8n/callback -> AI/storage`

Rules:

- Every HTTP request receives a `context_id`.
- Incoming `X-Request-ID` wins, then `X-Trace-ID`, then generated UUID.
- `get_audit_context()` reuses `request.state.context_id`; existing operation log `request_id` now aligns with C17A context.
- Webhook and callback payloads override `request.state.context_id` with their signed `context_id`.
- C15 payloads and C15H failure requests use the request payload `context_id` directly.
- AI prompt and future LLM hooks accept explicit `context_id`; otherwise they inherit the active context.
- Storage hooks inherit the active context and can be passed explicit object/file context by adapters.

## 5. Event Flow Diagram

Text flow:

```text
frontend request
  -> FastAPI event middleware creates or inherits context_id
  -> auth/session/RBAC/control-plane hooks emit security events
  -> control-plane/webhook/C15 services inherit or override context_id
  -> n8n trigger/start/callback/failure hooks emit execution events
  -> AI prompt/LLM hooks emit request/response events
  -> artifact/product knowledge/category/log hooks emit system storage events
  -> EventEmitter appends to memory buffer
  -> background emitter writes structured JSON to barong.audit_events logger
```

## 6. Integration Points List

- `emit_event(...)`: generic collector entry.
- `record_workflow_event(...)`: n8n/workflow execution events.
- `record_llm_request(...)` and `record_llm_response(...)`: before/after LLM client calls.
- `record_file_operation(...)`: generic storage event.
- `record_filebrowser_operation(...)`: FileBrowser adapter hook.
- `record_minio_operation(...)`: MinIO adapter hook.
- `record_product_knowledge_event(...)`: product knowledge memory hook.
- `get_event_buffer_snapshot()`: in-memory event buffer inspection for tests and future C17B/C17C readers.
- `get_event_emitter_stats()`: queue/buffer health stats.

## 7. Boundaries

C17A does not change C13/C14/C15 business behavior, does not add a database table, does not modify UI, does not change permissions, and does not connect external FileBrowser, MinIO, n8n, DeepSeek, GPT, or 4sapi services. It only records standardized events at existing behavior boundaries.

