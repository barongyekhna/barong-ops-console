#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

tmp_dir="$(mktemp -d)"
database_url="${DATABASE_URL:-postgresql://barong_test:barong_test@127.0.0.1:5432/barong_test}"
expected_revision="${EXPECTED_SCHEMA_REVISION:-pre20_o_ops_dr_001}"

archive_list="$tmp_dir/pg_restore.list"
archive="$tmp_dir/barong_ops_simulated.dump"
metadata="${archive}.metadata"

cat >"$archive_list" <<'EOF'
1; 2615 2200 SCHEMA - public postgres
2; 1259 100 TABLE public alembic_version postgres
3; 1259 101 TABLE public users postgres
4; 1259 102 TABLE public auth_sessions postgres
5; 1259 103 TABLE public event_streams postgres
6; 1259 104 TABLE public anomaly_events postgres
7; 1259 105 TABLE public ops_alerts postgres
8; 1259 106 TABLE public ops_alert_deliveries postgres
EOF

cat >"$metadata" <<EOF
created_at=20260617T000000Z
app_version=0.1.0
alembic_revision=${expected_revision}
database_url=postgresql://[redacted]@127.0.0.1:5432/barong_test
format=pg_dump_custom
archive=${archive}
EOF

printf 'PRE20-O DR simulation: DB backup plan\n'
./scripts/pg_backup.sh \
    --dry-run \
    --database-url "$database_url" \
    --output-dir "$tmp_dir"

printf '\nPRE20-O DR simulation: backup restore validation\n'
./scripts/pg_restore_db.sh \
    --validate-only \
    --archive "$archive" \
    --archive-list "$archive_list" \
    --expected-revision "$expected_revision"

printf '\nPRE20-O DR simulation: application rollback plan\n'
./scripts/rollback_release.sh \
    --env production \
    --service backend \
    --image "barong-ops-console-prod_console_backend:rollback-simulated" \
    --expected-schema-revision "$expected_revision" \
    --dry-run

printf '\nPRE20-O DR simulation: DB rollback restore-latest plan\n'
./scripts/db_rollback.sh \
    --mode restore-latest \
    --backup-dir "$tmp_dir" \
    --database-url "$database_url" \
    --expected-revision "$expected_revision" \
    --dry-run

printf '\nPRE20-O DR simulation: Alembic downgrade rollback plan\n'
./scripts/db_rollback.sh \
    --mode alembic-downgrade \
    --revision head-1 \
    --database-url "$database_url" \
    --expected-revision "$expected_revision" \
    --dry-run

printf '\nPRE20-O DR simulation completed.\n'
