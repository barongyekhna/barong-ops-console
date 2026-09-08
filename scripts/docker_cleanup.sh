#!/usr/bin/env bash
# 宿主机 Docker 瘦身：只删「确认没人用」的东西，默认演习，--execute 才动手。
#
# 会删：
#   1. 失败退出的一次性容器（不含 compose 项目里正常退出的 init 容器）
#   2. 无标签的构建残层（dangling images）
#   3. 每个仓库 rollback-* 标签只留最近 N 个（默认 3），其余删
#   4. 演练/测试用旧项目的镜像（前缀见 STALE_PROJECT_PREFIXES）
#   5. 没有任何容器挂载的匿名数据卷（dangling volumes）
# 不会删：正在被容器引用的镜像、命名数据卷、staging、安卓打包镜像、基础镜像。
set -euo pipefail

mode="dry-run"
keep_rollbacks=3
for arg in "$@"; do
    case "$arg" in
        --execute) mode="execute" ;;
        --dry-run) mode="dry-run" ;;
        --keep=*) keep_rollbacks="${arg#--keep=}" ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

STALE_PROJECT_PREFIXES=(
    "c19-asset-stage4-rehearsal_"
    "c19-asset-stage4-restore_"
    "c19-stage5-asset-rehearsal_"
    "c19-stage5-record-rehearsal_"
    "c19-stage5-record-restore_"
    "c19-record-stage4-rehearsal_"
    "c19-record-buildcheck_"
    "barong-ops-console-c19-migration-test_"
    "barong-ops-console-f12-test_"
    "baisuwan-agent_"
)

say() { printf '%s\n' "$*"; }
act() {
    if [[ "$mode" == "execute" ]]; then
        "$@"
    else
        say "  [演习] $*"
    fi
}

say "== 模式: $mode（rollback 标签每仓库保留 $keep_rollbacks 个）"
say "== 清理前:"
docker system df

# 正在被任何容器（含停止的）引用的镜像 ID，绝不碰。
in_use_ids="$(docker ps -a --format '{{.Image}}' | sort -u | while read -r ref; do docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || true; done | sort -u)"
is_in_use() { grep -qx "$1" <<<"$in_use_ids"; }

say
say "== 1. 失败退出的一次性容器"
docker ps -a --filter status=exited --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}' | while IFS=$'\t' read -r id name image status; do
    case "$name" in
        *volume-init*|*_1) say "  保留 $name ($status)"; continue ;;
    esac
    say "  删除容器 $name ($image, $status)"
    act docker rm "$id" >/dev/null
done

say
say "== 2. 无标签构建残层"
dangling_count="$(docker images -f dangling=true -q | wc -l)"
say "  共 $dangling_count 个"
if [[ "$dangling_count" -gt 0 ]]; then
    act docker image prune -f >/dev/null
fi

say
say "== 3. rollback 标签只留最近 $keep_rollbacks 个"
docker images --format '{{.Repository}}' | grep -v '<none>' | sort -u | while read -r repo; do
    tags="$(docker images "$repo" --format '{{.Tag}}\t{{.CreatedAt}}\t{{.ID}}' | { grep -E '^rollback-' || true; } | sort -t$'\t' -k2,2r)"
    [[ -z "$tags" ]] && continue
    total="$(wc -l <<<"$tags")"
    [[ "$total" -le "$keep_rollbacks" ]] && { say "  $repo: $total 个，不动"; continue; }
    say "  $repo: $total 个，删 $((total - keep_rollbacks)) 个"
    tail -n +"$((keep_rollbacks + 1))" <<<"$tags" | while IFS=$'\t' read -r tag created id; do
        if is_in_use "$(docker image inspect --format '{{.Id}}' "$repo:$tag" 2>/dev/null || echo none)"; then
            say "    保留 $repo:$tag（有容器在用）"
            continue
        fi
        act docker rmi "$repo:$tag" >/dev/null
    done
done

say
say "== 4. 演练/测试旧项目镜像"
for prefix in "${STALE_PROJECT_PREFIXES[@]}"; do
    docker images --format '{{.Repository}}:{{.Tag}}' | { grep "^$prefix" || true; } | while read -r ref; do
        if is_in_use "$(docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || echo none)"; then
            say "  保留 $ref（有容器在用）"
            continue
        fi
        say "  删除 $ref"
        act docker rmi "$ref" >/dev/null
    done
done

say
say "== 5. 无主匿名数据卷"
dangling_volumes="$(docker volume ls -f dangling=true --format '{{.Name}}' | grep -E '^[0-9a-f]{64}$' || true)"
if [[ -z "$dangling_volumes" ]]; then
    say "  无"
else
    say "  共 $(wc -l <<<"$dangling_volumes") 个（只删 64 位十六进制名的匿名卷，命名卷一律不碰）"
    while read -r vol; do
        [[ -z "$vol" ]] && continue
        act docker volume rm "$vol" >/dev/null
    done <<<"$dangling_volumes"
fi

say
say "== 清理后:"
docker system df
