#!/usr/bin/env python3
"""回填历史业务通知的组织归属。

2026-08-31 体检：205 条业务通知 `org_id` 为空，而「空 org」在可见性判定里
表示**全站通知** —— 于是制造公司的超管一直在收国际贸易独立站的死链告警、
K 品牌门失败、P 上传结果，全都带具体 SKU。

病根在写入侧：9 个生产者一个都没传 org_id。已在
`notifications/service.py:create_notification` 修好（有 product_id 就从产品表
推导组织），新通知一律带归属。**这个脚本处理的是存量。**

回填依据两条：
1. 顺着 `product_id` 查 `k_product_knowledge_products.workspace_key`；
2. `source = 'h_site_health'`（站点健康巡检）归国际贸易公司——独立站只有那一家，
   按组织名解析、不写死 id（2026-09-06：制造公司主页收到贸易公司死链告警后补上）。
两条都推不出的**保持为空**——不猜、不兜底到某个组织。

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

SITE_HEALTH_SQL = """
UPDATE p_notifications AS n
SET org_id = :trade_org_id
WHERE n.org_id IS NULL
  AND n.source = 'h_site_health'
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
        from backend.app.core.target_org_guard import (
            INTERNATIONAL_TRADE_ORG_NAME,
            resolve_target_org,
        )

        trade_org = resolve_target_org(db, INTERNATIONAL_TRADE_ORG_NAME)
        site_health = sum(int(r["条数"]) for r in rows if r["source"] == "h_site_health")
        print(f"能按产品回填 {fixable} 条；站点健康 {site_health} 条归贸易公司"
              f"（{trade_org.org_id if trade_org else '未解析到！'}）；")
        print(f"其余 {total - fixable - site_health} 条两条依据都推不出，按设计保持为空。")

        if not args.execute:
            print()
            print("这是演练。确认无误后加 --execute 真正写入。")
            return 0

        result = db.execute(
            text(BACKFILL_SQL), execution_options=SKIP_ORG_DATA_ISOLATION
        )
        health_rows = 0
        if trade_org is not None:
            health_rows = db.execute(
                text(SITE_HEALTH_SQL),
                {"trade_org_id": trade_org.org_id},
                execution_options=SKIP_ORG_DATA_ISOLATION,
            ).rowcount
        db.commit()
        print()
        print(f"已按产品回填 {result.rowcount} 条，站点健康归贸易公司 {health_rows} 条。")

        left = db.execute(
            text("SELECT COUNT(*) FROM p_notifications WHERE org_id IS NULL"),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).scalar()
        print(f"仍为空的还有 {left} 条（预期 = 真正的全站公告）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
