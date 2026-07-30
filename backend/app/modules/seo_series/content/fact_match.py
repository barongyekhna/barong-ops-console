"""事实匹配——**在选题阶段就问"我们凭什么写这题"**。

事实充分性门禁(``content_core.fact_sufficiency``)拦的是生成那一刻;这里拦的是
更早一步:一个高搜索量的词,如果三个事实源都说不出话,那它根本不该进队列。
等到生成时才被拦下,中间那趟 AI 调用就白花了,而且运营会误以为"系统在挑刺"。

三个事实源:
- **工艺库**(``content_core.facts``)——自有工厂唯一说得出、竞品抄不走的
- **产品事实**(K 的规格/卖点/包装)——GEO 也吃这一口
- **店型/类目**(B2B 的店型与其类目前缀)——B 端选题的依据

匹配是**词面重叠**,不是 AI 判断:AI 判断"这题有没有支撑"会一律说有(它总能
编出点什么),那这道门就等于没有。词面重叠会漏,但漏的方向是保守的——
它只会说"我看不出支撑",不会假装有。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 太通用的词参与匹配只会制造假阳性("the best portable" 里没有一个词有信息量)。
_STOPWORDS = frozenset(
    """a an and are as at be best buy can do does for from good how i in is it
    my of on or our should the to top use used using vs what when where which
    who why will with you your""".split()
)


def _tokens(text: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _craft_corpus(db: Session) -> list[tuple[str, set[str]]]:
    try:
        from ...content_core.facts import service as craft

        return [
            (f"工艺：{fact.claim[:60]}", _tokens(f"{fact.topic} {fact.claim} {fact.detail or ''}"))
            for fact in craft.approved_facts(db)
        ]
    except Exception:  # noqa: BLE001 - 事实源缺席不该让雷达崩
        logger.exception("craft-fact corpus unavailable")
        return []


def _product_corpus(db: Session) -> list[tuple[str, set[str]]]:
    try:
        from ...k_series.product_knowledge.models import KProductKnowledgeProduct

        out: list[tuple[str, set[str]]] = []
        rows = db.execute(
            select(
                KProductKnowledgeProduct.product_name_en,
                KProductKnowledgeProduct.primary_keyword,
                KProductKnowledgeProduct.structured_specs_json,
            )
        ).all()
        for name, keyword, specs in rows:
            blob = f"{name or ''} {keyword or ''} {specs or ''}"
            out.append((f"产品：{str(name or '')[:40]}", _tokens(blob)))
        return out
    except Exception:  # noqa: BLE001
        logger.exception("product corpus unavailable")
        return []


def _store_type_corpus(db: Session) -> list[tuple[str, set[str]]]:
    try:
        from ...b2b.store_types.models import B2BStoreType, B2BStoreTypeCategory

        out: list[tuple[str, set[str]]] = []
        prefixes: dict[Any, list[str]] = {}
        for row in db.execute(select(B2BStoreTypeCategory)).scalars():
            prefixes.setdefault(row.store_type_id, []).append(str(row.category_key))
        for store in db.execute(select(B2BStoreType)).scalars():
            blob = f"{store.key} {store.label} " + " ".join(prefixes.get(store.id, []))
            out.append((f"店型：{store.label}", _tokens(blob)))
        return out
    except Exception:  # noqa: BLE001 - B2B 表可能还没建
        logger.exception("store-type corpus unavailable")
        return []


class FactMatcher:
    """一次性载入三源,之后逐题纯内存匹配(同 GeoReachability 的理由)。"""

    def __init__(self, db: Session) -> None:
        self.sources = {
            "craft": _craft_corpus(db),
            "product": _product_corpus(db),
            "store_type": _store_type_corpus(db),
        }

    def support_for(self, keyword: str, *, audience: str = "consumer") -> dict[str, Any]:
        """{"supported": [...], "missing": [...], "has_support": bool}

        **判据按受众分,不是一套词面匹配走天下**——2026-07-30 首跑踩到:
        采购词("gift shop wholesale minimum order quantity")和工艺库/产品库
        一个词都不重叠,于是 25 条 B 端选题全被判成无支撑、分数 0、永远写不了。
        但采购方要的支撑根本不是词面重叠,是**"你们到底有没有工厂、有没有这类
        产品"**。所以:

        - C 端:词面重叠(它问的就是某个具体品类的事,对不上就是真没得写)
        - B 端:有任何已批准工艺事实 **或** 有任何产品,就算有支撑
        - 品牌/工艺:有工艺事实就算有支撑

        ``missing`` 说的是**缺哪一类事实**,不是"没救了":看到「缺工艺事实」
        就去录工艺,看到「缺产品事实」就去 K 补规格。
        """
        want = _tokens(keyword)
        supported: list[str] = []
        hit_sources: list[str] = []
        for source, corpus in self.sources.items():
            best: tuple[int, str] | None = None
            for label, tokens in corpus:
                overlap = len(want & tokens)
                if overlap >= 2 and (best is None or overlap > best[0]):
                    best = (overlap, label)
            if best is not None:
                hit_sources.append(source)
                supported.append(best[1])

        has_craft = bool(self.sources.get("craft"))
        has_product = bool(self.sources.get("product"))

        if audience == "wholesale":
            has_support = has_craft or has_product
            if has_support and not supported:
                supported = [
                    f"整厂能力：{len(self.sources['craft'])} 条工艺事实、"
                    f"{len(self.sources['product'])} 个在产产品"
                ]
            missing = [] if has_support else ["工艺事实或产品事实（两者至少要有一样）"]
        elif audience == "brand":
            has_support = has_craft
            if has_support and not supported:
                supported = [f"工艺库：{len(self.sources['craft'])} 条已批准事实"]
            missing = [] if has_support else ["工艺事实（去 SEO 工艺库录）"]
        else:
            has_support = bool(hit_sources)
            missing = []
            if "craft" not in hit_sources:
                missing.append("工艺事实（去 SEO 工艺库录）")
            if "product" not in hit_sources:
                missing.append("产品事实（去 K 补规格/卖点）")

        return {
            "supported": supported,
            "sources": hit_sources,
            "missing": missing,
            # 三源全空 = 写出来只能是空话。这类题不进队列。
            "has_support": has_support,
        }


__all__ = ["FactMatcher"]
