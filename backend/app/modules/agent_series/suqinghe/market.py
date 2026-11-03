"""竞品拆解(10-27):建档之后、跑关键词之前,她去谷歌搜同类商品页,一页页读,拆出买家在乎什么,用进 K。

硬线:K 的证据门规定卖点和文案只能写我们自己有事实的说法——这里产出的全是「市场情报」:
对方强调什么、按什么顺序讲、答买家哪些问题、价格带、关键词;**不产出任何关于我们产品的新事实**,一句原话不抄,品牌不进文案。
用法(pipeline._step_market):
- 搜:Serper /search(gl=us)取前 8–10 个商品页(排掉平台和内容站,一个域名一页;亚马逊的数据选品卡上已经有),顺手收相关搜索/PAA。
- 抓:common/webpage.read 一页页读(页间隔几秒,单页超时短),JSON-LD Product 先确定性抽,再让 fast 档模型从正文抽卖点/说法/FAQ。
- 拆:judge 档读所有页摘要 + 我们的档案事实 → 买家最在乎的事、我们有无、建议卖点顺序、四簇关键词、竞品名单、缺的事实。
- 用:种子关键词和竞品名单进 K 的关键词工作流;卖点按建议顺序排;读稿时核对有没有讲到买家在乎的;缺的事实上卡、记观察。
失败(搜不到、抓不到、模型不回)→ 这一步标 skipped,流水线照常往下,不发「卡住」卡;台账 sqh_serper_search / sqh_page_fetch。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..common import webpage
from .constants import MARKET_CARD_KIND, USAGE_LABEL, market_pages, page_gap_seconds
from .scoring import BRAND_TERMS

logger = logging.getLogger(__name__)
MARKET_USAGE_LABEL = f"{USAGE_LABEL}.market"
PAGE_TIMEOUT_S = 20.0
MIN_PAGES = 3
MAX_SEEDS = 30
PER_CLUSTER = 10
TEXT_FOR_MODEL = 12_000
# 平台、内容站、社交站不进「商品页」名单:亚马逊的数据走 Rainforest/Keepa,别的要么不是商品页要么抓不动
PLATFORM_HOSTS = (
    "amazon.", "ebay.", "walmart.", "aliexpress.", "alibaba.", "1688.", "temu.", "shein.", "etsy.", "target.", "homedepot.", "lowes.",
    "wayfair.", "overstock.", "bestbuy.", "costco.", "samsclub.", "youtube.", "reddit.", "pinterest.", "facebook.", "instagram.", "tiktok.",
    "wikipedia.", "quora.", "medium.", "nytimes.", "wirecutter", "outdoorgearlab", "gearjunkie", "bhphotovideo.", "newegg.", "dhgate.", "wish.",
)

FetchFn = Callable[[str], webpage.Page]
ModelFn = Callable[[Session, str, str], Any]


# ---------------------------------------------------------------- 搜


def search_pages(db: Session, *, org_id: str, query: str, limit: int | None = None) -> dict[str, Any]:
    """谷歌搜同类商品页。返回 {pages:[{url,title,snippet,domain}], serp_keywords:[...]} 或 {error}。走台账 sqh_serper_search。"""
    from r_system_v2.core.secret_manager import SecretManager
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_SERPER_SEARCH, RAQuotaExhaustedError, refund, try_consume

    from ...f_series.enrichment import serper_client

    query = " ".join(str(query or "").split())
    if not query:
        return {"error": "没有能搜的英文词"}
    key = str(SecretManager(db_session=db).get_key("serper", org_id) or "").strip()
    if not key:
        return {"error": "Serper 钥匙没绑"}
    try:
        try_consume(db, PROVIDER_SQH_SERPER_SEARCH, amount=1)
    except RAQuotaExhaustedError:
        return {"error": "今天她的谷歌搜索额度用完了"}
    db.commit()
    try:
        raw = serper_client.serper_search(api_key=key, query=query)
    except Exception as exc:  # noqa: BLE001 —— 出网失败退额度,原因带回去
        refund(db, PROVIDER_SQH_SERPER_SEARCH, amount=1)
        db.commit()
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:120]}"}
    pages = shop_pages(raw, limit=limit or market_pages())
    keywords = [str(k.get("keyword_text") or "").strip().lower() for k in serper_client.extract_keywords(raw) if isinstance(k, dict)]
    return {"query": query, "pages": pages, "serp_keywords": [k for k in dict.fromkeys(keywords) if k and len(k) <= 80][:20]}


def shop_pages(raw: dict[str, Any], *, limit: int) -> list[dict[str, str]]:
    """搜索结果 → 商品页名单:排掉平台/内容站,一个域名一页,按排名。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw.get("organic") if isinstance(raw.get("organic"), list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "").strip()
        if not url.startswith("http"):
            continue
        domain = webpage.registrable_domain(url)
        if not domain or domain in seen or is_platform(domain):
            continue
        seen.add(domain)
        out.append({"url": url, "title": str(item.get("title") or "")[:200], "snippet": str(item.get("snippet") or "")[:300], "domain": domain})
        if len(out) >= limit:
            break
    return out


def is_platform(domain: str) -> bool:
    d = domain.lower()
    return any(d.startswith(h) or f".{h}" in f".{d}" for h in PLATFORM_HOSTS)


# ---------------------------------------------------------------- 抓 + 抽


EXTRACT_ASK = (
    "下面是一个美国网店的商品页正文(可能夹着导航和页脚)。只按页面上写的抽,不翻译、不补充、不评价,只输出 JSON:\n"
    '{"title": "商品标题", "price": 数字或 null(美元), "bullets": ["卖点原句,最多 8 条,一条一句"], '
    '"claims": ["页面强调的功能/参数/材质/认证/保修这类说法,短语,最多 10 条"], "faq": [{"q": "问题", "a": "答案一句"}](最多 8 条), '
    '"sections": ["正文小标题,最多 8 个"], "image_count": 数字或 null}'
)


def extract_page(page: webpage.Page, fast: ModelFn, db: Session) -> dict[str, Any]:
    """一页 → 摘要。JSON-LD 先确定性抽;正文交给 fast 档模型抽卖点/说法/FAQ。"""
    from .brain import parse_json

    products = webpage.jsonld_products(page.html)
    ld = products[0] if products else {}
    summary: dict[str, Any] = {
        "url": page.final_url or page.url,
        "domain": page.domain,
        "title": (ld.get("name") or page.title or "")[:200],
        "price": ld.get("price"),
        "currency": ld.get("currency") or "",
        "brand": ld.get("brand") or "",
        "rating": ld.get("rating"),
        "review_count": ld.get("review_count"),
        "image_count": ld.get("image_count") or webpage.image_count(page.html) or None,
        "bullets": [],
        "claims": [],
        "faq": [],
        "sections": [],
        "via": page.via,
        "ok": page.ok,
    }
    text = (page.text or "")[:TEXT_FOR_MODEL]
    if not text:
        summary["ok"] = False
        return summary
    try:
        data = parse_json(fast(db, EXTRACT_ASK, f"页面地址:{summary['url']}\n正文:\n{text}"))
    except Exception as exc:  # noqa: BLE001 —— 一页抽不出不影响别的页
        logger.warning("market extract failed url=%s: %s", page.url, exc)
        data = None
    if isinstance(data, dict):
        summary["title"] = summary["title"] or _clean(data.get("title"))[:200]
        if summary["price"] is None:
            summary["price"] = webpage._number(data.get("price"))
        summary["bullets"] = _strs(data.get("bullets"), 8, 200)
        summary["claims"] = _strs(data.get("claims"), 10, 120)
        summary["faq"] = [
            {"q": _clean(f.get("q"))[:200], "a": _clean(f.get("a"))[:300]}
            for f in (data.get("faq") if isinstance(data.get("faq"), list) else [])
            if isinstance(f, dict) and _clean(f.get("q"))
        ][:8]
        summary["sections"] = _strs(data.get("sections"), 8, 100)
        if summary["image_count"] is None:
            summary["image_count"] = webpage._number(data.get("image_count"))
    return summary


def _clean(value: Any) -> str:
    return " ".join(str(value).split()).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _strs(value: Any, limit: int, width: int) -> list[str]:
    out = [_clean(v)[:width] for v in (value if isinstance(value, list) else []) if isinstance(v, str)]
    return [v for v in dict.fromkeys(out) if v][:limit]


# ---------------------------------------------------------------- 拆


SUMMARY_ASK = (
    "你是苏青禾,美国独立站 Barong Yekhna 的运营总管。下面是同类商品在美国几家网店的商品页摘要,和我们这件商品的档案事实。"
    "把别人家的页面拆开看:买家最在乎的是什么、他们按什么顺序讲、回答了什么问题、用什么词搜——然后对照我们的事实。\n"
    "铁规矩:你只总结别人强调什么,**不能替我们的产品编任何新事实**;我们有没有,只按档案事实判;拿不准就放进 missing/gaps。"
    "关键词里不能带任何品牌名、型号、店名。\n"
    "只输出 JSON:\n"
    '{"priorities": [{"what": "买家最在乎的一件事(中文)", "why": "从哪几家页面看出来的(中文一句)"}](3–5 条,按重要程度),\n'
    ' "ours": {"has": ["我们档案里有、可以讲的(中文短语)"], "missing": ["买家在乎但我们档案里没有事实的(中文短语)"]},\n'
    ' "bullet_order_hint": ["建议卖点讲的顺序,用主题短语(英文,2–4 词),最多 6 条"],\n'
    ' "keywords": {"category": ["品类词(英文小写,2–4 词)"], "attribute": ["属性/参数词"], "scene": ["场景/人群词"], "question": ["买家会搜的问题句"]}(每簇最多 10 条),\n'
    ' "competitors": {"brands": ["页面上出现的品牌名"], "domains": ["店的域名"]},\n'
    ' "gaps": ["要问老板或工厂才能补的事实,中文一句一条,最多 6 条"],\n'
    ' "note": "一句中文:这批竞品整体怎么样、我们机会在哪"}'
)


def pages_prompt(pages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, p in enumerate(pages, start=1):
        if not p.get("ok"):
            continue
        price = f"${p['price']:.2f}" if isinstance(p.get("price"), (int, float)) else "价格没抓到"
        lines.append(f"第 {i} 家 {p.get('domain')}:{p.get('title')} | {price} | 图 {p.get('image_count') or '?'} 张" + (f" | 品牌 {p['brand']}" if p.get("brand") else ""))
        for b in p.get("bullets") or []:
            lines.append(f"  卖点:{b}")
        for c in p.get("claims") or []:
            lines.append(f"  说法:{c}")
        for f in p.get("faq") or []:
            lines.append(f"  问答:{f.get('q')} → {f.get('a')}")
        if p.get("sections"):
            lines.append("  小标题:" + " / ".join(p["sections"]))
    return "\n".join(lines)


def parse_summary(result: Any, *, domains: list[str]) -> dict[str, Any]:
    """模型的拆解 → 只认形状对的,关键词去品牌、去重、封顶。"""
    from .brain import parse_json

    data = parse_json(result) or {}
    data = data if isinstance(data, dict) else {}
    priorities = [
        {"what": _clean(p.get("what"))[:120], "why": _clean(p.get("why"))[:200]}
        for p in (data.get("priorities") if isinstance(data.get("priorities"), list) else [])
        if isinstance(p, dict) and _clean(p.get("what"))
    ][:5]
    ours = data.get("ours") if isinstance(data.get("ours"), dict) else {}
    comp = data.get("competitors") if isinstance(data.get("competitors"), dict) else {}
    brands = [b for b in _strs(comp.get("brands"), 20, 60) if len(b) >= 2]
    comp_domains = [d.lower() for d in _strs(comp.get("domains"), 20, 80)]
    comp_domains = [d for d in dict.fromkeys([*comp_domains, *domains]) if d]
    # 只按品牌名过滤;店的域名词干("store"、"outdoor")太像普通词,会把正常关键词误杀,不拿它当黑名单
    banned = {b.lower() for b in brands} | set(BRAND_TERMS)
    # 11-03 放行词表:别家页面的牌子正好是老板放行过的普通词(比如也叫 Panda),不能因此把我们带 panda 的关键词全滤掉
    from ...k_series.product_knowledge import brand_allow

    banned = {b for b in banned if not brand_allow.is_covered(b)}
    kw_in = data.get("keywords") if isinstance(data.get("keywords"), dict) else {}
    keywords = {cluster: _keywords(kw_in.get(cluster), banned) for cluster in ("category", "attribute", "scene", "question")}
    return {
        "priorities": priorities,
        "ours": {"has": _strs(ours.get("has"), 12, 120), "missing": _strs(ours.get("missing"), 12, 120)},
        "bullet_order_hint": _keywords(data.get("bullet_order_hint"), banned, limit=6),
        "keywords": keywords,
        "competitors": {"brands": brands, "domains": comp_domains},
        "gaps": _strs(data.get("gaps"), 6, 200),
        "note": _clean(data.get("note"))[:300],
    }


_KW_OK = re.compile(r"^[a-z0-9][a-z0-9 \-'?,]{1,78}$")


def _keywords(value: Any, banned: set[str], *, limit: int = PER_CLUSTER) -> list[str]:
    out: list[str] = []
    for raw in (value if isinstance(value, list) else []):
        kw = " ".join(_clean(raw).lower().split())
        if not kw or not _KW_OK.match(kw) or len(kw.split()) > 12:
            continue
        if any(b and re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", kw) for b in banned):
            continue
        if kw not in out:
            out.append(kw)
        if len(out) >= limit:
            break
    return out


def seed_keywords(market: dict[str, Any]) -> list[str]:
    """给 K 关键词工作流的种子:品类词 + 属性词 + 场景词(问题句太长,不当种子),最多 MAX_SEEDS。"""
    kw = market.get("keywords") if isinstance(market.get("keywords"), dict) else {}
    seeds: list[str] = []
    for cluster in ("category", "attribute", "scene"):
        for k in kw.get(cluster) or []:
            if isinstance(k, str) and k and k not in seeds:
                seeds.append(k)
    return seeds[:MAX_SEEDS]


def competitor_names(market: dict[str, Any]) -> list[str]:
    comp = market.get("competitors") if isinstance(market.get("competitors"), dict) else {}
    names = [*(comp.get("brands") or []), *(comp.get("domains") or [])]
    return [str(n) for n in dict.fromkeys(names) if str(n).strip()][:50]


def reorder_bullets(review: list[dict[str, Any]], hint: list[str]) -> list[dict[str, Any]]:
    """按「买家最在乎」的主题顺序给卖点排序:每条卖点按最早命中的主题排前,命不中的保持原序排后。"""
    if not hint:
        return list(review)
    themes = [set(re.findall(r"[a-z0-9]+", str(h).lower())) - _STOP for h in hint]

    def rank(item: dict[str, Any]) -> int:
        words = set(re.findall(r"[a-z0-9]+", str(item.get("text") or "").lower()))
        for i, theme in enumerate(themes):
            if theme and len(theme & words) >= max(1, len(theme) // 2):
                return i
        return len(themes)

    return sorted(review, key=rank)  # sorted 稳定:同一档保持原序


_STOP = {"the", "a", "an", "and", "or", "for", "with", "of", "to", "in", "on", "is", "it", "your", "you"}


# ---------------------------------------------------------------- 整段:搜 → 抓 → 抽 → 拆


def research(
    db: Session,
    *,
    org_id: str,
    query: str,
    brief: str,
    fetch: FetchFn | None = None,
    fast: ModelFn | None = None,
    judge: ModelFn | None = None,
    gap_seconds: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一次完整拆解。永不抛:出错 → {"status": "skipped", "reason": ...}。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_PAGE_FETCH, RAQuotaExhaustedError, try_consume

    fetch = fetch or (lambda url: webpage.read(url, timeout_s=PAGE_TIMEOUT_S))
    fast = fast or _default_fast
    judge = judge or _default_judge
    gap = page_gap_seconds() if gap_seconds is None else gap_seconds
    at = (now or datetime.now(UTC)).isoformat()
    found = search_pages(db, org_id=org_id, query=query)
    if found.get("error"):
        return {"status": "skipped", "reason": f"搜不了:{found['error']}", "query": query, "at": at}
    pages: list[dict[str, Any]] = []
    for i, hit in enumerate(found["pages"]):
        try:
            try_consume(db, PROVIDER_SQH_PAGE_FETCH, amount=1)
        except RAQuotaExhaustedError:
            pages.append({**hit, "ok": False, "error": "今天抓页额度用完了"})
            break
        db.commit()
        if i and gap > 0:
            time.sleep(gap)
        page = fetch(hit["url"])
        if not page.ok:
            pages.append({**hit, "ok": False, "error": ("被拦(验证码/拒绝访问)" if page.blocked else page.error or "没拿到正文")})
            continue
        pages.append({**hit, **extract_page(page, fast, db)})
    ok_pages = [p for p in pages if p.get("ok")]
    if len(ok_pages) < MIN_PAGES:
        return {"status": "skipped", "reason": f"只读到 {len(ok_pages)} 页(至少 {MIN_PAGES} 页才拆)", "query": query, "pages": _slim_pages(pages), "serp_keywords": found.get("serp_keywords") or [], "at": at}
    try:
        result = judge(db, SUMMARY_ASK, f"我们这件商品的档案事实:\n{brief}\n\n同类商品页摘要:\n{pages_prompt(pages)}")
    except Exception as exc:  # noqa: BLE001 —— 模型不回就跳过,不挡品
        return {"status": "skipped", "reason": f"拆解没做成:{exc.__class__.__name__}: {str(exc)[:120]}", "query": query, "pages": _slim_pages(pages), "serp_keywords": found.get("serp_keywords") or [], "at": at}
    summary = parse_summary(result, domains=[p["domain"] for p in ok_pages])
    if not summary["priorities"] and not any(summary["keywords"].values()):
        return {"status": "skipped", "reason": "拆解的结果不合规矩(没有要点也没有关键词)", "query": query, "pages": _slim_pages(pages), "serp_keywords": found.get("serp_keywords") or [], "at": at}
    return {"status": "done", "query": query, "pages": _slim_pages(pages), "serp_keywords": found.get("serp_keywords") or [], **summary, "at": at}


def _slim_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """卡上和档案里留的每页信息:不留正文。"""
    out = []
    for p in pages:
        out.append(
            {
                "url": str(p.get("url") or "")[:300],
                "domain": str(p.get("domain") or ""),
                "title": str(p.get("title") or "")[:160],
                "ok": bool(p.get("ok")),
                "error": str(p.get("error") or "")[:120] or None,
                "price": p.get("price") if isinstance(p.get("price"), (int, float)) else None,
                "brand": str(p.get("brand") or "")[:60],
                "bullets": int(len(p.get("bullets") or [])),
                "faq": int(len(p.get("faq") or [])),
                "image_count": int(p["image_count"]) if isinstance(p.get("image_count"), (int, float)) else None,
                "highlight": (p.get("bullets") or [""])[0][:160] if p.get("bullets") else "",
                "claims": [str(c)[:120] for c in (p.get("claims") or [])][:6],
            }
        )
    return out


def _default_fast(db: Session, ask: str, extra: str) -> Any:
    from . import brain

    db.commit()
    return brain._execute("fast", [{"role": "user", "content": f"{ask}\n\n{extra}"}], timeout=90.0, usage_label=MARKET_USAGE_LABEL)


def _default_judge(db: Session, ask: str, extra: str) -> Any:
    from . import brain

    role = brain.plan_role(db)
    db.commit()
    return brain._execute(role, [{"role": "user", "content": f"{ask}\n\n{extra}"}], timeout=180.0, usage_label=MARKET_USAGE_LABEL)


# ---------------------------------------------------------------- 拆解卡


def card_text(market: dict[str, Any], *, sku: str, product_name: str) -> dict[str, Any]:
    pages = [p for p in market.get("pages") or [] if p.get("ok")]
    prices = [p["price"] for p in pages if isinstance(p.get("price"), (int, float))]
    price_text = f",价格 ${min(prices):.0f}–${max(prices):.0f}" if prices else ""
    kw = market.get("keywords") or {}
    n_kw = sum(len(v) for v in kw.values() if isinstance(v, list))
    priorities = [p.get("what", "") for p in market.get("priorities") or []]
    ours = market.get("ours") or {}
    lines = [
        *[f"买家最在乎 {i}:{p.get('what')}——{p.get('why')}" for i, p in enumerate(market.get("priorities") or [], start=1)],
        *([f"我们有、可以讲:{'、'.join(ours.get('has') or [])}"] if ours.get("has") else []),
        *([f"买家在乎但我们档案里没有:{'、'.join(ours.get('missing') or [])}"] if ours.get("missing") else []),
        *([f"要问你或工厂的:{';'.join(market.get('gaps') or [])}"] if market.get("gaps") else []),
        *([f"竞品:{'、'.join(competitor_names(market)[:10])}"] if competitor_names(market) else []),
        *([market.get("note", "")] if market.get("note") else []),
    ]
    return {
        "title": f"{sku} 竞品拆解:{len(pages)} 家同类页"[:60],
        "conclusion": (
            f"我读了 {len(pages)} 家美国网店的同类商品页{price_text},拆出买家最在乎的 {len(priorities)} 件事和 {n_kw} 个关键词,已经用进关键词研究和卖点顺序。"
            "这张卡给你看,不用批;驳回我就撤掉这份市场信息、重跑关键词。"
        ),
        "why": "\n".join(line for line in lines if line),
        "if_not": "不驳就照这份情报往下做;驳了只影响关键词种子和卖点顺序,不碰事实。",
        "confidence": "high" if len(pages) >= 6 and priorities else "medium",
        "evidence": {
            "sku": sku,
            "product_name": product_name,
            "query": market.get("query"),
            "pages": market.get("pages") or [],
            "priorities": market.get("priorities") or [],
            "ours": ours,
            "bullet_order_hint": market.get("bullet_order_hint") or [],
            "keywords": kw,
            "competitors": market.get("competitors") or {},
            "gaps": market.get("gaps") or [],
            "serp_keywords": market.get("serp_keywords") or [],
            "note": market.get("note") or "",
            "at": market.get("at"),
        },
    }



__all__ = [
    "EXTRACT_ASK",
    "MARKET_CARD_KIND",
    "MARKET_USAGE_LABEL",
    "SUMMARY_ASK",
    "card_text",
    "competitor_names",
    "extract_page",
    "is_platform",
    "pages_prompt",
    "parse_summary",
    "reorder_bullets",
    "research",
    "search_pages",
    "seed_keywords",
    "shop_pages",
]
