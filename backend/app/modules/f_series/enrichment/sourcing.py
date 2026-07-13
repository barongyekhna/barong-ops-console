"""F 1688 直连找货段：每类目词搜 3-5 个货源候选，自动进候选池。

复用 R-A 的现成件：
- ``build_supplier_keyword_profile``：DeepSeek 把英文类目/关键词抽成中文采购
  词（1688 分销池是国内池，必须中文搜；无 DeepSeek 密钥时启发式降级）。
- ``Alibaba1688OfficialApiProvider.search_offers_keyword_only``：词搜-only 通道，
  候选词从具体到宽泛逐个重试，零图搜成本。
- 额度：App 全局调用总闸（与 R-A 共账），每类目按 ~4 次调用预扣
  （词搜最多 4 个候选词重试）；F 手动触发天然优先。

红线照旧只标记不毙掉——``service.create_candidate`` 统一处理。
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.supplier_api import (
    Alibaba1688Credentials,
    Alibaba1688OfficialApiProvider,
)
from r_system_v2.ra.supplier_keyword_skill import build_supplier_keyword_profile

from . import service
from .models import FCategoryCandidate, FCategoryKeyword

# 每类目候选目标数（用户定的 3-5 个）与预扣的 App 调用数（词搜重试上限）。
OFFERS_PER_CATEGORY = 5
ESTIMATED_CALLS_PER_CATEGORY = 4


class SourcingProvider(Protocol):
    def search_offers_keyword_only(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> list[Any]: ...


class FSourcingUnavailableError(RuntimeError):
    """1688 密钥未绑定/不完整——full 模式跳过找货段，sourcing_only 直接失败。"""


def build_provider(db: Session, *, org_id: str) -> SourcingProvider:
    """从密钥编排取 1688 凭证并构建官方 API 词搜通道。"""
    try:
        secret_value = SecretManager(db_session=db).get_key("alibaba1688", org_id)
    except SecretManagerError as exc:
        raise FSourcingUnavailableError(f"1688 密钥未绑定：{exc}") from exc
    credentials = Alibaba1688Credentials.from_secret_value(secret_value or "")
    if not credentials.ready:
        raise FSourcingUnavailableError(
            "1688 官方 API 密钥不完整（需要 app_key/app_secret/access_token）。"
        )
    return Alibaba1688OfficialApiProvider(credentials=credentials)


def _pseudo_product(db: Session, node: dict[str, Any]) -> dict[str, Any]:
    """类目 → 伪产品档案（给 DeepSeek 抽中文采购词用）。

    title = 类目名 + 该类目最优英文关键词（放行的优先、related 优先），
    让采购词落在类目里的具体商品上而不是类目泛称。
    """
    rows = db.execute(
        select(FCategoryKeyword.keyword_text)
        .where(FCategoryKeyword.category_id == str(node["id"]))
        .where(FCategoryKeyword.status.in_(["approved", "candidate"]))
        .where(FCategoryKeyword.keyword_type == "related")
        .order_by(
            (FCategoryKeyword.status == "approved").desc(),
            FCategoryKeyword.rank.asc().nulls_last(),
        )
        .limit(3)
    ).all()
    keywords = [str(row[0]) for row in rows]
    title = " ".join([str(node.get("name") or ""), *keywords]).strip()
    return {
        "title": title or str(node.get("name") or ""),
        "category": str(node.get("name") or ""),
        "category_path": str(node.get("full_path") or ""),
    }


def _existing_source_urls(db: Session, category_id: str) -> set[str]:
    rows = db.execute(
        select(FCategoryCandidate.source_url).where(
            FCategoryCandidate.category_id == category_id
        )
    ).all()
    return {str(row[0]).strip() for row in rows if row[0]}


def source_category(
    db: Session,
    *,
    node: dict[str, Any],
    provider: SourcingProvider,
    org_id: str,
    run_id: UUID | None = None,
    limit: int = OFFERS_PER_CATEGORY,
) -> dict[str, int]:
    """一个类目找货：中文采购词 → 1688 词搜 → 去重落候选池。"""
    product = _pseudo_product(db, node)
    keyword_profile = build_supplier_keyword_profile(
        db, org_id=org_id, product=product
    )
    # RASupplierApiError（词搜业务失败）向上抛，由运行引擎按单节点错误收账，
    # 不阻断整批——只有密钥问题才是 FSourcingUnavailableError（build_provider）。
    offers = provider.search_offers_keyword_only(
        product=product,
        keyword_profile=keyword_profile,
        limit=limit,
    )

    seen_urls = _existing_source_urls(db, str(node["id"]))
    created = 0
    for offer in offers[:limit]:
        source_url = str(getattr(offer, "supplier_url", "") or "").strip()
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        payload = getattr(offer, "payload", None) or {}
        image_url = str(payload.get("image_url") or "").strip() or None
        moq_value = getattr(offer, "moq", None)
        service.create_candidate(
            db,
            category_id=str(node["id"]),
            title=str(getattr(offer, "title", "") or "1688 货源候选"),
            user=None,
            source_url=source_url,
            image_url=image_url,
            price_cny=getattr(offer, "unit_price_cny", None),
            moq=int(moq_value) if moq_value is not None else None,
            supplier_name=str(getattr(offer, "supplier_name", "") or "") or None,
            notes=None,
            run_id=run_id,
            source="alibaba1688",
        )
        created += 1
    return {"offers_seen": len(offers), "candidates_created": created}
