"""批发页上的产品链接:只留 Woo 上**真的还在卖**的。

**这是个不对称被补上**:指南链接我做了核实(`guides.filter_live` 去 WP 查
是不是真发布了,草稿一律不链),产品链接却没做同样的事。结果是哪天在 Woo 里
删了或下架一个产品,批发页上那张卡片会**一直挂着,点过去 404**——而且不报错,
只能靠肉眼在线上发现。

和指南那边完全同一套做法:**一次调用核全部**,核不了就一个都不删(宁可留着
可能失效的链接,也不能因为 WP 抖一下就把整页货清空)。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _wc_url(credentials: Any, path: str) -> str:
    """wc/v3 的地址。`wp_bridge._api_url` 写死了 wp/v2,产品在 Woo 那边。

    应用密码对 wp/v2 和 wc/v3 都通(P 系列早验过),所以鉴权照旧。
    """
    base = str(getattr(credentials, "base_url", "")).rstrip("/")
    return f"{base}/wp-json/wc/v3/{path.lstrip('/')}"


def live_product_ids(credentials: Any, woo_ids: list[int]) -> set[int] | None:
    """哪些产品在 Woo 上还是 publish。

    返回 `None` = **核不了**(打不通/返回意外形状)。调用方看到 None 要原样
    保留全部链接——把"查不到"当成"不存在"会在 WP 抖一下时清空整个批发页。
    """
    ids = sorted({int(i) for i in woo_ids if i})
    if not ids:
        return set()

    from ....services import wp_bridge

    include = ",".join(str(i) for i in ids)
    result = wp_bridge._request_json(  # noqa: SLF001 - 站内共享口径
        _wc_url(
            credentials,
            f"products?include={include}&status=publish&per_page=100&_fields=id",
        ),
        credentials=credentials,
        authenticated=True,
    )
    data = result.get("data")
    if not isinstance(data, list):
        logger.warning(
            "B2B product check failed (%s); keeping all links",
            result.get("error"),
        )
        return None
    return {
        int(row["id"])
        for row in data
        if isinstance(row, dict) and row.get("id")
    }


def drop_dead_products(groups: list[dict], live: set[int] | None) -> int:
    """把已下架/已删的产品从分组里摘掉,返回摘掉几个。

    `live is None`(核不了)时**一个都不动**。
    """
    if live is None:
        return 0
    removed = 0
    for group in groups:
        for category in group.get("categories") or []:
            products = category.get("products") or []
            kept = [p for p in products if _is_live(p, live)]
            removed += len(products) - len(kept)
            category["products"] = kept
        group["categories"] = [
            category
            for category in (group.get("categories") or [])
            if category.get("products")
        ]
        group["thumbs"] = [
            thumb for thumb in (group.get("thumbs") or []) if _is_live(thumb, live)
        ]
        group["count"] = sum(
            len(category.get("products") or [])
            for category in group.get("categories") or []
        )
    return removed


def _is_live(product: dict, live: set[int]) -> bool:
    import re

    match = re.search(r"[?&]p=(\d+)", str(product.get("url") or ""))
    if not match:
        # 没有 woo id 的行本来就不该出现在这里,保守起见留着。
        return True
    return int(match.group(1)) in live
