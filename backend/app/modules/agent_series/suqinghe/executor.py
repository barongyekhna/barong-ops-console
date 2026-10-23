"""苏青禾的第一个真执行器:老板批了「建 K 档案」卡 → 把草稿建进 K。

只做一件事,做完回读:
- 按 1688 offer 查重(source_system=1688 + source_record_id=offer_id,同一工作区),建过就不再建。
- 走 K 自己的 ``service.create_product``(SKU、类目、规格完整度都由 K 管),再挂参考图。
- 建完**回读**:英文名、来源、类目、参考图都对得上,档案才标 created;否则标 failed。

选择(10-23):1688 只有进价,售价老板还没定 → 一律先建成**单品草稿**(simple_product,不带价)。
K 的规矩是多变体产品每个变体必须有价,硬建 variable 只能填假价;变体清单原样写进
raw_input_text / manual_notes,老板在 K 的「基础档案」面板定价时再改成多变体(那里能改类型和变体)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import memory
from .models import SqhDossier

logger = logging.getLogger(__name__)
SOURCE_SYSTEM = "1688"


class ExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutorResult:
    dossier_id: int
    k_product_id: str
    created: bool  # False = 这个 offer 之前已经建过,这次只是认领
    sku: str | None
    reference_images_stored: int
    note: str


def _scope(db: Session):
    from ...k_series.product_knowledge.scope_shim import KScopeContext
    from ...w_series.logistics import _target_org_id

    org_id = _target_org_id(db)
    if not org_id:
        raise ExecutorError("找不到贸易公司组织,没法确定 K 的工作区。")
    return KScopeContext(workspace_key=str(org_id), business_context="independent_store", scope_mode="production")


def _existing_product(db: Session, *, workspace_key: str, offer_id: str):
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    return db.scalar(
        select(P).where(
            P.workspace_key == workspace_key,
            P.source_system == SOURCE_SYSTEM,
            P.source_record_id == offer_id,
        ),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )


def _ok(field: Any) -> Any:
    return field.get("value") if isinstance(field, dict) and field.get("status") == "ok" else None


def build_create_payload(dossier: SqhDossier) -> dict[str, Any]:
    """草稿 → ProductKnowledgeCreate 的参数(纯函数,测试直接验)。"""
    draft = dossier.draft or {}
    fields = draft.get("fields") or {}
    specs = draft.get("specs") or {}
    name_zh = _ok(fields.get("name_zh")) or ""
    name_en = _ok(fields.get("name_en"))

    additional: list[dict[str, Any]] = []
    for key, item in specs.items():
        value = _ok(item)
        if value in (None, ""):
            continue
        source = (item.get("sources") or [{}])[0]
        unit = item.get("unit")
        additional.append(
            {
                "key": f"sqh_{key}",
                "label": str(source.get("ref") or key)[:255],
                "source_label": str(source.get("ref") or key)[:255],
                "value": f"{value}{(' ' + unit) if unit else ''}",
                "raw_value": str(source.get("raw") or value)[:1000],
            }
        )
    structured = None
    if additional:
        structured = {
            "schema_version": "1.0",
            "source": {
                "platform": "operator",
                "note": f"苏青禾从 1688 offer {dossier.offer_id} 整理(档案 #{dossier.id}),老板批卡后建档",
            },
            "additional_specs": additional,
        }

    variants = draft.get("variants") or []
    variant_lines = [
        f"- {v.get('name_zh')}"
        + (f" / {v['name_en']}" if v.get("name_en") else "")
        + (f" · 进价 ¥{v['cost_price_cny']}" if v.get("cost_price_cny") not in (None, "") else "")
        + (f" · {v['weight_g']}g" if v.get("weight_g") else "")
        for v in variants
    ]
    attr_lines = [f"{a.get('name')}: {a.get('value')}" for a in (draft.get("other_attributes") or [])[:20]]
    raw_parts = [name_zh, f"1688: {dossier.source_url}"]
    if variant_lines:
        raw_parts.append("1688 规格(SKU):\n" + "\n".join(variant_lines))
    if attr_lines:
        raw_parts.append("其他属性:\n" + "\n".join(attr_lines))
    flagged = draft.get("flagged") or []
    notes = [f"苏青禾档案 #{dossier.id}(影子期建档)。"]
    if len(variants) > 1:
        notes.append(f"1688 有 {len(variants)} 个 SKU;售价未定,先建成单品草稿,定价时在基础档案面板改成多变体。")
    if flagged:
        notes.append("待老板处理:" + ";".join(f"{f['path']}({f['status']})" for f in flagged))

    category = _ok(fields.get("category"))
    package = _ok(fields.get("package_includes"))
    payload: dict[str, Any] = {
        "raw_input_text": "\n\n".join(p for p in raw_parts if p) or f"1688 offer {dossier.offer_id}",
        "raw_input_language": "zh",
        "target_market": "US",
        "product_type": "simple_product",
        "product_name_en": name_en,
        "source_system": SOURCE_SYSTEM,
        "source_record_id": str(dossier.offer_id),
        "source_url": dossier.source_url,
        "structured_specs_json": structured,
        "package_includes_json": package if isinstance(package, list) and package else None,
        "manual_notes": "\n".join(notes),
        "category_id": category.get("google_category_id") if isinstance(category, dict) else None,
    }
    return payload


def _reference_count(db: Session, product_id: Any) -> int:
    from ...k_series.product_knowledge.models import KProductKnowledgeMediaAsset as A

    return int(
        db.scalar(
            select(func.count()).select_from(A).where(A.product_id == product_id, A.asset_role == "reference"),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        or 0
    )


def create_k_from_dossier(db: Session, dossier_id: int, actor: User) -> ExecutorResult:
    """建档 + 回读。出错抛 ExecutorError(调用方负责记账,别让卡悄悄停在「已批」)。"""
    from ...k_series.product_knowledge import service as k_service
    from ...k_series.product_knowledge.manual_reference import attach_reference_image_urls
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P
    from ...k_series.product_knowledge.schemas import ProductKnowledgeCreate

    dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    if dossier is None:
        raise ExecutorError(f"档案 #{dossier_id} 不存在。")
    if dossier.status == "created" and dossier.k_product_id:
        return ExecutorResult(dossier.id, dossier.k_product_id, False, None, 0, "这份档案之前已经建过了。")
    if dossier.status != "ready":
        raise ExecutorError(f"档案 #{dossier.id} 状态是 {dossier.status},不是「待批」,不建。")

    scope = _scope(db)
    existing = _existing_product(db, workspace_key=scope.workspace_key, offer_id=str(dossier.offer_id))
    if existing is not None:
        dossier.status = "created"
        dossier.k_product_id = str(existing.id)
        db.add(dossier)
        db.commit()
        return ExecutorResult(dossier.id, str(existing.id), False, existing.sku, _reference_count(db, existing.id),
                              f"这个 1688 商品之前已经建进 K 了(SKU {existing.sku}),没有重复建。")

    payload = build_create_payload(dossier)
    try:
        request = ProductKnowledgeCreate(**payload)
    except Exception as exc:  # noqa: BLE001 —— 校验不过就是草稿有问题,原话给老板
        raise ExecutorError(f"草稿过不了 K 的建档校验:{str(exc)[:300]}") from exc
    product = k_service.create_product(db, payload=request, scope_context=scope)  # 内部会 commit
    product_id = product.id

    urls = list((dossier.draft or {}).get("reference_images") or [])
    stored = 0
    if urls:
        results = attach_reference_image_urls(db, product=product, urls=urls, variant=None, user=actor)
        stored = sum(1 for r in results if r.get("status") == "stored")
        db.commit()

    # ---- 回读:用新查询读,别信手里的对象 ----
    db.expire_all()
    fresh = db.get(P, product_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    problems: list[str] = []
    if fresh is None:
        raise ExecutorError("建完回读不到这个产品。")
    if (fresh.source_system, fresh.source_record_id) != (SOURCE_SYSTEM, str(dossier.offer_id)):
        problems.append("来源没写对")
    if payload.get("product_name_en") and fresh.product_name_en != payload["product_name_en"]:
        problems.append("英文名没写对")
    if payload.get("category_id") and str(fresh.google_product_category or "") != str(payload["category_id"]):
        problems.append("类目没绑上")
    actual_refs = _reference_count(db, fresh.id)
    if stored and actual_refs < stored:
        problems.append(f"参考图只回读到 {actual_refs}/{stored} 张")
    if not fresh.sku:
        problems.append("没有分到 SKU")
    if problems:
        raise ExecutorError("建档回读不一致:" + "、".join(problems) + f"(K 产品 {fresh.id} 已建,请老板看一眼)")

    dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    dossier.status = "created"
    dossier.k_product_id = str(fresh.id)
    dossier.draft = {**(dossier.draft or {}), "k_result": {"sku": fresh.sku, "reference_images": actual_refs, "url_count": len(urls)}}
    db.add(dossier)
    note = f"建好了:K 产品 {fresh.sku}," + (f"参考图 {actual_refs} 张" if actual_refs else "没挂上参考图")
    memory.log_activity(db, f"档案 #{dossier.id} {note}", kind="execute")
    memory.record(
        db, kind="observation", subject=f"建 K 档案 {fresh.sku}",
        body=f"1688 offer {dossier.offer_id} → K 产品 {fresh.sku}({fresh.id})。{note}",
        refs={"dossier_id": dossier.id, "k_product_id": str(fresh.id), "offer_id": dossier.offer_id},
    )
    db.commit()
    return ExecutorResult(dossier.id, str(fresh.id), True, fresh.sku, actual_refs, note)
