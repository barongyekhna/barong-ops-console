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
