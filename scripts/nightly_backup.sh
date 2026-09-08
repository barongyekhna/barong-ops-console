#!/usr/bin/env bash
# 每日在线备份（不停任何服务），由 systemd timer 调用，也可手动跑。
#
# 备份内容（本机 backups/nightly/）：
#   daily/<日期>/    主库 + C19 记录库 + C19 文件库 的 pg_dump 自定义格式（-Fc -Z9）
#                    n8n 的 SQLite 在线快照（sqlite3 backup API，不锁库）+ n8n 配置(含加密密钥)
#                    配置打包并加密（.env.*、nginx 站点、备份密钥）
#   mirror/          聊天文件目录、产品媒体(K/I/F)、n8n 二进制目录 的 rsync 镜像（文件本身不可变）
# 保留：日备 7 份、周备(周日) 4 份、月备(每月 1 号) 3 份。
# 异地：daily 当天目录整份 gpg 加密后 rsync 到洛杉矶 VPN 机，那边只留 3 天。
# 心跳：成功后 upsert worker_heartbeats(nightly-backup)，超过 26 小时没成功，
#       控制台主页站点健康卡和 scripts/check_worker_heartbeats.py 都会亮红。
set -euo pipefail
export LC_ALL=C.UTF-8

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

BACKUP_ROOT="${BARONG_NIGHTLY_ROOT:-$repo_root/backups/nightly}"
PASSPHRASE_FILE="${BARONG_BACKUP_PASSPHRASE_FILE:-/root/.barong-backup-passphrase}"
OFFSITE_HOST="${BARONG_OFFSITE_HOST:-root@45.76.173.147}"
OFFSITE_DIR="${BARONG_OFFSITE_DIR:-/var/backups/barong-nightly}"
OFFSITE_KEEP_DAYS="${BARONG_OFFSITE_KEEP_DAYS:-3}"
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=3

MAIN_PG="141ddd04b4d3_barong-ops-console_console_postgres_1"
RECORD_PG="c19-record_c19-record-postgres_1"
ASSET_PG="c19-asset_c19-asset-postgres_1"
N8N_DATA="/var/lib/docker/volumes/n8n_data/_data"
VOLUMES=/var/lib/docker/volumes

today="$(date -u +%Y-%m-%d)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
day_dir="$BACKUP_ROOT/daily/$today"
mirror_dir="$BACKUP_ROOT/mirror"
log_dir="$BACKUP_ROOT/logs"
mkdir -p "$day_dir" "$mirror_dir" "$log_dir" "$BACKUP_ROOT/weekly" "$BACKUP_ROOT/monthly"
chmod 700 "$BACKUP_ROOT" "$day_dir"
log="$log_dir/$today.log"
exec > >(tee -a "$log") 2>&1

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

heartbeat() {
    # $1 = ok|fail, $2 = error text
    local status="$1" error="${2:-}"
    local now; now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local sql
    if [[ "$status" == "ok" ]]; then
        sql="insert into worker_heartbeats (worker_name, module_key, last_success_at, last_attempt_at, consecutive_failures, last_error, expected_interval_seconds, updated_at)
             values ('nightly-backup', 'ops.backup', '$now', '$now', 0, null, 31200, '$now')
             on conflict (worker_name) do update set module_key='ops.backup', last_success_at=excluded.last_success_at, last_attempt_at=excluded.last_attempt_at, consecutive_failures=0, last_error=null, expected_interval_seconds=31200, updated_at=excluded.updated_at;"
    else
        error="${error//\'/\'\'}"
        sql="insert into worker_heartbeats (worker_name, module_key, last_attempt_at, consecutive_failures, last_error, expected_interval_seconds, updated_at)
             values ('nightly-backup', 'ops.backup', '$now', 1, '$error', 31200, '$now')
             on conflict (worker_name) do update set last_attempt_at=excluded.last_attempt_at, consecutive_failures=worker_heartbeats.consecutive_failures+1, last_error=excluded.last_error, updated_at=excluded.updated_at;"
    fi
    docker exec "$MAIN_PG" sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$0"' "$sql" || say "心跳写入失败（不影响备份文件）"
}

fail() {
    say "备份失败: $1"
    heartbeat fail "$1"
    exit 1
}
trap 'fail "第 $LINENO 行命令出错"' ERR

[[ -r "$PASSPHRASE_FILE" ]] || fail "缺少加密口令文件 $PASSPHRASE_FILE"

say "== 开始 $started_at → $day_dir"

# 1. 三个 PostgreSQL 库：在线 pg_dump，自定义格式，自带压缩。
dump_db() {
    local container="$1" out="$2"
    docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' > "$out.part"
    mv "$out.part" "$out"
    say "  $(basename "$out") $(du -h "$out" | cut -f1)"
}
say "1. 数据库"
dump_db "$MAIN_PG" "$day_dir/console.dump"
dump_db "$RECORD_PG" "$day_dir/c19-records.dump"
dump_db "$ASSET_PG" "$day_dir/c19-assets.dump"

# 2. n8n：SQLite 在线快照（backup API，一致且不锁写），外加配置（里面是加密密钥，丢了流程凭据全废）。
say "2. n8n"
python3 - "$N8N_DATA/database.sqlite" "$day_dir/n8n.sqlite.part" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst, pages=4096)
dst.close(); src.close()
PY
gzip -f "$day_dir/n8n.sqlite.part" && mv "$day_dir/n8n.sqlite.part.gz" "$day_dir/n8n.sqlite.gz"
cp -p "$N8N_DATA/config" "$day_dir/n8n.config"
chmod 600 "$day_dir/n8n.config"
say "  n8n.sqlite.gz $(du -h "$day_dir/n8n.sqlite.gz" | cut -f1)"

# 3. 配置：打包后对称加密，明文不落盘。
say "3. 配置"
config_paths=()
for candidate in \
    opt/barong-ops-console/.env.production \
    opt/barong-ops-console/.env.c19-asset.production \
    opt/barong-ops-console/.env.c19-record.production \
    opt/barong-ops-console/.env.staging \
    opt/barong-ops-console/backups/keys \
    etc/nginx/sites-available \
    etc/letsencrypt; do
    [[ -e "/$candidate" ]] && config_paths+=("$candidate")
done
tar -C / -czf - "${config_paths[@]}" \
    | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$PASSPHRASE_FILE" -o "$day_dir/config.tar.gz.gpg"
say "  config.tar.gz.gpg $(du -h "$day_dir/config.tar.gz.gpg" | cut -f1)"

# 4. 文件镜像：聊天文件、产品媒体、n8n 二进制。对象不可变，rsync 增量即可。
say "4. 文件镜像"
mirror() {
    local src="$1" name="$2"
    mkdir -p "$mirror_dir/$name"
    rsync -a --delete "$src/" "$mirror_dir/$name/"
    say "  $name $(du -sh "$mirror_dir/$name" | cut -f1)"
}
mirror "$VOLUMES/c19_asset_active_data/_data" c19-asset-active
mirror "$VOLUMES/console_k_media_data/_data" k-media
mirror "$VOLUMES/console_i_media_data/_data" i-media
mirror "$VOLUMES/console_f_media_data/_data" f-media
rsync -a --delete --exclude 'database.sqlite*' --exclude 'crash.journal' "$N8N_DATA/" "$mirror_dir/n8n-data/"
say "  n8n-data $(du -sh "$mirror_dir/n8n-data" | cut -f1)"

# 5. 清单 + 校验和
( cd "$day_dir" && sha256sum ./* > SHA256SUMS )
printf 'started_at=%s\nfinished_at=%s\nhost=%s\ngit_head=%s\n' "$started_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" > "$day_dir/MANIFEST"

# 6. 周备 / 月备（硬链接，不占双份空间）
if [[ "$(date -u +%u)" == "7" ]]; then
    rm -rf "$BACKUP_ROOT/weekly/$today"; cp -al "$day_dir" "$BACKUP_ROOT/weekly/$today"; say "5. 周备已留 $today"
fi
if [[ "$(date -u +%d)" == "01" ]]; then
    rm -rf "$BACKUP_ROOT/monthly/$today"; cp -al "$day_dir" "$BACKUP_ROOT/monthly/$today"; say "5. 月备已留 $today"
fi
prune_dir() {
    local dir="$1" keep="$2"
    local victims
    victims="$(find "$dir" -mindepth 1 -maxdepth 1 -type d -name '????-??-??' | sort | head -n -"$keep" || true)"
    [[ -z "$victims" ]] && return 0
    while read -r old; do
        [[ -z "$old" ]] && continue
        say "  过期删除 $old"; rm -rf "$old"
    done <<<"$victims"
}
prune_dir "$BACKUP_ROOT/daily" "$KEEP_DAILY"
prune_dir "$BACKUP_ROOT/weekly" "$KEEP_WEEKLY"
prune_dir "$BACKUP_ROOT/monthly" "$KEEP_MONTHLY"

# 7. 异地：整份 daily 目录先加密成一个包再传（那台机器只拿到密文），只留 N 天。
say "6. 异地 → $OFFSITE_HOST:$OFFSITE_DIR"
offsite_pkg="$BACKUP_ROOT/offsite-$today.tar.gpg"
tar -C "$BACKUP_ROOT/daily" -cf - "$today" | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$PASSPHRASE_FILE" -o "$offsite_pkg"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$OFFSITE_HOST" "mkdir -p '$OFFSITE_DIR' && chmod 700 '$OFFSITE_DIR'"
rsync -a --partial "$offsite_pkg" "$OFFSITE_HOST:$OFFSITE_DIR/"
remote_sha="$(ssh -o BatchMode=yes "$OFFSITE_HOST" "sha256sum '$OFFSITE_DIR/$(basename "$offsite_pkg")'" | cut -d' ' -f1)"
local_sha="$(sha256sum "$offsite_pkg" | cut -d' ' -f1)"
[[ "$remote_sha" == "$local_sha" ]] || fail "异地副本校验和不一致"
ssh -o BatchMode=yes "$OFFSITE_HOST" "ls -1 '$OFFSITE_DIR'/offsite-*.tar.gpg | sort | head -n -$OFFSITE_KEEP_DAYS | xargs -r rm -f; df -h / | tail -1"
rm -f "$offsite_pkg"
say "  异地副本 $(basename "$offsite_pkg") 校验一致"

say "== 完成 $(du -sh "$BACKUP_ROOT" | cut -f1) 本机占用"
heartbeat ok
