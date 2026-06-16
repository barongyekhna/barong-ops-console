# C17G Anomaly Detection Layer

C17G defines an anomaly detection layer for barong-ops-console observability
data. Its purpose is to let the system discover abnormal behavior automatically
instead of relying only on passive audit queries.

C17G reads C17A-F outputs, but does not modify C17A, C17B, C17C, C17D, C17E,
or C17F. It does not change production runtime behavior, does not add UI, does
not change API contracts, and does not execute a database migration.

## 1. AnomalyDetectionEngine Design

Canonical service: `backend/app/services/anomaly_detection.py::AnomalyDetectionEngine`.

Required methods:

- `analyze_log_stream()`
- `analyze_trace_patterns()`
- `analyze_rate_patterns()`
- `detect_security_violations()`

Supported modes:

- Streaming detection: append incoming C17A/C17B/C17C objects to an in-memory
  rolling window and emit alerts immediately when thresholds are crossed.
- Batch detection: analyze a deterministic historical slice from C17D records
  or C17E query results.
- Replay-based detection: convert C17F replay comparison divergence points into
  C17G `ReplayDiff` evidence and score them.

Input sources:

- C17A `EventRaw`
- C17B `LogEntry`
- C17C `ExecutionTrace`
- C17D `StorageRecordEnvelope`
- C17E `QueryResult`
- C17F `ExecutionReplay` / `ReplayDiff`

## 2. Anomaly Classification System

Canonical model:
`backend/app/schemas/anomaly_detection.py::AnomalyClassificationSystem`.

Behavior anomalies detect:

- Non-normal API call paths.
- Atypical workflow calls.
- Unexpected C13/C14/C15 module usage.
- Unusual execution chain patterns.
- Replay output/order/missing-step divergence from C17F.

Rate anomalies detect:

- Burst traffic.
- High-frequency `user_id` calls.
- `context_id` flood.
- C15H workflow retry storm.

Security anomalies detect:

- Unauthorized control-plane access attempts.
- RBAC bypass attempts.
- Webhook replay abuse.
- Invalid session or token patterns.
- Abnormal AI usage, including prompt injection patterns.

## 3. Scoring Model

Canonical model: `backend/app/schemas/anomaly_detection.py::AnomalyScore`.

```python
AnomalyScore = {
    "entity_id": "string",
    "entity_type": "user | api | workflow | context",
    "scores": {
        "behavior_score": 0,
        "rate_score": 0,
        "security_score": 0,
    },
    "total_score": 0,
    "severity": "low | medium | high | critical",
}
```

C17G uses:

```text
total_score = max(behavior_score, rate_score, security_score)
```

This keeps a critical security signal from being diluted by unrelated low
scores.

## 4. Baseline Model Design

Canonical model: `backend/app/schemas/anomaly_detection.py::BaselineModel`.

Baseline scopes:

- Per user.
- Per module.
- Per workflow.
- Per context_id.

Baseline fields:

- `request_rate_per_minute`
- `context_rate_per_minute`
- `retry_rate_per_minute`
- `security_event_rate_per_minute`
- `allowed_api_paths`
- `allowed_workflows`
- `allowed_modules`
- `action_patterns`
- `module_sequence_patterns`

Deviation rule:

```text
deviation = current - baseline
```

Rate rules compare the current rolling-window rate with the baseline rate and
trigger spike alerts when the current rate crosses the configured multiplier.

## 5. Alert System Schema

Canonical model: `backend/app/schemas/anomaly_detection.py::Alert`.

```python
Alert = {
    "alert_id": "string",
    "anomaly_type": "behavior | rate | security",
    "severity": "low | medium | high | critical",
    "related_context_id": "string | None",
    "related_trace_id": "string | None",
    "description": "string",
    "evidence": [
        "LogEntry | ExecutionTrace | ReplayDiff",
    ],
}
```

C17A `EventRaw` detections are projected into read-only `LogEntry` evidence
inside C17G so the Alert evidence contract stays unchanged.

## 6. Integration Architecture

C17G integration points:

- C17C Execution Trace: behavior analysis from ordered execution chains.
- C17D Storage Layer: source of `StorageRecordEnvelope` records.
- C17E Query Engine: filter support through `QueryResult`.
- C17F Replay System: diff-based anomaly detection through divergence points.

C17G reads only from these layers. It does not write into C17D, change C17E
query behavior, or execute C17F replay.

## 7. Detection Pipeline Flow

Pipeline:

1. Ingest C17A/C17B/C17C records from direct streams, C17D storage records, or
   C17E query results.
2. Normalize records into `LogEntry`, `EventRaw`, `ExecutionTrace`, and
   `ReplayDiff`.
3. Load the baseline model.
4. Run behavior, rate, and security detectors.
5. Compute `AnomalyScore`.
6. Map score to severity.
7. Emit `Alert` with context, trace, description, and evidence.

Streaming path:

1. Append the current event to an in-memory rolling window.
2. Prune records outside the configured window.
3. Compare current rates against baseline rates.
4. Emit alerts immediately when thresholds are crossed.

Batch path:

1. Read a historical slice.
2. Group records by user, context, workflow, and module.
3. Compare the slice against baseline.
4. Return a deterministic result bundle.

Replay path:

1. Read C17F replay comparison output.
2. Convert divergence points to `ReplayDiff`.
3. Score output mismatch, missing steps, step order mismatch, latency
   divergence, trace_id mismatch, and context_id mismatch.
4. Emit replay-backed anomaly alerts.

## 8. Severity Rules

Canonical model: `backend/app/schemas/anomaly_detection.py::SeverityRules`.

- 0-30: low.
- 30-60: medium.
- 60-80: high.
- 80-100: critical.

Boundary rule:

- Score 30 is medium.
- Score 60 is high.
- Score 80 is critical.

## 9. Completion Criteria

C17G is complete when:

- AnomalyDetectionEngine design is defined.
- Anomaly classification system is defined.
- Scoring model is defined.
- Baseline model is defined.
- Alert system schema is defined.
- C17C-D-E-F integration architecture is defined.
- Detection pipeline flow is defined.
- Severity rules are defined.
- Unit tests validate behavior, rate, security, baseline, and replay detection.

## 10. Non-Goals

- No modification to C17A-F.
- No production runtime hook.
- No UI.
- No API contract change.
- No database migration.
