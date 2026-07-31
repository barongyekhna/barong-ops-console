"""关键词雷达——SEO 的选题层。

一句话:**把"该写什么"从拍脑袋变成可复算的排序**。

流水线(每一步都能单独失败而不毁掉整轮):

    种子   → Keyword Planner 搜索量 → GEO 可达性去重门 → 事实匹配 → 打分入库
    ↑                                        ↓
    K 关键词 / 工艺话题 / 店型 / 手输     够得到的标为 GEO 领地,不进队列

**B 端不看搜索量。** 采购词("wholesale camping shower MOQ")月搜索量常常是
0 或测不出来,但它是最值钱的题——买一次几百件的人不会像消费者那样反复搜。
所以 B 端选题按**店型覆盖度**排:每个已启用店型至少一篇,缺的排前面。
拿搜索量给 B 端排序会把最赚钱的题排到最后。

**出网调用铁律**:Keyword Planner 是 OAuth + API 两跳 HTTP。所有读库动作在
出网前一次性做完并 ``commit()``,否则读事务挂在出网调用上,8 秒 idle-in-txn
死神会把它掐断(这坑本仓库踩过四次)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import constants as C
from .fact_match import FactMatcher
from .geo_reachability import GeoReachability, normalize
from .models import SeoRadarRun, SeoTopic

logger = logging.getLogger(__name__)


class SeoRadarError(RuntimeError):
    pass


# ---------------------------------------------------------------- 种子


def _k_keyword_seeds(db: Session, limit: int) -> list[dict[str, Any]]:
    """K 里已批准的产品关键词。C 端选题的主要种子。"""
    try:
        from ...k_series.product_knowledge.models import (
            KProductKnowledgeKeyword,
            KProductKnowledgeProduct,
        )
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    rows = db.execute(
        select(
            KProductKnowledgeKeyword.keyword_text,
            KProductKnowledgeProduct.google_product_category,
            KProductKnowledgeProduct.category_path,
        )
        .join(
            KProductKnowledgeProduct,
            KProductKnowledgeProduct.id == KProductKnowledgeKeyword.product_id,
        )
        # 只取已批准的:候选/驳回的词进雷达等于把 K 的审核结论作废。
        .where(KProductKnowledgeKeyword.status == "approved")
        .limit(limit * 4)
    ).all()
    for keyword, category_id, category_path in rows:
        norm = normalize(keyword)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(
            {
                "keyword": str(keyword).strip(),
                "source": C.SOURCE_KEYWORD_RADAR,
                "audience": C.AUDIENCE_CONSUMER,
                "google_category_id": category_id,
                "category_path": category_path,
            }
        )
        if len(out) >= limit:
            break
    return out


def _craft_topic_seeds(db: Session) -> list[dict[str, Any]]:
    """工艺库自己的话题。这些题**只有我们写得出来**——它们不来自搜索数据,
    来自我们真的知道怎么做这件事。"""
    try:
        from ...content_core.facts import service as craft
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fact in craft.approved_facts(db):
        topic = str(fact.topic or "").strip()
        if not topic or topic in seen:
            continue
        seen.add(topic)
        out.append(
            {
                "keyword": topic.replace("-", " "),
                "source": C.SOURCE_CRAFT_TOPIC,
                "audience": C.AUDIENCE_BRAND,
                "craft_topic": topic,
            }
        )
    return out


def _store_type_category(db: Session, store_id: Any) -> tuple[str | None, str | None]:
    """店型的主类目 (google_id, 路径)。

    店型本来就是**按谷歌类目前缀定义**的(gift_shop 吃 "Toys & Games" 等),
    所以类目不用问、不用猜——从店型自己的前缀推出来。

    有了它,B 端选题就能:
    - 挂产品链接时按**类目子树**找,而不是靠词面猜(2026-07-31 实测:一篇讲户外店
      批发的文章挂上了「包子捏捏」,就因为两个标题里都有 "Portable");
    - 批发链接指向**对应的店型专页**,而不是笼统的批发主页。

    取第一条前缀(sort 后稳定):一个店型吃多个类目,拿最主要的那个当锚点。
    """
    from sqlalchemy import text as sql_text

    from ...b2b.store_types.models import B2BStoreTypeCategory

    rows = list(
        db.execute(
            select(B2BStoreTypeCategory.category_key)
            .where(B2BStoreTypeCategory.store_type_id == store_id)
            .order_by(B2BStoreTypeCategory.category_key)
        ).scalars()
    )
    for key in rows:
        path = str(key or "").strip()
        if not path:
            continue
        try:
            row = db.execute(
                sql_text(
                    "SELECT id, full_path FROM k_category_google WHERE full_path = :p"
                ),
                {"p": path},
            ).first()
        except Exception:  # noqa: BLE001 - 类目树读不到就当没绑
            logger.exception("store-type category lookup failed: %s", path)
            return None, None
        if row:
            return str(row[0]), str(row[1])
    return None, None


def _store_type_seeds(db: Session) -> list[dict[str, Any]]:
    """B 端:每个已启用店型 × 采购决策问题。

    问题清单是**采购方真正要决定的事**,不是我们想说的事。顺序即重要性:
    起订量决定能不能谈,私标决定要不要谈,交期决定敢不敢谈。
    """
    try:
        from ...b2b.store_types.models import B2BStoreType
    except Exception:  # noqa: BLE001
        return []
    decisions = (
        "minimum order quantity",
        "private label and custom branding",
        "lead time and shipping",
        "factory audit and quality control",
        "payment terms",
    )
    out: list[dict[str, Any]] = []
    stores = db.execute(
        select(B2BStoreType)
        .where(B2BStoreType.outreach_status.in_(("active", "idle")))
        .order_by(B2BStoreType.sort_order)
    ).scalars()
    for store in stores:
        # **用 key 不用 label**:label 是控制台里给中国人看的中文标签(「礼品店」),
        # 拿它当英文关键词会写出中英混排的标题 —— 面向美国买家的内容一律英文
        # (死规矩)。key 本来就是英文 slug。
        name = str(store.key or "").replace("_", " ").strip()
        if not name:
            continue
        category_id, category_path = _store_type_category(db, store.id)
        for decision in decisions:
            out.append(
                {
                    "keyword": f"{name} wholesale {decision}",
                    "source": C.SOURCE_STORE_TYPE,
                    "audience": C.AUDIENCE_WHOLESALE,
                    "store_type_key": store.key,
                    "google_category_id": category_id,
                    "category_path": category_path,
                }
            )
    return out


# 每轮给各受众留的名额。**不能先到先得**:5 个店型 × 5 个采购决策正好 25 条,
# 会把 C 端和工艺题一条不剩地挤出去(2026-07-30 首跑就是这样,25 条全是 B 端)。
_AUDIENCE_QUOTA = {
    C.AUDIENCE_CONSUMER: 0.48,
    C.AUDIENCE_WHOLESALE: 0.32,
    C.AUDIENCE_BRAND: 0.20,
}


def collect_seeds(
    db: Session, *, extra: list[str] | None = None, limit: int = C.RADAR_MAX_SEEDS
) -> list[dict[str, Any]]:
    manual = [
        {
            "keyword": text,
            "source": C.SOURCE_MANUAL,
            "audience": C.AUDIENCE_CONSUMER,
        }
        for text in (str(k or "").strip() for k in extra or [])
        if text
    ]
    pools = {
        C.AUDIENCE_CONSUMER: _k_keyword_seeds(db, limit),
        C.AUDIENCE_WHOLESALE: _store_type_seeds(db),
        C.AUDIENCE_BRAND: _craft_topic_seeds(db),
    }

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(seed: dict[str, Any]) -> bool:
        norm = normalize(seed["keyword"])
        if not norm or norm in seen:
            return False
        seen.add(norm)
        out.append({**seed, "normalized": norm})
        return True

    # 手输永远优先——那是运营明确要的题。
    for seed in manual:
        take(seed)

    # 按配额各取一段;某一池不够,剩下的名额让给别人(而不是空着)。
    for audience, share in _AUDIENCE_QUOTA.items():
        quota = max(1, int(limit * share))
        taken = 0
        for seed in pools.get(audience, []):
            if taken >= quota or len(out) >= limit:
                break
            if take(seed):
                taken += 1
    for audience in _AUDIENCE_QUOTA:
        for seed in pools.get(audience, []):
            if len(out) >= limit:
                break
            take(seed)
    return out[:limit]


# ---------------------------------------------------------------- 搜索量


def _planner_metrics(
    db: Session, seeds: list[dict[str, Any]], *, org_id: str | None
) -> tuple[dict[str, dict[str, Any]], int, list[str]]:
    """{归一化词: 指标} + 花掉的额度 + 备注。

    C 端才打 Planner。B 端不打——见模块文档:采购词量太小,花额度换一个 0 回来
    毫无信息,还占着和 R-A 共用的桶。
    """
    wanted = [s for s in seeds if s["audience"] == C.AUDIENCE_CONSUMER]
    if not wanted:
        return {}, 0, ["没有 C 端种子，跳过 Keyword Planner"]

    from r_system_v2.ra.quota_ledger import (  # noqa: PLC0415
        PROVIDER_GOOGLE_ADS_PLANNER,
        RAQuotaExhaustedError,
        try_consume,
    )

    notes: list[str] = []
    granted: list[dict[str, Any]] = []
    for seed in wanted:
        try:
            try_consume(db, PROVIDER_GOOGLE_ADS_PLANNER, amount=1)
        except RAQuotaExhaustedError as exc:
            notes.append(f"额度用尽，剩下 {len(wanted) - len(granted)} 个种子没打：{exc}")
            break
        granted.append(seed)

    # 出网前把事务放掉——OAuth + API 两跳,读事务不能挂在上面。
    db.commit()

    # 取钥匙也在事务外:它要走 api-key 编排表并解密,慢到足以踩 8s idle-in-txn
    # (GEO 监测就是在这一步栽过的)。
    from ....db.session import SessionLocal  # noqa: PLC0415
    from r_system_v2.core.secret_manager import SecretManager  # noqa: PLC0415
    from r_system_v2.ra.google_keyword_planner import (  # noqa: PLC0415
        GoogleKeywordPlannerClient,
    )

    try:
        with SessionLocal() as key_session:
            value = SecretManager(db_session=key_session).get_key("google_ads", org_id)
    except Exception as exc:  # noqa: BLE001 - 没钥匙不该毁掉整轮,只是没搜索量
        logger.warning("google_ads key unavailable: %s", exc)
        return {}, 0, notes + ["Google Ads key 取不到，搜索量留空（只影响 C 端排序）"]
    if not value:
        return {}, 0, notes + ["Google Ads key 未配置，搜索量留空（只影响 C 端排序）"]

    client = GoogleKeywordPlannerClient.from_secret_value(value)
    metrics: dict[str, dict[str, Any]] = {}
    spent = 0
    for seed in granted:
        try:
            ideas = client.keyword_ideas(
                seed["keyword"], limit=C.RADAR_IDEAS_PER_SEED
            )
        except Exception as exc:  # noqa: BLE001 - 单个词失败不该毁掉整轮
            notes.append(f"「{seed['keyword'][:40]}」查询失败：{str(exc)[:120]}")
            continue
        spent += 1
        for idea in ideas.get("ideas") or []:
            norm = normalize(idea.get("keyword"))
            if norm:
                metrics[norm] = idea
    return metrics, spent, notes


# ---------------------------------------------------------------- 打分


def score_topic(
    *,
    audience: str,
    searches: int | None,
    attackability: int | None,
    has_support: bool,
    store_type_gap: bool,
) -> int:
    """越大越该先写。

    C 端 = 搜索量 × 可攻度 × 有事实支撑。B 端 = 覆盖度优先(缺一篇的店型顶格),
    因为采购词的搜索量根本测不出高低。
    """
    if not has_support:
        # 没有任何事实支撑的题一律沉底——不是不能写,是写了只能是空话。
        return 0
    if audience == C.AUDIENCE_WHOLESALE:
        return 900 if store_type_gap else 300
    if audience == C.AUDIENCE_BRAND:
        # 工艺题不靠搜索量立项:它是信任枢纽,而且只有我们写得出。
        return 700
    volume = min(int(searches or 0), 5000)
    reach = attackability if attackability is not None else 50
    return int((volume**0.5) * 4 + reach * 3)


# ---------------------------------------------------------------- 主流程


def run_radar(
    db: Session,
    *,
    scope_context: Any,
    extra_keywords: list[str] | None = None,
    username: str | None = None,
) -> SeoRadarRun:
    run = SeoRadarRun(
        status="running",
        requested_by_username=username,
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(run)
    db.flush()

    seeds = collect_seeds(db, extra=extra_keywords)
    run.seed_count = len(seeds)
    if not seeds:
        run.status = "success"
        run.notes_json = {"notes": ["没有种子——先在 K 录关键词，或录几条工艺事实。"]}
        run.finished_at = datetime.now(UTC)
        db.commit()
        return run

    # 出网前一次性读完 GEO 侧与三个事实源(见模块文档的 idle-in-txn 说明)。
    reachability = GeoReachability(db)
    matcher = FactMatcher(db)
    covered_store_types = {
        key
        for (key,) in db.execute(
            select(SeoTopic.store_type_key).where(
                SeoTopic.store_type_key.is_not(None),
                SeoTopic.status.in_(("picked", "written")),
            )
        ).all()
    }
    existing = {
        norm
        for (norm,) in db.execute(select(SeoTopic.normalized_keyword)).all()
    }

    metrics, planner_calls, notes = _planner_metrics(
        db, seeds, org_id=getattr(scope_context, "workspace_key", None)
    )
    run = db.get(SeoRadarRun, run.id)  # commit 之后重新取
    run.planner_calls = planner_calls

    created = 0
    geo_blocked = 0
    for seed in seeds:
        norm = seed["normalized"]
        reachable, reason = reachability.judge(seed["keyword"])
        if reachable:
            geo_blocked += 1
            continue
        if norm in existing:
            continue

        audience = seed["audience"]
        support = matcher.support_for(seed["keyword"], audience=audience)
        idea = metrics.get(norm) or {}
        topic = SeoTopic(
            keyword=seed["keyword"][:512],
            normalized_keyword=norm[:255],
            source=seed["source"],
            audience=audience,
            destination=C.destination_for(audience),
            google_category_id=seed.get("google_category_id"),
            category_path=seed.get("category_path"),
            store_type_key=seed.get("store_type_key"),
            craft_topic=seed.get("craft_topic"),
            avg_monthly_searches=idea.get("avg_monthly_searches"),
            competition_index=idea.get("competition_index"),
            cpc_high_micros=idea.get("cpc_high_micros"),
            geo_reachable=False,
            geo_reason=reason,
            fact_support_json=support,
            score=score_topic(
                audience=audience,
                searches=idea.get("avg_monthly_searches"),
                attackability=None,
                has_support=support["has_support"],
                store_type_gap=(
                    seed.get("store_type_key") is not None
                    and seed.get("store_type_key") not in covered_store_types
                ),
            ),
            status="candidate",
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
        )
        db.add(topic)
        existing.add(norm)
        created += 1

    run.candidate_count = created
    run.geo_blocked_count = geo_blocked
    run.status = "success"
    run.notes_json = {
        "notes": notes,
        # 明写被挡掉多少,别让"雷达跑完只出 3 条"看起来像故障。
        "geo_blocked": f"{geo_blocked} 个候选属于 GEO 领地，没进 SEO 队列（避免自我竞争）",
    }
    run.finished_at = datetime.now(UTC)
    db.commit()
    return run


def attach_terrain(
    db: Session, *, topic_id: UUID, scope_context: Any, user: Any | None = None
) -> SeoTopic:
    """给单个选题打可攻度——复用 GEO 阵地监测那一套(Serper + 守门人识别)。

    按需单题打,不批量:每次是一发 Serper,而且**可攻度只在准备动手写之前才有
    意义**。批量打整个队列等于替还没决定写的题付钱。
    """
    topic = db.get(SeoTopic, topic_id)
    if topic is None:
        raise SeoRadarError("这个选题不存在。")
    keyword = topic.keyword
    db.commit()  # 出网前放掉事务

    # 复用 GEO 的探测入口:它自带 Serper 台账、缓存(7 天内不重复打)、
    # 以及守门人域名识别。cluster_id=None 表示"不属于任何 GEO 簇的独立探测"。
    from ...geo_series.monitor.probe import normalize_question, probe_candidates

    probe_candidates(
        db,
        cluster_id=None,
        questions=[keyword],
        scope_context=scope_context,
        user=user,
    )

    from ...geo_series.monitor.probe import terrain_by_question

    readings = terrain_by_question(db, cluster_id=None)
    summary = readings.get(normalize_question(keyword)) or {}
    topic = db.get(SeoTopic, topic_id)
    topic.attackability = summary.get("attackability")
    topic.terrain = summary.get("terrain")
    support = topic.fact_support_json or {}
    topic.score = score_topic(
        audience=topic.audience,
        searches=topic.avg_monthly_searches,
        attackability=topic.attackability,
        has_support=bool(support.get("has_support")),
        store_type_gap=False,
    )
    db.commit()
    return topic


__all__ = [
    "SeoRadarError",
    "attach_terrain",
    "collect_seeds",
    "run_radar",
    "score_topic",
]
