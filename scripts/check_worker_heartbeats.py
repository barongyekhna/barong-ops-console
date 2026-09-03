#!/usr/bin/env python3
"""检查所有 worker 是否还在真的干活。**不依赖控制台 UI，不依赖登录。**

为什么必须独立于控制台（2026-08-31 体检）：
家规要求数字员工「出事就说」，但她们上报的通道就是控制台 —— 控制台够不着时，
她们没法上报「我够不着控制台」。白苏婉和霓旌就这样瘫了一周，而你收不到任何消息。
**任何依赖被监控对象本身的监控，都会在最需要它的时候失灵。**

这个脚本只连数据库，读 `worker_heartbeats` 表，判断谁已经太久没成功干成活了。
退出码：0 = 全部正常；1 = 有 worker 失联（可供 cron / 外部告警据此发通知）。

用法：
    # 在装了依赖的环境里（宿主机 .venv 或 backend 容器内）
    python scripts/check_worker_heartbeats.py
    python scripts/check_worker_heartbeats.py --json     # 机器可读，喂给 n8n / 告警

判据不是「多久没心跳」，而是**多久没成功**：一个一直在重试、一直失败的 worker
心跳很新鲜，但它并没有在干活（r-w-keepa-daemon 每轮 statement timeout 就是这样）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON（给告警管道用）"
    )
    args = parser.parse_args()

    from backend.app.db.session import SessionLocal
    from backend.app.services.worker_heartbeat import list_heartbeats

    with SessionLocal() as db:
        rows = list_heartbeats(db)

    stale = [row for row in rows if row["stale"]]

    if args.json:
        print(
            json.dumps(
                {"total": len(rows), "stale_count": len(stale), "workers": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if stale else 0

    if not rows:
        print("worker_heartbeats 表里还没有任何记录。")
        print("说明还没有 worker 接入心跳上报 —— 这本身就该处理。")
        return 1

    print(f"{'worker':<24}{'最后一次成功':<26}{'连续失败':<10}状态")
    print("-" * 78)
    for row in rows:
        silent = row["silent_seconds"]
        if silent is None:
            when = "从未成功过"
        elif silent < 120:
            when = f"{silent} 秒前"
        elif silent < 7200:
            when = f"{silent // 60} 分钟前"
        elif silent < 172800:
            when = f"{silent // 3600} 小时前"
        else:
            when = f"{silent // 86400} 天前"
        mark = "!! 失联" if row["stale"] else "正常"
        print(
            f"{row['worker_name']:<24}{when:<26}"
            f"{row['consecutive_failures']:<10}{mark}"
        )
        if row["stale"] and row["last_error"]:
            print(f"{'':<24}最后的错: {str(row['last_error'])[:80]}")

    print()
    if stale:
        print(f"有 {len(stale)} 个 worker 已经太久没干成活了：")
        for row in stale:
            print(f"  · {row['worker_name']}")
        print()
        print("注意：容器可能仍然显示 Up —— 这正是本检查存在的理由。")
        return 1

    print(f"全部 {len(rows)} 个 worker 都在正常干活。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
