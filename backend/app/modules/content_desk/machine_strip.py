"""「机器自己在跑的」那条绿窄条。**零按钮。**

只报状态。要处理去 GEO/SEO 老页面 —— 内容台的定位是「今天该你做什么」,
在这里加按钮就等于把 39 个按钮又搬一部分回来。

**直接调底层函数,不走 ``/seo/link-net`` 那个端点。** 两个理由:那个端点会顺带
调 ``collect_backlink_targets``,后者开头就打 WordPress(出网);而且它要
``seo.content.read``,内容台调它等于绕过自己的模块边界。

三条 lane 各自 try/except:一条查不动不该让整条窄条空白。三个数据源**都不出网**,
可以放心串在一个请求里。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _link_net(db: Session) -> dict[str, Any]:
    from ..content_links.link_push import state

    data = state(db)
    summary = data.get("summary") or {}
    posts = summary.get("posts") or 0
    return {
        "key": "link_net",
        "label": "文章内链",
        "ok": True,
        "text": f"覆盖 {posts} 篇 · {summary.get('products') or 0} 张产品卡",
    }


def _site_nav(db: Session) -> dict[str, Any]:
    from ..content_links.site_nav import HUBS, hub_item_counts, pinned_hubs

    counts = hub_item_counts(db)
    pinned = pinned_hubs(db)
    live = [h for h in HUBS if counts.get(h.key, 0) > 0 or h.key in pinned]
    return {
        "key": "site_nav",
        "label": "站内入口",
        "ok": True,
        "text": f"{len(live)} 个枢纽挂在导航上",
    }


def _self_check(db: Session) -> dict[str, Any]:
    from ..content_core.consistency import find_stranded

    stranded = find_stranded(db)
    return {
        "key": "self_check",
        "label": "内容自检",
        # 有卡死记录时变琥珀色,但**仍然不给按钮** —— 去老页面处理。
        "ok": not stranded,
        "text": f"{len(stranded)} 条卡住的记录" if stranded else "没有异常",
    }


def machine_lanes(db: Session) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for probe in (_link_net, _site_nav, _self_check):
        try:
            lanes.append(probe(db))
        except Exception:  # noqa: BLE001 - 一条坏掉不让整条窄条空白
            logger.exception("machine lane failed: %s", probe.__name__)
            lanes.append(
                {
                    "key": probe.__name__.strip("_"),
                    "label": "—",
                    "ok": False,
                    "text": "这一项暂时查不出来",
                }
            )
    return lanes


__all__ = ["machine_lanes"]
