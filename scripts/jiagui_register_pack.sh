#!/usr/bin/env bash
# 把交接目录里的一个风格包登记进控制台注册表(待生效)。宿主机上跑:
#   bash scripts/jiagui_register_pack.sh /root/claude_handoff/14_packs/sunny-pop-1.0.1.tar.gz
# 校验和从同名 .sha256 文件读;包从标准输入喂给 k-worker(容器里没挂交接目录)。检查不过 → 退出码 2,不会生效。
# 登记完由苏青禾发「风格包待生效」卡,老板批了才生效;只改进度的新版本她自动生效。
set -euo pipefail

pkg="${1:?用法: jiagui_register_pack.sh <id>-<版本>.tar.gz}"
container="${JIAGUI_CONTAINER:-k-worker}"
sum_file="${pkg}.sha256"
[[ -f "$pkg" ]] || { echo "找不到 $pkg" >&2; exit 1; }
[[ -f "$sum_file" ]] || { echo "找不到 $sum_file" >&2; exit 1; }
sha="$(awk '{print $1; exit}' "$sum_file")"
[[ "$sha" =~ ^[0-9a-f]{64}$ ]] || { echo "$sum_file 里不是 sha256" >&2; exit 1; }
name="$(basename "$pkg")"
docker exec -i "$container" python -m backend.app.modules.k_series.jiagui.cli register \
    --filename "$name" --sha256 "$sha" --by "handoff:${SUDO_USER:-${USER:-root}}" < "$pkg"
