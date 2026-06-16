# C17E Audit Query Engine

C17E defines the audit query engine for barong-ops-console observability data.
It reads C17D storage records and returns normalized C17A/C17B/C17C objects for
search, filtering, and execution-chain drill-down.

C17E does not modify C17A, C17B, C17C, or C17D. It does not execute a database
migration, change business logic, connect a UI, or create frontend
visualizations.

## 1. AuditQueryEngine Design

Canonical service: `backend/app/services/audit_query_engine.py::AuditQueryEngine`.

Supported query objects:

- C17B `LogEntry`
- C17C `ExecutionTrace`
- C17D `EventRaw`
- C17D `StorageRecordEnvelope` as the internal indexed read model

Responsibilities:

- Search structured logs by user, module, context, and event type.
- Filter storage records by time, status, latency, and action.
- Evaluate AND / OR / NOT boolean expressions.
- Drill down full execution traces by `context_id` or `trace_id`.
- Normalize every response into `QueryResult`.

## 2. search_logs API

Canonical method:

```python
AuditQueryEngine.search_logs(
    user_id=None,
    module=None,
    context_id=None,
    event_type=None,
    product_key=None,
    trace_id=None,
    time_range=None,
    limit=None,
)
```

Required filters:

- `user_id`
- `module`
- `context_id`
- `event_type`

The filters are combined with AND semantics. The return data is always decoded
to C17B `LogEntry` objects.

## 3. filter_system Logic

Canonical method:

```python
AuditQueryEngine.filter_system(
    time_range=None,
    status=None,
    min_latency_ms=None,
    max_latency_ms=None,
    action=None,
    module=None,
    context_id=None,
    trace_id=None,
    product_key=None,
    user_id=None,
    event_type=None,
    operator="AND",
    expression=None,
    entity_types=("LogEntry", "ExecutionTrace", "EventRaw"),
    limit=None,
)
```

Required filter capabilities:

- Time range: C17D `StorageTimeRange`
- Status: lifecycle status from C17D envelope
- Latency: C17B `latency_ms`, C17C `total_latency_ms`, or raw payload latency
- Action: C17B/EventRaw action or C17C step actions

Boolean logic:

- `AND`: all predicates must match.
- `OR`: any predicate or child expression may match.
- `NOT`: negates the grouped predicate result.

Direct filter arguments can be combined with a nested `FilterExpression`.

## 4. drill_down Execution Model

Canonical method:

```python
AuditQueryEngine.drill_down(context_id=None, trace_id=None, limit=None)
```

Input:

- `trace_id`, preferred for exact trace lookup
- `context_id`, for context-level trace discovery

Output:

- Complete C17C `ExecutionTrace`
- Step-by-step breakdown with step id, module, action, status, latency, timestamp,
  input keys, output keys, dependency reference, and error presence
- Text expansion:

```text
context_id -> root_event:event_id
chain expansion:
C14 capability
  v
C15 workflow
  v
n8n nodes
  v
AI calls
  v
DB writes
```

C17E performs inspection only. It does not execute replay.

## 5. Index Usage Strategy

C17E is based on C17D storage indexes:

- `idx_c17d_context_id`: context lookup across logs, traces, and raw events
- `idx_c17d_trace_id`: trace lookup and drill-down
- `idx_c17d_module_event_type`: module and event-type search
- `idx_c17d_timestamp`: time-series filtering
- `idx_c17d_product_user_status`: product, user, and status filtering

The current in-memory C17D adapter exposes direct methods for `context_id`,
`trace_id`, and `timestamp`. C17E builds a non-mutating local index view over
C17D `StorageRecordEnvelope` records to exercise the declared module,
event-type, product, user, status, and action lookup paths in tests. Future
physical adapters can replace that view with database-backed index methods.

## 6. QueryOptimizer Design

Canonical optimizer: `backend/app/services/audit_query_engine.py::QueryOptimizer`.

Selection rules:

1. Drill-down uses `trace_id` first, then `context_id`.
2. Broad filter queries with a time range use `idx_c17d_timestamp` first.
3. Exact trace and context searches use their dedicated indexes.
4. Module and event searches use `idx_c17d_module_event_type`.
5. Product, user, and status filters use `idx_c17d_product_user_status`.
6. Action-only filtering uses a C17E local shadow index because C17D does not
   define a physical action index.

The optimization plan records:

- selected index
- post-filter fields
- full-scan avoidance flag
- time-first filtering flag
- module partition-pruning flag
- cache key

## 7. QueryResult Schema

Every public method returns:

```python
QueryResult = {
    "query_id": "string",
    "result_count": 0,
    "execution_time_ms": 0.0,
    "data": [LogEntry | ExecutionTrace | EventRaw],
    "metadata": {
        "query_type": "search | filter | drill_down",
        "index_used": ["string"],
        "cache_hit": False,
    },
}
```

Metadata also carries optimizer details, searched storage tiers, candidate
count, post-filter fields, and drill-down expansion when applicable.

## 8. Integration With C17D Storage Layer

C17E consumes only the C17D `StorageAdapter` read surface:

- `query_by_context_id(context_id)`
- `query_by_trace_id(trace_id)`
- `query_by_time_range(time_range)`
- `records` from the side-effect-free in-memory adapter for local index tests

Hot/warm/cold integration:

- Hot records are read through context and trace indexes for live debugging.
- Warm records are filtered by timestamp, module, event type, product, user, and
  status.
- Cold records are reached through C17D metadata and archive pointers; C17E does
  not scan object storage directly.

Completion boundary:

- C17A/B/C/D modified: no
- Database migration executed: no
- Business logic changed: no
- UI integrated: no
