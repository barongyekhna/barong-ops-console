# C17B Structured Log Schema

## 1. LogEntry Schema Definition

Canonical schema: `backend/app/schemas/structured_logs.py::LogEntry`.

```json
{
  "log_id": "uuid",
  "event_id": "string",
  "timestamp": "ISO8601",
  "context_id": "string",
  "module": "C13 | C14 | C15 | C16 | C17 | system",
  "event_type": "string",
  "action": "string",
  "source": "api | n8n | ai | webhook | system | frontend | backend",
  "entity": {
    "user_id": "string | null",
    "product_key": "string | null",
    "workflow_id": "string | null",
    "request_id": "string | null"
  },
  "status": "success | failed | pending",
  "latency_ms": 0,
  "request": {},
  "response": {},
  "metadata": {
    "ip": "string | null",
    "user_agent": "string | null",
    "trace_depth": 0,
    "retry_count": 0
  },
  "tags": ["string"]
}
```

Schema rules:

- Every C17A event must be normalized into `LogEntry` before C17B storage.
- Raw C17A event storage is not allowed in C17B storage helpers.
- `context_id` is always present and represents the request root trace id.
- `module` remains the indexable module code.
- `tags` must include the standardized module tag.
- `status` is normalized to `success`, `failed`, or `pending`.

## 2. LogNormalizer Implementation Plan

Implementation: `backend/app/services/structured_logs.py::LogNormalizer`.

Input:

- `C17A AuditEvent`
- mapping compatible with a C17A raw event stream

Output:

- `LogEntry`

Responsibilities:

- Schema enforcement through the `LogEntry` Pydantic model.
- Missing field filling for `log_id`, `event_id`, `timestamp`, `context_id`, entity fields, metadata fields, request, response, and tags.
- Tag generation for context, module code, semantic module tag, source, status, event type, and available entity ids.
- Module inference when raw module is missing or not part of the C17B module enum.
- Status normalization from common aliases into `success`, `failed`, or `pending`.

Storage helpers:

- `log_entry_to_jsonl(entry)` accepts only `LogEntry`.
- `log_entry_to_db_record(entry)` accepts only `LogEntry`.
- Passing a raw C17A event directly to C17B storage helpers raises `TypeError`.

## 3. Context ID Propagation Mapping

Rule:

```text
context_id = request root trace id
```

Propagation path:

```text
frontend_request
  -> backend
  -> control-plane
  -> n8n
  -> AI
  -> storage
```

Requirements:

- All `LogEntry` records inherit one `context_id`.
- AI, n8n, and webhook records must preserve the same `context_id`.
- If a raw event lacks `context_id`, the normalizer fills it with the same safe normalization rule used by C17A.
- `entity.request_id` defaults to `context_id` when no separate request id exists.

## 4. Module Tagging Table

The `module` field is the indexable code. The semantic tag is generated into
`LogEntry.tags`.

| Module | Standard tag |
| --- | --- |
| C13 | `module:control` |
| C14 | `module:capability` |
| C15 | `module:execution` |
| C16 | `module:security` |
| C17 | `module:observability` |
| system | `module:infra` |

## 5. Storage Format

Default format: JSONL.

Each line is one `LogEntry` JSON object:

```json
{"context_id":"ctx-root","event_id":"evt-1","module":"C15","event_type":"workflow.execution.end"}
```

Future DB ingestion:

- `log_entry_to_db_record(entry)` returns the full `LogEntry` plus flattened index fields.
- No DB migration is executed in C17B.
- No table creation is required for this stage.

Indexable fields:

- `context_id`
- `timestamp`
- `module`
- `event_type`
- `product_key`
- `user_id`

## 6. Query Model Design

Canonical model: `backend/app/schemas/structured_logs.py::LogQueryModel`.

Supported query selectors:

- `by_context_id`
- `by_module`
- `by_product_key`
- `by_event_type`
- `by_time_range`
- `by_status`

`by_time_range` uses `LogTimeRange`:

```json
{
  "start_at": "ISO8601 | null",
  "end_at": "ISO8601 | null"
}
```

The query model is storage-neutral and can target JSONL scans now or DB indexes
later.

## 7. Migration Plan: C17A Raw Events to Structured Logs

Plan:

1. Read C17A `AuditEvent` records from the existing in-memory buffer or structured logger stream.
2. Pass every raw event through `LogNormalizer`.
3. Persist only `LogEntry` records in JSONL by default.
4. For future DB ingestion, call `log_entry_to_db_record(entry)` and index the flattened fields.
5. Backfill historical C17A JSON logs by streaming line by line through `LogNormalizer`.
6. Reject direct raw event storage in C17B storage helpers.

Explicit non-goals:

- Do not modify C17A collector logic.
- Do not change the hook system.
- Do not change API behavior.
- Do not execute a database migration.
- Do not introduce new business logic.

## 8. Completion Status

Completion model: `backend/app/schemas/structured_logs.py::StructuredLogCompletionStatus`.

C17B is complete when:

- `LogEntry` schema is defined.
- `LogNormalizer` is defined.
- Context propagation mapping is defined.
- Module tagging table is defined.
- JSONL storage format is defined.
- Query model is defined.
- Migration plan is defined.
- Raw event storage remains disallowed.
