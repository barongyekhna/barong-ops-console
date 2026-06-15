# C15A Workflow Registry System

## Scope

C15A defines the read-only n8n Workflow Registry System for
barong-ops-console. It is the single source of truth for module to workflow
bindings and hidden webhook references.

It does not execute n8n workflows, trigger AI models, modify staging or
production, or auto-create unregistered workflows.

## Workflow Registry Model

```json
{
  "workflow_id": "string",
  "module": "string",
  "trigger": "webhook",
  "status": "active | inactive | deprecated | error",
  "n8n_webhook": "string",
  "version": "string",
  "created_at": "string",
  "updated_at": "string"
}
```

The `n8n_webhook` value is an opaque `n8n-webhook-ref://...` reference. Real
n8n webhook addresses, tokens, credentials, query strings, and host URLs are
blocked by validation.

## Module Binding Mapping

Current C15A registry source:

| module | workflow_id | status | webhook exposure |
| --- | --- | --- | --- |
| `integration.n8n_test_bridge` | `n8n.workflow.integration.n8n_test_bridge.dispatch.v1` | `active` | hidden reference only |
| `integration.n8n_test_bridge` | `n8n.workflow.integration.n8n_test_bridge.legacy.v1` | `deprecated` | hidden reference only |

The mapping proves that one module can bind multiple workflows. Bindings are
queryable through:

- `GET /workflow-registry/registry`
- `GET /workflow-registry/module-bindings`
- `GET /workflow-registry/modules/{module}/workflows`
- `GET /workflow-registry/workflows/{workflow_id}`

## Status Management Logic

| status | behavior |
| --- | --- |
| `active` | Explicitly bound workflow may be dispatched by C15B. C15A itself does not dispatch. |
| `inactive` | Registered but forbidden from execution. |
| `deprecated` | Queryable/read-only, not executable. |
| `error` | Blocks execution until status changes. |

`GET /workflow-registry/decision` returns the registry decision for a module and
workflow pair without executing anything.

## Registry Rules

- Unregistered workflows are blocked.
- A module must be explicitly bound to a workflow.
- Real n8n webhook addresses are hidden and rejected if present.
- C15A registry data is the single source of truth.
- No POST, PATCH, DELETE, run, execute, sync, or invoke API is exposed.
- C15A never calls n8n and never triggers AI models.

## System Flow

```text
Module -> C15A Registry -> C15B -> n8n webhook -> C15D callback
```

Flow contract:

1. Module requests a workflow by explicit module/workflow_id binding.
2. C15A validates registration, module binding, hidden webhook reference, and
   status.
3. C15B may dispatch only an active decision from C15A.
4. n8n webhook returns through the governed callback boundary.
5. C15D callback records results without mutating C15A registration.

## Completion Status

C15A is complete:

- Workflow registry implementation: complete.
- Module-binding mapping: complete.
- Status management logic: complete.
- System flow diagram: complete.
- Hidden webhook policy: enforced.
- Registry single source of truth: enforced.
- n8n execution: not performed.
- AI model trigger: not performed.
- Production/staging changes: not performed.

Can proceed to C15B: yes. C15B must consume C15A decisions and may only dispatch
workflows when C15A returns an active, explicitly bound workflow with a hidden
webhook reference.
