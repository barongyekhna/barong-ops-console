# PRE20-M Operations Closure Report

Audit date: 2026-06-17

Mode: static repository and documentation audit only. No deployment, production
runtime, staging runtime, migration, test execution, CI/CD change, Docker
change, or code fix was executed.

Scope covered:

- `docs/`
- `scripts/`
- `docker-compose.example.yml`
- `docker-compose.staging.yml`
- `docker-compose.production.yml`
- `backend/app/`
- `frontend/`
- `backend/alembic/versions/`
- CI/CD assumptions from repository structure and PRE20-L
- PRE20-A through PRE20-L output documents

Operational closure verdict: not closed for real production operations and
disaster recovery. The C01-C08 console foundation has meaningful deployment and
smoke-check discipline, but rollback, migration promotion, backup/restore, DR,
incident response, and C18/C19 recovery are incomplete.

### 1. Deployment Readiness Matrix

| Capability | Status | Evidence | Operational conclusion |
| --- | --- | --- | --- |
| Standard deployment flow | Partial | `docs/OPS01_SAFE_RELEASE_RUNBOOK.md`, `scripts/safe_compose_release.sh` | Backend/frontend deployment has a guarded script path with dry-run, pre/post smoke, explicit project/compose mapping, and confirmation gates. It does not cover migrations, Postgres, Nginx, certbot, workers, queues, external providers, or C18/C19 runtime state. |
| Staging to production flow | Partial | `docs/C02_DUAL_ENV_OPERATIONS.md`, C03-C08 production release docs | The principle is documented: same commit, staging first, owner approval, production release, production smoke, rollback awareness. Enforcement is manual and not bound to CI/CD or a release manifest. |
| Environment isolation | Strong for C01-C08 foundation | `docker-compose.staging.yml`, `docker-compose.production.yml`, `scripts/check_dual_env_status.sh` | Staging and production use separate projects, ports, networks, volumes, and env files. Postgres is internal-only in both Compose files. |
| Static deploy file validation | Partial | `scripts/check_staging_deploy_files.sh`, `scripts/check_production_deploy_files.sh` | Scripts validate required files, env ignore rules, compose config, names, ports, and selected safety invariants. Production static check is much narrower than staging and does not validate later C15/C16/C18/C19 operational requirements. |
| Release artifact discipline | Weak | Compose builds local images directly from the repository | No image registry promotion, immutable artifact manifest, signed release metadata, commit-to-image attestation, or artifact retention policy was found. |
| Migration promotion | Failing | `scripts/safe_compose_release.sh` releases backend/frontend only; C05 used manual Alembic; PRE20-G records stale production Alembic evidence after C08 | There is no generalized staging/prod migration gate. Later migrations exist, but production application evidence is missing after C08. |
| Database schema deployability | Failing for C18/C19 | PRE20-A/B/E/G; `backend/alembic/versions/` | `organizations`, `org_memberships`, `contact_identities`, `messages`, conversations, friend requests, attachments, module bindings, callback store, DLQ, and C17 durable observability tables are not fully covered by managed migrations. |
| Backend runtime topology | Partial | `backend/Dockerfile`, `docker-compose.*.yml` | Backend starts a single Uvicorn app. No worker, scheduler, queue, migration runner, sandbox executor, callback worker, or alerting service is defined. |
| Frontend deployment | Partial | `frontend/Dockerfile`, `frontend/src/app/api/backend/[...path]/route.ts`, PRE20-H | The frontend image runs verify/typecheck/build during image build. The proxy allowlist exposes only selected paths and does not expose C18/C19 tenant/contact/messaging/attachment workflows or operator observability surfaces. |
| CI/CD automation | Failing | PRE20-L; repository has no CI workflow files | Build/test/deploy/promotion are manual scripts and documents. No GitHub Actions/GitLab/Jenkins/Circle/Azure pipeline was found. |
| C01-C08 production release evidence | Partial to strong | C01-C08 docs and OPS01 docs | Production release evidence exists for foundation, env isolation, users, roles, permissions, module registry, and read-only adapter contracts. |
| C09-C19 production release evidence | Failing | PRE20-G | C09 is staging/production-independent no-execute; most C10-C19 features are no deploy path, local/mock only, memory-only, or schema-only. |

Deployment readiness summary:

- Ready for guarded manual backend/frontend releases of the existing C01-C08
  console foundation.
- Not ready for automated production release.
- Not ready for migration-bearing releases without a separate approved manual
  migration task.
- Not ready for C18/C19 production operations.
- Not ready for C20 entry as an operationally closed system.

---

### 2. Rollback Capability Report

| Rollback type | Status | Evidence | Gap |
| --- | --- | --- | --- |
| One-click service rollback | Missing | `scripts/safe_compose_release.sh` creates rollback tags but has no rollback command | There is no script that retags the rollback image, recreates the service from it, waits for health, and runs post-rollback smoke. |
| Backend/frontend image rollback reference | Partial | OPS01 docs and C05-C08 release docs record rollback tags | Tags identify the prior image, but they are recovery references, not an executed or automated rollback path. |
| Automatic rollback on failed deploy | Missing | `safe_compose_release.sh` fails after health/smoke failure | The script does not restore the previous image/container automatically after failed health or smoke. Operator must decide a new task. |
| DB rollback | Missing | No production DB rollback runbook found | No production procedure ties backup, migration downgrade, application image rollback, smoke, and data validation together. |
| Alembic schema downgrade | Partial in code/test only | Alembic versions define `downgrade()`; `scripts/test_backend_db_docker.sh` downgrades example DB to base | Downgrade is tested in an example stack, but not documented as a production-safe rollback path. Destructive downgrades could drop tables/data. |
| Migration rollback before production release | Missing | `safe_compose_release.sh` does not run Alembic | No pre-migration backup, migration dry-run, migration lock, production restore point, or post-migration validation gate exists. |
| Image rollback for Postgres | Not applicable / missing | Postgres target is explicitly forbidden by safe release | This is good for deploy safety, but no database engine version rollback plan is documented. |
| Nginx/cert rollback | Minimal | `docs/C01_PRODUCTION_DEPLOYMENT.md` says revert vhost and reload after `nginx -t` | No current Nginx backup path was reliably confirmed in C01 acceptance. Cert renewal/rollback playbook is absent. |
| C18/C19 memory-state rollback | Missing | PRE20-C/G/K identify process-memory C18/C19 state | Memory-only module bindings, conversations, friend requests, callback/DLQ, and non-durable observability cannot be rolled back or recovered after restart/worker switch. |

Rollback conclusion:

- The project has release-time rollback tagging for backend/frontend images.
- It does not have a safe operational rollback mechanism.
- It does not have DB rollback or production migration rollback closure.
- It cannot rollback C18/C19 process-memory state because that state is not
  durable.

---

### 3. Smoke Test Coverage Map

| Smoke target | Current coverage | Evidence | Result |
| --- | --- | --- | --- |
| Frontend availability | Covered narrowly | `scripts/production_smoke_check.sh` checks `/login`; `scripts/staging_smoke_check.sh` checks staging `/login` | Verifies frontend route availability, not authenticated console workflows. |
| Backend API health | Covered narrowly | Production checks `/api/backend/health`; staging checks frontend proxy health and direct backend `/health` | Verifies backend process/proxy reachability. |
| Backend service identity/env | Partially covered | Smoke checks `"status":"ok"` and service name; dual-env check validates expected env | Good for environment confusion detection. |
| DB container health | Covered at container level | Smoke and dual-env scripts check Docker status and Postgres internal port exposure | Confirms container health, not application DB queryability. |
| Backend DB connectivity | Not covered | `backend/app/api/routes/health.py` returns `database="not_configured"` | A green health check does not prove SQLAlchemy can connect, run a query, or see migrated schema. |
| Auth health check | Partial | `/login` returns 200; historical release docs include selected unauthenticated 401 and owner checks | The standard smoke scripts do not perform login, session validation, `/auth/me`, permission resolution, or authenticated API smoke. |
| API route smoke beyond health | Weak | C03-C08 release docs have manual/read-only checks; standard smoke scripts do not cover feature APIs | C12/C17/C18/C19 API availability is not verified by production smoke. |
| Frontend proxy allowlist | Partial | Proxy allows selected C01-C17-ish paths; PRE20-H/G document gaps | C18/C19, approval console, operation logs, audit query, trace, replay, anomaly, callback/failure workflows are not covered. |
| C18 basic access validation | Missing | PRE20-E/G/J | No production smoke for org lifecycle, membership, visibility, org context, or data isolation. Required migrations and UI/proxy paths are incomplete. |
| C19 basic access validation | Missing | PRE20-C/E/G/K | No production smoke for contacts, conversations, messages, friends, or attachments. Several routes are memory-only, fake-envelope, missing migration, or 501 schema-only. |
| Security headers/docs disabled | Not in standard smoke | PRE20-L recommends adding this | Production smoke does not verify security headers, docs disabled, OpenAPI disabled, or firewall behavior. |
| External providers/n8n | Intentionally not covered as live | C01/C02/OPS01 docs; PRE20-C/E/G | Current system intentionally does not execute real n8n/provider workflows. |

Smoke-test conclusion:

- Current smoke tests are valuable process/proxy/container checks.
- They are insufficient as production health verification.
- The largest verification gap is that `/health` does not test DB connectivity
  or schema readiness.
- Production health cannot be trusted for C18/C19 or migration-bearing releases.

---

### 4. Runbook Completeness Review

| Runbook area | Status | Evidence | Operational gap |
| --- | --- | --- | --- |
| Initial production deployment | Partial | `docs/C01_PRODUCTION_DEPLOYMENT.md` | Covers env creation, first migration, owner bootstrap, Nginx, HTTPS, login acceptance, and basic rollback notes. It is initial-deploy oriented and predates OPS01 safe release. |
| Dual environment operations | Strong for boundaries | `docs/C02_DUAL_ENV_OPERATIONS.md`, `docs/C02_STAGING_SETUP.md` | Clear production/staging separation rules, safe read-only commands, and prohibited commands. |
| Backend/frontend safe release | Partial to strong | `docs/OPS01_SAFE_RELEASE_RUNBOOK.md`, `docs/OPS01_SAFE_RELEASE_SEAL.md` | Strong guardrails for backend/frontend container replacement. No built-in rollback execution, migrations, DB backup, or failed-release recovery beyond script failure. |
| Common deployment failure | Partial | OPS01 documents Compose v1 `ContainerConfig` avoidance | Specific Compose v1 issue is covered. General failure modes such as build failure, health timeout, smoke failure, bad env, bad migration, and bad frontend proxy allowlist are not fully playbooked. |
| Dependency recovery | Missing | No Postgres restore/Nginx cert/host recovery runbook found | No documented recovery for Postgres volume loss, DB corruption, certificate expiry, Nginx outage, disk full, Docker daemon failure, or server replacement. |
| Worker crash recovery | Not implemented / not documented | Compose defines no workers | No worker services exist. This avoids worker restart playbooks now, but callback/DLQ/C17/C18/C19 memory state still behaves like worker-local state without recovery. |
| Memory-state recovery | Missing | PRE20-C/G/J/K identify process-memory stores | No runbook can recover C13 kill switch, C15 callback/DLQ, C17 in-memory events/storage/anomaly, C18 module/shared bindings, C19 conversations/friends after restart. |
| Deployment failure recovery | Incomplete | `safe_compose_release.sh` has health wait and smoke checks | Failed health/smoke stops the script, but there is no automated restore, rollback command, or documented decision tree. |
| Migration failure recovery | Missing | C05 manual Alembic history; PRE20-G migration gap | No standard pre-backup, lock, downgrade/restore, current/head verification, or application compatibility matrix. |
| Incident playbook | Missing | C17 docs are design/implementation docs, not incident runbooks | No severity levels, ownership, escalation path, triage workflow, communications template, or postmortem template found. |
| Operations playbook | Partial | C02 safe read-only commands and OPS01 safe release docs | Good for "how not to break prod"; incomplete for "how to recover prod." |

Runbook conclusion:

- Deployment guardrails are documented.
- Operational recovery playbooks are not complete.
- The docs currently prevent unsafe actions better than they enable reliable
  restoration after a real incident.

---

### 5. Backup & Recovery Assessment

| Recovery area | Status | Evidence | Risk |
| --- | --- | --- | --- |
| Postgres backup strategy | Missing | No `pg_dump`, `pg_restore`, WAL archive, backup script, retention policy, or backup schedule found | Production data cannot be recovered from repository-defined operations. |
| Point-in-time recovery | Missing | No PITR/WAL/archive/RPO/RTO evidence found | Cannot recover to a pre-incident point after bad migration, accidental write, or corruption. |
| Restore drill | Missing | No restore rehearsal document or script found | Backup usability is unknown because no backup mechanism is defined. |
| Migration restore | Missing | Alembic downgrade exists in migrations and example tests only | No production-safe migration restore procedure. Downgrade may destroy data and is not paired with backups. |
| Postgres volume recovery | Missing | Compose uses named volumes `console_postgres_data` and `console_staging_postgres_data` | No documented snapshot, off-host copy, restore target, or volume replacement process. |
| Env/secret recovery | Missing / local only | C01/C02 say real env files stay server-local and must not be printed | Good secrecy boundary, but no documented escrow, rotation, or disaster recovery process for lost env/secrets. |
| Operation log recovery | Depends on Postgres backup, which is missing | `operation_logs` table is DB-backed | Operation logs survive process restart only if DB survives; no DB backup means audit history recovery is not closed. |
| C17 observability recovery | Failing | PRE20-C/E/G/K | Event collector, storage adapter, audit query, replay, and anomaly paths are mostly process-memory or schema/test utilities. Restart loses non-durable observability state. |
| C18 state recovery | Failing | PRE20-C/E/G/J/K | Module bindings/shared modules are process-memory; org/membership migrations are incomplete. |
| C19 state recovery | Failing | PRE20-C/E/G/K | Conversations/friends are memory-only; message send is not persisted; history/read/attachments are 501; key migrations are missing. |
| Disaster recovery strategy | Missing | No DR runbook, no RPO/RTO, no cold/warm standby, no rebuild-from-backup procedure | Full system recovery after server loss is not defined. |

Backup and recovery conclusion:

- Backup/restore is the largest operational gap.
- The system cannot claim disaster recovery readiness.
- Current recovery posture is "keep the Postgres volume and avoid touching it,"
  not a real backup/restore strategy.

---

### 6. Incident Response Readiness

| Incident-response capability | Status | Evidence | Assessment |
| --- | --- | --- | --- |
| Logging availability | Partial | Python/Uvicorn logs, `barong.audit_events` logger, DB-backed `operation_logs` | Basic logs and operation logs exist. C17 event stream is in-memory/logging-only and can drop events. |
| Request trace headers | Partial | `backend/app/middleware/event_collector.py` sets request/trace headers | Useful for debugging single requests, but not connected to durable trace search. |
| C17 observability usability | Weak | PRE20-E/G/K; C17H is dashboard design only | Structured logs, traces, storage, audit query, replay, anomaly are not complete durable production tools. |
| Operation-log access for operators | Partial | Backend API exists at `/api/app/operation-logs/*` | API is DB-backed, but PRE20-G/H note no clear production frontend/proxy operator workflow. |
| Alerting existence | Missing | C17G anomaly detection has schema/service concepts, not production alert delivery | No alert sink, notification channel, on-call policy, acknowledgement, suppression, or escalation workflow found. |
| Debugging workflow | Partial | C02 read-only checks, smoke scripts, dual-env check | Good first checks for frontend/backend/Postgres container reachability. Does not cover DB query health, migrations, tenant/IM state, callback/DLQ, or external provider issues. |
| Error triage | Partial | `/errors` page/API exists for foundation records | Error records are foundation/demo-era and not a complete incident system. |
| Security incident response | Weak | Security headers, firewall routes, replay/rate-limit tables exist | Technical controls exist, but no breach/credential rotation/session revocation playbook was found. |
| Deployment incident response | Partial | OPS01 safe release guardrails | Deploy failures stop, but rollback and migration recovery require manual new tasks. |
| Data incident response | Missing | No backup/restore/PITR | Accidental data loss, bad writes, or DB corruption cannot be confidently recovered. |

Incident-readiness conclusion:

- Operators can run basic smoke/status checks.
- Operators cannot rely on C17 for complete incident reconstruction.
- There is no production alerting or incident playbook.
- Data incidents are not recoverable from documented procedures.

---

### 7. Critical Operational Gaps (P0)

| ID | P0 gap | Why it matters |
| --- | --- | --- |
| P0-M-01 | Cannot recover system from data loss | No Postgres backup, restore, PITR, RPO/RTO, or restore drill exists. A lost/corrupt `console_postgres_data` volume is not recoverable from documented operations. |
| P0-M-02 | Cannot rollback safely after migration-bearing release | Backend/frontend safe release does not run or rollback Alembic. Later migrations have no generalized production promotion path, and C18/C19 migrations are incomplete. |
| P0-M-03 | Cannot verify production health deeply enough | Smoke checks verify `/login`, `/health`, Docker status, and ports, but backend health reports `database="not_configured"` and no standard production smoke validates DB queryability, authenticated auth/session flows, permissions, C18, or C19. |
| P0-M-04 | Rollback tag is not rollback | OPS01 rollback tags are references only. No rollback command, automatic failed-release recovery, or tested production rollback procedure exists. |
| P0-M-05 | C18/C19 state cannot survive restart or multi-worker routing | Module bindings, shared modules, conversations, friend requests, callback/DLQ-like state, and C17 memory-backed observability can disappear or diverge. There is no recovery strategy. |
| P0-M-06 | C18/C19 production access cannot be operationally validated | Frontend navigation/proxy does not expose the full tenant/contact/messaging/attachment surface, and backend persistence/migrations are incomplete. |
| P0-M-07 | Incident response lacks alerting and durable observability | Operation logs exist, but C17 event/trace/storage/replay/anomaly paths are not durable production systems and no alert pipeline exists. |
| P0-M-08 | CI/CD does not enforce release readiness | There is no CI pipeline binding tests, image build, migration checks, smoke, staging acceptance, production approval, and rollback metadata. |
| P0-M-09 | DR strategy is absent | No server rebuild plan, backup restore plan, secret recovery plan, standby plan, RPO/RTO, or DR exercise exists. |

P0 conclusion:

- The system can be manually deployed and smoke-checked at the C01-C08
  foundation level.
- It cannot yet be considered production-operable in the sense of safe rollback,
  disaster recovery, durable incident response, or C18/C19 runtime recovery.

---

### 8. Operational Maturity Score

Scoring basis: repository evidence only. Scores measure production operations
capability, not code correctness or feature ambition.

| Dimension | Score | Rationale |
| --- | ---: | --- |
| Deployment readiness | 55% | Strong manual backend/frontend safe release guardrails and environment isolation; weak CI/CD, artifact promotion, migration automation, and C09-C19 release evidence. |
| Rollback readiness | 20% | Rollback image tags exist, but no one-click rollback, no automatic failed-release rollback, no DB rollback, no migration rollback runbook, and no C18/C19 memory-state rollback. |
| Observability readiness | 35% | DB-backed operation logs and request/event logging exist; C17 durable logs/traces/replay/anomaly/dashboard/alerting are incomplete or memory-backed. |
| Recovery readiness | 10% | No documented Postgres backup/restore/PITR/DR strategy. Memory-state recovery is impossible for current C15/C17/C18/C19 process-local stores. |

Overall operational maturity: 30%.

Final assessment:

- Deployment closure: partial.
- Rollback closure: not closed.
- Smoke-test closure: partial, too shallow for production health.
- Runbook closure: partial for deployment, not closed for incidents/recovery.
- Backup/recovery closure: not closed.
- DR closure: not closed.
- C18/C19 operational closure: not closed.

PRE20-M conclusion: barong-ops-console does not yet have complete real
production operations and disaster recovery capability. The required closure
work is operational architecture, not a small code fix: backup/restore, migration
release control, real rollback, durable observability, alerting, CI/CD gates, and
C18/C19 persistence/recovery must be designed and exercised before the system can
be treated as production-operable beyond the current C01-C08 console foundation.
