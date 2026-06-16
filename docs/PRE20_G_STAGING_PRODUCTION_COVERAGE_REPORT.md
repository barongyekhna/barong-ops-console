# PRE20-G Staging / Production Coverage Report

Date: 2026-06-16

Mode: static repository audit only. No deployment, production runtime, staging runtime, migration, UI change, or code fix was executed.

Scope covered:

- `backend/app/`
- `frontend/`
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/app/api/`
- `backend/app/repositories/`
- `backend/app/middleware/`
- `backend/app/sandbox/`
- `backend/app/core/`
- `docs/`
- `tests/`
- `docker-compose.example.yml`
- `docker-compose.staging.yml`
- `docker-compose.production.yml`

Repository note: there are no top-level `services/`, `schemas/`, `api/`, `repositories/`, `middleware/`, `sandbox/`, or `core/` directories. Their active implementation paths are under `backend/app/`.

Status rules used:

- 🟢 PRODUCTION RELEASED: auditable staging or production release record exists, production route/runtime is reachable for the released scope, and smoke/release evidence is documented.
- 🟡 STAGING ONLY: staging validation exists, but production release or production gateway exposure is explicitly absent.
- 🔴 LOCAL / MOCK ONLY: local/demo/mock/schema-only/in-memory behavior, or production-visible demo behavior that is not a real released business/runtime feature.
- ⚫ NO DEPLOY PATH: code exists, but no complete deploy record, migration application path, frontend/proxy surface, or runtime service path proves it can reach staging or production.

### 1. Deployment Coverage Matrix

| Feature | Staging | Production | Status |
|---|---|---|---|
| C01 console foundation: frontend/backend/postgres, HTTPS, health | C02 later established staging; C01 itself predates staging-first | C01 production acceptance archived | 🟢 PRODUCTION RELEASED |
| C02 dual environment isolation: staging/prod compose, env separation, smoke checks | `docker-compose.staging.yml`, staging smoke, dual-env check | `docker-compose.production.yml`, production smoke, dual-env check | 🟢 PRODUCTION RELEASED |
| C03 owner-created user management API and `/users` UI | C03D staging acceptance | C03E production release | 🟢 PRODUCTION RELEASED |
| C04 role catalog API/UI | C04D staging acceptance | C04E production release | 🟢 PRODUCTION RELEASED |
| C05 permission registry, `/auth/me.permissions`, `/permissions/me`, `/permissions/registry` | C05E staging acceptance plus Alembic `c05b_permissions_001` | C05F production release plus Alembic `c05b_permissions_001` | 🟢 PRODUCTION RELEASED |
| C06 user permission assignment API/UI | C06D staging acceptance | C06E production backend/frontend release | 🟢 PRODUCTION RELEASED |
| C07 module registry, module-aware navigation, module access state | C07E staging safe release | C07F production safe release | 🟢 PRODUCTION RELEASED |
| C08 module adapter registry/shell as read-only no-execute contract | C08E staging safe release | C08F production safe release | 🟢 PRODUCTION RELEASED |
| C09 execution provider registry/status shell | C09E staging validation referenced | C09F/G explicitly production-independent; no production gateway/release required | 🟡 STAGING ONLY |
| F11 foundation demo run/latest and foundation data loop | Demo route/UI exists; staging release not independently proven after C08 | Demo route/UI was part of foundation-era product shell, but remains demo-only | 🔴 LOCAL / MOCK ONLY |
| F12 n8n test bridge | Test/demo bridge only | Test/demo bridge only; no real n8n production workflow | 🔴 LOCAL / MOCK ONLY |
| Foundation jobs/artifacts/reviews/errors/memory CRUD | DB-backed demo/metadata records only | Pages/API exist as foundation/demo records, not real business execution | 🔴 LOCAL / MOCK ONLY |
| `/products` and `/settings` frontend pages | Empty states only | Empty states only | 🔴 LOCAL / MOCK ONLY |
| C08 adapter action execution | No execution path | No execution path; C08 production release is read-only contract shell only | 🔴 LOCAL / MOCK ONLY |
| C09 provider execution / request system | No-op/mock/contract-only | No production execution system, no queue, no worker, no submit/run endpoint | 🔴 LOCAL / MOCK ONLY |
| C10 sandbox runner/runtime/bridge | No staging deployment evidence | No production deployment evidence; mock-only service code and no public API | 🔴 LOCAL / MOCK ONLY |
| C12 approval persistence API | No staging release record found | Migration/API code exists, but no production release or Alembic application record found | ⚫ NO DEPLOY PATH |
| C13 module switch runtime gate / policy / execution flow guard | No staging deployment evidence | Service/schema code only; no released production API or migration | 🔴 LOCAL / MOCK ONLY |
| C13 emergency kill switch | No staging deployment evidence | Process-memory service only; no durable API/release path | 🔴 LOCAL / MOCK ONLY |
| C14 secret rules and external dependency governance | No staging deployment evidence | Contract/read-only/static governance; no release path or live dependency connector | 🔴 LOCAL / MOCK ONLY |
| C14X AI execution binding/model lock/capability/allocation/prompt generator | No staging deployment evidence | Static/read-only contract APIs in code, but no release record or live AI/model path | 🔴 LOCAL / MOCK ONLY |
| C15A workflow registry | No staging deployment evidence | Static/read-only workflow registry; no live workflow execution | 🔴 LOCAL / MOCK ONLY |
| C15B webhook gateway | No staging deployment evidence | Validates/gates contract payloads; frontend/Nginx block ingress and no dispatch is released | 🔴 LOCAL / MOCK ONLY |
| C15C payload standardization | No staging deployment evidence | Transform API code exists, but no staging/prod release record | ⚫ NO DEPLOY PATH |
| C15D callback handler | No staging deployment evidence | In-memory callback context/result store; no durable release path | 🔴 LOCAL / MOCK ONLY |
| C15E result normalization | No staging deployment evidence | Transform API code exists, but no staging/prod release record | ⚫ NO DEPLOY PATH |
| C15F module-workflow binding | No staging deployment evidence | Static/read-only binding model; no workflow runtime | 🔴 LOCAL / MOCK ONLY |
| C15G security isolation layer | No staging deployment evidence | Code-level only; docs state no staging/production change | ⚫ NO DEPLOY PATH |
| C16 session-cookie/auth-session upgrade | No staging deployment evidence | `auth_sessions` migration exists, but no production release/application record found | ⚫ NO DEPLOY PATH |
| C16 control-plane isolation / advanced security hardening | No staging deployment evidence | Code-level only; C16 docs state no staging/production deployment changed | ⚫ NO DEPLOY PATH |
| C17 audit event collector | No staging deployment evidence | Middleware/service uses process memory/logging; no durable released observability path | 🔴 LOCAL / MOCK ONLY |
| C17 structured logs | No staging deployment evidence | Service/schema only; no API, no table, no release path | ⚫ NO DEPLOY PATH |
| C17 execution trace | No staging deployment evidence | Service/schema only; no API, no table, no release path | ⚫ NO DEPLOY PATH |
| C17 storage layer / audit query / replay / anomaly detection | No staging deployment evidence | In-memory/service/test layer only; no durable production service | 🔴 LOCAL / MOCK ONLY |
| C17 operation log list/detail API | Operation logs are used by released features, but no external proxy/UI release record found | DB table exists, but product access path is not released through frontend proxy | ⚫ NO DEPLOY PATH |
| C18 organization lifecycle and memberships | No staging deployment evidence | Models/routes exist, but Alembic migrations for `organizations` and `org_memberships` are missing | ⚫ NO DEPLOY PATH |
| C18 module binding/shared modules/module visibility | No staging deployment evidence | Process-memory registries; no durable production path | 🔴 LOCAL / MOCK ONLY |
| C18 permission/data isolation middleware | No staging deployment evidence | Middleware code exists, but depends on incomplete C18 persistence and bindings | ⚫ NO DEPLOY PATH |
| C19 contact identity and global contact directory | No staging deployment evidence | Model/routes exist, but `contact_identities` migration is missing | ⚫ NO DEPLOY PATH |
| C19 messages | No staging deployment evidence | Send returns envelope only; history/read routes return 501; `messages` migration/repository missing | 🔴 LOCAL / MOCK ONLY |
| C19 conversations | No staging deployment evidence | Direct conversations are process-memory; group chat returns 501 | 🔴 LOCAL / MOCK ONLY |
| C19 friends/messaging permission | No staging deployment evidence | Friend requests/status are process-memory only | 🔴 LOCAL / MOCK ONLY |
| C19 attachments | No staging deployment evidence | Upload/fetch routes return 501 schema-only notices; no storage path | 🔴 LOCAL / MOCK ONLY |
| C19 communication extensions | No staging deployment evidence | Schema-only future contracts; no mounted runtime route or migration | ⚫ NO DEPLOY PATH |

### 2. STAGING ONLY Features List

- P1 - C09 Execution Provider contract/status layer: C09E staging validation is referenced, but C09F/G explicitly says production gateway exposure is not required and runtime execution remains disabled.

No other audited feature had a clear "staging accepted, production not released" record. Most C10-C19 features did not reach staging at all.

### 3. LOCAL / MOCK ONLY Features List

- P0 - C08/C09/C10 execution chain: adapters are no-execute, providers are no-op/mock/contract-only, and sandbox runtime is mock-only.
- P0 - C13 emergency kill switch: process-local memory, no durable/cluster-wide release path.
- P0 - C18 module/shared binding: process-memory tenant/module state.
- P0 - C19 messaging/conversation/friend state: process-memory, 501, or envelope-only behavior.
- P0 - C17 event/storage/audit-query/replay/anomaly paths: in-memory observability that cannot be trusted across workers or restarts.
- P1 - F11 Foundation Demo and F12 n8n Test Bridge: demo/mock flows can create successful-looking records but do not run real business or real n8n production workflows.
- P1 - C14/C14X/C15 registry, governance, workflow, and binding surfaces: contract/read-only/static state; no runtime connector or live execution.
- P1 - C15 callback handler and failure handling: in-memory callback/DLQ stores.
- P2 - `/products` and `/settings`: visible empty-state UI, not shipped business/product functionality.

### 4. NO DEPLOY PATH Features List

- P0 - C12 approval persistence API: migration and API code exist, but no staging/prod release record or production Alembic application record was found.
- P0 - C16 auth session and security hardening migrations: `auth_sessions`, login-lockout fields, and security tables exist in Alembic, but C16 docs state no staging/production deployment changed.
- P0 - C18 organization/membership/contact identity/message persistence: models/routes exist, but required migrations are missing for `organizations`, `org_memberships`, `contact_identities`, and `messages`.
- P1 - C15C payload standardization and C15E result normalization: transform routes/code exist, but no staging/prod release record was found.
- P1 - C15G control-plane/security isolation: code-level and Nginx-template changes exist, but no release record proves they are deployed.
- P1 - C17 structured logs, execution trace, and operation-log product access: no released API/UI/proxy path for production operators.
- P1 - C18 permission/data isolation middleware: code exists but durable org/binding dependencies are incomplete.
- P2 - C19 communication extensions: future schema only, no mounted runtime route.

### 5. Critical Release Gaps (P0)

- P0 - Missing CI/CD pipeline: no `.github`, GitLab CI, Jenkinsfile, CircleCI, Drone, or Azure pipeline was found. Build/test/package/promotion is manual via scripts and documents.
- P0 - Missing migration promotion path: `scripts/safe_compose_release.sh` only releases backend/frontend containers. It does not run Alembic. C05 used manual Alembic in backend containers; no generalized staging/prod migration gate exists.
- P0 - Documented production Alembic state is stale for later code: C08F records production current/head as `c05b_permissions_001`. Later migrations `c12d_approval_001`, `c16_auth_sessions_001`, `c16_fix4_login_lockout_001`, and `c16_adv_security_001` have no production application evidence in the audited release docs.
- P0 - C18/C19 DB-backed APIs cannot survive production deploy: `organizations`, `org_memberships`, `contact_identities`, and `messages` have models/routes but no Alembic table migration.
- P0 - Frontend not deployed for C18/C19/C12/C17 operator workflows: current frontend navigation/proxy does not expose tenant, approval, contact, messaging, attachment, operation-log, audit-query, trace, or anomaly workflows.
- P0 - Mock/demo can leak into production UX: foundation demo, n8n test bridge, placeholder products, no-execute adapters/providers, and demo job/artifact/review/memory records can appear successful while not representing real business execution.
- P0 - No feature-level staging-to-production ledger after C08: C09-C19 code exists in the repository, but release records mostly say no staging/production change or contain no release record at all.

### 6. CI/CD Pipeline Map

Build flow:

- Backend image: `backend/Dockerfile` installs `backend/requirements.txt` and starts `uvicorn backend.app.main:app`.
- Frontend image: `frontend/Dockerfile` runs `npm ci`, `npm run verify`, `npm run typecheck`, and `npm run build`, then packages Next.js standalone output.
- Compose build: `docker-compose.example.yml`, `docker-compose.staging.yml`, and `docker-compose.production.yml` all build local images directly from the repository.

Test flow:

- `scripts/test_backend_docker.sh` builds backend and runs `tests/backend/test_health.py`.
- `scripts/test_backend_db_docker.sh` runs backend DB tests, Alembic upgrade/downgrade/upgrade, and selected API tests against the example DB.
- `scripts/test_frontend_docker.sh` builds the frontend image, which executes verify/typecheck/build.
- `scripts/test_foundation_acceptance.sh` chains backend, DB, frontend, compose config, diff checks, and safety scans.
- These are manually invoked scripts, not CI pipeline jobs.

Package flow:

- Packaging is local Docker image creation by Compose.
- OPS01 safe release creates rollback image tags for the previously running backend/frontend image.
- No artifact registry, immutable build artifact promotion, signed release manifest, or commit-to-image attestation was found.

Staging flow:

- Static deployment check: `scripts/check_staging_deploy_files.sh`.
- Runtime smoke check: `scripts/staging_smoke_check.sh`.
- Release mechanism: `scripts/safe_compose_release.sh --env staging --service backend|frontend --execute` with `CONFIRM_SAFE_RELEASE=yes`.
- Scope limit: backend/frontend only; postgres target is forbidden; migrations are not automated.
- Staging remains server-local on `127.0.0.1:3100` and `127.0.0.1:8100`.

Production flow:

- Static deployment check: `scripts/check_production_deploy_files.sh`.
- Runtime smoke check: `scripts/production_smoke_check.sh`.
- Release mechanism: `scripts/safe_compose_release.sh --env production --service backend|frontend --execute` with both `CONFIRM_SAFE_RELEASE=yes` and `CONFIRM_PRODUCTION_RELEASE=yes`.
- Scope limit: backend/frontend only; postgres target is forbidden; migrations are manual when explicitly approved.
- Production public entry is `https://ops.barongyekhna.com` through the reviewed Nginx template.

Manual deploy gap:

- Build, test, release, migration, staging acceptance, production acceptance, and rollback tagging are not bound together in an automated pipeline.
- Smoke checks verify login/health/container status, not every feature route or migration dependency.
- Feature releases are documented per C-stage only through C08. C09-C19 do not have equivalent production promotion evidence.

Backend deployment coverage:

- `backend/app/main.py` mounts public, app, and control-plane routers, so current source contains many C09-C19 FastAPI routes.
- The release evidence only proves production promotion through C08. A route being imported by `main.py` is not enough to prove it passed staging or production.
- Backend container runtime is present for `console_backend` and `console_staging_backend`; no worker, queue, scheduler, sandbox executor, callback worker, or migration runner service is defined in compose.

Frontend deployment coverage:

- `frontend/Dockerfile` builds a production Next.js standalone bundle and runs verify/typecheck/build during image creation.
- The frontend proxy allowlist exposes only selected public/app/control-plane paths. C18/C19 tenant/contact/messaging APIs, approval workflows, operation logs, audit query, traces, replay, and anomaly workflows are not exposed through the production console proxy.
- `/products` and `/settings` are visible pages but remain empty states.

Docker / infra coverage:

- `docker-compose.staging.yml` and `docker-compose.production.yml` both define only Postgres, backend, and frontend services.
- Both compose files isolate Postgres on Docker networks and expose backend/frontend on loopback host ports.
- Neither compose file defines a migration job, background worker, queue, cache/Redis, object storage, websocket service, or external provider connector.
- Runtime env templates exist for staging and production, but compose/static checks do not verify all later C16/C15 security variables or feature-specific DB migration requirements.

### 7. Deployment Risk Summary

What would break on production deploy:

- C18/C19 DB-backed routes can fail immediately because required tables are not in Alembic.
- C12/C16 code can require migrations that have no documented production application path after C08.
- Frontend calls for C18/C19/C12/C17 will return 404 through the current `/api/backend` proxy because the allowlist does not expose them.
- C15/C17/C18/C19 in-memory state will split across workers and reset on restart.
- Any real execution attempt remains blocked because C08/C09/C10/C13/C14/C15 are still no-execute/contract/mock layers.

What never reached staging:

- C10 sandbox runtime, C12 approval persistence, C13 module switch/kill switch/gate, C14/C14X governance, C15 workflow/webhook/callback/normalization layers, C16 security hardening, C17 observability/search/replay/anomaly, C18 organization/tenant isolation, and C19 messaging/contact/attachment systems have no clear staging release record in the audited docs.

What is only local runtime:

- Mock execution provider, sandbox runner/runtime/bridge, foundation demo, n8n test mock dispatcher, C13 kill switch, C15 callback/DLQ stores, C17 event/storage/query/replay/anomaly stores, C18 module/shared bindings, C19 conversations/friend requests/messages/attachments, and schema-only communication extensions.

Overall verdict:

- The production-released surface is strongest from C01-C08: environment, auth/users/roles/permissions, module registry, and read-only module adapter contracts.
- C09 is staging-only and intentionally no-execute.
- C10-C19 are mostly code-level, test-level, mock-level, schema-level, or missing-migration work. They should be treated as implemented-but-unreleased or not deployable until each has a staging acceptance, migration plan, frontend/proxy path, and production release record.
