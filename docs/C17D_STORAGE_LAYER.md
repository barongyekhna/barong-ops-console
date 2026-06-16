# C17D Storage Layer

C17D defines the storage layer for barong-ops-console observability data. It is
responsible for long-term, safe, and efficient storage/query of C17A event logs,
C17B structured logs, and C17C execution traces.

C17D does not modify C17A, C17B, or C17C. It does not execute replay, run a
database migration, change API behavior, or connect runtime storage backends.

## 1. Storage Architecture Design

The storage architecture has three mandatory layers:

| Layer | Age | Purpose | Contents | Backend design |
| --- | --- | --- | --- | --- |
| L1 Hot Storage | 0-7 days | Real-time query and fast trace debugging | execution traces, recent logs, active context_id | PostgreSQL primary, Redis hot cache |
| L2 Warm Storage | 7-90 days | Analysis, retrospective debugging, statistics | structured logs, aggregated traces, module-level analytics | PostgreSQL indexed partitions |
| L3 Cold Storage | 90+ days | Compressed archive and audit history | raw logs archive, compressed execution traces, audit history | S3-compatible object storage plus PostgreSQL archive metadata |

Future physical tables should keep PostgreSQL as the query control plane, Redis
as an L1 accelerator, and object storage as the compressed L3 payload archive.

## 2. Data Model

C17D supports three core entities:

### LogEntry

Source: C17B `LogEntry`.

Storage projection:

- `context_id`: primary correlation id.
- `trace_id`: copied from payload/response when present, otherwise falls back to
  `entity.request_id` or `context_id`.
- `event_id`, `product_key`, `user_id`, `module`, `event_type`, `timestamp`,
  `status`: flattened index fields.
- `payload`: full C17B DB-ready record.

### ExecutionTrace

Source: C17C `ExecutionTrace`.

Storage projection:

- `context_id`, `trace_id`, `root_event_id`.
- `module`: first module in the trace chain, with full module list retained in
  payload.
- `event_type`: `execution.trace`.
- `timestamp`: first step timestamp.
- `status`: C17C final status.
- `payload`: full C17C DB-ready record with step count and module list.

### EventRaw

Source: C17A raw audit event stream.

Storage projection:

- `event_id`, `timestamp`, `context_id`, `trace_id`, `product_key`, `user_id`,
  `workflow_id`, `module`, `event_type`, `action`, `source`, `status`.
- `payload` and `metadata` are sanitized through the existing C17A helper.
- Intended as debugging fallback and cold archive input, not as C17B storage.

## 3. StorageAdapter Interface

Canonical interface:

```python
write_log(log)
write_trace(trace)
write_event_raw(raw_event)
query_by_context_id(context_id)
query_by_trace_id(trace_id)
query_by_time_range(time_range)
archive_to_cold_storage()
```

Backend targets:

- PostgreSQL: main durable store for L1/L2 records and cold archive metadata.
- Redis: L1 hot cache for active `context_id` and trace debug lookups.
- S3 / Object Storage: compressed L3 archive objects.

The repository includes only a side-effect-free in-memory adapter for C17D
validation. Runtime backend connections are intentionally not enabled here.

## 4. Indexing Strategy

Required index fields:

- `context_id`
- `trace_id`
- `event_id`
- `product_key`
- `user_id`
- `module`
- `timestamp`
- `status`

Index classes:

- Primary index: `context_id`
- Secondary index: `trace_id`
- Point lookup index: `event_id`
- Operational filter index: `product_key + user_id + status`
- Search index: `module + event_type`
- Time-series index: `timestamp`

PostgreSQL should use composite and time-partitioned indexes when the future
database migration is approved. Redis keys should mirror the hot `context_id`
and `trace_id` lookup paths. Cold object storage should not be scanned directly;
PostgreSQL archive metadata should point to object keys.

## 5. Retention Policy Design

Retention windows:

- Hot: 7 days
- Warm: 90 days
- Cold: 1-3 years, compressed

Automatic migration rules:

- TTL migration job scans timestamp indexes for records older than 7 days.
- Hot Redis keys expire when data leaves L1.
- Batch archiving selects records older than 90 days.
- Compression step writes JSONL batches as `.jsonl.gz` or equivalent compressed
  objects.
- PostgreSQL keeps archive object metadata for later lookup.

## 6. Hot / Warm / Cold Data Flow

Write path:

```text
C17A Event
  -> C17B LogEntry
  -> C17C ExecutionTrace
  -> C17D Storage Layer
```

L1 flow:

- Write recent LogEntry and ExecutionTrace records to PostgreSQL.
- Mirror active context and trace indexes into Redis.
- Serve live debug queries by `context_id` and `trace_id`.

L2 flow:

- TTL job removes records older than 7 days from Redis.
- PostgreSQL keeps indexed structured logs and aggregated traces.
- Analytics query by timestamp, module, event type, product, user, and status.

L3 flow:

- Batch archiver reads records older than 90 days by timestamp index.
- Records are serialized to JSONL batches, compressed, and stored in object
  storage.
- PostgreSQL keeps archive metadata and index pointers.

## 7. Migration Strategy: C17C to C17D

1. Read C17C `ExecutionTrace` objects or JSONL records without changing C17C.
2. Project `trace_id`, `context_id`, `root_event_id`, modules, timestamp, and
   status.
3. Write projected records through `StorageAdapter.write_trace()`.
4. Keep C17B `LogEntry` writes on `StorageAdapter.write_log()`.
5. Store C17A `EventRaw` only as debugging fallback and cold archive input.
6. Run any historical backfill offline after an explicit DB migration is
   approved later.

This migration strategy does not modify C17A/B/C and does not execute a
database migration in C17D.

## 8. Query Performance Strategy

- Prefer `context_id` for cross-entity correlation queries.
- Use `trace_id` for trace drill-down.
- Require time bounds for broad operational queries.
- Use `module + event_type` for search-style filters.
- Keep `timestamp` indexed for retention scans and range queries.
- Keep hot Redis TTLs aligned with L1 retention.
- Use PostgreSQL partitioning by timestamp in the future physical schema.
- Keep cold archive object keys in PostgreSQL metadata to avoid object-store
  scans.

## 9. Completion Boundary

C17D is complete when:

- Storage architecture is defined.
- LogEntry, ExecutionTrace, and EventRaw storage models are defined.
- StorageAdapter interface is defined.
- Indexing strategy is defined.
- Retention policy is defined.
- Hot/warm/cold data flow is defined.
- C17C-to-C17D migration strategy is defined.
- Query performance strategy is defined.

C17D does not implement execution replay. Replay belongs to C17F.
