# C17C Execution Trace System

## Scope

C17C defines the replay-ready execution trace layer for barong-ops-console. It
turns step events from C14, C15, n8n, AI, and storage boundaries into a single
ordered `ExecutionTrace`.

C17C does not modify C17A or C17B, does not change business logic, does not
change API contracts, does not execute a database migration, and does not alter
n8n runtime behavior.

## 1. ExecutionTrace Schema

Canonical schema: `backend/app/schemas/execution_trace.py::ExecutionTrace`.

```json
{
  "trace_id": "string",
  "context_id": "string",
  "root_event_id": "string",
  "chain": [
    {
      "step_id": "string",
      "step_index": 0,
      "module": "C14 | C15 | n8n | AI | DB | system",
      "action": "string",
      "input": {},
      "output": {},
      "status": "success | failed | pending",
      "latency_ms": 0,
      "timestamp": "ISO8601",
      "error": null,
      "retry_count": 0,
      "dependency_step_id": "string | null"
    }
  ],
  "final_status": "success | failed | partial",
  "total_latency_ms": 0
}
```

Rules:

- `trace_id` and `context_id` are propagated across the whole request.
- `root_event_id` points to the first event that opened the trace.
- `chain` is ordered by contiguous `step_index` values.
- Each step captures input snapshot, output snapshot, latency, error,
  retry count, and dependency step reference.
- `final_status` is `failed` when any step failed, `partial` when a step is
  pending or a required/dependency step is missing, and `success` otherwise.

## 2. Trace Hook Injection Points

Model: `TraceHookInjectionCatalog`.

| Layer | Hook action | Lifecycle | Captures |
| --- | --- | --- | --- |
| C14 | `capability_selection_start` | start | input, latency, retry, dependency |
| C14 | `capability_selection_result` | complete | output, latency, error, retry, dependency |
| C15 | `workflow_trigger` | start | input, latency, retry, dependency |
| C15 | `workflow_step_start` | start | input, latency, retry, dependency |
| C15 | `workflow_step_complete` | complete | output, latency, error, retry, dependency |
| n8n | `node_execution_start` | start | input, latency, retry, dependency |
| n8n | `node_execution_end` | complete | output, latency, error, retry, dependency |
| n8n | `workflow_completion` | complete | output, latency, error, retry, dependency |
| AI Layer | `prompt_send` | start | prompt input, latency, retry, dependency |
| AI Layer | `response_receive` | complete | response output, latency, error, retry, dependency |
| DB / Storage | `write_start` | start | input, latency, retry, dependency |
| DB / Storage | `write_success_failure` | complete | output, latency, error, retry, dependency |

Every hook must carry:

```text
trace_id + context_id + root_event_id + step_id
```

## 3. Cross-System Trace Mapping

Model: `CrossSystemTraceMapping`.

```text
frontend_request
  -> backend API (C13/C14/C16)
  -> execution engine (C15)
  -> n8n workflow
  -> AI call (GPT / DeepSeek / 4sapi)
  -> DB / FileStorage
```

Mapping rules:

- Frontend/backend and C13/C16 control/security boundaries map to C17C module
  `system` unless the event is specifically a C14 or C15 step.
- C14 capability selection maps to module `C14`.
- C15 workflow execution maps to module `C15`.
- n8n node/workflow events map to module `n8n`.
- GPT, DeepSeek, and 4sapi prompt/response events map to module `AI`.
- DB and file/object storage writes map to module `DB`.

## 4. Step Lifecycle Definition

Model: `TraceStepLifecycleDefinition`.

Lifecycle states:

```text
start    -> captures input, marks the step pending
complete -> captures output, final status, latency, and error
record   -> captures an atomic one-shot step
```

Step contract:

- `input`: request or prompt snapshot before the operation.
- `output`: response, workflow result, AI response, or storage result snapshot.
- `latency_ms`: reported latency, or derived from paired start/complete
  timestamps.
- `error`: sanitized error object when the step failed.
- `retry_count`: max retry/attempt value observed for the step.
- `dependency_step_id`: previous `step_id` that this step depends on.

Replay rule:

```text
sort by step_index -> replay input/output snapshots -> preserve dependency order
```

## 5. TraceAggregator Design

Implementation: `backend/app/services/execution_trace.py::TraceAggregator`.

Responsibilities:

- Collect step events.
- Merge start/complete records into one `ExecutionTraceStep`.
- Maintain ordering by explicit `step_index`, then timestamp, then arrival order.
- Compute per-step and total latency.
- Detect missing terminal steps, missing dependency references, and required
  actions absent from the trace.

Public helpers:

- `aggregate_execution_trace(events)`
- `detect_missing_trace_steps(trace)`
- `trace_step_event_from_log_entry(log_entry)`
- `execution_trace_to_json(trace)`
- `execution_trace_to_jsonl(trace)`
- `execution_trace_to_db_record(trace)`

## 6. Storage Format

Model: `TraceStorageFormatDesign`.

Supported formats:

- JSON debug: full pretty `ExecutionTrace` for local inspection.
- JSONL stream: one `TraceStepEvent` or `ExecutionTrace` per line.
- Future DB table ready: flattened index fields, no migration executed.

Indexable fields:

```text
trace_id
context_id
root_event_id
module
final_status
```

DB-ready record shape:

```json
{
  "trace_id": "trace-root",
  "context_id": "ctx-root",
  "root_event_id": "evt-root",
  "final_status": "success",
  "total_latency_ms": 80,
  "chain": [],
  "modules": ["C14", "C15", "n8n", "AI", "DB"],
  "step_count": 5,
  "indexable_fields": [
    "trace_id",
    "context_id",
    "root_event_id",
    "module",
    "final_status"
  ]
}
```

## 7. Execution Flow Diagram

```text
frontend_request [trace_id, context_id]
  -> backend API (C13/C14/C16) [trace_id, context_id]
  -> C14 capability selection [trace_id, context_id]
  -> C15 workflow execution [trace_id, context_id]
  -> n8n workflow/node execution [trace_id, context_id]
  -> AI call: GPT / DeepSeek / 4sapi [trace_id, context_id]
  -> DB / FileStorage write [trace_id, context_id]
  -> ExecutionTrace JSON/JSONL [replay-ready]
```

## 8. Migration Plan: C17B Logs to C17C Traces

Model: `C17BToC17CMigrationPlan`.

Plan:

1. Read C17B `LogEntry` JSONL or normalized `LogEntry` objects without changing
   C17B.
2. Group entries by `trace_id` when present, otherwise by `context_id`.
3. Map the first grouped `LogEntry.event_id` to `root_event_id`.
4. Map `LogEntry.request` to `TraceStepEvent.input`.
5. Map `LogEntry.response` to `TraceStepEvent.output`.
6. Map `LogEntry.latency_ms` and `metadata.retry_count` to step lifecycle
   fields.
7. Infer C17C module values as `C14`, `C15`, `n8n`, `AI`, `DB`, or `system`.
8. Aggregate step events into ordered `ExecutionTrace` records.
9. Write C17C JSON debug or JSONL stream output. Future DB output stays
   table-ready only.

Explicit constraints:

- C17A modified: no.
- C17B modified: no.
- Business logic changed: no.
- API contract changed: no.
- Database migration executed: no.
- n8n runtime changed: no.

## Completion Status

C17C is complete when:

- `ExecutionTrace` schema is defined.
- Trace hook injection points are defined.
- Cross-system mapping is defined.
- Step lifecycle is defined.
- `TraceAggregator` is implemented.
- JSON/JSONL/DB-ready storage helpers are implemented.
- C17B-to-C17C migration plan is defined.
- Any request can be reconstructed from ordered step input/output snapshots.
