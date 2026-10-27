"""第⑥步:她自己找货(10-27)。

货从哪来:F 系列(找货页)的候选池——1688 链接、进价、起订量、月销、图都在,只缺重量(批了开详情页核实)。
先把这池子挑完,不重新搜 1688、不花图搜额度;池子空了再做下一步(按类目自己去补货)。

每天怎么挑:早间计划排完后挑一次。候选按 F 的分(起订量/月销/一件代发/价位)排好,挑出来的交给她判:
露营户外、轻小件、起订量小、进价放得进美国同类价;刀具/驱蚊药片/液体气罐/别人品牌/定制加印的不要。
每个挑中的查一次谷歌购物(走台账 sqh_serper_shopping),卡上写美国同类中位价。
一张卡一个候选(dedupe_key = candidate:<F 候选 id>,同一个候选永远只发一次);一天最多 picks_per_day 张,
老板没处理的攒到 picks_max_pending 张就不再发。

批 → F 候选标 approved,同一个链接按第①步排队建档(建档卡再批一次:写进 K 的内容还是要过目)。
驳 → F 候选标 rejected、原因写进去;老板批过驳过的候选和原因都在记忆里,下次挑之前先看一遍。
建进 K 之后 → F 候选标 imported_to_k 并记上 K 产品 id(F 页面上看得到这个品的去向)。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...f_series.enrichment.models import FCategoryCandidate
from . import amazon_signals, cards, dossiers, memory, office, pricing, scoring
from .constants import CANDIDATE_CARD_KIND, FACTORY_BRIEF, USAGE_LABEL, pick_min_score, picks_max_pending, picks_per_day, weight_class_kg
from .models import SqhCard, SqhDossier

logger = logging.getLogger(__name__)

_X = SKIP_ORG_DATA_ISOLATION
PICKS_USAGE_LABEL = f"{USAGE_LABEL}.picks"
POOL_LIMIT = 40  # 一次给她看多少个候选(按分数取前面的,一个类目最多 PER_CATEGORY 个,别让一个类目霸屏)
PER_CATEGORY = 8
JUDGE_TIMEOUT_SECONDS = 150.0
_DETAIL_URL = re.compile(r"^https?://detail\.1688\.com/offer/(\d+)\.html", re.I)
_US_QUERY_OK = re.compile(r"^[a-z0-9][a-z0-9 \-]{1,58}[a-z0-9]$")
_HYPE_WORDS = {"best", "top", "cheap", "cheapest", "strongest", "rated", "no.1", "#1", "2025", "2026", "2027"}

JudgeFn = Callable[[Session, str, str], Any]
ShoppingFn = Callable[[Session, str], dict[str, Any]]
AmazonFn = Callable[[Session, str], dict[str, Any]]
KeepaFn = Callable[[Session, list[str]], tuple[list[dict[str, Any]], str | None]]
SHORTLIST_MAX = 6  # 初筛最多留几个去取数据打分(每个要查谷歌购物 + 亚马逊 + Keepa,别浪费额度)


@dataclass(frozen=True)
class Pick:
    f_candidate_id: str
    reason: str
    risks: tuple[str, ...]
    us_query: str
    weight_class: str = "medium"  # light / medium / heavy(她按常识判;F 池没有真重量)
    flags: tuple[str, ...] = ()  # scoring.VETO_FLAGS / DEDUCT_FLAGS 里的词
    factory_pts: int = 5  # 和工厂的关系 0–15
    factory_why: str = ""


# ---------------------------------------------------------------- 候选池


def offer_id_of(url: str | None) -> str | None:
    """F 的候选只有链接没有 offer id;s.click 短链不认(开不了详情页)。"""
    match = _DETAIL_URL.match((url or "").strip())
    return match.group(1) if match else None


def _taken_offer_ids(db: Session) -> set[str]:
    """已经在她手上的 offer:排过队的档案(不管批没批)+ 已经建进 K 的。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P
    from .executor import SOURCE_SYSTEM

    taken = {str(v) for v in db.scalars(select(SqhDossier.offer_id), execution_options=_X) if v}
    taken |= {
        str(v)
        for v in db.scalars(select(P.source_record_id).where(P.source_system == SOURCE_SYSTEM), execution_options=_X)
        if v
    }
    return taken


def _carded_ids(db: Session) -> set[str]:
    rows = db.scalars(select(SqhCard.dedupe_key).where(SqhCard.kind == CANDIDATE_CARD_KIND), execution_options=_X)
    return {str(key).split(":", 1)[1] for key in rows if key and ":" in str(key)}


def pool(db: Session, *, limit: int = POOL_LIMIT, per_category: int = PER_CATEGORY) -> list[FCategoryCandidate]:
    """F 池里还没发过卡、还没在她手上、能开详情页、没踩 F 红线的候选,按 F 的分从高到低,一个类目最多 per_category 个。"""
    rows = db.scalars(
        select(FCategoryCandidate)
        .where(FCategoryCandidate.status == "pending_review", FCategoryCandidate.automation_blocked.is_(False))
        .order_by(FCategoryCandidate.score.desc().nulls_last(), FCategoryCandidate.recommended_rank.asc().nulls_last(), FCategoryCandidate.created_at.desc()),
        execution_options=_X,
    ).all()
    carded, taken = _carded_ids(db), _taken_offer_ids(db)
    picked: list[FCategoryCandidate] = []
    per_cat: dict[str, int] = {}
    seen_offers: set[str] = set()
    for row in rows:
        offer_id = offer_id_of(row.source_url)
        if not offer_id or offer_id in taken or offer_id in seen_offers or str(row.id) in carded:
            continue
        if per_cat.get(row.category_id, 0) >= per_category:
            continue
        per_cat[row.category_id] = per_cat.get(row.category_id, 0) + 1
        seen_offers.add(offer_id)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _category_tail(path: str | None, parts: int = 2) -> str:
    bits = [p.strip() for p in str(path or "").split(">") if p.strip()]
    return " > ".join(bits[-parts:]) if bits else ""


def candidate_line(row: FCategoryCandidate) -> str:
    sales = (row.score_json or {}).get("monthly_sales") if isinstance(row.score_json, dict) else None
    return (
        f"- id={row.id} | {row.title[:60]} | 类目:{_category_tail(row.category_path)} | 画像:{row.profile_product_en or '-'}"
        f" | 进价 ¥{row.price_cny if row.price_cny is not None else '?'} | 起订 {row.moq or '?'} | 月销 {sales if sales is not None else '?'} | F 分 {row.score or '?'}"
    )


# ---------------------------------------------------------------- 她的判断


_PICK_ASK = (
    "你是独立站(面向美国买家)的运营总管,在给老板初筛今天值得上架的新品候选。下面是找货池里按分数排好的 1688 候选,"
    "只能从里面挑,最多留 {limit} 个(留下的我会再去查美国同类价、亚马逊销量和竞争,按评分卡打分,过线的才发给老板);"
    "宁缺毋滥,没有合适的就给空数组。\n"
    "要的:露营户外、和店里已有的类目相近;起订量 1–2;轻小件(常识判断——帐篷、床垫、桌椅、炉具这类大件不要);"
    "进价换成美元后在美国同类价里放得进 30% 以上毛利(美国同类价你先按常识估)。\n"
    "不要的:标题带别人的品牌或型号(Coleman、Stanley、Thermacell、YETI、Ozark Trail 这类);刀具、防身、武器;"
    "需要 EPA/FDA 的(驱蚊药片、杀虫剂、入口的、医疗的);液体、气罐、压缩气体;定制、加印、定做;儿童用品;店里已经有的同类;"
    "和老板之前驳过的那种类似的。\n"
    "工厂能力(判「和工厂的关系」用):" + FACTORY_BRIEF + "\n"
    "每个留下的给:reason(一句中文,为什么值得,说人话、别夸);risks(一条一句中文:带电/锂电池、带磁、易碎、"
    "季节性、尺寸可能偏大、材质或认证要核实之类,没有就空数组);us_query(美国买家在 Google 搜这类东西的英文品类词,"
    "2–4 个小写单词,不带品牌,用来查同类价和亚马逊);weight_class(light / medium / heavy,按常识估这件东西连包装的重量:"
    "light 不到半公斤,medium 半公斤到两公斤,heavy 两公斤以上);flags(从这些词里选,没有就空数组:"
    "battery 带电/锂电池、magnet 带磁、pressure 带压、fragile 易碎、seasonal 季节性、liquid 液体、gas 气罐、custom 定制加印、"
    "epa_fda 需要 EPA/FDA、knife 刀具武器、child 儿童用品、brand 带别人品牌、oversize 大件);"
    "factory_fit(pts 0–15:能自己组装/换外观/做套装 12–15,改改包装或配件 8–11,只能原样转卖 3–5;why 一句中文)。\n"
    'Reply JSON only: {{"picks": [{{"id": "<候选 id>", "reason": "...", "risks": ["..."], "us_query": "...", "weight_class": "light", '
    '"flags": [], "factory_fit": {{"pts": 10, "why": "..."}}}}], "note": "一句中文:这批候选整体怎么样(可空)"}}'
)


def _store_brief(db: Session) -> str:
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    rows = db.execute(
        select(P.sku, P.product_name_en, P.product_status).order_by(P.created_at.desc()).limit(40),
        execution_options=_X,
    ).all()
    lines = [f"- {sku}:{(name or '')[:50]}({status})" for sku, name, status in rows]
    return "店里已有的品(别挑同类):\n" + ("\n".join(lines) if lines else "- (还没有)")


def _boss_history(db: Session, *, limit: int = 20) -> str:
    rows = memory.recent(db, limit=200, kinds=("decision",))
    lines = []
    for row in rows:
        refs = row.refs if isinstance(row.refs, dict) else {}
        if refs.get("kind") != CANDIDATE_CARD_KIND:
            continue
        lines.append(f"- {row.body[:160]}")
        if len(lines) >= limit:
            break
    hints = [f"- {row.body[:160]}" for row in memory.relevant(db, "选品 找货 候选 新品 不要", limit=6)]
    text = "老板对之前选品卡的决定(照着避、照着挑):\n" + ("\n".join(lines) if lines else "- (还没有)")
    if hints:
        text += "\n老板交代过的相关话:\n" + "\n".join(hints)
    return text


def _default_judge(db: Session, ask: str, extra: str) -> Any:
    from . import brain

    role = brain.plan_role(db)  # 她当天 Claude 额度用完就降到便宜档
    db.commit()  # 出网前放掉事务
    return brain._execute(role, [{"role": "user", "content": f"{ask}\n\n{extra}".strip()}], timeout=JUDGE_TIMEOUT_SECONDS, usage_label=PICKS_USAGE_LABEL)


def parse_picks(result: Any, *, pool_ids: set[str], limit: int, fallback_query: dict[str, str] | None = None) -> list[Pick]:
    """模型挑的 → 只认池子里有的,去重、截到 limit;us_query 不合规矩就用画像的英文名顶上,再不行就空(卡上写没比价)。"""
    from .brain import parse_json

    data = parse_json(result) or {}
    out: list[Pick] = []
    seen: set[str] = set()
    for item in data.get("picks") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid not in pool_ids or cid in seen:
            continue
        seen.add(cid)
        reason = str(item.get("reason") or "").strip()[:200]
        risks = tuple(str(r).strip()[:120] for r in (item.get("risks") or []) if isinstance(r, str) and str(r).strip())[:6]
        query = _clean_query(item.get("us_query")) or _clean_query((fallback_query or {}).get(cid))
        weight_class = str(item.get("weight_class") or "").strip().lower()
        if weight_class not in scoring.WEIGHT_CLASSES:
            weight_class = "medium"
        known = set(scoring.VETO_FLAGS) | set(scoring.DEDUCT_FLAGS)
        flags = tuple(dict.fromkeys(str(f).strip().lower() for f in (item.get("flags") or []) if isinstance(f, str) and str(f).strip().lower() in known))
        fit = item.get("factory_fit") if isinstance(item.get("factory_fit"), dict) else {}
        try:
            factory_pts = max(0, min(15, int(round(float(fit.get("pts"))))))
        except (TypeError, ValueError):
            factory_pts = 5
        out.append(
            Pick(
                f_candidate_id=cid,
                reason=reason or "值得试一下。",
                risks=risks,
                us_query=query,
                weight_class=weight_class,
                flags=flags,
                factory_pts=factory_pts,
                factory_why=str(fit.get("why") or "").strip()[:200],
            )
        )
        if len(out) >= limit:
            break
    return out


def _clean_query(value: Any) -> str:
    query = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if not _US_QUERY_OK.match(query) or any(word in query.split() for word in _HYPE_WORDS):
        return ""
    return query


# ---------------------------------------------------------------- 发卡


def _competitors_slim(stats: dict[str, Any]) -> dict[str, Any]:
    keep = {k: stats.get(k) for k in ("query", "n", "min", "p25", "median", "p75", "max", "error") if stats.get(k) is not None}
    return keep


def confidence_for(*, goods_usd: float | None, median: float | None, risks: int) -> str:
    """把握:美国同类中位价是进价的几倍。4 倍以上且没风险 = 高;不到 2.5 倍或风险一堆 = 低。"""
    if risks >= 3:
        return "low"
    if goods_usd and median:
        room = median / goods_usd
        if room < 2.5:
            return "low"
        if room >= 4 and risks == 0:
            return "high"
    return "medium"


def score_candidate(
    row: FCategoryCandidate,
    pick: Pick,
    *,
    shopping: dict[str, Any],
    amazon: dict[str, Any] | None,
    keepa: list[dict[str, Any]] | None,
    keepa_error: str | None,
    a: pricing.Assumptions,
) -> dict[str, Any]:
    """评分卡(scoring.scorecard 的薄封装:从 F 候选和初筛结果里取字段)。"""
    return scoring.scorecard(
        title=row.title or "",
        category_path=row.category_path,
        profile_en=row.profile_product_en,
        price_cny=float(row.price_cny) if row.price_cny is not None else None,
        weight_class=pick.weight_class,
        flags=pick.flags,
        factory_pts=pick.factory_pts,
        factory_why=pick.factory_why,
        shopping=shopping,
        amazon=amazon,
        keepa=keepa,
        keepa_error=keepa_error,
        a=a,
        kg_by_class=weight_class_kg(),
    )


def build_card_text(row: FCategoryCandidate, pick: Pick, competitors: dict[str, Any], a: pricing.Assumptions, card: dict[str, Any] | None = None, amazon: dict[str, Any] | None = None, keepa: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """卡上的话和证据(纯函数,测试直接验)。card = scoring.scorecard 的结果(没有就只按旧样子写)。"""
    price = float(row.price_cny) if row.price_cny is not None else None
    goods = round(price / a.usd_cny, 2) if price is not None else None
    sales = (row.score_json or {}).get("monthly_sales") if isinstance(row.score_json, dict) else None
    n = int(competitors.get("n") or 0)
    if n > 0:
        comp_text = f"美国同类({competitors.get('query')})中位 ${competitors.get('median')},一半在 ${competitors.get('p25')}–${competitors.get('p75')}"
    else:
        comp_text = "美国同类价没拿到" + (f"({competitors.get('error')})" if competitors.get("error") else "(没有能查的英文词)")
    facts = f"1688 进价 ¥{price if price is not None else '?'}" + (f"(≈${goods:.2f})" if goods is not None else "") + f",起订 {row.moq or '?'},月销 {sales if sales is not None else '?'}"
    score_text = f"评分 {card['total']}/{card['max']}" + (f"(没拿到:{'、'.join(card['missing'])})" if card.get("missing") else "") + ";" if card else ""
    conclusion = f"{score_text}{facts};{comp_text}。批了我就开详情页建档(先建草稿、不上架),建档卡再给你过目。"
    why = pick.reason
    if card:
        why += "\n" + "\n".join(scoring.lines(card))
    if pick.risks:
        why += "\n风险:" + "；".join(pick.risks)
    why += "\n重量和尺寸 1688 列表里没有,运费按估计重量算的;批了我开页面核实再算真账。"
    offer_id = offer_id_of(row.source_url) or ""
    return {
        "title": f"选品:{row.title[:24]}",
        "conclusion": conclusion,
        "why": why,
        "if_not": "不批就算了,这个品我不再提。",
        "confidence": scoring.confidence(card) if card else confidence_for(goods_usd=goods, median=competitors.get("median") if n > 0 else None, risks=len(pick.risks)),
        "evidence": {
            "scorecard": card,  # 评分卡(六维);下面的 score 是 F 池自己的分
            "amazon": amazon,
            "keepa": keepa or [],
            "weight_class": pick.weight_class,
            "flags": list(pick.flags),
            "f_candidate_id": str(row.id),
            "offer_id": offer_id,
            "source_url": row.source_url,
            "image_url": row.image_url,
            "title_zh": row.title,
            "category_path": row.category_path,
            "profile_product_en": row.profile_product_en,
            "price_cny": price,
            "goods_usd": goods,
            "moq": row.moq,
            "monthly_sales": sales,
            "score": row.score,
            "reason": pick.reason,
            "risks": list(pick.risks),
            "us_query": pick.us_query,
            "competitors": _competitors_slim(competitors),
            "recheck": {"type": CANDIDATE_CARD_KIND, "f_candidate_id": str(row.id)},
        },
    }


def _fingerprint(db: Session, recheck: dict[str, Any]) -> str:
    """老板在 F 页面上已经放行/驳回、或价变了 → 卡作废,她按新数据重看。"""
    row = db.get(FCategoryCandidate, UUID(str(recheck.get("f_candidate_id"))), execution_options=_X) if recheck.get("f_candidate_id") else None
    if row is None:
        return cards.fingerprint({"gone": True})
    return cards.fingerprint({"status": row.status, "price_cny": str(row.price_cny), "url": row.source_url})


cards.register_fingerprinter(CANDIDATE_CARD_KIND, _fingerprint)


def _default_shopping(db: Session, query: str) -> dict[str, Any]:
    from .executor import ExecutorError, _scope

    try:
        org_id = _scope(db).workspace_key
    except ExecutorError as exc:
        return {"query": query, "n": 0, "error": str(exc)}
    return pricing.fetch_shopping(db, query=query, org_id=org_id)


def _default_amazon(db: Session, query: str) -> dict[str, Any]:
    from .executor import ExecutorError, _scope

    try:
        org_id = _scope(db).workspace_key
    except ExecutorError as exc:
        return {"keyword": query, "error": str(exc)}
    return amazon_signals.competition(db, org_id=org_id, keyword=query)


def _default_keepa(db: Session, asins: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    from .executor import ExecutorError, _scope

    try:
        org_id = _scope(db).workspace_key
    except ExecutorError as exc:
        return [], str(exc)
    return amazon_signals.keepa_top(db, org_id=org_id, asins=asins)


def _set_activity(db: Session, activity: str, task: str) -> None:
    state = office.get_state(db)
    state.activity = activity
    state.task = task[:300]
    state.progress = None
    db.add(state)


def cards_today(db: Session, now: datetime) -> int:
    start, end = dossiers.la_day_bounds(now)
    return int(
        db.scalar(
            select(func.count()).select_from(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND, SqhCard.created_at >= start, SqhCard.created_at < end),
            execution_options=_X,
        )
        or 0
    )


def pending_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND, SqhCard.status == "pending"), execution_options=_X) or 0)


def run_picks(
    db: Session,
    *,
    now: datetime | None = None,
    judge: JudgeFn | None = None,
    shopping: ShoppingFn | None = None,
    amazon: AmazonFn | None = None,
    keepa: KeepaFn | None = None,
) -> dict[str, Any]:
    """挑一轮:初筛(她)→ 取数据(谷歌购物/亚马逊/Keepa)→ 评分卡 → 红线否决、过线的发卡。返回 {"cards": [refs], "skipped": 原因 | None, "scored": [...]}。"""
    now = now or datetime.now(UTC)
    quota = picks_per_day() - cards_today(db, now)
    if quota <= 0:
        return {"cards": [], "skipped": "today_done"}
    if pending_count(db) >= picks_max_pending():
        return {"cards": [], "skipped": "pending_full"}
    rows = pool(db)
    if not rows:
        memory.log_activity(db, "找货池里没有能挑的候选了(F 池子挑空了,或剩下的都是开不了页面/踩红线的)。", kind="pick")
        db.commit()
        return {"cards": [], "skipped": "pool_empty"}
    by_id = {str(row.id): row for row in rows}
    judge = judge or _default_judge
    shopping = shopping or _default_shopping
    amazon = amazon or _default_amazon
    keepa = keepa or _default_keepa
    _set_activity(db, "thinking", f"在找货池里挑今天的新品({len(rows)} 个候选)")
    db.commit()
    extra = "候选:\n" + "\n".join(candidate_line(row) for row in rows) + "\n\n" + _store_brief(db) + "\n\n" + _boss_history(db)
    shortlist = min(SHORTLIST_MAX, max(quota, quota * 2))
    try:
        result = judge(db, _PICK_ASK.format(limit=shortlist), extra)
    except Exception as exc:  # noqa: BLE001 —— 挑不成不拖垮 worker,写流水,下一次再挑
        logger.exception("picks judge failed")
        memory.log_activity(db, f"挑新品这一步没做成:{exc.__class__.__name__}: {str(exc)[:120]}", kind="error")
        _set_activity(db, "working", "挑新品没做成,看流水")
        db.commit()
        return {"cards": [], "skipped": "judge_failed"}
    fallback = {cid: (row.profile_product_en or "") for cid, row in by_id.items()}
    picks = parse_picks(result, pool_ids=set(by_id), limit=shortlist, fallback_query=fallback)
    if not picks:
        memory.log_activity(db, f"看了 {len(rows)} 个候选,今天没有值得发给老板的。", kind="pick")
        _set_activity(db, "working", "今天的候选都不够格,没发卡")
        db.commit()
        return {"cards": [], "skipped": "nothing_worth", "scored": []}
    a = pricing.assumptions()
    min_score = pick_min_score()
    refs: list[str] = []
    scored: list[dict[str, Any]] = []
    for pick in picks:
        if len(refs) >= quota:
            break
        row = by_id[pick.f_candidate_id]
        _set_activity(db, "thinking", f"给候选打分:{row.title[:30]}")
        db.commit()
        competitors = shopping(db, pick.us_query) if pick.us_query else {"query": "", "n": 0}
        amz = amazon(db, pick.us_query) if pick.us_query else {"keyword": "", "error": "没有能查的英文词"}
        asins = [t.get("asin") for t in (amz.get("top") or []) if isinstance(t, dict) and t.get("asin")] if isinstance(amz, dict) else []
        keepa_rows, keepa_error = keepa(db, asins) if asins else ([], "亚马逊首页没拿到 ASIN")
        card_score = score_candidate(row, pick, shopping=competitors, amazon=amz, keepa=keepa_rows, keepa_error=keepa_error, a=a)
        scored.append({"f_candidate_id": pick.f_candidate_id, "total": card_score["total"], "vetoed": card_score["vetoed"]})
        if card_score["vetoed"]:
            memory.log_activity(db, f"否决:{row.title[:30]}——{'；'.join(card_score['vetoed'])[:150]}", kind="pick")
            db.commit()
            continue
        if card_score["total"] < min_score:
            memory.log_activity(db, f"没过线:{row.title[:30]} 评分 {card_score['total']}/{card_score['max']}(线 {min_score})" + (f",没拿到:{'、'.join(card_score['missing'])}" if card_score["missing"] else ""), kind="pick")
            db.commit()
            continue
        text = build_card_text(row, pick, competitors, a, card_score, amazon=amz if isinstance(amz, dict) else None, keepa=keepa_rows)
        card, created = cards.create_card(
            db,
            dedupe_key=f"{CANDIDATE_CARD_KIND}:{row.id}",
            kind=CANDIDATE_CARD_KIND,
            title=text["title"],
            conclusion=text["conclusion"],
            why=text["why"],
            if_not=text["if_not"],
            reversible=True,
            confidence=text["confidence"],
            evidence=text["evidence"],
        )
        if created:
            refs.append(card.ref)
            memory.log_activity(db, f"挑了一个候选:{row.title[:30]},评分 {card_score['total']}/{card_score['max']},卡 #{card.ref} 等老板看。", kind="pick")
        db.commit()
    if not refs:
        memory.log_activity(db, f"初筛留了 {len(picks)} 个,打分后没有过线的(线 {min_score}),今天没发卡。", kind="pick")
        _set_activity(db, "working", "今天的候选打分都没过线,没发卡")
        db.commit()
        return {"cards": [], "skipped": "nothing_passed", "scored": scored}
    _set_activity(db, "working", f"今天挑了 {len(refs)} 个新品候选,等老板看")
    db.commit()
    return {"cards": refs, "skipped": None, "scored": scored}


def should_pick(*, now: datetime, last_plan: Any) -> bool:
    """早间计划排完了(今天的 last_plan_date)才挑——先排活,再找货。"""
    return last_plan == now.astimezone(dossiers.LA).date()


# ---------------------------------------------------------------- 批了 / 驳了 / 建进 K 了


def _candidate_of(db: Session, card: SqhCard) -> FCategoryCandidate | None:
    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    raw = evidence.get("f_candidate_id")
    try:
        return db.get(FCategoryCandidate, UUID(str(raw)), execution_options=_X) if raw else None
    except ValueError:
        return None


def after_decision(db: Session, card: SqhCard, *, decision: str, actor: User) -> dict[str, Any]:
    """选品卡决定之后:驳 → F 候选标 rejected 记原因;批 → F 候选标 approved,同一个链接按第①步排队建档。"""
    row = _candidate_of(db, card)
    if row is None:
        return {"ok": False, "note": "F 里找不到这个候选了,没法接着做。"}
    if decision == "reject":
        if row.status == "pending_review":
            row.status = "rejected"
            row.notes = f"苏青禾选品卡 #{card.ref} 老板驳回:{card.decision_reason or ''}"[:2000]
            row.reviewed_by_user_id = actor.id
            db.add(row)
            db.flush()
        return {"ok": True, "note": "好,这个不做了,原因我记住了。"}
    if row.status == "pending_review":
        row.status = "approved"
        row.notes = f"苏青禾选品卡 #{card.ref} 老板批了"
        row.reviewed_by_user_id = actor.id
        db.add(row)
        db.flush()
    try:
        dossier, created, position = dossiers.enqueue(db, url=str(row.source_url or ""), actor_user_id=str(actor.id), channel="web")
    except dossiers.DossierError as exc:
        return {"ok": False, "note": str(exc)}
    dossier.capture = {**(dossier.capture or {}), "f_candidate_id": str(row.id), "pick_card_ref": card.ref}
    db.add(dossier)
    db.flush()
    return {"ok": True, "queued": True, "dossier_id": dossier.id, "note": dossiers.queue_reply(position, created=created, status=dossier.status)}


def mark_imported(db: Session, dossier: SqhDossier, k_product_id: str) -> bool:
    """建进 K 之后回写 F:这个候选的去向(imported_to_k + K 产品 id)。不是选品卡来的档案不动。"""
    capture = dossier.capture if isinstance(dossier.capture, dict) else {}
    raw = capture.get("f_candidate_id")
    if not raw:
        return False
    try:
        row = db.get(FCategoryCandidate, UUID(str(raw)), execution_options=_X)
    except ValueError:
        return False
    if row is None or row.status == "imported_to_k":
        return False
    row.status = "imported_to_k"
    try:
        row.k_product_id = UUID(str(k_product_id))
    except ValueError:
        pass
    db.add(row)
    db.flush()
    return True
