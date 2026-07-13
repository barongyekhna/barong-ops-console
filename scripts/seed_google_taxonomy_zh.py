#!/usr/bin/env python3
"""把谷歌官方 zh-CN 产品类目表按 ID 灌进 k_category_google.name_zh。

官方文件与 K 树同版本（2021-09-21，5595 节点），按 ID 精确对齐，零翻译成本。
幂等：重复执行只是重写同样的值。

用法（生产在 backend 容器内跑）：
    python scripts/seed_google_taxonomy_zh.py                # 官方 URL 下载
    python scripts/seed_google_taxonomy_zh.py --file xx.txt  # 本地文件
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

from sqlalchemy import create_engine, text

OFFICIAL_URL = os.getenv(
    "GOOGLE_TAXONOMY_ZH_URL",
    "https://www.google.com/basepages/producttype/taxonomy-with-ids.zh-CN.txt",
)


def load_lines(path: str | None) -> list[str]:
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()
    request = urllib.request.Request(OFFICIAL_URL, headers={"User-Agent": "barong-ops"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read().decode("utf-8").splitlines()


def parse(lines: list[str]) -> dict[str, str]:
    """"632 - 五金/硬件 > 五金泵" → {"632": "五金泵"}（取路径最后一段）。"""
    mapping: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or " - " not in line:
            continue
        raw_id, path = line.split(" - ", 1)
        raw_id = raw_id.strip()
        leaf = path.split(">")[-1].strip()
        if raw_id.isdigit() and leaf:
            mapping[raw_id] = leaf[:512]
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="本地 taxonomy 文件路径")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL 未设置", file=sys.stderr)
        return 2

    mapping = parse(load_lines(args.file))
    if len(mapping) < 5000:
        print(f"解析结果异常（只有 {len(mapping)} 条），中止", file=sys.stderr)
        return 2

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id FROM k_category_google")).all()
        known = {str(row[0]) for row in rows}
        payload = [
            {"i": cat_id, "zh": name_zh}
            for cat_id, name_zh in mapping.items()
            if cat_id in known
        ]
        connection.execute(
            text("UPDATE k_category_google SET name_zh = :zh WHERE id = :i"),
            payload,
        )
        missing = len(known) - len(payload)
    print(f"已写入中文名 {len(payload)} 条；库内未匹配 {missing} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
