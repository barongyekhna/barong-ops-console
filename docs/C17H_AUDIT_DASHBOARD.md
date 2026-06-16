# C17H Audit Dashboard

C17H defines the read-only audit visualization layer for barong-ops-console.
Its purpose is to make the C17 audit system understandable to humans by
combining structured logs, execution traces, replay results, and anomaly alerts
into one context-first dashboard.

C17H does not modify C17A, C17B, C17C, C17D, C17E, C17F, or C17G. It does not
change backend logic, API contracts, database schema, replay execution, anomaly
detection behavior, or production runtime behavior. This document is design
only and does not implement frontend code.

## 1. AuditDashboard Architecture

Canonical UI shell:

```text
AuditDashboardUI
  -> AuditDashboardQueryClient
  -> AuditQueryEngine (C17E)
  -> C17D Storage Layer
```

Responsibilities:

- Present a log explorer for C17B `LogEntry` records.
- Present execution trace drill-down for C17C `ExecutionTrace` records.
- Present existing C17F `ExecutionReplay` results as a read-only overlay.
- Present C17G `Alert` records and highlight affected log, timeline, and graph
  entities.
- Keep the primary navigation key as `context_id`; use `trace_id` for exact
  execution path highlighting.
- Preserve module tagging from C17B and C17C instead of inventing separate UI
  categories.

Top-level view model:

```text
AuditDashboardState
  selected_context_id
  selected_trace_id
  filters
  query_results
  selected_log_entry
  selected_execution_trace
  replay_overlay
  anomaly_alerts
  refresh_state
```

The dashboard never writes to C17D and never mutates replay or anomaly state.
Near real-time behavior is a read refresh only: poll the C17E query surface on a
short interval, or use an existing read stream if one is later approved. Auto
refresh should pause while a user is inspecting a fixed trace snapshot.

## 2. UI Component Breakdown

`AuditDashboardUI` is composed of the following read-only components.

| Component | Purpose | Primary data | Query path |
| --- | --- | --- | --- |
| OverviewPanel | System health, request volume, anomaly count, latency summary | C17E `QueryResult`, C17G alerts | `filter_system` with time range and status |
| FilterPanel | Module, time, user, context, trace, status, event type, product filters | UI filter state | Maps to `search_logs` and `filter_system` |
| LogExplorer | Search box plus result scope controls | C17B `LogEntry` | `search_logs` |
| LogTable | Structured log rows with module tags and anomaly marks | C17B `LogEntry` | `search_logs` result data |
| TraceViewer | Step list for selected trace or context | C17C `ExecutionTrace` and C17E drill-down metadata | `drill_down` |
| TimelineView | Ordered context timeline with zoom | `LogEntry`, `ExecutionTrace.chain`, alerts, replay overlay | `drill_down` plus filtered logs |
| ExecutionGraphView | Node-based execution graph | `ExecutionTrace.chain`, C17B logs, replay result, alerts | `drill_down` plus overlays |
| ReplayPanel | Read-only replay comparison details | C17F `ExecutionReplay`, `ReplayResult`, `ReplayDiff` | Existing C17F result supplied by trace/context lookup |
| AnomalyPanel | Alert list and evidence inspector | C17G `Alert`, `AnomalyScore`, evidence | C17G output correlated by context/trace |

Layout strategy:

```text
Header: context_id search, trace_id search, auto-refresh state
Left rail: FilterPanel and saved query chips
Main upper band: OverviewPanel
Main lower tabs: Logs | Trace | Timeline | Graph
Right inspector: ReplayPanel and AnomalyPanel for the selected context
```

The first screen should be operational, not a marketing page. It should show the
latest context groups, health metrics, and anomalies immediately.

## 3. Query-Driven UI Design

C17H treats C17E as the required query boundary.

### search_logs UI

User controls:

- `context_id`
- `trace_id`
- `module`
- `user_id`
- `event_type`
- `product_key`
- `time_range`
- `limit`

Query mapping:

```text
AuditQueryEngine.search_logs(
  user_id,
  module,
  context_id,
  event_type,
  product_key,
  trace_id,
  time_range,
  limit
)
```

The LogTable displays `timestamp`, `module`, `event_type`, `action`, `source`,
`status`, `latency_ms`, `entity.user_id`, `entity.workflow_id`, `context_id`,
and `tags`. Row expansion shows sanitized `request`, `response`, and
`metadata`.

### filter_system UI

User controls:

- Time range presets and explicit start/end timestamps.
- Status segment: all, success, failed, pending, partial.
- Latency bounds.
- Module and action filters.
- Entity type scope: LogEntry, ExecutionTrace, EventRaw.
- Boolean mode: AND, OR, NOT for advanced filters.

Query mapping:

```text
AuditQueryEngine.filter_system(
  time_range,
  status,
  min_latency_ms,
  max_latency_ms,
  action,
  module,
  context_id,
  trace_id,
  product_key,
  user_id,
  event_type,
  operator,
  expression,
  entity_types,
  limit
)
```

The UI should expose optimizer metadata in a compact diagnostics area:
`index_used`, `searched_tiers`, `candidate_count`, `post_filters`,
`cache_hit`, and `full_scan_avoided`.

### drill_down UI

Primary actions:

- Select a `context_id` from any log, alert, timeline event, or graph node.
- Select a `trace_id` for exact path highlighting.
- Open the full chain expansion from C17E metadata.

Query mapping:

```text
AuditQueryEngine.drill_down(context_id, trace_id, limit)
```

`trace_id` is preferred when both ids are present. `context_id` is used to
discover related traces and logs.

## 4. Timeline View Design

Canonical component:

```text
TimelineView
```

Timeline grouping:

```text
context_id
  -> sorted events by timestamp
  -> trace path by step_index when an ExecutionTrace is available
```

Required chronological structure:

```text
[API Request]
  -> [RBAC Check]
  -> [C14 Capability]
  -> [C15 Workflow]
  -> [n8n Execution]
  -> [AI Call]
  -> [DB Write]
```

Ordering rules:

1. Sort all visible events by normalized UTC `timestamp`.
2. For C17C trace steps, preserve `step_index` when timestamps collide.
3. Use `dependency_step_id` to draw dependency markers.
4. Attach C17B `LogEntry` records to the nearest matching trace step by
   `context_id`, `trace_id`, `event_id`, `action`, or timestamp proximity.
5. Mark missing, pending, or failed steps from C17C final status and C17E
   drill-down metadata.

Zoom modes:

| Zoom | Intended use | Rendering |
| --- | --- | --- |
| seconds | Debug one request or replay divergence | Per-step ticks with latency labels |
| minutes | Inspect request bursts and retry storms | Group by minute with expandable steps |
| hours | Audit operational windows | Context clusters and anomaly density |

Timeline event shape:

```text
TimelineEvent
  event_id
  context_id
  trace_id
  timestamp
  stage
  module
  action
  status
  latency_ms
  source_model
  source_ref
  anomaly_ids
  replay_state
```

Visual semantics:

- Failed or critical anomaly events are emphasized first.
- Pending or partial traces use a neutral incomplete state.
- C17G alerts appear as badges on the affected event and as a side lane.
- C17F replay differences appear as a second comparison lane below the original
  event sequence.

## 5. Execution Graph Model

Canonical component:

```text
ExecutionGraphView
```

Graph goal:

```text
ExecutionTrace.chain -> nodes and edges -> human-readable execution path
```

Required node types:

| Node type | Source mapping | Example |
| --- | --- | --- |
| API | C17A/C17B system, frontend, backend, RBAC, control-plane events | `api.request.received`, `rbac.check` |
| C14 capability | C17C step module `C14` | capability selection |
| C15 workflow | C17C step module `C15` | workflow trigger or step |
| n8n node | C17C step module `n8n` | node execution |
| AI call | C17C step module `AI` | prompt send or response receive |
| DB write | C17C step module `DB` | storage write |

Graph node model:

```text
ExecutionGraphNode
  node_id
  node_type
  label
  context_id
  trace_id
  step_id
  module
  action
  status
  timestamp
  latency_ms
  retry_count
  source_model
  source_ref
  anomaly_ids
  replay_state
```

Graph edge model:

```text
ExecutionGraphEdge
  edge_id
  from_node_id
  to_node_id
  context_id
  trace_id
  dependency_step_id
  step_order
  status
  latency_ms
  anomaly_ids
  replay_divergence
```

Edge creation rules:

1. Use `dependency_step_id` when present.
2. Otherwise connect nodes by contiguous `step_index`.
3. Collapse repeated n8n nodes only at high zoom; retain full nodes at trace
   debug zoom.
4. Preserve failed and anomalous nodes even when graph density is reduced.

Highlight behavior:

- `trace_id` highlight marks the exact execution path through all nodes and
  edges.
- C17G alert highlight marks nodes and edges whose source ref appears in alert
  evidence or whose `context_id`/`trace_id` matches the alert.
- C17F replay overlay adds original vs replay status, divergence points, and
  simulated latency differences without changing the graph topology.

## 6. Data Flow Architecture

The dashboard follows the required data flow:

```text
C17D Storage
  -> C17E AuditQueryEngine
  -> C17H AuditDashboardUI
```

Expanded read path:

```text
C17A EventRaw
  -> C17B LogEntry
  -> C17C ExecutionTrace
  -> C17D StorageRecordEnvelope
  -> C17E QueryResult
  -> C17H View Models
  -> OverviewPanel / LogTable / TraceViewer / TimelineView / ExecutionGraphView
```

Overlay path:

```text
C17F ExecutionReplay / ReplayDiff
  -> C17G Alert evidence when replay-backed anomaly exists
  -> C17H ReplayPanel and graph/timeline overlay
```

Data access rules:

- Read only from query/replay/anomaly outputs.
- No direct cold object storage scans from the UI.
- No dashboard-side writes, acknowledgement mutations, replay execution, or
  anomaly state changes.
- Broad queries require a time range or a bounded limit.
- The UI should prefer hot context and trace lookups for near real-time
  debugging.

## 7. Integration With C17A-G

| Stage | C17H usage | Boundary |
| --- | --- | --- |
| C17A Audit Event Collector | Shows API, RBAC, control-plane, webhook, AI, file, and storage event origins when projected through C17B/C17D/C17E | No collector changes |
| C17B Structured Log Schema | Renders `LogEntry` in LogExplorer and LogTable; uses `tags` for module awareness | No schema changes |
| C17C Execution Trace System | Builds TraceViewer, TimelineView, and ExecutionGraphView from ordered `ExecutionTrace.chain` | No trace aggregation changes |
| C17D Storage Layer | Uses C17D only through C17E query results and declared indexes | No storage writes or migrations |
| C17E Audit Query Engine | Required query driver for search, filtering, and drill-down | No query contract changes |
| C17F Execution Replay System | Displays existing `ExecutionReplay`, `ReplayResult`, and replay divergence overlays | No replay execution from C17H |
| C17G Anomaly Detection Layer | Displays `Alert`, severity, evidence, and highlight markers | No anomaly scoring or alert mutation |

## 8. Visualization Mapping Strategy

Core mapping:

| Data field | UI mapping |
| --- | --- |
| `context_id` | Primary grouping, dashboard search, timeline lane, graph scope |
| `trace_id` | Exact path highlight and replay correlation |
| `module` | Badge, graph node type, timeline stage, filter chip |
| `tags` | Secondary module and semantic labels |
| `status` / `final_status` | Row state, node state, edge state, timeline marker |
| `latency_ms` / `total_latency_ms` | Overview metric, timeline span, edge label |
| `retry_count` | Step badge and anomaly signal |
| `error` | TraceViewer detail and failed node marker |
| `Alert.severity` | AlertPanel priority and graph/timeline emphasis |
| `ReplayResult.divergence_points` | Replay overlay and divergence markers |

Module visual mapping:

| Module or node | Visual intent |
| --- | --- |
| API/system | Entry and boundary checkpoint |
| C14 | Capability decision |
| C15 | Workflow orchestration |
| n8n | External workflow node |
| AI | Model call or prompt boundary |
| DB | Write or persistence boundary |
| C16/RBAC | Security checkpoint inside API/system stage |
| C17 | Observability event or dashboard self context |

Anomaly priority:

1. Critical security anomalies.
2. Failed trace steps and replay divergence.
3. High behavior/rate anomalies.
4. Pending or partial execution chains.
5. Low and medium informational anomalies.

Replay overlay strategy:

- Original trace remains the base layer.
- Replay steps are displayed as a comparison row or ghost edge.
- Divergence points are linked back to `step_id` and `step_index`.
- `simulated_latency_ms` is shown beside original `latency_ms`.
- `skipped` replay steps are distinct from failed original steps.

## 9. Read-Only Design Constraints

C17H must obey these constraints:

- No mutation APIs.
- No alert acknowledgement or suppression.
- No replay execution controls.
- No DB migration.
- No new backend contract.
- No direct backend business logic changes.
- No direct writes to C17D.
- No raw secret or unsanitized payload rendering.

Sensitive payload handling:

- Show request/response keys by default.
- Expand sanitized payloads only on explicit row inspection.
- Preserve the sanitization guarantees from C17A and C17B.
- Do not display raw secret values even if an upstream source accidentally
  includes secret-shaped fields.

## 10. Completion Criteria

C17H is complete at the design level when:

- `AuditDashboardUI` architecture is defined.
- UI component breakdown is defined.
- `TimelineView` behavior and zoom modes are defined.
- `ExecutionGraphView` node and edge model is defined.
- Data flow architecture is defined as C17D -> C17E -> C17H.
- C17A-G integration boundaries are defined.
- Query-driven UI behavior is defined for `search_logs`, `filter_system`, and
  `drill_down`.
- Visualization mapping strategy is defined.
- Read-only, context-first, trace-first, near real-time, and module-aware design
  principles are preserved.

