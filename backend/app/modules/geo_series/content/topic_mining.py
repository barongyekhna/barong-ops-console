"""类目级选题深挖——把一个话题的问句挖到底。

**为什么需要它**:原有的选题候选(``topic_sourcing``)是**零成本复用**——读 K 做
产品时顺手抓的 FAQ(每产品 3 条 query)和 F 的类目关键词。这对"这个产品有哪些
买家问题"够用,对"这个**类目**的问句挖到底"远远不够:

- 抓的是**产品名**("便携露营淋浴器"),而品类词("pop up shower tent")的
  「大家还在问」里有一整批问句是产品名永远碰不到的;
- 只抓了**第一层** PAA。Google 的「大家还在问」是棵树,点开一个会冒出更多,
  真正的长尾在第二层往下。

话题权威是"把一个话题写透"换来的,而写透的前提是**先把问句挖全**。挖不出来的
问句,再好的写作能力也写不出对应的文章。

**成本纪律**:这是新增的付费出网调用,按死规矩当天接台账
(``geo_serper_topics``,默认 300/天)。额度用尽就优雅停下并说清楚,
绝不打超额请求——Serper 12 天烧光 5 万次那次事故换来的。

**事务纪律**:每一发 Serper 之前都 ``commit()``。出网调用绝不能圈在事务里。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.faq_research import (
    _intent_cluster,
    is_faq_question_candidate,
    is_faq_text_brand_safe,
    is_specification_paraphrase_question,
)
from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import KScopeContext
from .models import GeoContentCluster, GeoMinedQuestion

logger = logging.getLogger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SEARCH_LOCALE = {"gl": "us", "hl": "en"}
REQUEST_TIMEOUT = 20.0

# 一轮最多打几发。种子 + 二级展开合起来的上限,防止一个类目吃掉整天额度。
MAX_SEED_QUERIES = 10
MAX_EXPANSION_QUERIES = 12


class TopicMiningError(RuntimeError):
    pass


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip("?").strip()


def head_noun_of(chunk: str) -> str | None:
    words = [w for w in re.findall(r"[a-z0-9]+", str(chunk or "").lower()) if len(w) >= 4]
    if not words:
        return None
    last = words[-1]
    return last[:-1] if last.endswith("s") else last


def leaf_head_map(
    categories: list[tuple[str, str | None]]
) -> dict[str, str]:
    """{中心词: 叶子类目id}。按**问句里出现的中心词**归档,比按种子归档准得多。

    父级名 "Portable Toilets & Showers" 拆出来的 "Portable Toilets" 本身不带 id
    (它来自非叶子节点),但 "toilet" 这个中心词在兄弟叶子
    "Portable Toilets & Urination Devices" 里,所以照样能归对。

    而且这样连"从淋浴种子挖出来、内容其实是马桶"的问句也能归对——
    PAA 漂移是常态,按种子归档会把它们记错地方。
    """
    out: dict[str, str] = {}
    for name, category_id in categories:
        if not category_id:
            continue
        for chunk in re.split(r"\s*&\s*", name):
            head = head_noun_of(chunk)
            if head:
                out.setdefault(head, category_id)
    return out


def head_nouns(chunks: list[str]) -> set[str]:
    """类目的**中心词**(已做单复数归一)。

    "Portable Showers" → shower;"Privacy Enclosures" → enclosure。
    中心词就是这个类目本身,修饰词(portable / camping)不是——
    "portable toilet" 也有 portable,但它不是淋浴。
    """
    out: set[str] = set()
    for chunk in chunks:
        words = [w for w in re.findall(r"[a-z0-9]+", str(chunk or "").lower()) if len(w) >= 4]
        if words:
            last = words[-1]
            out.add(last[:-1] if last.endswith("s") else last)
    return out


def _on_topic(question: str, heads: set[str]) -> bool:
    """挖到的问句得落在这棵类目子树里。

    判据是**中心词**,而且中心词取自**全部种子**(含父级)——所以同父类目下的
    相邻品(便携马桶)算在内,那是下一批产品的选题储备,不是跑题。

    这道门挡的是真正漂出去的:PAA 会从"露营淋浴"漂到"家用淋浴改造""房车水泵"
    这类完全不同的购买场景。判据用中心词而不是词面重叠数——
    2026-07-30 试过"共享 2 个词",把 "What is a solar shower?" 误杀了
    (只共享 shower 一个词,但明显就是这个类目的题)。
    """
    if not heads:
        return True
    words = {
        (w[:-1] if w.endswith("s") else w)
        for w in re.findall(r"[a-z0-9]+", question.lower())
        if len(w) >= 4
    }
    return bool(words & heads)


def _attribute(question: str, head_map: dict[str, str]) -> str | None:
    """这条问句属于哪个叶子类目——看它提到了哪个类目的中心词。"""
    words = {
        (w[:-1] if w.endswith("s") else w)
        for w in re.findall(r"[a-z0-9]+", question.lower())
        if len(w) >= 4
    }
    for head, category_id in head_map.items():
        if head in words:
            return category_id
    return None


def _accept(question: str) -> bool:
    """与 topic_sourcing 同一道门:真问句、品牌安全、不是规格复述。"""
    return bool(
        question
        and is_faq_question_candidate(question)
        and is_faq_text_brand_safe(question)
        and not is_specification_paraphrase_question(question)
    )


# ------------------------------------------------------------------ 种子


def _subtree_categories(db: Session, cluster: GeoContentCluster) -> list[tuple[str, str | None]]:
    """整棵子树的 (类目名, 类目id):自己 + 兄弟叶子 + 父级。

    **带上 id 是关键**:挖到的问句要按"它是从哪个类目的种子挖出来的"归档,
    而不是按"从哪个簇发起的"。举例:从淋浴簇发起深挖,顺带挖到的便携马桶问句
    属于 `Portable Toilets & Urination Devices` 这个**兄弟叶子**——
    等那个簇建起来的时候,这些问句就已经在那儿等着了。
    记在发起簇名下,则两头都错:现在污染淋浴簇的列表,将来马桶簇又拿不到。

    ``k_category_google`` 没有 ORM 模型(仓库里都是裸 SQL),这里同规。
    路径字符串里只有祖先,**兄弟叶子必须查树**。查不到就退回路径末两级。
    """
    from sqlalchemy import text as sql_text

    path = str(cluster.category_path or "")
    parts = [p.strip() for p in path.split(">") if p.strip()]
    fallback: list[tuple[str, str | None]] = [(n, None) for n in reversed(parts[-2:])]

    google_id = str(getattr(cluster, "google_category_id", "") or "").strip()
    if not google_id:
        return fallback
    try:
        rows = db.execute(
            sql_text(
                """
                WITH me AS (
                    SELECT id, name, parent_id FROM k_category_google WHERE id = :gid
                )
                SELECT c.id, c.name, c.is_leaf
                FROM k_category_google c, me
                WHERE c.parent_id = me.parent_id OR c.id = me.parent_id
                """
            ),
            {"gid": google_id},
        ).all()
    except Exception:  # noqa: BLE001 - 类目树读不到不该毁掉整轮
        logger.exception("category subtree lookup failed")
        return fallback

    out: list[tuple[str, str | None]] = []
    for cid, name, is_leaf in rows:
        text_name = str(name or "").strip()
        if not text_name:
            continue
        # 父级(非叶子)不归档到任何具体类目——它的问句可能属于底下任何一个叶子。
        out.append((text_name, str(cid) if is_leaf else None))
    return out or fallback


def build_seeds(
    db: Session, *, cluster: GeoContentCluster, scope_context: KScopeContext
) -> list[tuple[str, str | None]]:
    """种子查询 (词, 该词归属的类目id)。**整棵子树的类目词优先,产品词其次**。

    类目词是这个模块存在的理由——产品名抓不到品类层的问句,更抓不到
    "还没上但迟早要上"的兄弟品类的问句。
    """
    seeds: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    def add(text: Any, category_id: str | None) -> None:
        cleaned = " ".join(str(text or "").split()).strip()
        key = cleaned.lower()
        if cleaned and key not in seen and len(cleaned) >= 4:
            seen.add(key)
            seeds.append((cleaned, category_id))

    # ① **整棵子树**:父类目 + 它底下的所有叶子。
    #
    # 用户拍板(2026-07-30):"我要做最完整的产品链,所有产品都卖"。这家工厂没有
    # 固定品类,F 系列做的就是类目富化——同一个父类目底下的相邻品今天没有、
    # 明天就会上。所以选题面不是"我们现在卖的那一个叶子",是**整棵子树**。
    #
    # "&" 一定要拆开:淋浴帐篷(Privacy Enclosures)和淋浴器在同一个叶子里,
    # 不拆就挖不到帐篷那半边——而那正是这个模块存在的理由。
    for name, category_id in _subtree_categories(db, cluster):
        for chunk in re.split(r"\s*&\s*", name):
            add(chunk, category_id)

    # ② 簇的话题
    add(cluster.topic, cluster.google_category_id)

    # ③ 簇里每个产品的主关键词
    product_ids = cluster.product_ids_json if isinstance(cluster.product_ids_json, list) else []
    identifiers = {str(x).strip() for x in product_ids if str(x).strip()}
    if identifiers:
        for product in db.execute(select(KProductKnowledgeProduct)).scalars():
            if (
                str(product.id) in identifiers
                or str(getattr(product, "product_key", "")) in identifiers
            ):
                add(getattr(product, "primary_keyword", None), cluster.google_category_id)

    return seeds[:MAX_SEED_QUERIES]


# ------------------------------------------------------------------ 抓取


def _fetch(api_key: str, query: str) -> dict[str, Any]:
    response = httpx.post(
        SERPER_SEARCH_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": 10, **SEARCH_LOCALE},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _harvest(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """从一个 Serper 响应里收 (问句, 来源类型)。

    三个位置各有各的价值:
    - ``peopleAlsoAsk`` 是 Google 自己认定的"同一意图下人们还在问什么",最值钱;
    - ``relatedSearches`` 里问句形态的那些,是下一层意图;
    - 论坛结果的标题往往就是一个原汁原味的买家问题。
    """
    out: list[tuple[str, str]] = []
    for row in payload.get("peopleAlsoAsk") or []:
        if isinstance(row, dict) and row.get("question"):
            out.append((str(row["question"]).strip(), "people_also_ask"))
    for row in payload.get("relatedSearches") or []:
        text = str((row or {}).get("query") if isinstance(row, dict) else row).strip()
        if text:
            out.append((text, "organic_question"))
    for row in payload.get("organic") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        link = str(row.get("link") or "").lower()
        if not title:
            continue
        forum = any(
            host in link
            for host in ("reddit.com", "quora.com", "forum", "community", "stackexchange")
        )
        out.append((title, "forum_question" if forum else "organic_question"))
    return out


_SOURCE_WEIGHT = {
    "people_also_ask": 100,
    "forum_question": 80,
    "organic_question": 60,
}
_INTENT_BONUS = {
    "compatibility": 25,
    "operation": 20,
    "travel_logistics": 20,
    "maintenance": 15,
    "safety": 15,
    "buyer_concern": 5,
}


def _score(source_type: str, intent: str, depth: int) -> int:
    # 二级展开出来的问句更长尾,给一点加成:它们竞争小,恰恰是能打的那批。
    return _SOURCE_WEIGHT.get(source_type, 50) + _INTENT_BONUS.get(intent, 0) + depth * 5


# ------------------------------------------------------------------ 主流程


def mine_cluster_questions(
    db: Session,
    *,
    cluster_id: UUID,
    scope_context: KScopeContext,
    user: Any | None = None,
    expand: bool = True,
) -> dict[str, Any]:
    """深挖一个类目的问句。返回本轮战报(新增多少、花了多少额度、为什么停)。"""
    from r_system_v2.ra.quota_ledger import (
        PROVIDER_GEO_SERPER_TOPICS,
        RAQuotaExhaustedError,
        ensure_quota_schema,
        refund,
        try_consume,
    )

    cluster = db.get(GeoContentCluster, cluster_id)
    if cluster is None:
        raise TopicMiningError("这个话题簇不存在。")

    ensure_quota_schema(db)
    seeds = build_seeds(db, cluster=cluster, scope_context=scope_context)
    if not seeds:
        raise TopicMiningError("挖不出种子——这个簇既没有类目路径也没有产品关键词。")

    # 已经知道的问句(K/F 的候选 + 已挖过的 + 已写过的),挖出来重复的不再记。
    from .topic_sourcing import list_topic_candidates

    known: set[str] = {
        _norm(c["question"]) for c in list_topic_candidates(
            db, cluster=cluster, scope_context=scope_context
        )
    }
    known |= {
        _norm(q)
        for (q,) in db.execute(
            select(GeoMinedQuestion.question).where(
                GeoMinedQuestion.cluster_id == cluster_id
            )
        ).all()
    }
    # 相关性尺子 = 整棵子树 + 产品关键词的**中心词**。
    vocab = head_nouns([text for text, _cid in seeds])
    # 归档尺子:问句里出现哪个中心词,就归哪个叶子类目。
    head_map = leaf_head_map(_subtree_categories(db, cluster))
    org_id = getattr(scope_context, "workspace_key", None)

    # 出网前放掉事务;取钥匙也在事务外(GEO 监测在这一步栽过)。
    db.commit()
    from ....db.session import SessionLocal
    from ..monitor.service import _serper_key  # noqa: PLC0415

    with SessionLocal() as key_session:
        api_key = _serper_key(key_session, org_id)

    notes: list[str] = []
    off_topic: list[str] = []
    spent = 0
    found: list[dict[str, Any]] = []
    expansion_pool: list[tuple[str, str | None]] = []

    def run_query(query: str, depth: int, category_id: str | None) -> bool:
        """打一发。返回是否还能继续(额度、错误)。

        ``category_id`` 是这个种子归属的类目——挖到的问句跟着它归档,
        而不是跟着"从哪个簇发起"。
        """
        nonlocal spent
        try:
            try_consume(db, PROVIDER_GEO_SERPER_TOPICS, amount=1)
        except RAQuotaExhaustedError as exc:
            notes.append(f"额度用尽，停在第 {spent} 发：{exc}")
            return False
        db.commit()  # 出网前放掉

        try:
            payload = _fetch(api_key, query)
        except Exception as exc:  # noqa: BLE001 - 一发失败不该毁掉整轮
            logger.warning("topic mining query failed: %s (%s)", query[:60], exc)
            notes.append(f"「{query[:40]}」查询失败：{str(exc)[:80]}")
            try:
                refund(db, PROVIDER_GEO_SERPER_TOPICS, amount=1)
                db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("topic mining quota refund failed")
            return True
        spent += 1

        for text, source_type in _harvest(payload):
            key = _norm(text)
            if not key or key in known or not _accept(text):
                continue
            if not _on_topic(text, vocab):
                off_topic.append(text[:60])
                known.add(key)  # 记下来,别在二级展开里又捡回来
                continue
            known.add(key)
            intent = _intent_cluster(text) or "buyer_concern"
            found.append(
                {
                    "question": text[:512],
                    "normalized": key[:255],
                    "source_type": source_type,
                    "intent": intent,
                    "depth": depth,
                    "score": _score(source_type, intent, depth),
                    "seed": query[:255],
                    # 按问句里的中心词归档;找不到才退回种子的类目。
                    "google_category_id": _attribute(text, head_map) or category_id,
                }
            )
            # 值得展开的两类:PAA(Google 认定的同意图问句)和相关搜索
            # (这个空间里人们还搜什么)。两者展开出来都还在同一个话题内,
            # 而且相关搜索能带出 PAA 碰不到的词面(solar / heated / tent…)。
            if depth == 0 and source_type in ("people_also_ask", "organic_question"):
                # 展开出来的问句继承种子的类目归属。
                expansion_pool.append((text, category_id))
        return True

    for seed_text, seed_category in seeds:
        if not run_query(seed_text, 0, seed_category):
            break
    if expand and not any("额度用尽" in n for n in notes):
        for question, category_id in expansion_pool[:MAX_EXPANSION_QUERIES]:
            if not run_query(question, 1, category_id):
                break

    # 落表。挖到的问句必须存下来,否则下次进来又是一片空白。
    now = datetime.now(UTC)
    for row in found:
        db.add(
            GeoMinedQuestion(
                cluster_id=cluster_id,
                question=row["question"],
                normalized_question=row["normalized"],
                source_type=row["source_type"],
                intent=row["intent"],
                depth=row["depth"],
                score=row["score"],
                seed_query=row["seed"],
                google_category_id=row["google_category_id"],
                discovered_at=now,
                workspace_key=scope_context.workspace_key,
                business_context=scope_context.business_context,
                scope_mode=scope_context.scope_mode,
            )
        )
    db.commit()

    if off_topic:
        # 明说挡掉了多少,别让"只挖到 20 个"看起来像挖不动。
        notes.append(
            f"挡掉 {len(off_topic)} 个漂到相邻品类的问句（如「{off_topic[0]}」）"
        )

    return {
        "seeds": [text for text, _cid in seeds],
        "queries_spent": spent,
        "off_topic_dropped": len(off_topic),
        "new_questions": len(found),
        "expanded": min(len(expansion_pool), MAX_EXPANSION_QUERIES) if expand else 0,
        "notes": notes,
    }


def mined_candidates(
    db: Session, *, cluster_id: UUID, google_category_id: str | None = None
) -> list[dict[str, Any]]:
    """这个簇能用的已挖问句,形状与 ``topic_sourcing`` 的候选一致好合并。

    **按类目取,不按发起簇取。** 从淋浴簇顺带挖到的马桶问句归档在马桶那个叶子
    名下,所以:淋浴簇看不到它们(不污染列表),马桶簇一建起来就能看到(不白挖)。
    没有类目归属的(来自父级这种非叶子种子)只给发起簇——它们可能属于底下任何
    一个叶子,先放在挖它的人手边。
    """
    from sqlalchemy import or_

    conditions = [
        (GeoMinedQuestion.cluster_id == cluster_id)
        & GeoMinedQuestion.google_category_id.is_(None)
    ]
    if google_category_id:
        conditions.append(
            GeoMinedQuestion.google_category_id == str(google_category_id)
        )
    rows = db.execute(
        select(GeoMinedQuestion)
        .where(or_(*conditions))
        .order_by(GeoMinedQuestion.score.desc())
    ).scalars()
    return [
        {
            "question": row.question,
            "source_type": row.source_type,
            "intent": row.intent,
            "score": row.score,
            "origin": "mined",
            "depth": row.depth,
        }
        for row in rows
    ]


__all__ = [
    "MAX_EXPANSION_QUERIES",
    "MAX_SEED_QUERIES",
    "TopicMiningError",
    "build_seeds",
    "mine_cluster_questions",
    "mined_candidates",
]
