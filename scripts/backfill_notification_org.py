#!/usr/bin/env python3
"""回填历史业务通知的组织归属。

2026-08-31 体检：205 条业务通知 `org_id` 为空，而「空 org」在可见性判定里
表示**全站通知** —— 于是制造公司的超管一直在收国际贸易独立站的死链告警、
K 品牌门失败、P 上传结果，全都带具体 SKU。

病根在写入侧：9 个生产者一个都没传 org_id。已在
`notifications/service.py:create_notification` 修好（有 product_id 就从产品表
推导组织），新通知一律带归属。**这个脚本处理的是存量。**

回填依据只有一条：顺着 `product_id` 查 `k_product_knowledge_products.workspace_key`。
查不到就**保持为空**——不猜、不兜底到某个组织。站点健康那类没有产品可依的
（体检时 35 条）会留在原样，它们确实是全站性质的。

默认只做演练（dry-run），加 --execute 才真写。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BACKFILL_SQL = """
UPDATE p_notifications AS n
SET org_id = p.workspace_key
FROM k_product_knowledge_products AS p
WHERE n.org_id IS NULL
  AND n.product_id IS NOT NULL
  AND p.id = n.product_id
  AND COALESCE(p.workspace_key, '') <> ''
"""

PREVIEW_SQL = """
SELECT n.source,
       COUNT(*) AS 条数,
       COUNT(p.id) AS 能推导出组织的
FROM p_notifications AS n
LEFT JOIN k_product_knowledge_products AS p ON p.id = n.product_id
WHERE n.org_id IS NULL
GROUP BY n.source
ORDER BY 2 DESC
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="真的写库（默认只演练）"
    )
    args = parser.parse_args()

    from sqlalchemy import text

    from backend.app.db.session import SessionLocal
    from backend.app.services.data_isolation import SKIP_ORG_DATA_ISOLATION

    with SessionLocal() as db:
        rows = db.execute(
            text(PREVIEW_SQL), execution_options=SKIP_ORG_DATA_ISOLATION
        ).mappings().all()

        if not rows:
            print("没有 org_id 为空的通知，无需回填。")
            return 0

        print(f"{'来源':<20}{'条数':>8}{'能推导出组织':>16}")
        print("-" * 46)
        total = fixable = 0
        for row in rows:
            print(f"{row['source']:<20}{row['条数']:>8}{row['能推导出组织的']:>16}")
            total += int(row["条数"])
            fixable += int(row["能推导出组织的"])
        print("-" * 46)
        print(f"{'合计':<20}{total:>8}{fixable:>16}")
        print()
        print(f"能回填 {fixable} 条；其余 {total - fixable} 条没有 product_id，")
        print("按设计保持为空（它们确实是全站性质的，比如站点健康巡检）。")

        if not args.execute:
            print()
            print("这是演练。确认无误后加 --execute 真正写入。")
            return 0

        result = db.execute(
            text(BACKFILL_SQL), execution_options=SKIP_ORG_DATA_ISOLATION
        )
        db.commit()
        print()
        print(f"已回填 {result.rowcount} 条。")

        left = db.execute(
            text("SELECT COUNT(*) FROM p_notifications WHERE org_id IS NULL"),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).scalar()
        print(f"仍为空的还有 {left} 条（预期 = 没有 product_id 的那些）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
