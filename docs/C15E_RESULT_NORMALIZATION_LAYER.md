# C15E Result Normalization Layer

## Scope

C15E defines the result normalization boundary after C15D callback handling.
It converts workflow output into one frontend-ready result contract:

```json
{
  "context_id": "string",
  "module": "string",
  "workflow_id": "string",
  "status": "pending | running | success | failed | unknown",
  "result": {},
  "metadata": {}
}
```

C15E does not execute workflows, does not call n8n, does not call external
APIs, does not mutate staging or production, does not run Docker/pytest, and
does not modify C15A-D implementation files.

## 1. Normalization Engine Design

Engine API:

```text
POST /result-normalization/normalize
```

Inspection API:

```text
GET /result-normalization/normalization-engine
```

Engine flow:

```text
C15D stored result or n8n output
-> flexible JSON parser
-> workflow-specific schema mapping if available
-> fallback common JSON extraction if no mapping matches
-> K/P/SEO module adapter
-> C15E standard result contract
```

Supported input forms:

- C15D result storage record with `workflow_output` and `execution_metadata`.
- n8n item arrays such as `[{ "json": {...}, "pairedItem": ... }]`.
- Direct JSON objects with `result`, `output`, `data`, or `payload`.
- JSON strings that parse into one of the supported shapes.
- Wrapped requests with `raw_output` or `n8n_output` plus optional
  `schema_mappings`.

Raw n8n structures such as `pairedItem`, `binary`, execution run data, and
workflow run envelopes are stripped or unwrapped before the frontend result is
returned.

## 2. Schema Mapping Model

Inspection API:

```text
GET /result-normalization/schema-mapping
```

Mapping direction:

```text
workflow-specific -> standard result schema
```

Mapping rule shape:

```json
{
  "mapping_id": "string",
  "workflow_id": "string",
  "module": "optional string",
  "field_paths": {
    "context_id": ["path", "to", "context"],
    "module": ["path", "to", "module"],
    "workflow_id": ["path", "to", "workflow"],
    "status": ["path", "to", "status"],
    "result": ["path", "to", "result"],
    "metadata": ["path", "to", "metadata"]
  },
  "result_paths": {
    "standard_result_key": ["path", "to", "workflow_specific_value"]
  },
  "metadata_paths": {
    "standard_metadata_key": ["path", "to", "workflow_specific_value"]
  },
  "fallback_result_path": ["optional", "path"]
}
```

Rules:

- `context_id`, `module`, and `workflow_id` mappings are required.
- `status`, `result`, and `metadata` mappings are optional but preferred.
- String path segments traverse objects.
- Numeric string path segments traverse arrays.
- If no mapping matches the workflow, C15E uses fallback normalization.
- If a mapping is invalid or incomplete, C15E falls back to sanitized common
  JSON extraction.

## 3. Module Adapter Rules

Inspection API:

```text
GET /result-normalization/module-adapters
```

Supported module families:

```text
K
P
SEO
```

Adapter output shape for supported families:

```json
{
  "summary": "string or null",
  "items": [],
  "data": {}
}
```

Rules:

- K-series maps knowledge outputs such as `answer`, `insights`, and
  `recommendations` into `summary`, `items`, and `data`.
- P-series maps product outputs such as `product`, `products`, `items`,
  `draft`, and `listing` into `summary`, `items`, and `data`.
- SEO maps `keywords`, `recommendations`, `title`, and `meta_description` into
  `summary`, `items`, and `data`.
- Generic modules keep the same standard top-level C15E output and pass
  sanitized result data through.

No adapter calls module APIs or triggers follow-up execution.

## 4. UI Output Structure

Inspection API:

```text
GET /result-normalization/ui-output-structure
```

Frontend result contract:

```json
{
  "context_id": "ctx.c15c.<16 hex chars> or ctx.c15e.<16 hex chars>",
  "module": "module key",
  "workflow_id": "workflow id",
  "status": "pending | running | success | failed | unknown",
  "result": {
    "summary": "string or null",
    "items": [],
    "data": {}
  },
  "metadata": {
    "stage": "C15E",
    "component": "Result Normalization Layer",
    "result_schema_version": "c15e_standard_result_v1",
    "module_family": "K | P | SEO | generic",
    "adapter_rule": "string",
    "schema_mapping_id": "string or null",
    "source_schema": "workflow_specific | standard_json | fallback",
    "source_format": "c15d_storage | c15d_notification | n8n_items | json_object | json_string | json_list | fallback",
    "fallback_used": false,
    "extracted_fields": [],
    "source_metadata": {},
    "frontend_consumable": true,
    "raw_n8n_structure_exposed": false
  }
}
```

UI compatibility rules:

- Frontend consumes the C15E response directly.
- C15D storage names such as `workflow_output` and `execution_metadata` are not
  exposed as top-level fields.
- Raw n8n item structures are not exposed.
- URLs, webhook references, credentials, tokens, secrets, and authorization
  values are rejected.

## 5. Completion Status

Completion API:

```text
GET /result-normalization/completion-status
```

C15E is complete:

- Output normalization engine: implemented.
- Workflow-specific schema mapping: implemented.
- Flexible JSON parsing: implemented.
- Fallback normalization: implemented.
- K/P/SEO module adapter rules: implemented.
- UI-compatible output contract: implemented.
- Raw n8n structure exposure: blocked.
- Runtime execution trigger: not performed.
- n8n dispatch: not performed.
- External API call: not performed.
- Production/staging change: not performed.
- Docker/pytest/git commit: not performed.

Can proceed to C15F: yes.
