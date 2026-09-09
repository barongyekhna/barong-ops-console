#!/usr/bin/env bash
# 重建 10 个 worker。本轮改了 backend/app/main.py（日志配置，公共层）。
#
# 必须先 rm 再 up：compose 1.29.2 的 recreate 路径要读旧容器镜像的
# ContainerConfig 字段，新版 Docker 已不写该字段 → KeyError，且崩在
# 「旧容器已改名、新容器未建」的中间态，十个 worker 会同时躺下。
# 2026-09-02 实际踩过一次。
set -uo pipefail
cd /opt/barong-release-20260831
SERVICES="r-w-worker r-a-worker k-worker k-mcp geo-worker seo-worker baisuwan-worker nijing-worker yinchengyue-worker key-health-worker"

echo "== 1/3 构建 =="
docker-compose -p barong-ops-console -f docker-compose.production.yml build $SERVICES || exit 1

echo "== 2/3 先删旧容器（数据都在具名卷上）=="
for s in $SERVICES; do
  for c in $(docker ps -a --format '{{.Names}}' | grep -E "^[0-9a-f]{12}_${s}$|^${s}$"); do
    docker rm -f "$c" >/dev/null 2>&1 && echo "  removed $c"
  done
done

echo "== 3/3 全新创建 =="
docker-compose -p barong-ops-console -f docker-compose.production.yml up -d --no-deps --no-build $SERVICES

echo; echo "== 结果 =="
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E "worker|mcp"
echo; echo "== 启动错误检查（等 25 秒）=="
sleep 25
for c in $SERVICES; do
  err=$(docker logs "$c" 2>&1 | grep -iE "ModuleNotFoundError|ImportError|Traceback" | head -1)
  printf "  %-20s %s\n" "$c" "${err:-干净}"
done
