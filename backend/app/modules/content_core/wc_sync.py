"""一次批量问 Woo:这些产品现在长什么样、在不在线、主图是哪张。

## 为什么必须问 Woo

控制台**本地没有可用的公网图 URL**(2026-07-31 核实):
- ``k_product_knowledge_media_assets`` 存的是磁盘相对路径,只有渲染器(PDF 图册)能用
- 控制台自己的 ``/api/app/k/media/{id}/file`` 要鉴权,独立站前台取不到
- 上架时 n8n 抓图走的是一次性 job token URL,过期即失效

所以要在文章里放**带图的产品卡片**,图只能来自 Woo。

## 一次调用拿四样东西

``_fields=id,name,permalink,status,images`` ——

- ``status`` → 死链核查(在不在线)
- ``permalink`` → 真实地址,干掉站内到处都是的 ``?p=4148``
- ``images[0].src`` → 主图兜底
- ``images[0].id`` → **WP 附件 id**,这一样最值钱

## 为什么要存附件 id 而不只是图片 URL

插件拿到附件 id 可以直接 ``wp_get_attachment_image($id, 'woocommerce_thumbnail')``:
自动出 ``srcset`` / ``width`` / ``height`` / ``loading=lazy``,**零布局抖动**,
而且走 WP 已经生成好的缩略图,不会把 2000px 原图塞进 300px 的卡片。
``image_src`` 只作为附件被删掉时的兜底 ``<img>``。

## fail-open 的语义

打不通返回 ``None``,**不是空字典**。调用方必须据此保留现状——
一次网络抖动绝不能把全站的产品卡片清空。这条和 ``wp_sync.fetch_post_states``
以及 ``b2b/website/products_live`` 是同一条纪律。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Woo 的 include 列表有上限;和 wp_sync 保持同一个批量大小。
_BATCH = 50


def _wc_url(credentials: Any, path: str) -> str:
    """wc/v3 的地址。``wp_bridge._api_url`` 写死了 wp/v2,这里自己拼。"""
    from ...services import wp_bridge

    base = wp_bridge._api_url(credentials, "__x__")  # noqa: SLF001
    root = base.split("/wp-json/")[0].rstrip("/")
    return f"{root}/wp-json/wc/v3/{path.lstrip('/')}"


def fetch_product_states(
    credentials: Any, product_ids: list[int]
) -> dict[int, dict[str, Any]] | None:
    """``{woo_id: {status, name, permalink, image_id, image_src, image_alt}}``

    返回 ``None`` = 核不了(凭据不可用 / WP 打不通)。**调用方必须保留现状。**
    某个 id 查不到就是它不在结果里(产品被删了)。
    """
    from ...services import wp_bridge

    wanted = sorted({int(p) for p in product_ids if p})
    if not wanted:
        return {}
    if credentials is None:
        return None

    out: dict[int, dict[str, Any]] = {}
    reached_any = False
    for start in range(0, len(wanted), _BATCH):
        chunk = wanted[start : start + _BATCH]
        query = urlencode(
            {
                "include": ",".join(str(p) for p in chunk),
                "per_page": len(chunk),
                "status": "any",
                "_fields": "id,name,permalink,status,images",
            }
        )
        result = wp_bridge._request_json(  # noqa: SLF001
            _wc_url(credentials, f"products?{query}"),
            credentials=credentials,
            authenticated=True,
        )
        if not result.get("reachable"):
            logger.warning("Woo product-state fetch failed: %s", result.get("error"))
            continue
        reached_any = True
        for row in result.get("data") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            images = row.get("images") or []
            first = images[0] if images and isinstance(images[0], dict) else {}
            out[int(row["id"])] = {
                "status": str(row.get("status") or ""),
                "name": str(row.get("name") or "").strip(),
                "permalink": str(row.get("permalink") or "").strip(),
                "image_id": int(first["id"]) if str(first.get("id") or "").isdigit() else None,
                "image_src": str(first.get("src") or "").strip(),
                "image_alt": str(first.get("alt") or "").strip(),
            }
    # 一批都没打通 = 核不了。别让调用方误以为"这些产品全没了"。
    return out if reached_any else None


def fetch_product_states_safely(
    db: Any, product_ids: list[int]
) -> dict[int, dict[str, Any]] | None:
    """自己解析凭据的版本。出网前调用方应已 ``commit()`` 放掉事务。"""
    from ...services import wp_bridge

    try:
        credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        logger.exception("WP credential resolution failed")
        return None
    if credentials is None:
        return None
    try:
        return fetch_product_states(credentials, product_ids)
    except Exception:  # noqa: BLE001 - 核不了就是核不了,调用方保留现状
        logger.exception("Woo product-state fetch crashed")
        return None


__all__ = ["fetch_product_states", "fetch_product_states_safely"]
