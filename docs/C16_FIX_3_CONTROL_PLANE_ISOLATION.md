# C16-FIX-3 Control Plane Isolation

## Status

C16-FIX-3 is complete at code level.

No business logic, C14/C15 service behavior, sandbox behavior, runtime execution,
Docker workflow, staging workflow, or production workflow was changed.

## API Segmentation

The backend now exposes only these API layers:

- Public API: `/api/public/*`
- Application API: `/api/app/*`
- Control Plane API: `/api/control-plane/*`

Legacy unprefixed backend routes are not mounted.

## Control Plane Exposed Endpoints

The following router groups are mounted only below `/api/control-plane/*`:

- C13/registry plane: `/modules/*`, `/agents/*`, `/workflows/*`
- C09 execution provider plane: `/execution-providers/registry`, `/execution-providers/me`
- C14 adapter/dependency plane: `/module-adapters/*`, `/external-dependencies/*`
- C14X binding plane: `/ai-execution-bindings/*`, `/model-locks/*`, `/capability-bindings/*`, `/module-allocations/*`, `/execution-prompts/*`
- C15 workflow plane: `/workflow-registry/*`, `/module-workflow-bindings/*`
- C15 execution/callback plane: `/webhook-gateway/*`, `/payload-standardization/*`, `/callback-handler/*`, `/result-normalization/*`, `/failure-handling/*`
- Execution triggers: `/foundation-demo/run`, `/foundation-demo/latest`, `/n8n-test/run`, `/n8n-test/latest`, `/n8n-test/callback`

The effective public shape is `/api/control-plane/<router-prefix>/<route>`.

## Isolation Enforcement Design

`backend/app/main.py` now installs a request middleware for every path matching
`/api/control-plane` or `/api/control-plane/*`.

The middleware:

1. Reads the configured session cookie.
2. Validates the session through the existing session validation service.
3. Normalizes legacy RBAC aliases.
4. Allows only `owner`, `admin`, and `system`.
5. Returns `401` for missing or invalid sessions.
6. Returns `403` for authenticated non-control-plane roles.

Unknown control-plane routes remain default-denied by FastAPI routing. A
privileged session reaches the router and receives `404`; unprivileged requests
are denied before routing.

## Middleware Implementation Points

- Backend middleware: `backend/app/main.py`
- Control-plane prefix: `/api/control-plane`
- Allowed role set: `owner`, `admin`, `system`
- Route mount points:
  - `PUBLIC_API_PREFIX = "/api/public"`
  - `APPLICATION_API_PREFIX = "/api/app"`
  - `CONTROL_PLANE_API_PREFIX = "/api/control-plane"`

The Next backend proxy keeps the existing frontend facade `/api/backend/*`, but
maps backend requests by layer:

- public facade path -> `/api/public/*`
- application facade path -> `/api/app/*`
- C09/C13/C14/C15/execution/binding/workflow facade path -> `/api/control-plane/*`

Direct proxy access to `/api/backend/api/control-plane/*`, raw webhook ingress,
callback receiver, and execution submit paths is denied.

## Before/After Architecture

Before:

- Routers were mounted at legacy unprefixed backend paths.
- C14/C15/execution/binding/workflow routes were reachable through the same
  route surface as ordinary application APIs.
- The frontend proxy allowlist contained C14/C15 paths without a backend layer
  distinction.
- Execution triggers such as `n8n-test/run` and `foundation-demo/run` were
  ordinary backend proxy paths.

After:

- Business/application routes are under `/api/app/*`.
- Public routes are under `/api/public/*`.
- C09/C13/C14/C15/execution/workflow/binding/callback routes are under
  `/api/control-plane/*`.
- The control-plane middleware enforces role isolation before route execution.
- The frontend proxy can no longer route C14/C15/execution paths to application
  APIs; those paths map only to the control plane.

## Risk Reduction

- Ordinary authenticated users cannot access control-plane routes.
- C14/C15 APIs no longer share the application API namespace.
- Execution triggers are no longer public or application API routes.
- Direct app-layer bypasses for binding/workflow/execution paths return `404`.
- Callback and webhook ingress paths are not exposed through the frontend proxy.
- C10 sandbox code remains without public router exposure.

## Verification Added

- Backend: `tests/backend/test_control_plane_isolation.py`
- Frontend proxy: `tests/frontend/control-plane-isolation.test.mjs`

These tests were added but not executed as part of this fix because C16-FIX-3
explicitly forbids pytest, Docker, runtime execution, staging deployment, and
production deployment.

## Final C16 Audit Readiness

Ready for final C16 audit.

Residual audit focus:

- Confirm deployment routing points clients at `/api/public`, `/api/app`, and
  `/api/control-plane`.
- Confirm any external callback integration has an explicit system/admin
  control-plane authentication path before enabling live callbacks.
