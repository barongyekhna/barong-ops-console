"""把链接图推给 WordPress——**一次写,不管站上有 10 篇还是 500 篇文章**。

## 为什么是推一个 option,而不是改 N 篇文章

改文章正文是本仓库唯一没有先例的高危动作:
- WP REST 默认返回 ``content.rendered``(过完 ``the_content`` 全套过滤器)。
  要拿原始 HTML 必须 ``?context=edit`` 取 ``content.raw``——**取错一次就把渲染后的
  HTML 写回 post_content,文章永久变形**。
- 人一旦在 WP 里手改过一篇,区块编辑器会插 ``<!-- wp:html -->`` 分隔符,
  非贪婪正则的行为不再可预测。
- 每次刷新 N 次 PUT + N 条 revision。

改成推一个 option 之后:文章 HTML 一个字节不碰,所以**不用重新审稿、不用重跑
品牌门**;插件在渲染时查表,所以链接天然永远最新。

## 四道护栏(缺一条都会出事)

1. **指纹短路**(最强)——三个触发点连着打,只有第一次真出网。
2. **最小间隔 15 分钟**——手动按钮不受限(照 b2b ``republish_if_due`` 的写法)。
3. **dirty 标志**——被间隔挡下时置位,下次无条件重算。
   **没有这条,一次 20 个 SKU 的连续上架会因为间隔护栏丢掉最后几个。**
4. 出网前 ``db.commit()`` 放掉事务(idle-in-txn 死规矩,本仓库踩过四次)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .link_graph import build_link_map, canonical_json, fingerprint, summarize

logger = logging.getLogger(__name__)

# 插件读的那个 WP option。**这个字符串必须和 php 里的一致**——
# 有一条测试跨文件断言它出现在插件源码里,那是唯一能抓住漂移的办法。
LINK_MAP_OPTION = "barong_content_links"
CTA_STYLE_OPTION = "barong_content_cta_style"

FINGERPRINT_KEY = "link_map_fingerprint"
PUSHED_AT_KEY = "link_map_pushed_at"
DIRTY_KEY = "link_map_dirty"
SUMMARY_KEY = "link_map_summary"

# 定时/触发式刷新的最小间隔。人手动点不受限。
MIN_LINK_MAP_INTERVAL_MINUTES = 15


def _get(db: Session, key: str) -> str:
    from .models import ContentLinkSetting

    row = db.scalar(
        select(ContentLinkSetting.value).where(ContentLinkSetting.key == key)
    )
    return str(row or "")


def _set(db: Session, key: str, value: str) -> None:
    from .models import ContentLinkSetting

    row = db.get(ContentLinkSetting, key)
    if row is None:
        db.add(ContentLinkSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def state(db: Session) -> dict[str, Any]:
    """控制台面板要显示的东西。不出网。"""
    import json

    try:
        summary = json.loads(_get(db, SUMMARY_KEY) or "{}")
    except (TypeError, ValueError):
        summary = {}
    return {
        "fingerprint": _get(db, FINGERPRINT_KEY),
        "pushed_at": _get(db, PUSHED_AT_KEY),
        "dirty": _get(db, DIRTY_KEY) == "1",
        "summary": summary if isinstance(summary, dict) else {},
    }


def _waited_long_enough(db: Session) -> tuple[bool, str]:
    pushed = _get(db, PUSHED_AT_KEY)
    if not pushed:
        return True, ""
    try:
        last = datetime.fromisoformat(pushed)
    except ValueError:
        return True, ""
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    deadline = last + timedelta(minutes=MIN_LINK_MAP_INTERVAL_MINUTES)
    now = datetime.now(UTC)
    if now >= deadline:
        return True, ""
    remaining = int((deadline - now).total_seconds() // 60) + 1
    return False, f"距上次推送不足 {MIN_LINK_MAP_INTERVAL_MINUTES} 分钟，还要等 {remaining} 分钟"


def push_link_map(db: Session, *, force: bool = False) -> dict[str, Any]:
    """重算并推送。返回一份可以直接给人看的战报。

    ``force`` 只跳过指纹短路(手动"我就是想立刻推一次"),**不跳过间隔护栏**——
    间隔由 ``refresh_if_due`` 那一层管。
    """
    import json

    from ...services import wp_bridge

    link_map = build_link_map(db)
    payload = canonical_json(link_map)
    new_fingerprint = fingerprint(link_map)
    stats = summarize(link_map)

    if not force and new_fingerprint == _get(db, FINGERPRINT_KEY):
        _set(db, DIRTY_KEY, "0")
        db.commit()
        # **让人看得见"什么都没做"也是正确结果**。
        return {"ok": True, "changed": False, "reason": "内容没有变化，未推送", **stats}

    # 出网前放掉事务。
    db.commit()
    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        return {"ok": False, "changed": False, "reason": "WordPress 凭据不可用", **stats}

    result = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, "settings"),  # noqa: SLF001
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={LINK_MAP_OPTION: payload},
    )
    if not result.get("reachable"):
        _set(db, DIRTY_KEY, "1")
        db.commit()
        return {
            "ok": False,
            "changed": False,
            "reason": f"推送失败：{result.get('error')}",
            **stats,
        }

    _set(db, FINGERPRINT_KEY, new_fingerprint)
    _set(db, PUSHED_AT_KEY, datetime.now(UTC).isoformat())
    _set(db, DIRTY_KEY, "0")
    _set(db, SUMMARY_KEY, json.dumps(stats, ensure_ascii=False))
    db.commit()
    return {"ok": True, "changed": True, "bytes": len(payload), **stats}


def refresh_if_due(db: Session, *, manual: bool = False) -> dict[str, Any]:
    """带间隔护栏的入口。三个自动触发点和定时兜底都走这里。"""
    if manual:
        return push_link_map(db, force=False)
    ok, reason = _waited_long_enough(db)
    if not ok:
        # 挡下来了就置 dirty——否则一次连续上架会丢掉最后几个产品。
        _set(db, DIRTY_KEY, "1")
        db.commit()
        return {"ok": True, "changed": False, "skipped": True, "reason": reason}
    return push_link_map(db, force=False)


def refresh_link_map_safely(db: Session) -> None:
    """挂在上架/发布回报里的版本——**它出问题绝不许把那次回报带崩**。"""
    try:
        refresh_if_due(db)
    except Exception:  # noqa: BLE001 - 内链是增益,回报是本职
        logger.exception("link map refresh failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "CTA_STYLE_OPTION",
    "DIRTY_KEY",
    "FINGERPRINT_KEY",
    "LINK_MAP_OPTION",
    "MIN_LINK_MAP_INTERVAL_MINUTES",
    "PUSHED_AT_KEY",
    "SUMMARY_KEY",
    "push_link_map",
    "refresh_if_due",
    "refresh_link_map_safely",
    "state",
]
