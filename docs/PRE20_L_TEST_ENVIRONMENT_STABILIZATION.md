# PRE20-L: Test Environment Stabilization Plan

Scope: static audit of `tests/backend`, `tests/frontend`, `scripts/test_*.sh`, `backend/app`, `backend/alembic`, Docker Compose files, dependency manifests, and implicit CI assumptions.

Path note: the requested `backend/tests/` and `frontend/tests/` directories are not present in this repository. The active test roots are `tests/backend` and `tests/frontend`.

Execution constraint: no tests were run, no dependencies were installed, no CI/CD files were changed, and no product code was modified. Status below is based on repository structure, scripts, manifests, and static imports only.

## 1. Test System Status Map

### Current Inventory

| Area | Static count / files | Current standard entry | Status |
| --- | ---: | --- | --- |
| Backend pytest files | 70 `tests/backend/test_*.py` files | No single full-suite command in repo metadata | Partial |
| Frontend Node tests | 11 `tests/frontend/*.test.mjs` files | No `npm test` script | Partial |
| Requested backend test root | `backend/tests/` absent | Tests live under `tests/backend` | Path gap |
| Requested frontend test root | `frontend/tests/` absent | Tests live under `tests/frontend` | Path gap |
| Backend smoke Docker | `scripts/test_backend_docker.sh` | Builds backend, runs `tests/backend/test_health.py` only | Working but narrow |
| Backend DB Docker | `scripts/test_backend_db_docker.sh` | Example Postgres + selected pytest files + Alembic cycle | Partial |
| Frontend Docker | `scripts/test_frontend_docker.sh` | Builds frontend image; Dockerfile runs `verify`, `typecheck`, `build` | Partial |
| Foundation acceptance | `scripts/test_foundation_acceptance.sh` | Chains the above scripts plus static safety scans | Partial |
| CI config | No `.github` / GitLab CI file found | Manual scripts only | Broken / absent |

### Green: Working Tests

These are expected to be runnable in the existing Docker paths or as pure local tests once dependencies are installed. They do not require production/staging state.

- `scripts/test_backend_docker.sh`: isolated example Docker build plus `tests/backend/test_health.py`; does not start DB because it uses `--no-deps`.
- Static backend tests that only validate metadata, schemas, or pure services, for example `test_security.py`, `test_roles.py`, `test_structured_logs.py`, `test_attachment_schema.py`, `test_org_membership_schema.py`, `test_organization_schema.py`, `test_contact_identity_schema.py`, `test_sandbox_execution_context.py`, `test_sandbox_runtime_finalization.py`, `test_execution_flow_gate.py`, `test_approval_workflow_engine.py`, `test_audit_query_engine.py`, `test_execution_replay.py`, `test_execution_trace.py`, `test_anomaly_detection.py`, and similar service-contract tests.
- Frontend Node test files use Node built-in `node:test` and `assert`; this is a sound low-dependency design when executed under the pinned Node 24 Docker image.

### Yellow: Partial Tests

These tests exist and are useful, but their repeatability depends on implicit setup.

- Backend API and DB tests using `TestClient`, `owner_client`, `auth_client`, `SessionLocal`, SQLAlchemy, Alembic, or direct table cleanup.
- Static grep found 47 backend files touching `SessionLocal`, SQLAlchemy, `engine`, `Base.metadata.create_all`, or Alembic.
- Static grep found 27 backend files touching `TestClient` or auth fixtures.
- Static grep found 29 backend files importing `backend.app.main` / `app`; imports bind settings and the default `DATABASE_URL` before individual tests can override them.
- `scripts/test_backend_db_docker.sh` covers only selected legacy/foundation files, not the full C01-C19 surface.
- `frontend/Dockerfile` copies `tests/frontend` and `verify-foundation.mjs` checks that selected test files exist, but the Docker build does not run `node --test tests/frontend/*.test.mjs`.
- `frontend/package.json` has `verify`, `typecheck`, and `build`, but no `test` or `test:frontend` command.

### Red: Broken / Absent Test Paths

These are not repeatable as a standardized system today.

- Host backend `pytest` is not standardized. Existing docs record prior failures where `pytest` was missing from the available host Python environment.
- Full backend suite has no documented bootstrap that creates an isolated DB, applies Alembic, runs all tests, and tears down state.
- Direct `pytest tests/backend` can hit a default example Postgres URL and fail once fixtures touch `SessionLocal`.
- Direct DB/API tests can fail when tables are absent because `conftest.py` deletes from many tables but does not own migration setup.
- Frontend test suite is not part of the package scripts or Docker test script.
- CI/CD test execution is absent; current assumptions are manual script invocation.

## 2. Dependency Missing Report

### Python Runtime Dependencies

Observed in `backend/requirements.txt`:

- Present: `pytest==8.3.5`, `pydantic==2.13.4`, `pydantic-settings==2.8.1`, `fastapi==0.115.12`, `SQLAlchemy==2.0.41`, `psycopg==3.2.9`, `psycopg-binary==3.2.9`, `httpx==0.28.1`, `anyio==4.13.0`, `alembic==1.16.1`, `argon2-cffi==25.1.0`, `uvicorn==0.34.0`.
- No direct static version conflict was found in the pinned set.
- `httpx` is present, which is required by Starlette/FastAPI `TestClient`.
- Async runtime is mostly framework-provided (`anyio`); no current static evidence of `pytest-asyncio`, `asyncpg`, or `aiosqlite` usage.

### Missing / Misclassified Python Test Dependencies

- Missing `requirements-dev.txt`.
- Missing `pyproject.toml`, `pytest.ini`, `tox.ini`, or `noxfile.py`.
- Missing standard local virtualenv bootstrap.
- `pytest`, `httpx`, and Alembic are mixed into runtime `requirements.txt`; this makes the production backend image install test tooling.
- `backend/Dockerfile` copies `tests/backend` into the backend image, further blurring runtime and test layers.
- No coverage tooling is declared (`pytest-cov`) and no test marker tooling/config exists.
- No lint/type-check dependency standard exists for backend.

### Frontend Dependencies

- `frontend/package.json` pins Node-facing dependencies and requires `node >=24.0.0`.
- No frontend test script is declared.
- No explicit `node --test` command is wired into package scripts, Docker scripts, or CI.
- The frontend test files import `.ts` sources directly, so repeatability depends on Node 24 native TypeScript handling plus installed frontend dependencies.

### Runtime Import Failure Risks

- If host Python has not installed backend requirements, test collection fails on imports such as `pytest`, `pydantic`, `fastapi`, `sqlalchemy`, `httpx`, or `argon2`.
- `backend.app.db.session` initializes `settings = get_settings()` and `engine = create_engine(settings.database_url)` at import time. This does not connect immediately, but it freezes the selected DB URL for tests that import `app` before overriding environment.
- `backend.app.main` imports all route modules and middleware, so a single missing runtime dependency can break many otherwise pure tests during collection.
- DB/API fixtures touch `SessionLocal`; without an available test Postgres and migrated schema, failures move from collection/import to fixture setup/runtime.

## 3. Broken Test Inventory

### Broken by Missing Local Environment

- Host `pytest` execution is not reliable because the repo lacks a canonical `.venv` / install contract.
- Prior repository docs already record host failures: `pytest: command not found`, `python` missing, and `python3` lacking `pytest` / project dependencies.
- There is no command such as `make test`, `scripts/test_backend_local.sh`, or `python -m pytest` documented with environment preparation.

### Broken by DB Bootstrap Gap

- `tests/backend/conftest.py` uses `SessionLocal` to delete rows from many tables but does not run Alembic or create the DB.
- Many DB tests rely on the external state established by `scripts/test_backend_db_docker.sh`, but that script runs a curated subset only.
- Some newer tests call `Base.metadata.create_all(bind=engine, checkfirst=True)` inside file-level fixtures; others rely on Alembic. This creates inconsistent schema ownership.
- There is no per-test transaction rollback, per-test schema, or per-run database isolation standard.

### Broken by Incomplete Test Entrypoints

- `scripts/test_backend_docker.sh` runs only `test_health.py`; it is a smoke test, not a backend test suite.
- `scripts/test_backend_db_docker.sh` does not include many C05-C19 test files, including permission assignment, module adapter, execution provider, sandbox, approval, callback, payload/result normalization, control-plane, audit, C18, and C19 suites.
- `scripts/test_frontend_docker.sh` only builds the frontend image; the image build runs `npm run verify`, `npm run typecheck`, and `npm run build`, but not the 11 Node test files.
- `scripts/test_foundation_acceptance.sh` is a foundation safety gate, not a full test runner.

### Broken by CI Absence

- No CI workflow file was found.
- No CI install step exists for Python or frontend dependencies.
- No CI Postgres service definition exists.
- No CI artifact, coverage, marker, or matrix policy exists.

## 4. CI/CD Test Gap Analysis

### Script: `scripts/test_backend_docker.sh`

- Coverage: one health endpoint test.
- Strength: isolated from production/staging; no DB dependency.
- Gap: no explicit compose project name; can share default Compose project names with local runs.
- Gap: does not validate imports, route registration, auth, DB, migrations, C01-C19 coverage, or full backend collection.
- Classification: Working smoke test; not a CI suite.

### Script: `scripts/test_backend_db_docker.sh`

- Coverage: selected schema, config, security, auth, owner bootstrap, registry, jobs, artifacts/reviews/errors, memory/operation logs, foundation demo, n8n bridge, and Alembic upgrade/downgrade/check.
- Strength: uses explicit project `barong-ops-console-f12-test`, example DB, and cleanup with `down --volumes --remove-orphans`.
- Gap: does not run the full backend suite.
- Gap: Alembic upgrade happens after the initial non-DB pytest group; this is valid for current selected tests but fragile as tests evolve.
- Gap: no pytest markers separate unit/integration/system.
- Gap: no parallel isolation; all tests share one DB and cleanup strategy.
- Classification: Partial integration suite.

### Script: `scripts/test_frontend_docker.sh`

- Coverage: frontend image build only.
- Strength: Dockerfile runs `npm ci`, `npm run verify`, `npm run typecheck`, and `npm run build`.
- Gap: does not run `node --test tests/frontend/*.test.mjs`.
- Gap: `npm run verify` checks existence and static source constraints, not behavior of every frontend test.
- Gap: no browser/system test layer.
- Classification: Partial build/verification gate.

### Script: `scripts/test_foundation_acceptance.sh`

- Coverage: chains smoke DB/build scripts, Compose config validation, `git diff --check`, dependency file cleanliness, and safety scans for public registration, external SDKs, URLs, secrets, console output, protected paths, host dependency directories, and unexpected Compose files.
- Strength: valuable static release gate.
- Gap: assumes manual invocation; no CI runner.
- Gap: `git diff --quiet` on dependency/migration files can fail unrelated local work and is not a stable CI test boundary unless CI checkout state is clean.
- Gap: does not execute full C01-C19 test matrix.
- Gap: no test isolation beyond what the called scripts implement.
- Classification: Partial acceptance gate.

### C01-C19 Coverage Summary

| Capability range | Tests exist? | Covered by current scripts? | Gap |
| --- | --- | --- | --- |
| C01-C02 deployment/env isolation | Docs and scripts exist | Static acceptance only | No automated CI workflow |
| C03-C04 owner/users/roles | Backend tests exist | Partially via DB script | Roles tests not consistently included |
| C05-C06 permissions | Backend/frontend tests exist | Mostly not in current scripts | Permission assignment and frontend tests omitted |
| C07-C09 module/adapter/provider | Backend/frontend tests exist | Mostly static existence/build only | Node tests and backend suites omitted |
| C10 sandbox | Backend tests exist | Not in scripts | No sandbox unit/integration lane |
| C12 approval | Backend tests exist | Not in scripts | Approval persistence/API not in standard suite |
| C13 module switch/flow gate | Backend tests exist | Not in scripts | Gate tests omitted |
| C14 dependency/model/capability | Backend/frontend tests exist | Not in scripts | Contract tests omitted |
| C15 callback/workflow/payload/result/security | Backend/frontend tests exist | Not fully in scripts | Callback and normalization tests omitted |
| C16 control-plane/security | Backend/frontend tests exist | Not in scripts | Control-plane regression omitted |
| C17 audit/storage/trace/anomaly | Backend tests exist | Partially via memory logs | Audit/trace/anomaly suites omitted |
| C18 org lifecycle/visibility/isolation | Backend tests exist | Not in scripts | Multi-tenant integration omitted |
| C19 contact/conversation/message/attachment | Backend tests exist | Not in scripts | Messaging/contact integration omitted |

## 5. Test Architecture Design

### Unit Tests

Purpose: fast, deterministic service/schema/pure logic validation without DB or network.

Standard:

- Location: `tests/backend/unit`, `tests/frontend/unit`.
- Backend target: schemas, validators, policy engines, pure service functions, sandbox request validation, permission calculations, route allowlist helpers where no DB is needed.
- Frontend target: permission state helpers, module visibility helpers, proxy allowlist helpers, normalization functions, path builders.
- No `SessionLocal`, no `TestClient`, no Alembic, no real environment files.
- Required marker: `@pytest.mark.unit` for backend; `npm run test:unit` for frontend.

### Integration Tests

Purpose: validate API + DB + migration contracts in an isolated test database.

Standard:

- Location: `tests/backend/integration`.
- Backend target: FastAPI `TestClient`, auth flows, users, permissions, registry APIs, jobs, artifacts, reviews, memory, n8n test bridge, approvals, callback handler, C18/C19 flows.
- DB setup: create isolated test DB/schema, run `alembic upgrade head`, run tests, rollback/truncate, destroy DB/schema.
- Tests must not call `Base.metadata.create_all` as a substitute for migrations except for narrow metadata-only unit tests.
- Required marker: `@pytest.mark.integration`.

### System Tests

Purpose: validate full stack behavior through Docker Compose.

Standard:

- Location: `tests/system` or `scripts/test_system_docker.sh`.
- Stack: example/test Compose project only, unique project name, ephemeral DB volume, backend, frontend.
- Coverage: health, login, owner-only pages, frontend proxy, key C18/C19 user workflows, and safe n8n test bridge behavior.
- No production/staging containers, volumes, real env files, or real external providers.
- System tests should run after backend/frontend unit and integration lanes.

### Mock Isolation Layer

Purpose: keep C09/C10/external execution boundaries testable without real provider calls.

Standard:

- C09 provider mock: canonical no-op/mock provider registry fixture that asserts no live execution, no provider URL leakage, no credentials, and exact GET-only frontend proxy paths.
- C10 sandbox mock: canonical sandbox runtime fixture that validates request contracts, trust-zone boundaries, resource limits, and no direct runtime bypass.
- n8n test bridge mock: current mock-only dispatch pattern should be formalized as a shared fixture with assertions that `external_http_attempted` and `webhook_triggered` remain false unless explicitly running an approved test/demo webhook lane.
- External dependency mock: C14 provider/dependency tests should use a registry fixture rather than ad hoc test-local objects.

## 6. Environment Standardization Plan

### Dev

Python:

- Use Python `3.12.x`, aligned with `backend/Dockerfile` (`python:3.12.13-slim`).
- Create a local `.venv` only inside the repo root or another ignored workspace-local path.
- Split dependencies:
  - `backend/requirements.txt`: runtime only.
  - `backend/requirements-dev.txt`: `-r requirements.txt`, `pytest`, `httpx` if test-only, `pytest-cov`, optional lint/type tools, and migration/test utilities.
- Add a standard command such as `python -m pip install -r backend/requirements-dev.txt`.
- Never install into system Python.
- Add pytest config with markers: `unit`, `integration`, `db`, `system`, `slow`.

Frontend:

- Use Node `24.15.x` or the declared `>=24.0.0`.
- Use `npm ci` from `frontend`.
- Add package scripts:
  - `test`: run all frontend Node tests.
  - `test:unit`: run helper/proxy tests.
  - `verify`: keep current static verifier.
  - `typecheck`: keep current TypeScript check.

### Docker Test

- Add a dedicated test layer rather than using production runtime images for tests.
- Do not copy `tests/backend` or install `pytest` in the final backend runtime image.
- Add a backend test image/stage that installs dev requirements and copies tests.
- Add a frontend test command that runs `node --test /tests/frontend/*.test.mjs` before or alongside `verify/typecheck/build`.
- Add `docker-compose.test.yml` or a test profile with:
  - unique project naming,
  - ephemeral Postgres volume,
  - `DATABASE_URL` pointing only at the test DB service,
  - no production/staging env files,
  - no published ports unless system tests require them.

### Staging

- Staging tests should be smoke/acceptance tests against the staging stack, not destructive integration tests.
- Use staging-only owner/test accounts and staging-only secrets.
- Do not reset staging DB in test scripts.
- Run Alembic migrations as a controlled release step before staging acceptance.
- Staging test coverage should include health, login, selected owner-only API checks, frontend proxy, and no external-provider execution.

### Production Test

- Production tests must be read-only smoke checks only.
- No test account creation, no DB writes, no migration test cycles, no n8n webhook execution, no provider calls.
- Production smoke should validate health, security headers, docs disabled where expected, and public route behavior.

### DB Test Strategy

- Use Alembic as the source of truth for integration schemas.
- Before integration tests: create isolated DB/schema, run `alembic upgrade head`, assert `alembic current`.
- During tests: prefer per-test transaction rollback. If rollback is impractical with `TestClient`, use explicit ordered truncation via a shared fixture.
- After tests: drop isolated DB/schema or remove the Compose volume.
- Remove ad hoc `Base.metadata.create_all` from integration tests over time; keep it only in metadata-focused unit tests if needed.
- Make `DATABASE_URL` mandatory for integration tests; fail fast if it points at production/staging or the default example URL outside Docker.

## 7. Critical Issues (P0)

1. Cannot reliably run host `pytest`.
   - Root cause: no virtualenv standard, no `requirements-dev.txt`, no pytest config, and prior docs show missing host pytest/project dependencies.

2. Full backend DB test layer is broken as a repeatable system.
   - Root cause: DB setup is script-specific and partial; `conftest.py` assumes tables exist; tests mix Alembic, direct `create_all`, and shared deletion cleanup.

3. CI is absent.
   - Root cause: no workflow file, no dependency install job, no Postgres service, no standardized test commands.

4. Frontend tests are not executed by the standard Docker test script.
   - Root cause: no `npm test`; Docker build only runs `verify`, `typecheck`, and `build`.

5. Runtime and test environments are mixed.
   - Root cause: backend runtime requirements include pytest/test tooling, backend image copies tests, and there is no separate test image stage.

6. Current scripts do not cover C01-C19.
   - Root cause: scripts are foundation-era curated subsets and safety scans, not a complete test matrix.

## 8. Fix Strategy Plan

### Phase 1: Install and Manifest Fixes

- Create `backend/requirements-dev.txt` with `-r requirements.txt` plus test-only tools.
- Move test-only packages out of runtime requirements where safe:
  - keep runtime packages required by the app,
  - keep Alembic in runtime only if the deployment model runs migrations from the backend image,
  - keep `pytest` out of the runtime image.
- Add pytest config with test markers and default discovery.
- Add frontend `test` script for `node --test`.
- Add a top-level documented test command map.

### Phase 2: Environment Bootstrap

- Add local backend bootstrap:
  - create `.venv`,
  - install dev requirements,
  - require explicit `DATABASE_URL` for integration tests.
- Add Docker backend test stage:
  - install dev requirements,
  - run unit tests without DB,
  - run integration tests after Alembic upgrade against test Postgres.
- Add frontend test stage:
  - `npm ci`,
  - `npm run test`,
  - `npm run verify`,
  - `npm run typecheck`,
  - `npm run build`.

### Phase 3: DB and Fixture Correction

- Introduce a single integration DB fixture that owns:
  - migrated schema,
  - cleanup order,
  - transaction/rollback or truncation strategy,
  - safety checks preventing production/staging URLs.
- Replace test-local `Base.metadata.create_all` integration setup with Alembic-backed setup.
- Split `conftest.py` into unit-safe and integration-only fixtures so pure tests do not import DB-heavy app setup unnecessarily.

### Phase 4: CI Pipeline Correction

- Add CI jobs:
  - backend unit: install dev requirements, run `pytest -m unit`.
  - backend integration: start Postgres service, run Alembic, run `pytest -m integration`.
  - frontend unit: `npm ci`, `npm run test`.
  - frontend build: `npm run verify`, `npm run typecheck`, `npm run build`.
  - system Docker: run full test Compose stack for smoke/system flows.
- Store logs and coverage artifacts.
- Make CI fail on missing markers for new tests.

### Phase 5: C01-C19 Coverage Completion

- Map every C01-C19 capability to at least one unit/integration/system test.
- Ensure C18 and C19 flows run in integration lane with DB isolation.
- Ensure C09 provider and C10 sandbox mocks are canonical fixtures.
- Keep `scripts/test_foundation_acceptance.sh` as a safety gate, but stop treating it as full test coverage.

### Target End State

The system should have three repeatable commands:

- Local fast path: backend unit tests + frontend unit tests, no DB.
- Local/Docker integration path: backend API + DB with Alembic and isolated Postgres.
- CI full path: backend unit, backend integration, frontend tests/build, and system smoke against an ephemeral full stack.

This makes PRE20-L's goal concrete: the project becomes repeatable, verifiable, and automatable without relying on manual host state or hidden staging/production assumptions.
