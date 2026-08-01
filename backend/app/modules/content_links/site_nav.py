"""枢纽页的站内入口:主导航 + 主页区块。

由来(2026-08-01):用户问「指南页和工厂页怎么在主页上看不到」。查下来账比这更难看:

- ``/guides/`` 有 5 篇已发布指南,**全站零入口**——只有 sitemap 和文章间内链能到
- ``/factory/`` 是空的(工艺文还没发),但用户要它进导航
- ``/posts/`` 正文区写着 "Nothing Found",**却挂在主导航上**

也就是说:**有内容的页面没人进得去,没内容的页面反而挂在导航上。**

所以这里管的不是"加两个菜单项",而是一条规矩:

    枢纽页有内容 → 保证它在导航和主页上有入口
    枢纽页没内容 → 把入口摘掉

两个方向都要自动,只做前一半就会在用户下架文章之后留一个死链导航项。这条规矩
一写死,以后加新枢纽(比较页、案例页……)只需要在 ``HUBS`` 里加一行。

**只碰自己的菜单项**:认领依据是 URL 精确等于枢纽 URL。Shop / Wholesale /
Contact 这些是用户自己排的,本模块一个都不许动——自动化碰用户手工排的东西,
一次误删就够让人再也不敢开自动同步了。

写完必须回读(``external_side_effect_verify`` 死规矩):菜单项 POST 成功
不等于它真的进了那个菜单、真的显示出来。
"""

from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 主页那一页(page-blank.php + <div id="by-home">,控制台自己管的纯 HTML)。
HOME_PAGE_ID = 1446
# 主页区块插在这个 section 之前——批发那块是主页的收尾 CTA,内容入口该在它上面。
HOME_ANCHOR = '<section class="bywhole">'
HOME_BLOCK_CLASS = "byhubs"

# 主导航挤到几项就会换行。2026-08-01 用户实测:7 项换行,难看;摘掉
# Privacy Policy 和 Track your order(都挪进页脚)之后 5 项一行放得下。
# **枢纽是自动进导航的**,所以这个数必须在战报里报出来——否则哪天自动加了
# 第三个枢纽又换行,人只会觉得"网站突然变丑了",不知道是这里干的。
# 不做硬拦截:该有的入口不能因为排版被吃掉,该做的是让人看见并自己决定摘谁。
HEADER_COMFORTABLE_MAX = 6


@dataclass(frozen=True)
class HubSpec:
    """一个枢纽页。

    key      内部标识
    label    菜单和主页上显示的字(买家看得懂的话,不是内部黑话)
    path     站内路径
    blurb    主页卡片上的一句话
    """

    key: str
    label: str
    path: str
    blurb: str

    @property
    def url(self) -> str:
        return f"https://barongyekhna.com{self.path}"


HUBS: tuple[HubSpec, ...] = (
    HubSpec(
        key="guides",
        label="Guides",
        path="/guides/",
        blurb="How to choose, what the numbers mean, and what actually matters in use.",
    ),
    HubSpec(
        key="factory",
        label="How We Make It",
        # 菜单上不写 "Factory"——买家不关心我们有厂,关心的是东西怎么做出来的。
        # 同一个页面,换一句人话就从"关于我们"变成"值得点进去"。
        path="/factory/",
        blurb="Materials, tooling and the tests every unit goes through before it ships.",
    ),
)


def hub_item_counts(db: Session) -> dict[str, int]:
    """每个枢纽底下**真正已经发布**的文章数。不出网。

    判据是 ``wp_status == 'publish'``,不是 ``published_url`` 非空——
    草稿期就已经写库了,published_url 非空 ≠ 线上可见(这条踩过)。
    """
    counts = {hub.key: 0 for hub in HUBS}
    try:
        from ..geo_series.content.models import GeoContentItem

        counts["guides"] = len(
            db.execute(
                select(GeoContentItem.id).where(GeoContentItem.wp_status == "publish")
            ).all()
        )
    except Exception:  # noqa: BLE001 - 一个枢纽算不出来不该拖垮另一个
        logger.exception("guides hub count failed")
    try:
        from ..seo_series.content.constants import DESTINATION_FACTORY
        from ..seo_series.content.models import SeoContentItem

        counts["factory"] = len(
            db.execute(
                select(SeoContentItem.id).where(
                    SeoContentItem.wp_status == "publish",
                    SeoContentItem.destination == DESTINATION_FACTORY,
                )
            ).all()
        )
    except Exception:  # noqa: BLE001
        logger.exception("factory hub count failed")
    return counts


def desired_hubs(db: Session) -> tuple[list[HubSpec], list[HubSpec]]:
    """(该挂入口的, 该摘掉入口的)。"""
    counts = hub_item_counts(db)
    live = [h for h in HUBS if counts.get(h.key, 0) > 0]
    empty = [h for h in HUBS if counts.get(h.key, 0) <= 0]
    return live, empty


# ---------------------------------------------------------------- 主导航


def _primary_menu_id(wp_bridge: Any, credentials: Any) -> int | None:
    """找到挂在 ``primary`` 位置的那个菜单。

    **不写死 id**:菜单是用户在 WP 后台建的,他随时可能重建一个。按位置找,
    重建之后照样对得上。
    """
    result = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, "menus"),  # noqa: SLF001
        credentials=credentials,
        authenticated=True,
    )
    if not result.get("reachable"):
        return None
    for menu in result.get("data") or []:
        if "primary" in (menu.get("locations") or []):
            return int(menu["id"])
    return None


def sync_primary_menu(db: Session) -> dict[str, Any]:
    """让主导航和枢纽的真实内容对上。返回一份能直接给人看的战报。"""
    from ...services import wp_bridge

    live, empty = desired_hubs(db)
    # 出网前放掉事务(idle-in-txn 铁律)。
    db.commit()

    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        return {"ok": False, "reason": "WordPress 凭据不可用"}
    menu_id = _primary_menu_id(wp_bridge, credentials)
    if menu_id is None:
        return {"ok": False, "reason": "找不到 primary 位置的菜单"}

    listing = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(  # noqa: SLF001
            credentials, f"menu-items?menus={menu_id}&per_page=100"
        ),
        credentials=credentials,
        authenticated=True,
    )
    if not listing.get("reachable"):
        return {"ok": False, "reason": f"读菜单失败：{listing.get('error')}"}
    existing = listing.get("data") or []

    # 认领:URL 精确相等。别的菜单项一律不碰。
    by_url = {str(i.get("url") or "").rstrip("/") + "/": i for i in existing}
    added: list[str] = []
    removed: list[str] = []

    for hub in live:
        if hub.url in by_url:
            continue
        create = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, "menu-items"),  # noqa: SLF001
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload={
                "title": hub.label,
                "url": hub.url,
                "menus": menu_id,
                "status": "publish",
                "type": "custom",
                # 排在 Wholesale(2) 之后、Posts(4) 之前。同序号按 id 排,
                # 所以 Guides 会在 How We Make It 前面(先建的先出)。
                "menu_order": 3,
            },
        )
        if create.get("reachable"):
            added.append(hub.label)
        else:
            logger.warning("menu item create failed: %s", create.get("error"))

    for hub in empty:
        item = by_url.get(hub.url)
        if item is None:
            continue
        drop = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(  # noqa: SLF001
                credentials, f"menu-items/{item['id']}?force=true"
            ),
            credentials=credentials,
            authenticated=True,
            method="DELETE",
        )
        if drop.get("reachable"):
            removed.append(hub.label)

    # 🔴 回读。POST 返回 200 不等于它真的进了那个菜单。
    verify = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(  # noqa: SLF001
            credentials, f"menu-items?menus={menu_id}&per_page=100"
        ),
        credentials=credentials,
        authenticated=True,
    )
    final_urls = {
        str(i.get("url") or "").rstrip("/") + "/" for i in (verify.get("data") or [])
    }
    missing = [h.label for h in live if h.url not in final_urls]
    lingering = [h.label for h in empty if h.url in final_urls]
    ok = not missing and not lingering

    final_items = verify.get("data") or []
    titles = [
        str((i.get("title") or {}).get("rendered") or "").strip()
        for i in sorted(final_items, key=lambda x: x.get("menu_order") or 0)
    ]
    titles = [t for t in titles if t]
    return {
        "ok": ok,
        "menu_id": menu_id,
        "added": added,
        "removed": removed,
        "header_titles": titles,
        "header_count": len(titles),
        "crowded": len(titles) > HEADER_COMFORTABLE_MAX,
        "in_menu": sorted(h.label for h in live if h.url in final_urls),
        "reason": (
            ""
            if ok
            else f"回读对不上——没进去：{missing or '无'}；没摘掉：{lingering or '无'}"
        ),
    }


# ---------------------------------------------------------------- 主页区块


def render_hub_section(hubs: list[HubSpec]) -> str:
    """主页上的内容入口区。

    刻意**不带图**:主页已有的 .bygrid 是带图的类目瓦片,内容入口再来一排图会
    跟它抢眼睛,而且我们手上没有能代表"指南"这种抽象东西的真实照片——
    AI 配图在这个位置就是纯噪音(而且首页放 AI 图,B 端买手一眼认出就完了)。
    """
    if not hubs:
        return ""
    cards = "".join(
        f'<a class="byhub" href="{_html.escape(h.path, quote=True)}">'
        f'<span class="byhubname">{_html.escape(h.label)}</span>'
        f'<span class="byhubsub">{_html.escape(h.blurb)}</span>'
        f'<span class="byhubgo">Read →</span></a>'
        for h in hubs
    )
    style = (
        "<style>"
        f".{HOME_BLOCK_CLASS}{{padding:0 0 clamp(48px,8vw,92px)}}"
        f".{HOME_BLOCK_CLASS} .byhubs-in{{display:grid;gap:14px;"
        "grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}"
        ".byhub{display:flex;flex-direction:column;gap:7px;padding:26px 24px;"
        "background:var(--card);border:1px solid var(--line);border-radius:3px;"
        "text-decoration:none;color:var(--ink)}"
        ".byhub:hover{border-color:rgba(27,26,24,.28)}"
        ".byhubname{font-family:var(--serif);font-size:21px;line-height:1.25}"
        ".byhubsub{color:var(--slate);font-size:14px;line-height:1.6}"
        ".byhubgo{color:var(--faint);font-size:13px;margin-top:4px}"
        "</style>"
    )
    return (
        f'<section class="{HOME_BLOCK_CLASS}">{style}'
        f'<div class="byw"><div class="byhubs-in">{cards}</div></div></section>'
    )


def apply_hub_section(page_html: str, block: str) -> str:
    """把区块幂等地放进主页。

    三种情况一条规则:已经有 → 原地替换;没有且 block 非空 → 插在锚点前;
    block 为空(所有枢纽都空了) → 连带把旧区块摘掉。

    ``re.sub`` 的替换值走 ``lambda``,不走字符串——区块里带 URL,里面的 ``\\1``
    之类会被当成反向引用吃掉(这个坑 html_blocks 里也写着)。
    """
    pattern = re.compile(
        rf'<section class="{HOME_BLOCK_CLASS}">.*?</section>', re.DOTALL
    )
    if pattern.search(page_html):
        return pattern.sub(lambda _m: block, page_html, count=1)
    if not block:
        return page_html
    if HOME_ANCHOR in page_html:
        return page_html.replace(HOME_ANCHOR, block + HOME_ANCHOR, 1)
    # 锚点没了(主页被重排过)——插在最外层 div 收尾之前,总比不插好。
    tail = page_html.rfind("</div>")
    if tail == -1:
        return page_html + block
    return page_html[:tail] + block + page_html[tail:]


def sync_home_section(db: Session) -> dict[str, Any]:
    """把内容入口区同步到主页。写完回读。"""
    from ...services import wp_bridge

    live, _empty = desired_hubs(db)
    block = render_hub_section(live)
    db.commit()  # 出网前放掉事务

    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        return {"ok": False, "reason": "WordPress 凭据不可用"}

    current = wp_bridge._request_json(  # noqa: SLF001
        # **必须 context=edit 拿 content.raw**。默认返回的是过完 the_content
        # 全套过滤器的 rendered——把它写回去,主页会被永久改形。
        wp_bridge._api_url(  # noqa: SLF001
            credentials, f"pages/{HOME_PAGE_ID}?context=edit&_fields=id,content"
        ),
        credentials=credentials,
        authenticated=True,
    )
    if not current.get("reachable"):
        return {"ok": False, "reason": f"读主页失败：{current.get('error')}"}
    raw = str(((current.get("data") or {}).get("content") or {}).get("raw") or "")
    if not raw:
        return {"ok": False, "reason": "主页原始内容为空，拒绝写入"}

    updated = apply_hub_section(raw, block)
    if updated == raw:
        return {"ok": True, "changed": False, "reason": "主页已经是最新的"}

    result = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, f"pages/{HOME_PAGE_ID}"),  # noqa: SLF001
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={"content": updated},
    )
    if not result.get("reachable"):
        return {"ok": False, "reason": f"写主页失败：{result.get('error')}"}

    # 🔴 回读。
    verify = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(  # noqa: SLF001
            credentials, f"pages/{HOME_PAGE_ID}?context=edit&_fields=id,content"
        ),
        credentials=credentials,
        authenticated=True,
    )
    stored = str(((verify.get("data") or {}).get("content") or {}).get("raw") or "")
    if block and HOME_BLOCK_CLASS not in stored:
        return {"ok": False, "reason": "写完回读没找到区块——主页没有真的改到"}
    return {"ok": True, "changed": True, "hubs": [h.label for h in live]}


def sync_site_nav(db: Session) -> dict[str, Any]:
    """导航 + 主页一起同步。控制台按钮和自动触发都走这个。"""
    return {"menu": sync_primary_menu(db), "home": sync_home_section(db)}


def sync_site_nav_safely(db: Session) -> dict[str, Any]:
    """自动触发点用这个——入口同步出问题绝不许把发布/上架回报带崩。"""
    try:
        return sync_site_nav(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("site nav sync failed")
        return {"ok": False, "reason": str(exc)[:200]}


__all__ = [
    "HEADER_COMFORTABLE_MAX",
    "HOME_BLOCK_CLASS",
    "HOME_PAGE_ID",
    "HUBS",
    "HubSpec",
    "apply_hub_section",
    "desired_hubs",
    "hub_item_counts",
    "render_hub_section",
    "sync_home_section",
    "sync_primary_menu",
    "sync_site_nav",
    "sync_site_nav_safely",
]
