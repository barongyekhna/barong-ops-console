"""把 /wholesale/ 主页和店型子页写进 WordPress。

照 `geo_series/content/guides_index.py` 的模式,但**修掉了它的一个缺陷**:
那边在**任何** unreachable 结果上都 fallback 到"新建页面",WP 一超时就会多出
一个重复页。这边是 1 主页 + N 子页,炸起来更狠,所以:

1. 先按存下来的 id 更新
2. 更新失败**只在 HTTP 404 时**才考虑重建
3. 重建前先按 slug 查一遍,把手工建的/id 丢了的页面认领回来

**死规矩**:`db.commit()` 必须在出网之前(长事务被 idle-in-transaction 掐断,
这一轮已经栽过两次)。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services import wp_bridge
from ..store_types import catalog as store_type_catalog
from ..store_types import service as store_type_service
from ..store_types.models import B2BStoreType
from ..wholesale.models import STATUS_READY, B2BWholesaleItem
from . import guides, pages
from .models import (
    GUIDE_CATEGORIES_KEY,
    GUIDE_COUNT_PREFIX,
    LAST_PUBLISHED_KEY,
    STORE_TYPE_PAGE_ID_PREFIX,
    WHOLESALE_PAGE_ID_KEY,
    B2BSiteSetting,
)

logger = logging.getLogger(__name__)

_PAGES_PATH = "pages"
SITE_BASE = "https://barongyekhna.com"
# 插件读这个 option 给指南文章加「Buying for a store?」回链。
GUIDE_LINKS_OPTION = "barong_b2b_guide_links"
# 产品页小窗的文案(标题/联系方式/政策条)。
#
# ⚠️ 2026-07-30 抓到的真 bug:`policies.widget_policies()` **只有测试在引用**,
# 生产代码里没有任何地方把它推到 WP——小窗文案是当初手动推上去的一次性动作。
# 结果 policies.py 号称"唯一真相源",对小窗其实不成立:改了代码线上纹丝不动。
# 线上因此挂着一句漏了 "First" 的免运费(读起来像每单都免,还和页面/图册打架)。
# 现在挂进发布动作:重新生成页面的同时把小窗文案也推一遍,两者不可能再脱节。
WIDGET_POLICY_OPTION = "barong_b2b_policy"
# 定时重发的最小间隔。护栏针对的是"定时被误配成每分钟一次",不是正常节奏。
MIN_REPUBLISH_INTERVAL_MINUTES = 30


class PublishError(RuntimeError):
    """人能看懂的错误,直接冒到界面上。"""


# --------------------------------------------------------------------------
# KV
# --------------------------------------------------------------------------


def _get(db: Session, key: str) -> str | None:
    row = db.execute(
        select(B2BSiteSetting.value).where(B2BSiteSetting.key == key)
    ).scalar_one_or_none()
    return str(row) if row else None


def _set(db: Session, key: str, value: str) -> None:
    existing = db.get(B2BSiteSetting, key)
    if existing is None:
        db.add(B2BSiteSetting(key=key, value=value))
    else:
        existing.value = value
    db.flush()


# --------------------------------------------------------------------------
# 组数据:店型 → 类目 → 产品
# --------------------------------------------------------------------------


def _product_url(item: B2BWholesaleItem) -> str:
    """`/?p=<id>` 会 301 到真实固定链接,不用多打一次 API 拿 permalink。"""
    return f"{SITE_BASE}/?p={item.woo_product_id}" if item.woo_product_id else ""


def _as_product(item: B2BWholesaleItem) -> dict[str, Any]:
    return {
        "sku": item.sku,
        "name": item.product_name,
        "url": _product_url(item),
        "image": item.image_url or "",
        # 连接 GEO 指南要用（簇的 product_ids_json 里存的是 K 产品 id）
        "k_product_id": str(item.k_product_id) if item.k_product_id else "",
        # 排序用,不渲染
        "updated_at": item.updated_at,
    }


def collect_groups(db: Session) -> list[dict[str, Any]]:
    """每个**有货**的店型一组,组内按谷歌类目分。

    只收 `status == ready`(填全批发信息)且已上过 Woo 的产品——页面上点进去
    必须真的有产品页,否则就是死链。
    """
    items = [
        item
        for item in db.scalars(select(B2BWholesaleItem))
        if item.status == STATUS_READY and item.woo_product_id
    ]
    if not items:
        return []

    groups: list[dict[str, Any]] = []
    store_types = db.scalars(
        select(B2BStoreType).order_by(B2BStoreType.sort_order, B2BStoreType.label)
    )
    for store_type in store_types:
        prefixes = store_type_service.prefixes_for(db, store_type.key)
        if not prefixes:
            continue
        matched = [
            item
            for item in items
            if store_type_service.matches_any_prefix(item.category_path, prefixes)
        ]
        if not matched:
            continue

        # 组内按谷歌类目分组。叶子类目太细,取到倒数第二层更像"货架分类"。
        buckets: OrderedDict[str, list[B2BWholesaleItem]] = OrderedDict()
        for item in sorted(matched, key=lambda i: i.sku):
            path = list(item.category_path or [])
            name = path[-1] if path else "Other"
            buckets.setdefault(name, []).append(item)

        slug = pages.store_type_slug(store_type.key)
        # **网站上一律用对外英文名**。DB 里的 label 是中文,那是给控制台看的
        # ——直接印到英文站上买家看不懂(2026-07-29 首次生成时页面出现
        # "户外装备店")。目录里没有就退回中文名,至少不空。
        spec = store_type_catalog.spec_for(store_type.key)
        public_label = (spec or {}).get("public_label") or store_type.label
        groups.append(
            {
                "key": store_type.key,
                "label": public_label,
                "console_label": store_type.label,
                "slug": slug,
                "url": f"/{pages.WHOLESALE_SLUG}/{slug}/",
                "count": len(matched),
                # 卡片上放最新填好批发价的几个——新品最需要曝光,还能自动轮换。
                "thumbs": [
                    _as_product(item)
                    for item in sorted(
                        matched,
                        key=lambda i: i.updated_at,
                        reverse=True,
                    )[: pages.CARD_THUMBS]
                ],
                "categories": [
                    {
                        "name": name,
                        # 全路径:guide_link_map 按它对 GEO 簇
                        "path": " > ".join(rows[0].category_path or []),
                        "products": [_as_product(i) for i in rows],
                        # 指南在 publish() 里填（要凭据向 WP 核状态）
                        "guides": [],
                    }
                    for name, rows in buckets.items()
                ],
            }
        )
    return groups


# --------------------------------------------------------------------------
# 写 WordPress
# --------------------------------------------------------------------------


def _find_by_slug(credentials: Any, slug: str) -> int | None:
    """按 slug 找回页面。id 丢了、或页面是手工建的,靠这个认领回来。"""
    result = wp_bridge._request_json(  # noqa: SLF001 - 站内共享口径
        wp_bridge._api_url(credentials, f"{_PAGES_PATH}?slug={slug}&status=any"),
        credentials=credentials,
        authenticated=True,
    )
    data = result.get("data")
    if isinstance(data, list) and data:
        page_id = data[0].get("id")
        return int(page_id) if page_id else None
    return None


def _write_page(
    credentials: Any,
    *,
    page_id: int | None,
    slug: str,
    title: str,
    content: str,
    parent: int | None = None,
    status: str = "publish",
) -> tuple[int | None, str | None]:
    """更新或创建一个页面。返回 (page_id, link)。

    **不像 guides_index 那样"失败就新建"** —— 只有确实 404(页面被删了)才
    重建,其余失败一律放弃本次,避免 WP 抖一下就多出一堆重复页。
    """
    payload: dict[str, Any] = {
        "title": title,
        "slug": slug,
        "content": content,
        "status": status,
    }
    if parent:
        payload["parent"] = parent

    if page_id:
        result = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, f"{_PAGES_PATH}/{page_id}"),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload=payload,
        )
        if result.get("reachable"):
            data = result.get("data")
            link = data.get("link") if isinstance(data, dict) else None
            return page_id, link
        if result.get("status") != 404:
            # WP 超时/500 —— 放弃本次,**绝不因此新建一个重复页**。
            raise PublishError(
                f"更新页面 {slug} 失败（{result.get('error')}），本次不改动。"
            )
        logger.warning("Page %s (%s) is gone; recovering", page_id, slug)

    # 没有 id，或者 id 指向的页面确实没了：先按 slug 认领
    found = _find_by_slug(credentials, slug)
    if found:
        result = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, f"{_PAGES_PATH}/{found}"),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload=payload,
        )
        if result.get("reachable"):
            data = result.get("data")
            link = data.get("link") if isinstance(data, dict) else None
            return found, link
        raise PublishError(f"更新页面 {slug} 失败（{result.get('error')}）。")

    created = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, _PAGES_PATH),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload=payload,
    )
    if not created.get("reachable"):
        raise PublishError(f"创建页面 {slug} 失败（{created.get('error')}）。")
    data = created.get("data")
    if not isinstance(data, dict):
        raise PublishError(f"创建页面 {slug} 返回了预期外的内容。")
    return int(data.get("id")), data.get("link")


def publish(db: Session) -> dict[str, Any]:
    """生成主页 + 全部店型子页。幂等:重复跑不会多建页面。"""
    groups = collect_groups(db)
    main_id = _get(db, WHOLESALE_PAGE_ID_KEY)
    child_ids = {
        group["key"]: _get(db, f"{STORE_TYPE_PAGE_ID_PREFIX}{group['key']}")
        for group in groups
    }
    # **出网前先结束事务**：下面是一串 HTTP，长事务会被 idle-in-transaction 掐断。
    db.commit()

    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        raise PublishError("WordPress 凭据没配置。")

    # 每个类目段落挂它自己的指南（方案 B）。**按这一页实际有的产品连**,
    # 不按店型配置的宽前缀——否则会推销你不卖的货。
    _attach_guides(db, groups, credentials)

    # 子页先发：主页的卡片要链到它们，先有子页才不会出死链。
    published: list[dict[str, Any]] = []
    for group in groups:
        page_id, link = _write_page(
            credentials,
            page_id=int(child_ids[group["key"]]) if child_ids[group["key"]] else None,
            slug=group["slug"],
            title=f"Wholesale - {group['label']}",
            content=pages.render_store_type_page(group),
            parent=int(main_id) if main_id else None,
            status="publish",
        )
        published.append(
            {"key": group["key"], "label": group["label"],
             "count": group["count"], "page_id": page_id, "link": link}
        )
        _set(db, f"{STORE_TYPE_PAGE_ID_PREFIX}{group['key']}", str(page_id))
        _set(db, f"{GUIDE_COUNT_PREFIX}{group['key']}", str(_guide_count(group)))
        db.commit()

    new_main_id, main_link = _write_page(
        credentials,
        page_id=int(main_id) if main_id else None,
        slug=pages.WHOLESALE_SLUG,
        title=pages.WHOLESALE_TITLE,
        content=pages.render_wholesale_page(groups),
        status="publish",
    )
    _set(db, WHOLESALE_PAGE_ID_KEY, str(new_main_id))
    _set(db, LAST_PUBLISHED_KEY, datetime.now(UTC).isoformat())
    db.commit()

    # 反向那条:WP 类目 → 批发页。一次 option 写入,插件读它给指南文章加回链。
    link_map = guides.guide_link_map(db, groups)
    _push_guide_links(credentials, link_map)
    # 小窗文案跟着一起推：同一个「重新生成」动作，页面/图册/小窗三面同步。
    widget_pushed = _push_widget_policy(credentials)
    _set(db, GUIDE_CATEGORIES_KEY, str(len(link_map)))
    db.commit()

    return {
        "main_page_id": new_main_id,
        "main_link": main_link,
        "store_type_pages": published,
        "groups": len(groups),
        "guides_linked": sum(_guide_count(g) for g in groups),
        "guide_categories_mapped": len(link_map),
        "widget_policy_pushed": widget_pushed,
    }


def _guide_count(group: dict) -> int:
    """这个店型页上一共挂了几篇指南(各类目段落之和)。"""
    return sum(
        len(c.get("guides") or []) for c in (group.get("categories") or [])
    )


def _attach_guides(db: Session, groups: list[dict], credentials: Any) -> None:
    """给每个类目段落填 guides。失败不影响发页面——指南是加分项不是必需。"""
    for group in groups:
        for category in group.get("categories") or []:
            ids = [
                p.get("k_product_id")
                for p in (category.get("products") or [])
                if p.get("k_product_id")
            ]
            if not ids:
                continue
            try:
                found = guides.guides_for_products(db, ids)
                post_ids = guides.post_ids_for_products(db, ids)
                category["guides"] = guides.filter_live(
                    credentials, found, post_ids=post_ids
                )
            except Exception:  # noqa: BLE001 - 指南挂不上不该拦住发页面
                logger.exception(
                    "B2B guide lookup failed for category %s",
                    category.get("name"),
                )
                category["guides"] = []


def _push_widget_policy(credentials: Any) -> bool:
    """把产品页小窗的文案从 `policies.py` 推到站点 option。

    小窗文案**从这里派生,不在别处存第二份**——这正是 policies.py 那条
    「能从一处派生的绝不复制第二份」。以前这一步是手动的,所以脱节过。
    """
    import json as _json

    from .. import policies

    payload = {
        "headline": policies.WIDGET_HEADLINE,
        "subline": policies.WIDGET_SUBLINE,
        "cta": policies.WIDGET_CTA,
        "email": policies.B2B_CONTACT_EMAIL,
        "whatsapp": policies.CONTACT_WHATSAPP,
        "policies": [entry["text"] for entry in policies.widget_policies()],
    }
    try:
        result = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, "settings"),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload={
                WIDGET_POLICY_OPTION: _json.dumps(payload, ensure_ascii=False)
            },
        )
    except Exception:  # noqa: BLE001 - 小窗文案推不上去不该拦住发页面
        logger.exception("B2B widget policy push failed")
        return False
    if not result.get("reachable"):
        # 插件没装时 WP 会静默丢弃未注册的 option,所以这里要留痕。
        logger.warning(
            "B2B widget policy push not applied (%s)", result.get("error")
        )
        return False
    return True


def _push_guide_links(credentials: Any, link_map: dict) -> None:
    """写站点 option。走 _request_json 而不是 wp_bridge.set_option——
    后者有 ALLOWED_OPTIONS 白名单只放 barong_redirect_map,照 wp_categories.py
    的先例直接调底层。"""
    import json as _json

    try:
        wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, "settings"),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload={
                GUIDE_LINKS_OPTION: _json.dumps(link_map, ensure_ascii=False)
            },
        )
    except Exception:  # noqa: BLE001 - 反向链接是加分项
        logger.exception("B2B guide-link option push failed")


def publish_safely(db: Session) -> dict[str, Any] | None:
    """给自动触发路径用:发布出问题绝不能把调用方带崩。"""
    try:
        return publish(db)
    except Exception:  # noqa: BLE001
        logger.exception("B2B wholesale page publish failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("B2B wholesale publish rollback failed")
        return None


def republish_if_due(
    db: Session,
    *,
    min_interval_minutes: int = MIN_REPUBLISH_INTERVAL_MINUTES,
) -> dict[str, Any]:
    """定时触发用的入口(n8n 每天打一次)。

    **为什么定时重发就能把新指南捞上来**:重发本身会向 WP 批量核一遍每篇指南
    的发布状态。控制台**不知道**用户什么时候在 WP 里点了发布(n8n 只落草稿,
    发布是手动的,不经过控制台),所以"定期回去核一遍"是唯一可靠的办法。

    **最小间隔护栏**:这条路会往 WP 写 1 主页 + N 子页。万一 n8n 的定时被误配
    成每分钟一次,没护栏就是往 WP.com 上砸请求。间隔内直接跳过——反正间隔内
    也不会有新东西。手动按钮走的是另一条路,不受这个限制。
    """
    last = _get(db, LAST_PUBLISHED_KEY)
    if last and min_interval_minutes > 0:
        try:
            previous = datetime.fromisoformat(last)
        except ValueError:
            previous = None
        if previous is not None:
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=UTC)
            waited = (datetime.now(UTC) - previous).total_seconds() / 60
            if waited < min_interval_minutes:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": (
                        f"距上次生成只过了 {int(waited)} 分钟"
                        f"（最小间隔 {min_interval_minutes} 分钟）。"
                    ),
                }

    result = publish_safely(db)
    if result is None:
        # 失败不抛给 n8n：抛了会触发重试风暴,而重试解决不了 WP 打不通这类问题。
        # 面板上的「上次生成」时间会停住,肉眼看得见页面变旧了。
        return {"ok": False, "skipped": False}
    return {
        "ok": True,
        "skipped": False,
        "groups": result["groups"],
        "guides_linked": result["guides_linked"],
        "guide_categories_mapped": result["guide_categories_mapped"],
    }


def status(db: Session) -> dict[str, Any]:
    groups = collect_groups(db)
    return {
        "main_page_id": _get(db, WHOLESALE_PAGE_ID_KEY),
        "last_published_at": _get(db, LAST_PUBLISHED_KEY),
        "store_types": [
            {
                "key": g["key"],
                "label": g["label"],
                "count": g["count"],
                "url": g["url"],
                "page_id": _get(db, f"{STORE_TYPE_PAGE_ID_PREFIX}{g['key']}"),
                # 上次发布时**真的挂上去**的篇数(已向 WP 核过发布状态)。
                # 这里不重算:重算要出网,而且面板该显示"页面上现在是什么"。
                "guides": int(_get(db, f"{GUIDE_COUNT_PREFIX}{g['key']}") or 0),
            }
            for g in groups
        ],
        "guide_categories_mapped": int(_get(db, GUIDE_CATEGORIES_KEY) or 0),
    }
