"""F 类目富化服务层。

- 树浏览：直接读 K 的 ``k_category_google``（共享同一棵树，F 只加状态层），
  每个节点带上 F 的富化统计（关键词数/候选数）= F 标记层。
- 选段展开：父类目 → 递归收整棵子树，超上限拒绝（请用户收窄）。
- 红线：只标记不毙掉——命中的候选 ``automation_blocked=True`` 断自动链，
  进待审队列等用户人工放行或删除（锂电按用户规则不算红线）。
- 进 K：approved 的候选一键搬进 K（channel=dtc、直绑谷歌类目），
  之后走 K→I→P 现成链。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from ....models.user import User
from ....modules.k_series.product_knowledge.category_resolver import (
    bind_google_category_id,
)
from ....modules.k_series.product_knowledge.sku_allocator import ensure_product_sku
from ....services.data_isolation import without_org_data_isolation
from ..enrichment import constants as C
from .models import FCategoryCandidate, FCategoryKeyword

# 共享的全局谷歌类目树（K 建的，无 org 列的参考数据）。裸 SQL 读取要包
# without_org_data_isolation()，否则 C18G 严格隔离会拒掉不带 org_id 的语句。
_GOOGLE_TREE = "k_category_google"

# 红线类目/词（确定性匹配，只标记不毙掉）。锂电池明确不在红线内（用户规则）。
_RED_LINE_TERMS: tuple[tuple[str, str], ...] = (
    ("weapon", "武器类目"),
    ("firearm", "枪械类目"),
    ("ammunition", "弹药类目"),
    ("knives", "刀具类目（部分平台需资质）"),
    ("tobacco", "烟草类目"),
    ("vaporizer", "电子烟类目"),
    ("e-cigarette", "电子烟类目"),
    ("prescription", "处方类产品"),
    ("pharmaceutical", "药品类目"),
    ("medical device", "医疗器械（需认证）"),
    ("baby formula", "婴儿食品（需认证）"),
    ("car seat", "儿童安全座椅（需认证）"),
    ("helmet", "头盔（需安全认证）"),
    ("smoke detector", "烟雾报警器（需认证）"),
)

# 供应商报重 sanity：>= 15kg 直发运费风险（W 系列规则表落地前先粗标）。
_HEAVY_WEIGHT_KG = 15.0


def category_node(db: Session, category_id: str) -> dict[str, Any] | None:
    with without_org_data_isolation():
        row = db.execute(
            text(
                f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
                "WHERE id = :i"
            ),
            {"i": category_id},
        ).mappings().first()
    return dict(row) if row else None


def _stats_by_category(
    db: Session, category_ids: list[str]
) -> dict[str, dict[str, int]]:
    if not category_ids:
        return {}
    stats: dict[str, dict[str, int]] = {
        cid: {"keywords": 0, "candidates": 0} for cid in category_ids
    }
    keyword_rows = db.execute(
        select(FCategoryKeyword.category_id, func.count())
        .where(FCategoryKeyword.category_id.in_(category_ids))
        .group_by(FCategoryKeyword.category_id)
    ).all()
    for category_id, count in keyword_rows:
        stats[str(category_id)]["keywords"] = int(count)
    candidate_rows = db.execute(
        select(FCategoryCandidate.category_id, func.count())
        .where(FCategoryCandidate.category_id.in_(category_ids))
        .group_by(FCategoryCandidate.category_id)
    ).all()
    for category_id, count in candidate_rows:
        stats[str(category_id)]["candidates"] = int(count)
    return stats


def browse_tree(db: Session, parent_id: str | None) -> list[dict[str, Any]]:
    """一层一层往下钻：parent_id=None 给根节点；每个节点带子节点数 + F 统计。"""
    if parent_id:
        where = "parent_id = :p"
        params: dict[str, Any] = {"p": parent_id}
    else:
        where = "parent_id IS NULL"
        params = {}
    with without_org_data_isolation():
        rows = db.execute(
            text(
                f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
                f"WHERE {where} ORDER BY name ASC"
            ),
            params,
        ).mappings().all()
    nodes = [dict(row) for row in rows]
    ids = [str(node["id"]) for node in nodes]
    child_counts: dict[str, int] = {}
    if ids:
        with without_org_data_isolation():
            count_rows = db.execute(
                text(
                    f"SELECT parent_id, COUNT(*) AS n FROM {_GOOGLE_TREE} "
                    "WHERE parent_id IN :ids GROUP BY parent_id"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": ids},
            ).all()
        child_counts = {str(parent): int(n) for parent, n in count_rows}
    stats = _stats_by_category(db, ids)
    for node in nodes:
        node_id = str(node["id"])
        node["children_count"] = child_counts.get(node_id, 0)
        node["keywords_count"] = stats.get(node_id, {}).get("keywords", 0)
        node["candidates_count"] = stats.get(node_id, {}).get("candidates", 0)
    return nodes


def search_tree(db: Session, q: str, limit: int = 30) -> list[dict[str, Any]]:
    q = (q or "").strip()
    limit = max(1, min(limit, 100))
    with without_org_data_isolation():
        rows = db.execute(
            text(
                f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
                "WHERE (:q = '' OR full_path ILIKE :like OR name ILIKE :like "
                "OR name_zh ILIKE :like) "
                "ORDER BY is_leaf DESC, level ASC, full_path ASC LIMIT :limit"
            )
            if db.get_bind().dialect.name == "postgresql"
            else text(
                f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
                "WHERE (:q = '' OR lower(full_path) LIKE lower(:like) "
                "OR lower(name) LIKE lower(:like) "
                "OR lower(COALESCE(name_zh, '')) LIKE lower(:like)) "
                "ORDER BY is_leaf DESC, level ASC, full_path ASC LIMIT :limit"
            ),
            {"q": q, "like": f"%{q}%", "limit": limit},
        ).mappings().all()
    nodes = [dict(row) for row in rows]
    stats = _stats_by_category(db, [str(node["id"]) for node in nodes])
    for node in nodes:
        node_id = str(node["id"])
        node["keywords_count"] = stats.get(node_id, {}).get("keywords", 0)
        node["candidates_count"] = stats.get(node_id, {}).get("candidates", 0)
    return nodes


def expand_selection(db: Session, category_ids: list[str]) -> list[dict[str, Any]]:
    """选中的节点 + 全部子孙节点（去重）。超过 MAX_NODES_PER_RUN 抛 ValueError。"""
    clean_ids = [str(c).strip() for c in category_ids if str(c or "").strip()]
    if not clean_ids:
        raise ValueError("至少选择一个类目节点。")
    with without_org_data_isolation():
        rows = db.execute(
            text(
                f"""
                WITH RECURSIVE sel(id) AS (
                    SELECT id FROM {_GOOGLE_TREE} WHERE id IN :ids
                    UNION
                    SELECT c.id FROM {_GOOGLE_TREE} c JOIN sel s ON c.parent_id = s.id
                )
                SELECT g.id, g.name, g.full_path, g.level, g.is_leaf
                FROM {_GOOGLE_TREE} g JOIN sel ON g.id = sel.id
                ORDER BY g.full_path ASC
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": clean_ids},
        ).mappings().all()
    nodes = [dict(row) for row in rows]
    if not nodes:
        raise ValueError("所选类目不存在（谷歌树里找不到这些节点）。")
    if len(nodes) > C.MAX_NODES_PER_RUN:
        raise ValueError(
            f"所选类目展开后共 {len(nodes)} 个节点，超过单次上限 "
            f"{C.MAX_NODES_PER_RUN}。请选小一级的子类目分批跑。"
        )
    return nodes


def keyword_query_for_node(node: dict[str, Any]) -> str:
    """节点 → Serper 查询词：单词的泛名（如 Accessories）带上父级语境。"""
    name = str(node.get("name") or "").strip()
    if len(name.split()) >= 2:
        return name
    segments = [
        segment.strip()
        for segment in str(node.get("full_path") or "").split(">")
        if segment.strip()
    ]
    if len(segments) >= 2:
        return f"{segments[-2]} {name}".strip()
    return name


def detect_red_flags(
    *, category_path: str, title: str, weight_note: str | None
) -> list[dict[str, str]]:
    """确定性红线检查：类目红线 + 报重 sanity。只产出标记，不做删除。"""
    flags: list[dict[str, str]] = []
    haystack = f"{category_path} {title}".lower()
    for term, reason in _RED_LINE_TERMS:
        if term in haystack:
            flags.append({"type": "category_red_line", "reason": f"{reason}（命中「{term}」）"})
    if weight_note:
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(kg|千克|公斤)", weight_note.lower()
        ):
            if float(match.group(1)) >= _HEAVY_WEIGHT_KG:
                flags.append(
                    {
                        "type": "heavy_weight",
                        "reason": (
                            f"供应商报重 {match.group(1)}kg ≥ {_HEAVY_WEIGHT_KG:g}kg，"
                            "中国直发运费风险，需人工核算"
                        ),
                    }
                )
                break
    return flags


def create_candidate(
    db: Session,
    *,
    category_id: str,
    title: str,
    user: User | None,
    source_url: str | None = None,
    image_url: str | None = None,
    price_cny: Decimal | None = None,
    moq: int | None = None,
    supplier_name: str | None = None,
    weight_note: str | None = None,
    notes: str | None = None,
    run_id: UUID | None = None,
    source: str = "manual",
    profile_product_zh: str | None = None,
    profile_product_en: str | None = None,
    score_json: dict[str, Any] | None = None,
    structured_specs_json: dict[str, Any] | None = None,
) -> FCategoryCandidate:
    node = category_node(db, category_id)
    if node is None:
        raise ValueError("类目不存在（谷歌树里找不到该节点）。")
    title = (title or "").strip()
    if not title:
        raise ValueError("候选产品标题不能为空。")
    flags = detect_red_flags(
        category_path=str(node["full_path"]),
        title=title,
        weight_note=weight_note,
    )
    candidate = FCategoryCandidate(
        id=uuid4(),
        run_id=run_id,
        category_id=str(node["id"]),
        category_path=str(node["full_path"]),
        title=title[:512],
        source=source,
        source_url=(source_url or None),
        image_url=(image_url or None),
        price_cny=price_cny,
        moq=moq,
        supplier_name=(supplier_name or None),
        weight_note=(weight_note or None),
        structured_specs_json=(structured_specs_json or None),
        red_flags_json=(flags or None),
        automation_blocked=bool(flags),
        status="pending_review",
        notes=(notes or None),
        profile_product_zh=(profile_product_zh or None),
        profile_product_en=(profile_product_en or None),
        score_json=score_json,
        created_by_user_id=user.id if user is not None else None,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _contains_cjk(value: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in value)


def import_candidate_to_k(
    db: Session,
    *,
    candidate: FCategoryCandidate,
    user: User | None,
) -> dict[str, Any]:
    """人工放行（approved）的候选搬进 K：channel=dtc + 直绑谷歌类目。"""
    from ...k_series.product_knowledge.constants import (
        TARGET_ORGANIZATION_NAME as K_ORG_NAME,
    )
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct
    from ...k_series.product_knowledge.scope_shim import default_scope_context
    from ...k_series.product_knowledge.service import _generate_unique_product_key

    if candidate.status == "imported_to_k":
        raise ValueError("该候选已经搬进 K 了。")
    if candidate.status != "approved":
        raise ValueError("候选必须先人工放行（approved）才能搬进 K。")

    source_record_id = str(candidate.id)
    already = db.execute(
        select(KProductKnowledgeProduct.id)
        .where(KProductKnowledgeProduct.source_system == "f_enrichment")
        .where(KProductKnowledgeProduct.source_record_id == source_record_id)
        .limit(1)
    ).first()
    if already is not None:
        candidate.status = "imported_to_k"
        candidate.k_product_id = already[0]
        db.flush()
        return {"product_id": str(already[0]), "deduped": True}

    # 主关键词：该类目已放行的词优先（related 优先、rank 靠前优先），否则用标题。
    keyword_row = db.execute(
        select(FCategoryKeyword.keyword_text)
        .where(FCategoryKeyword.category_id == candidate.category_id)
        .where(FCategoryKeyword.status == "approved")
        .order_by(
            (FCategoryKeyword.keyword_type == "related").desc(),
            FCategoryKeyword.rank.asc().nulls_last(),
        )
        .limit(1)
    ).first()
    primary_keyword = keyword_row[0] if keyword_row else candidate.title
    secondary_rows = db.execute(
        select(FCategoryKeyword.keyword_text)
        .where(FCategoryKeyword.category_id == candidate.category_id)
        .where(FCategoryKeyword.status.in_(["approved", "candidate"]))
        .where(FCategoryKeyword.keyword_type.in_(["related", "people_also_ask"]))
        .order_by(FCategoryKeyword.rank.asc().nulls_last())
        .limit(20)
    ).all()
    secondary_keywords = [row[0] for row in secondary_rows] or None

    raw_lines = [candidate.title]
    if candidate.supplier_name:
        raw_lines.append(f"1688 供应商: {candidate.supplier_name}")
    if candidate.price_cny is not None:
        raw_lines.append(f"1688 价格: ¥{candidate.price_cny}")
    if candidate.moq is not None:
        raw_lines.append(f"MOQ: {candidate.moq}")
    if candidate.weight_note:
        raw_lines.append(f"供应商报重: {candidate.weight_note}")
    if candidate.source_url:
        raw_lines.append(f"货源链接: {candidate.source_url}")
    if candidate.notes:
        raw_lines.append(f"备注: {candidate.notes}")

    scope = default_scope_context()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key=_generate_unique_product_key(db),
        workspace_key=scope.workspace_key,
        business_context=scope.business_context,
        scope_mode=scope.scope_mode,
        organization_name=K_ORG_NAME,
        product_name_en=candidate.title[:512],
        primary_keyword=str(primary_keyword)[:512],
        secondary_keywords_json=secondary_keywords,
        brand_name=None,
        target_market="US",
        product_type="simple_product",
        canonical_language="en",
        moq=candidate.moq,
        channel="dtc",
        category_path=candidate.category_path,
        category_confidence=Decimal("1"),
        reference_image_url=candidate.image_url,
        source_system="f_enrichment",
        source_record_id=source_record_id,
        product_status="draft",
        review_status="draft",
        raw_input_text="\n".join(raw_lines),
        raw_input_language="zh" if _contains_cjk(candidate.title) else "en",
        structured_specs_json=candidate.structured_specs_json,
    )
    product.category_review_needed = not bind_google_category_id(
        db, product, candidate.category_id
    )
    ensure_product_sku(db, product, force_allocate=True)
    db.add(product)
    candidate.status = "imported_to_k"
    candidate.k_product_id = product.id
    candidate.reviewed_by_user_id = user.id if user is not None else None
    db.flush()
    return {"product_id": str(product.id), "deduped": False}
