"""R→K 搬运：把 R-W 仓库里的产品搬进 K 产品知识库。

每个产品：
- 基础字段映射（title / brand / price / asin…）。
- **自动落类目**：channel=amazon 直绑 Keepa 节点；channel=dtc 走对齐表落
  Google（category_resolver.assign_category —— R 来的产品正是它的调用点）。
- **带参考图**：products_rw.image_url → K.reference_image_url（临时作图参考，
  跳 I 时自动填入，I 存回时清除）。
- 按 asin（source_record_id）在同 scope 内去重，重复搬运跳过。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ....models.user import User
from . import category_resolver as CR
from .constants import TARGET_ORGANIZATION_NAME
from .models import KProductKnowledgeProduct
from .scope_shim import KScopeContext

_RW_COLUMNS = (
    "asin, marketplace, title, brand, category_id, category_path, "
    "price, image_url, source_query"
)


def transfer_from_rw(
    db: Session,
    *,
    asins: list[str],
    channel: str,
    user: User | None,
    scope_context: KScopeContext,
) -> dict[str, Any]:
    from .service import _generate_unique_product_key

    channel = (channel or "dtc").strip().lower()
    if channel not in ("amazon", "dtc"):
        channel = "dtc"
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for raw_asin in asins:
        asin = (raw_asin or "").strip()
        if not asin:
            continue
        rw = db.execute(
            text(f"SELECT {_RW_COLUMNS} FROM products_rw WHERE asin = :a"),
            {"a": asin},
        ).mappings().first()
        if rw is None:
            errors.append({"asin": asin, "reason": "not_in_rw"})
            continue
        already = db.execute(
            text(
                "SELECT id FROM k_product_knowledge_products "
                "WHERE source_record_id = :a AND workspace_key = :w "
                "AND business_context = :b LIMIT 1"
            ),
            {
                "a": asin,
                "w": scope_context.workspace_key,
                "b": scope_context.business_context,
            },
        ).first()
        if already is not None:
            skipped.append(asin)
            continue
        try:
            # savepoint：单产品失败只回滚它自己，不影响整批已成功的
            with db.begin_nested():
                product = KProductKnowledgeProduct(
                    id=uuid4(),
                    product_key=_generate_unique_product_key(db),
                    workspace_key=scope_context.workspace_key,
                    business_context=scope_context.business_context,
                    scope_mode=scope_context.scope_mode,
                    organization_name=TARGET_ORGANIZATION_NAME,
                    product_name_en=((rw["title"] or "")[:512] or None),
                    primary_keyword=(
                        (rw["source_query"] or rw["title"] or "")[:512] or None
                    ),
                    brand_name=rw["brand"],
                    sku=asin,
                    parent_sku=asin,
                    target_market="US",
                    product_type="simple_product",
                    canonical_language="en",
                    regular_price=rw["price"],
                    price_currency="USD",
                    channel=channel,
                    amazon_category_id=rw["category_id"],
                    category_path=rw["category_path"],
                    reference_image_url=rw["image_url"],
                    source_system="r_w",
                    source_record_id=asin,
                    product_status="draft",
                    review_status="draft",
                    raw_input_text=(rw["title"] or asin),
                )
                # 新 Keepa 类目自动创建（#7）+ 按 channel 自动落类目（#5/#6）
                CR.ensure_amazon_category(db, rw["category_id"], rw["category_path"])
                CR.assign_category(db, product)
                db.add(product)
                db.flush()
            created.append(
                {
                    "asin": asin,
                    "product_id": str(product.id),
                    "channel": channel,
                    "amazon_category_id": product.amazon_category_id,
                    "google_product_category": product.google_product_category,
                    "category_review_needed": product.category_review_needed,
                    "has_reference_image": bool(product.reference_image_url),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单产品失败不阻断整批
            errors.append({"asin": asin, "reason": str(exc)[:200]})

    return {"created": created, "skipped": skipped, "errors": errors}
