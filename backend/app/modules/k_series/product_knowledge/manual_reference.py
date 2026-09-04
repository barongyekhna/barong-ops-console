"""手动建品的参考图解析:贴图链直下,或从 1688 货源链接自动取主图。

两条路,按优先级:
1. 用户直接贴了参考图链接(1688 主图右键复制地址)——走 F 系列的守卫下载
   (域名白名单 alicdn/amazon 防 SSRF + alicdn 防盗链浏览器头 + 磁盘缓存),
   经 K канonical 媒体路径落库,渲染管线即可稳定读本地字节。
2. 只贴了货源链接——尝试 1688 官方 `alibaba.cross.productInfo` 拿主图。
   实测(2026-07-22)该接口被 ACL 挡(需在 1688 开放平台申请「寻源通」权限组),
   当前会安静跳过;权限批下来的那天,本功能自动开始工作,代码零改动。

调用方(建品路由)负责 fail-safe:参考图失败绝不阻塞建品。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ....models.user import User
from .models import KProductKnowledgeProduct

logger = logging.getLogger(__name__)

_OFFER_ID_PATTERN = re.compile(r"detail\.1688\.com/offer/(\d+)\.html", re.IGNORECASE)
_IMAGE_URL_PATTERN = re.compile(
    r"https?://[^\"\s,]+?\.(?:jpg|jpeg|png|webp)", re.IGNORECASE
)


def extract_offer_id(source_url: str | None) -> str | None:
    match = _OFFER_ID_PATTERN.search(source_url or "")
    return match.group(1) if match else None


def _offer_main_image(db: Session, offer_id: str) -> str | None:
    """经 1688 官方详情接口取主图;ACL 未开通时返回 None(安静降级)。"""

    from ...w_series.logistics import _target_org_id
    from r_system_v2.core.secret_manager import SecretManager
    from r_system_v2.ra.supplier_api import (
        Alibaba1688Credentials,
        Alibaba1688OfficialApiProvider,
    )

    org_id = _target_org_id(db)
    if not org_id:
        return None
    secret = SecretManager(db_session=db).get_key("alibaba1688", org_id)
    provider = Alibaba1688OfficialApiProvider(
        credentials=Alibaba1688Credentials.from_secret_value(secret)
    )
    payload = provider._call_product_info(offer_id)  # noqa: SLF001 - 既有内部口径
    if not isinstance(payload, dict):
        return None
    for candidate in _IMAGE_URL_PATTERN.findall(json.dumps(payload)):
        if "alicdn" in candidate:
            return candidate
    return None


def attach_manual_reference_image(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    reference_image_url: str | None,
    source_url: str | None,
    user: User | None,
    set_main: bool = True,
) -> dict[str, Any]:
    """解析并落库一张参考图。返回结果摘要(供日志/trace)。

    ``set_main`` 控制成功后是否把这张图设为产品主参考图
    (多图批量入库时只有第一张成功的才是主图)。
    """

    from ...f_series.enrichment.images import (
        FImageUnavailableError,
        get_candidate_image,
    )
    from .image_render_jobs import store_reference_image_asset

    image_url = (reference_image_url or "").strip()
    origin = "pasted"
    if not image_url:
        offer_id = extract_offer_id(source_url)
        if not offer_id:
            return {"status": "skipped", "reason": "no_image_source"}
        image_url = _offer_main_image(db, offer_id) or ""
        origin = "offer_api"
        if not image_url:
            return {"status": "skipped", "reason": "offer_api_unavailable_or_acl"}

    try:
        contents, mime_type = get_candidate_image(
            f"k-manual-{product.id}", image_url, "full"
        )
    except FImageUnavailableError as exc:
        return {"status": "failed", "reason": str(exc)[:200], "origin": origin}

    store_reference_image_asset(
        db,
        product=product,
        contents=contents,
        mime_type=mime_type,
        source_url=image_url,
        user=user,
    )
    if set_main:
        product.reference_image_url = image_url
        db.add(product)
    db.flush()
    return {"status": "stored", "origin": origin, "bytes": len(contents)}


def attach_variant_reference_images(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User | None,
) -> list[dict[str, Any]]:
    """变体(颜色)专属参考图:从变体行的 attributes_json.reference_image_url
    下载入库,资产绑定该变体并打上 variant_color 标记。

    同色多卡(1 个装/2 个装)只入库一次;单张失败跳过不阻塞。渲染管线据
    variant_color 自动出"每色主图",上架时挂到对应 Woo variation。
    """

    from sqlalchemy import select

    from ...f_series.enrichment.images import (
        FImageUnavailableError,
        get_candidate_image,
    )
    from .image_render_jobs import store_reference_image_asset
    from .models import KProductKnowledgeVariant

    variants = list(
        db.scalars(
            select(KProductKnowledgeVariant)
            .where(KProductKnowledgeVariant.product_id == product.id)
            .order_by(KProductKnowledgeVariant.created_at.asc())
        )
    )
    results: list[dict[str, Any]] = []
    seen_colors: set[str] = set()
    for variant in variants:
        attrs = variant.attributes_json if isinstance(variant.attributes_json, dict) else {}
        url = str(attrs.get("reference_image_url") or "").strip()
        if not url:
            continue
        color_key = str(variant.color or "").strip() or variant.variant_sku
        if color_key in seen_colors:
            continue
        seen_colors.add(color_key)
        try:
            contents, mime_type = get_candidate_image(
                f"k-variant-ref-{product.id}-{color_key}", url, "full"
            )
            store_reference_image_asset(
                db,
                product=product,
                contents=contents,
                mime_type=mime_type,
                source_url=url,
                user=user,
                variant=variant,
                extra_metadata={
                    "variant_reference": True,
                    "variant_color": str(variant.color or "").strip() or None,
                },
            )
            results.append({"status": "stored", "color": color_key})
        except (FImageUnavailableError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "variant reference image failed product=%s color=%s: %s",
                product.id,
                color_key,
                str(exc)[:160],
            )
            results.append(
                {"status": "failed", "color": color_key, "reason": str(exc)[:160]}
            )
    if results:
        db.flush()
    return results


def attach_manual_reference_images(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    reference_image_urls: list[str] | None,
    source_url: str | None,
    user: User | None,
) -> list[dict[str, Any]]:
    """多条参考图逐张入库;单张失败跳过。一条没贴时回退货源链接推断。

    第一张成功入库的设为主参考图,其余作为备用媒资留给渲染管线。
    """

    urls: list[str] = []
    for candidate in reference_image_urls or []:
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in urls:
            urls.append(cleaned)

    if not urls:
        return [
            attach_manual_reference_image(
                db,
                product=product,
                reference_image_url=None,
                source_url=source_url,
                user=user,
            )
        ]

    results: list[dict[str, Any]] = []
    main_assigned = False
    for url in urls:
        result = attach_manual_reference_image(
            db,
            product=product,
            reference_image_url=url,
            source_url=source_url,
            user=user,
            set_main=not main_assigned,
        )
        if result.get("status") == "stored":
            main_assigned = True
        results.append(result)
    return results


def attach_reference_image_urls(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    urls: list[str],
    variant: object | None,
    user: User | None,
) -> list[dict[str, Any]]:
    """建好之后补参考图链接(「基础档案」面板),逐条入库、逐条回结果。

    - ``variant`` 为 None:产品级参考图;产品还没有主参考图时,第一张存成功的
      成为主参考图(不覆盖已有主图——后补的图是补充,不是替换)。
    - 给了 ``variant``:该变体(颜色)的专属参考图,打 ``variant_reference`` +
      ``variant_color`` 标记,与建品时 attach_variant_reference_images 同口径,
      colorway 出图能认。
    - 每条 URL 一个 savepoint,单条失败不拖累其他;域名不在白名单直接判
      ``host_not_allowed``,不走网络。
    返回 ``[{url, status, variant_sku, asset_id, error}]``。
    """

    from ...f_series.enrichment.images import (
        FImageUnavailableError,
        _host_allowed,
        get_candidate_image,
    )
    from .image_render_jobs import store_reference_image_asset

    variant_sku = getattr(variant, "variant_sku", None)
    variant_color = str(getattr(variant, "color", None) or "").strip() or None
    extra_metadata = (
        {"variant_reference": True, "variant_color": variant_color}
        if variant is not None
        else None
    )
    results: list[dict[str, Any]] = []
    for url in urls:
        entry: dict[str, Any] = {
            "url": url,
            "status": "failed",
            "variant_sku": variant_sku,
            "asset_id": None,
            "error": None,
        }
        if not _host_allowed(url):
            entry["error"] = (
                "host_not_allowed: 只收 1688(alicdn)/ Amazon 图片直链,"
                "其他图请在图片管理里用本地上传。"
            )
            results.append(entry)
            continue
        cache_key = (
            f"k-variant-ref-{product.id}-{variant_sku}"
            if variant is not None
            else f"k-manual-{product.id}"
        )
        try:
            with db.begin_nested():
                contents, mime_type = get_candidate_image(cache_key, url, "full")
                asset = store_reference_image_asset(
                    db,
                    product=product,
                    contents=contents,
                    mime_type=mime_type,
                    source_url=url,
                    user=user,
                    variant=variant,  # type: ignore[arg-type]
                    extra_metadata=extra_metadata,
                )
                if variant is None and not (product.reference_image_url or "").strip():
                    product.reference_image_url = url
                    db.add(product)
                db.flush()
            entry["status"] = "stored"
            entry["asset_id"] = asset.id
        except FImageUnavailableError as exc:
            entry["error"] = str(exc)[:200]
        except Exception as exc:  # noqa: BLE001 - 单条失败不拖累其他,但要原话回给人
            logger.warning(
                "reference image attach failed product=%s url=%s: %s",
                product.id,
                url[:120],
                str(exc)[:200],
            )
            entry["error"] = getattr(exc, "message", None) or str(exc)[:200]
        results.append(entry)
    return results
