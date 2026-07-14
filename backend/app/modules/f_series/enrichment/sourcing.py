"""F 1688 找货段 v2：画像驱动——拿类目画像里的每个产品名去 1688 找货。

v1 的教训（2026-07-14）：拿类目泛称（如"公文包"）搜 1688 分销选品池，
池内无匹配时 API 退化成单字模糊匹配+热销兜底（回来的是茶包盒/菜刀/湿巾）。
用户拍板的 v2 设计：**类目画像（DeepSeek 生成的"这个类目通常有哪些产品"）
就是找货的弹药库**——"野营炊具套装""钛合金叉勺"这种具体产品名一搜一个准。

流程（每类目）：
1. 确保画像存在（无则生成一次，永久缓存）
2. 遍历画像每个产品的中文名 → 1688 词搜 → 每产品收 3-5 个 offer
3. 相关性把关（2-gram 子串，见 offer_matches_product）→ 落候选池
   （notes 记来源产品名，按 offer URL 类目内去重）

额度：F 独立总闸 f_1688_app_calls（默认 1 万/天，用户拍板 R-A 9万/F 1万），
逐产品记账，额度尽温和抛 RAQuotaExhaustedError（运行引擎停批明天续）。
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

import os

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.quota_ledger import (
    PROVIDER_F_1688_APP_CALLS,
    PROVIDER_F_1688_IMAGE_SEARCH,
    PROVIDER_SERPER,
    RAQuotaExhaustedError,
    refund,
    try_consume,
)
from r_system_v2.ra.supplier_api import (
    Alibaba1688Credentials,
    Alibaba1688OfficialApiProvider,
    RASupplierApiError,
    is_acl_denied,
)

from . import profiles as profile_engine
from . import scoring
from . import serper_client
from . import service
from .models import FCategoryCandidate, FProductMarketRef

# 单次搜索调用最多收多少个 offer（词搜/图搜同口径）。
OFFERS_PER_PRODUCT = 5

# 跨境权限未开通时降级分销池，并把开通指引带回运行台账（只记一次）。
CROSSBORDER_ACL_NOTE = (
    "跨境全站词搜权限未开通（1688 开放平台给应用订购「跨境数字化选品」"
    "权限组后自动切换大池），词搜段已用分销选品池（仅 1196 件的样板间）"
)


def _candidates_target() -> int:
    """每个画像产品要凑够几家货源（凑够即停，保护 CPS credit 池）。"""
    try:
        return max(1, int(os.getenv("F_CANDIDATES_PER_PRODUCT", "10")))
    except ValueError:
        return 10


def _images_per_product() -> int:
    """图搜接力每产品最多喂多少张种子图（用户拍板"几十上百都可以"）。"""
    try:
        return max(1, int(os.getenv("F_IMAGES_PER_PRODUCT", "30")))
    except ValueError:
        return 30


class SourcingProvider(Protocol):
    def search_offers_keyword_only(
        self,
        *,
        product: dict[str, Any],
        keyword_profile: dict[str, Any],
        limit: int,
    ) -> list[Any]: ...

    def search_offers_keyword_crossborder(
        self,
        *,
        keyword: str,
        limit: int,
    ) -> list[Any]: ...

    def search_offers_cps_image(
        self,
        *,
        image_url: str,
        limit: int,
    ) -> list[Any]: ...


class FSourcingUnavailableError(RuntimeError):
    """1688 密钥未绑定/不完整——full 模式跳过找货段，sourcing_only 直接失败。"""


class FSourcingNoMatchError(RuntimeError):
    """词搜+图搜接力都没有该类目任何画像产品的新增货源。

    单节点级错误：运行引擎按节点错误收账继续，不阻断整批。
    calls_used 随异常带回（额度已真实消耗，台账不能丢账）。"""

    def __init__(self, message: str, *, calls_used: int = 0) -> None:
        super().__init__(message)
        self.calls_used = calls_used


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


def _cjk_bigrams(text: str) -> set[str]:
    """中文 2-gram 集合（只保留双字都含中文的窗口）。"""
    grams: set[str] = set()
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if all("一" <= ch <= "鿿" for ch in pair):
            grams.add(pair)
    return grams


def offer_matches_product(
    title: str,
    product_zh: str,
    extra_terms: list[str] | None = None,
) -> bool:
    """相关性把关：offer 标题须与画像产品名共享至少一个中文 2-gram。

    1688 分销池在无匹配时会退化成单字碰瓷+热销兜底（"公文包"的"包"命中
    茶包收纳盒），所以按 2 字滑窗判定：
    - "公文包"{公文,文包} vs "茶包收纳盒" → 无共享 → 拦
    - "野营炊具套装"{野营,营炊,炊具,具套,套装} vs "户外厨具套装" → "套装"
      命中 → 放（1688 对同类货的叫法差异是常态，宽一点是对的）
    """
    grams = _cjk_bigrams(str(product_zh or ""))
    for term in extra_terms or []:
        term = str(term or "").strip()
        if len(term) >= 2 and any("一" <= ch <= "鿿" for ch in term):
            grams.update(_cjk_bigrams(term))
    if not grams:
        return True  # 无中文判据时不拦（避免全灭在自己手里）
    return any(gram in title for gram in grams)


def _store_market_refs(
    db: Session,
    *,
    category_id: str,
    product_zh: str,
    product_en: str,
    refs: list[dict[str, str]],
    run_id: UUID | None,
) -> None:
    """市场参考页落库：(类目, 产品, 页面URL) 去重，自兜底绝不阻断找货。"""
    if not refs or not product_zh:
        return
    from uuid import uuid4

    try:
        existing = {
            str(row[0])
            for row in db.execute(
                select(FProductMarketRef.page_url)
                .where(FProductMarketRef.category_id == category_id)
                .where(FProductMarketRef.profile_product_zh == product_zh)
            ).all()
        }
        for ref in refs:
            page_url = str(ref.get("page_url") or "").strip()
            if not page_url or page_url in existing:
                continue
            existing.add(page_url)
            db.add(
                FProductMarketRef(
                    id=uuid4(),
                    category_id=category_id,
                    profile_product_zh=product_zh,
                    profile_product_en=product_en or None,
                    title=str(ref.get("title") or "") or None,
                    page_url=page_url,
                    source_domain=str(ref.get("source_domain") or "") or None,
                    site_type=str(ref.get("site_type") or "") or None,
                    image_url=str(ref.get("image_url") or "") or None,
                    run_id=run_id,
                )
            )
        db.flush()
    except Exception:  # noqa: BLE001 - 参考页是锦上添花，出错回滚跳过
        db.rollback()


def _existing_source_urls(db: Session, category_id: str) -> set[str]:
    rows = db.execute(
        select(FCategoryCandidate.source_url).where(
            FCategoryCandidate.category_id == category_id
        )
    ).all()
    return {str(row[0]).strip() for row in rows if row[0]}


def _keyword_search_for_product(
    db: Session,
    provider: SourcingProvider,
    *,
    product_zh: str,
    product_en: str,
) -> tuple[list[Any], str, int]:
    """词搜段（前置，命中免费直接算数）。返回 (offers, 通道, 消耗调用数)。

    双通道：先试跨境全站词搜（大池）；应用权限组未开通（ACL 拒）就
    整轮降级分销选品池——降级状态挂在 provider 实例上（一次运行只浪费
    一次探测调用，且退款），权限一开自动回到大池。
    """
    calls = 0
    if not getattr(provider, "_f_crossborder_denied", False):
        try_consume(db, PROVIDER_F_1688_APP_CALLS)
        calls += 1
        try:
            db.rollback()
            offers = provider.search_offers_keyword_crossborder(
                keyword=product_zh or product_en,
                limit=OFFERS_PER_PRODUCT,
            )
            return offers, "crossborder", calls
        except RASupplierApiError as exc:
            if not is_acl_denied(exc):
                raise
            provider._f_crossborder_denied = True  # noqa: SLF001 - 运行级降级标记
            refund(db, PROVIDER_F_1688_APP_CALLS)
            calls -= 1
    try_consume(db, PROVIDER_F_1688_APP_CALLS)
    calls += 1
    db.rollback()
    offers = provider.search_offers_keyword_only(
        product={"title": product_zh or product_en, "title_zh": product_zh},
        keyword_profile={
            "product_type_zh": product_zh,
            "core_keywords_zh": [product_zh] if product_zh else [],
        },
        limit=OFFERS_PER_PRODUCT,
    )
    return offers, "fenxiao", calls


def source_category(
    db: Session,
    *,
    node: dict[str, Any],
    provider: SourcingProvider,
    org_id: str,
    run_id: UUID | None = None,
    serper_api_key: str | None = None,
) -> dict[str, Any]:
    """一个类目找货：画像的每个产品 = 词搜前置 + 图搜接力，凑够目标即停。

    图搜接力（2026-07-14 用户拍板）：词搜池只有 1196 件样板间，没吃饱就用
    serper 谷歌图片拿一批种子图，逐张喂 CPS 分销大池图搜（已付费 50 万次
    credit 池）。额度逐调用记账（F 双闸 + serper）；RAQuotaExhaustedError
    向上抛，运行引擎按额度尽停批。serper_api_key 缺失时只跑词搜段。
    """
    profile = profile_engine.ensure_profile(
        db,
        category_id=str(node["id"]),
        category_path=str(node["full_path"]),
        name_zh=(str(node["name_zh"]) if node.get("name_zh") else None),
        org_id=org_id,
    )
    products = [
        item
        for item in (profile.products_json or [])
        if str(item.get("zh") or "").strip()
    ]
    if not products:
        raise FSourcingNoMatchError(
            f"类目「{node.get('name_zh') or node.get('name')}」画像为空，无从找货。"
        )

    seen_urls = _existing_source_urls(db, str(node["id"]))
    created = 0
    filtered = 0
    duplicates = 0
    offers_seen = 0
    calls_used = 0
    image_calls = 0
    channels_used: set[str] = set()
    search_errors: list[str] = []
    target = _candidates_target()
    images_cap = _images_per_product()

    for item in products:
        product_zh = str(item.get("zh") or "").strip()
        product_en = str(item.get("en") or "").strip()
        product_created = 0

        def ingest(offers: list[Any]) -> None:
            """把关+去重+落池（词搜/图搜同口径）。"""
            nonlocal created, filtered, duplicates, offers_seen, product_created
            offers_seen += len(offers)
            for offer in offers[:OFFERS_PER_PRODUCT]:
                title = str(getattr(offer, "title", "") or "")
                if not offer_matches_product(title, product_zh):
                    filtered += 1
                    continue
                source_url = str(getattr(offer, "supplier_url", "") or "").strip()
                if not source_url or source_url in seen_urls:
                    duplicates += 1
                    continue
                seen_urls.add(source_url)
                payload = getattr(offer, "payload", None) or {}
                image_url = str(payload.get("image_url") or "").strip() or None
                moq_value = getattr(offer, "moq", None)
                moq_int = int(moq_value) if moq_value is not None else None
                sales_value = getattr(offer, "monthly_sales", None)
                service.create_candidate(
                    db,
                    category_id=str(node["id"]),
                    title=title or "1688 货源候选",
                    user=None,
                    source_url=source_url,
                    image_url=image_url,
                    price_cny=getattr(offer, "unit_price_cny", None),
                    moq=moq_int,
                    supplier_name=str(getattr(offer, "supplier_name", "") or "")
                    or None,
                    notes=f"画像产品: {product_zh}"
                    + (f" ({product_en})" if product_en else ""),
                    run_id=run_id,
                    source="alibaba1688",
                    profile_product_zh=product_zh or None,
                    profile_product_en=product_en or None,
                    score_json=scoring.base_components(
                        moq=moq_int,
                        monthly_sales=(
                            int(sales_value) if sales_value is not None else None
                        ),
                        one_piece_hint=bool(getattr(offer, "one_piece_hint", False)),
                    ),
                )
                created += 1
                product_created += 1

        # ---- A. 词搜段（免费池前置，命中直接算数）----
        try:
            offers, channel, kw_calls = _keyword_search_for_product(
                db, provider, product_zh=product_zh, product_en=product_en
            )
            calls_used += kw_calls
            channels_used.add(channel)
            ingest(offers)
        except RAQuotaExhaustedError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单产品词搜失败不阻断
            refund(db, PROVIDER_F_1688_APP_CALLS)
            search_errors.append(f"{product_zh} 词搜: {str(exc)[:80]}")

        # ---- B. 图搜接力（没吃饱才发动：serper 种子图 → CPS 大池）----
        if product_created < target and serper_api_key:
            seed_urls: list[str] = []
            try:
                try_consume(db, PROVIDER_SERPER)
                db.rollback()
                # 用英文名搜种子图（用户拍板 2026-07-15）：独立站卖欧美市场，
                # 中文名搜出来的产品风格偏中文圈；英文种子图 → 1688 图搜
                # 找到的才是欧美风格的同款。
                raw = serper_client.serper_images(
                    api_key=serper_api_key, query=product_en or product_zh
                )
                seed_urls = serper_client.extract_image_urls(raw, limit=images_cap)
                # 顺手收割图片来源网页（竞品定价/变体研究，组头展示）
                _store_market_refs(
                    db,
                    category_id=str(node["id"]),
                    product_zh=product_zh,
                    product_en=product_en,
                    refs=serper_client.extract_market_refs(raw, limit=3),
                    run_id=run_id,
                )
            except RAQuotaExhaustedError:
                raise
            except Exception as exc:  # noqa: BLE001 - 种子图失败只跳过接力
                refund(db, PROVIDER_SERPER)
                search_errors.append(f"{product_zh} 种子图: {str(exc)[:80]}")

            for seed_url in seed_urls:
                if product_created >= target:
                    break
                try_consume(db, PROVIDER_F_1688_IMAGE_SEARCH)
                try_consume(db, PROVIDER_F_1688_APP_CALLS)
                calls_used += 1
                image_calls += 1
                try:
                    db.rollback()
                    offers = provider.search_offers_cps_image(
                        image_url=seed_url, limit=OFFERS_PER_PRODUCT
                    )
                except Exception as exc:  # noqa: BLE001 - 单图失败换下一张
                    refund(db, PROVIDER_F_1688_IMAGE_SEARCH)
                    refund(db, PROVIDER_F_1688_APP_CALLS)
                    calls_used -= 1
                    image_calls -= 1
                    search_errors.append(f"{product_zh} 图搜: {str(exc)[:60]}")
                    continue
                channels_used.add("cps_image")
                ingest(offers)

        if product_created and product_zh:
            # 组内价格分依赖全组，本产品落库后立即重算该组总分与 top3。
            scoring.rescore_product_group(
                db,
                category_id=str(node["id"]),
                profile_product_zh=product_zh,
            )

    if created == 0:
        detail = f"；搜索失败 {len(search_errors)} 个产品" if search_errors else ""
        raise FSourcingNoMatchError(
            f"类目「{node.get('name_zh') or node.get('name')}」按 {len(products)} 个"
            f"画像产品词搜+图搜接力，无新增货源（不相关 {filtered} 条、重复"
            f" {duplicates} 条{detail}）——可到候选池手动贴 1688 全站链接",
            calls_used=calls_used,
        )
    return {
        "offers_seen": offers_seen,
        "candidates_created": created,
        "filtered_irrelevant": filtered,
        "products_searched": len(products),
        "calls_used": calls_used,
        "image_calls": image_calls,
        "channel_note": (
            CROSSBORDER_ACL_NOTE
            if channels_used and "crossborder" not in channels_used
            else None
        ),
    }
