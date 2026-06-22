# API Key System Audit - Human Report

Checked at: 2026-06-22T14:58:00Z

## Verdict

API Key Orchestration storage, owner-only routes, frontend route bindings, and backend key isolation service exist. The production database currently has zero active API keys and zero active module-key bindings.

The management layer is usable at the route level, but the full execution flow is not complete: `resolve_module_api_key_for_injection` is only referenced by tests and the API key service itself. No production module execution path calls it, so `module -> api key -> backend execution -> response` is a BROKEN FLOW for real modules.

## Storage And Routes

- `api_key_records`: present, 0 active records
- `api_key_module_bindings`: present, 0 active bindings
- `/api/backend/api-key-orchestration/keys`: 200 through frontend proxy
- `/api/backend/api-key-orchestration/bindings`: 200 through frontend proxy
- `/api/backend/organizations?limit=100&offset=0`: 200, returned 2 real organizations for dropdown binding

## Security Isolation

- API key plaintext is not returned by list/create/update responses.
- Stored key values use backend envelope encryption in `ApiKeyRecord.encrypted_key_value`.
- Frontend now displays only "已加密保存" and does not display hash prefixes.
- Binding creation checks org mismatch and raises isolation errors.

## Broken Link

The backend injection function exists:

- `backend/app/services/api_key_orchestration.py::resolve_module_api_key_for_injection`

But production modules do not call it. Search result:

- Service definition only
- Test references only

This means keys can be managed and bound, but modules do not yet consume assigned keys during actual execution.

## Deployment Decision

Do not restart containers. The API key management UI/API is present, but the real module execution key injection chain is not fully connected.
