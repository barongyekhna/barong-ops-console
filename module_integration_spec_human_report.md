# Module Integration Spec Human Report

- Audit ID: `final_preprod_20260623T181922Z_9658bfcf`
- Dynamic test module: `demo.audit_preprod_9658bfcf`

## Plain-English Result

The system has two module concepts today: a dynamic DB registry used by `/api/control-plane/modules`, and a static manifest registry used by module control, API key binding, module access, and the execution gate.

A new module can be created through the dynamic registry, but it is not automatically onboarded into the static manifest registry. Because API key binding and module control both require `get_module_manifest()`, a newly created dynamic module cannot bind keys or be enabled through the control center without a code-level static manifest addition.

## Onboarding Requirements

- Static manifest in backend/app/core/modules.py for control-center, API-key binding, module access, and execution gate recognition.
- Dynamic DB module via /api/control-plane/modules for foundation/demo registry records.
- Module key must use lowercase dot segments for static manifests; dynamic creation currently allows foundation/demo/n8n_test prefixes only.

## API Key Binding Requirements

- Organization must exist and not be deleted.
- API key must be active and belong to the same org.
- module_id must resolve through get_module_manifest(), not only the DB module table.
- key_alias is normalized and used by execution gate key_requirements.

## Execution Pipeline

- module -> module_control_state -> api_key_binding -> key injection -> service dispatch -> operation/event logs.
- Current ExecutionRouter states it does not perform live external calls.
- n8n-test route records mock-only blocked external dispatch.

## Boarding Decision

NO-GO for arbitrary new module onboarding until dynamic registration feeds the same manifest path used by module control, API key binding, permissions, and execution.
