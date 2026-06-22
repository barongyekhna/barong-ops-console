# Module Integration Standard

Generated at: 2026-06-22

## Module Identity

- Every module must have a stable `module_id` matching the manifest `module_key`.
- Module IDs must use lowercase dot-separated namespaces, for example `business.products`.
- New modules must be added to the manifest registry before they can be controlled or receive API key bindings.

## Organization Binding

- Runtime control state is bound by `org_id + module_id`.
- The Module Control Center auto-registers missing org/module control rows from the manifest registry.
- Deleted organizations are excluded from auto-registration.
- Mutating control-plane JSON bodies must not include `org_id`; owner-only control APIs use path-scoped org identifiers and backend-side validation.

## API Key Dependency Rules

- A module must declare the key alias it needs, such as `serper`, `openai`, or `deepseek`.
- API keys are stored per org and can only be bound to modules in the same org.
- Cross-org key binding is forbidden.
- Deleted or disabled keys cannot be injected.

## Execution Pipeline Rules

- Check module registration.
- Check org/module control state.
- Generate payload or prompt.
- Resolve backend key binding by `org_id + module_id + key_alias`.
- Inject the key only in backend process memory.
- Execute the provider call from backend code only.
- Normalize and return results without key material.

## Error Handling Rules

- Module runtime errors must update `runtime_status=error`.
- Safe `runtime_error_code` and `runtime_error_message` may be displayed in the owner control center.
- Raw provider secrets, authorization headers, tokens, or credentials must never be stored in runtime error messages.

## Security Isolation Rules

- Frontend never receives API key values.
- Responses must not include `key_value`, `encrypted_key_value`, or full `key_fingerprint`.
- API key deletion is soft deletion.
- Bindings are disabled when a key is deleted.
- RBAC core must remain the security boundary; new control surfaces use owner-only dependencies.
