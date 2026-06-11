# K05B Migration Isolated Test Report

Status: K05B isolated Docker migration test completed.

Date: 2026-06-11.

## 1. K05B Goal

K05B tests the K Product Knowledge migration only inside an isolated Docker
Compose test project.

This run did not touch staging, production, live services, backend runtime,
frontend runtime, tests, Docker configuration, staging configuration, or
production configuration.

## 2. Test Environment

- Worktree path: `/opt/barong-ops-console-worktrees/k-series-product-knowledge`
- Branch: `feature/k-series-product-knowledge`
- HEAD commit: `ed28170faf9aa836a4055fa4c6a9c90e9f298065`
- Docker compose file used: `docker-compose.example.yml`
- Docker project name: `barong-k-series-product-knowledge-test`
- Docker services used: `db`, one-off `backend` containers
- Staging/prod env read: no
- Env files read: no
- Live services connected: no
- Staging/production run: no

## 3. Alembic Safety

Heads command used:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm --no-deps backend python -m alembic -c backend/alembic.ini heads
```

Heads result:

```text
k05a_product_knowledge_001 (head)
```

Additional Alembic verification commands:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm --no-deps backend python -m alembic -c backend/alembic.ini show k05a_product_knowledge_001
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm --no-deps backend python -m alembic -c backend/alembic.ini history --verbose
```

Observed revision chain:

```text
f07_core_001 -> c05b_permissions_001 -> k05a_product_knowledge_001 (head)
```

Observations:

- Multiple heads exist: no
- K migration revision appears in heads: yes
- K migration appears in the upgrade path: yes
- `down_revision = c05b_permissions_001`: yes
- `c05b_permissions_001` is still resolvable in this branch: yes
- C series migration changes could require future rebase: yes
- Passing K05B in this branch does not remove the future merge-time head
  revalidation requirement.

## 4. Upgrade Result

Pre-upgrade current command:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini current
```

Pre-upgrade current result: no applied revision reported in the isolated empty
test DB.

Upgrade command used:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini upgrade head
```

Upgrade result: passed.

Observed upgrade path:

```text
Running upgrade  -> f07_core_001, create core foundation tables
Running upgrade f07_core_001 -> c05b_permissions_001, create permission tables
Running upgrade c05b_permissions_001 -> k05a_product_knowledge_001, create K series product knowledge tables
```

Post-upgrade current result:

```text
k05a_product_knowledge_001 (head)
```

Errors: none.

## 5. K Table Verification

Verification method:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml exec -T db psql -U barong_console_example -d barong_console_example -c "<information_schema table check>"
```

| Table name | Found | Verification method |
| --- | --- | --- |
| `k_product_knowledge_products` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_attributes` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_translations` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_keywords` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_risk_terms` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_research_runs` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_ai_events` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_versions` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_media_assets` | yes | `information_schema.tables` in isolated test DB |
| `k_product_knowledge_review_items` | yes | `information_schema.tables` in isolated test DB |

## 6. Core Table Safety

Static scan target:

```text
backend/alembic/versions/20260611_01_k_series_product_knowledge_tables.py
```

Static scan command:

```sh
rg -n "op\.(alter_table|batch_alter_table|add_column|drop_column|drop_constraint|create_foreign_key|drop_table|create_table|create_index|drop_index|execute)" backend/alembic/versions/20260611_01_k_series_product_knowledge_tables.py
```

Static review result:

- Migration includes `op.alter_table`: no
- Migration includes `op.batch_alter_table`: no
- Migration includes `op.add_column` or `op.drop_column`: no
- Migration drops non-K tables: no
- Downgrade drops tables: yes, K table constants only
- Migration modifies `operation_logs`: no
- Migration modifies `users`, `roles`, `permissions`, `organizations`, or formal
  scope tables: no
- Migration creates FK to formal scope table: no
- Migration creates FK to core users table: no
- K migration FK targets are K-only: product self-reference, K child tables to
  `k_product_knowledge_products`, and K AI events to
  `k_product_knowledge_research_runs`.

The isolated DB upgrade necessarily applied existing base and C05B migrations
before K05A. Non-K safety for K05A was confirmed by static migration review,
not by attributing every resulting non-K table in the empty test DB to K05A.

## 7. Downgrade / Cleanup

Downgrade was run: yes.

Downgrade command:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini downgrade c05b_permissions_001
```

Downgrade result: passed.

Post-downgrade current result:

```text
c05b_permissions_001
```

Post-downgrade K table verification: all 10 K tables were absent in the
isolated test DB.

Final re-upgrade command:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini upgrade head
```

Final re-upgrade result: passed.

Final current result:

```text
k05a_product_knowledge_001 (head)
```

Final K table verification: all 10 K tables were present again.

Cleanup command:

```sh
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml down -v
```

Cleanup result:

```text
Stopping barong-k-series-product-knowledge-test_db_1 ... done
Removing barong-k-series-product-knowledge-test_db_1 ... done
Removing network barong-k-series-product-knowledge-test_default
```

Final isolated project `ps` result:

```text
Name   Command   State   Ports
------------------------------
```

## 8. Boundary Confirmation

- Modified backend runtime: no
- Modified frontend runtime: no
- Modified tests: no
- Created new migration: no
- Modified existing migration: no
- Modified Docker/staging/production configuration: no
- Ran staging/production: no
- Read env: no
- Read `.env.production`: no
- Read `.env.staging`: no
- Connected live services: no
- Used default Docker Compose project name: no
- Used independent Docker project: yes,
  `barong-k-series-product-knowledge-test`
- Committed changes: no

## 9. K05C / Next Step Recommendation

K05B passed in the isolated Docker test project, but this does not permit
staging or production execution.

Next step should remain non-live and owner-approved. Reasonable next steps are:

- K06 backend CRUD API skeleton planning, or
- K05C model/API planning only.

Before merging to latest C main, before any real Alembic run, or before any
staging/production consideration, Alembic heads and `down_revision` must be
revalidated again.

## 10. Final Git Checks

Final command:

```sh
git diff --name-only
```

Result: no tracked file diff output. The new report is untracked until owner
approval to stage/commit.

Final command:

```sh
git diff --check
```

Result: passed with no output.

Final command:

```sh
git status --short --untracked-files=all
```

Result:

```text
?? docs/k_series/K05B_MIGRATION_ISOLATED_TEST_REPORT.md
```

Files created or modified:

- `docs/k_series/K05B_MIGRATION_ISOLATED_TEST_REPORT.md`

Modified files outside allowed paths: no.

Can commit: yes, after owner approval only.

Suggested commit message:

```text
docs: add K05B isolated migration test report
```
