#!/usr/bin/env bash
# 带迁移的后端+前端发版:先用新镜像把库升到 head,再走安全发版脚本重建容器。
# 用法: scripts/release_backend_with_migration.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
COMPOSE=(docker-compose -p barong-ops-console -f docker-compose.production.yml)
echo "== 工作树状态"; git status --short
echo "== 构建后端镜像"
"${COMPOSE[@]}" build console_backend
echo "== 用新镜像升级数据库到 head"
"${COMPOSE[@]}" run --rm --no-deps -w /app/backend console_backend python -m alembic upgrade head
echo "== 发后端"
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes ./scripts/safe_compose_release.sh --env production --service backend --execute
echo "== 发前端"
CONFIRM_SAFE_RELEASE=yes CONFIRM_PRODUCTION_RELEASE=yes ./scripts/safe_compose_release.sh --env production --service frontend --execute
echo "== 完成"
