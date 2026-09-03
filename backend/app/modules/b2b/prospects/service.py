"""Service layer for B2B customer prospecting."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.quota_ledger import (
    PROVIDER_B2B_SERPER_PLACES,
    RAQuotaExhaustedError,
    daily_budget,
    ensure_quota_schema,
    try_consume,
)

from ....models.organization import OrganizationRecord
from . import screening
from .models import (
    PROSPECT_STATUS_APPROVED,
    PROSPECT_STATUS_NEW,
    PROSPECT_STATUS_REJECTED,
    B2BProspect,
    B2BProspectQuery,
    B2BProspectSweep,
    B2BTargetCity,
)
from .serper_places import SerperPlacesError, search_places
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION

logger = logging.getLogger(__name__)

TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"


class ProspectError(RuntimeError):
    """挖掘流程的可预期错误(配置缺失、额度耗尽等)。"""


# --------------------------------------------------------------------------
# 密钥
# --------------------------------------------------------------------------
def _serper_key(db: Session) -> str:
    org_id = db.scalar(
        select(OrganizationRecord.org_id)
        .where(OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME)
        .where(OrganizationRecord.status != "deleted")
        .limit(1)
    )
    if not org_id:
        raise ProspectError(
            f"目标组织不存在：{TARGET_ORGANIZATION_NAME}（B2B 只挂国际贸易组织）"
        )
    try:
        key = SecretManager(db_session=db).get_key("serper", org_id)
    except SecretManagerError as exc:
        raise ProspectError(f"Serper 密钥未配置：{exc}") from exc
    if not key:
        raise ProspectError("Serper 密钥未配置（去密钥管理绑一把）。")
    return key


# --------------------------------------------------------------------------
# 清洗与去重
# --------------------------------------------------------------------------
def _domain_of(website: str | None) -> str | None:
    if not website:
        return None
    candidate = website.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    host = (urlparse(candidate).netloc or "").lower()
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _dedupe_key(place: dict, *, city: str, country: str) -> str:
    """有网站按域名去重(最可靠);没网站退化成"店名+城市",保证总有键。"""
    domain = _domain_of(place.get("website"))
    if domain:
        return f"domain:{domain}"
    name = re.sub(r"\s+", " ", str(place.get("title") or "")).strip().lower()
    return f"name:{country}:{city.lower()}:{name}"


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 跑批
# --------------------------------------------------------------------------
# 用户拍板(2026-07-27):小城市优先但不只做小城,大城两成、小城八成。
# 大城市地图结果被连锁店(MEC/Patagonia)霸占,不是目标客户;小镇店铺几乎
# 没人开发过。但完全不碰大城市也不对——那里店铺密度高。
BIG_CITY_POPULATION = 500_000
SMALL_CITY_RUN = 4  # 每跑 4 个小城穿插 1 个大城


def _mixed_city_order(cities: list[B2BTargetCity]) -> list[B2BTargetCity]:
    """按 8:2 交替排:小城优先,每四个小城插一个大城。"""
    big = [c for c in cities if (c.population or 0) >= BIG_CITY_POPULATION]
    small = [c for c in cities if (c.population or 0) < BIG_CITY_POPULATION]
    ordered: list[B2BTargetCity] = []
    big_index = 0
    for position, city in enumerate(small, start=1):
        ordered.append(city)
        if position % SMALL_CITY_RUN == 0 and big_index < len(big):
            ordered.append(big[big_index])
            big_index += 1
    ordered.extend(big[big_index:])
    return ordered


def run_sweep(
    db: Session,
    *,
    max_queries: int = 50,
    country: str | None = None,
    store_type: str | None = None,
) -> dict[str, object]:
    """跑一批"查询模板 × 城市"组合。

    - 跑过的组合永不重复跑(靠 b2b_prospect_sweeps 拦),支持断点续跑。
    - 每次 Serper 调用**先扣额度再发请求**,额度耗尽温和停止,已抓到的全保留。
    - 城市顺序走 `_mixed_city_order`:**小城八成、大城两成**(用户拍板的 28 分)。
      大城市精品店天天被人开发,小镇店铺几乎没人找过,机会反而更大;但大城市
      一个都不漏,只是排在后面。纯按人口降序跑过一次,抓回来的 40 家全是
      MEC/Patagonia 这类连锁,一家能谈的都没有。
    """
    ensure_quota_schema(db)
    api_key = _serper_key(db)

    query_stmt = select(B2BProspectQuery).where(B2BProspectQuery.active.is_(True))
    if country:
        query_stmt = query_stmt.where(B2BProspectQuery.country == country)
    if store_type:
        query_stmt = query_stmt.where(B2BProspectQuery.store_type == store_type)

    # **只挖正在跑的那个店型**。这是结构性保护,不是技术限制:用户一个人处理
    # 回复,同时开几条线他本人就是瓶颈。产品类目以后有几十个,这道门保证他的
    # 负担恒定。
    from ..store_types import service as store_type_service

    active_keys = store_type_service.active_store_type_keys(db)
    if not active_keys:
        raise ProspectError(
            "现在没有店型在跑。去「店型」里挑一个开跑——一次只开一种，"
            "回复才接得住。"
        )
    if store_type and store_type not in active_keys:
        raise ProspectError(
            f"店型 {store_type} 不在跑批状态，先去「店型」里把它开跑。"
        )
    query_stmt = query_stmt.where(B2BProspectQuery.store_type.in_(active_keys))

    queries = list(db.scalars(query_stmt))
    if not queries:
        raise ProspectError(
            "正在跑的店型底下没有启用的查询模板，先去配置页加几条。"
        )

    done_pairs = {
        (row.query_id, row.city_id)
        for row in db.scalars(select(B2BProspectSweep))
    }

    executed = 0
    created = 0
    seen_total = 0
    quota_stopped = False
    errors: list[str] = []

    for query in queries:
        city_stmt = (
            select(B2BTargetCity)
            .where(B2BTargetCity.active.is_(True))
            .where(B2BTargetCity.country == query.country)
            .order_by(
                B2BTargetCity.priority.desc(),
                B2BTargetCity.population.desc().nullslast(),
                B2BTargetCity.city.asc(),
            )
        )
        for city in _mixed_city_order(list(db.scalars(city_stmt))):
            if executed >= max_queries:
                break
            if (query.id, city.id) in done_pairs:
                continue

            try:
                try_consume(db, PROVIDER_B2B_SERPER_PLACES, amount=1)
            except RAQuotaExhaustedError:
                quota_stopped = True
                break

            rendered = query.query_template.replace("{city}", city.city)
            # 出网前先结束事务：长事务被 idle-in-transaction 掐断踩过。
            db.commit()
            try:
                places = search_places(
                    api_key=api_key,
                    query=rendered,
                    country=query.country,
                    language=query.language,
                )
                error_text = None
            except SerperPlacesError as exc:
                places = []
                error_text = str(exc)[:500]
                errors.append(f"{rendered}: {error_text}")

            executed += 1
            seen_total += len(places)
            new_here = _persist_places(
                db,
                places=places,
                query=query,
                city=city,
                rendered_query=rendered,
            )
            created += new_here
            db.add(
                B2BProspectSweep(
                    query_id=query.id,
                    city_id=city.id,
                    ran_at=datetime.now(timezone.utc),
                    results_count=len(places),
                    new_count=new_here,
                    error=error_text,
                )
            )
            try:
                db.commit()
            except IntegrityError as exc:
                # 一个城市写失败不该让整轮抓取 500,已抓到的必须保住。
                db.rollback()
                created -= new_here
                errors.append(f"{rendered}: 写入冲突已跳过 ({exc.orig})"[:300])
                logger.warning("B2B prospect persist conflict: %s", rendered)

        if quota_stopped or executed >= max_queries:
            break

    return {
        "queries_executed": executed,
        "places_seen": seen_total,
        "prospects_created": created,
        "quota_stopped": quota_stopped,
        "errors": errors[:10],
        **quota_status(db),
    }


def _persist_places(
    db: Session,
    *,
    places: list[dict],
    query: B2BProspectQuery,
    city: B2BTargetCity,
    rendered_query: str,
) -> int:
    created = 0
    # 同一次搜索里,连锁店的多个门店常共用一个网站域名 → 去重键相同。
    # 只查库不够:同批未提交的记录查不到,两条都会插进去,提交时唯一键炸
    # (2026-07-27 实际踩过,整轮抓取 500)。所以批内也要去重。
    batch_keys: set[str] = set()
    for place in places:
        name = str(place.get("title") or "").strip()
        if not name:
            continue
        key = _dedupe_key(place, city=city.city, country=query.country)
        if key in batch_keys:
            continue
        exists = db.scalar(
            select(B2BProspect.id).where(B2BProspect.dedupe_key == key)
        )
        if exists is not None:
            continue
        batch_keys.add(key)
        db.add(
            B2BProspect(
                dedupe_key=key,
                store_name=name[:255],
                website=(str(place.get("website") or "").strip() or None),
                phone=(str(place.get("phoneNumber") or "").strip() or None),
                address=(str(place.get("address") or "").strip() or None),
                city=city.city,
                region=city.region,
                country=query.country,
                rating=(str(place.get("rating")) if place.get("rating") else None),
                reviews_count=_as_int(place.get("ratingCount")),
                store_type=query.store_type,
                language=query.language,
                source_query=rendered_query[:255],
                place_category=(
                    str(place.get("category") or "").strip()[:128] or None
                ),
                place_cid=(str(place.get("cid") or "").strip()[:64] or None),
                status=PROSPECT_STATUS_NEW,
            )
        )
        created += 1
    return created


# --------------------------------------------------------------------------
# 额度
# --------------------------------------------------------------------------
def quota_status(db: Session) -> dict[str, int]:
    """今日已用 / 每日额度。台账表和 R-A/F 共用一张,只是 provider 不同。"""
    ensure_quota_schema(db)
    used = int(
        db.scalar(
            text(
                "SELECT COALESCE(used, 0) FROM ra_provider_quota_usage "
                "WHERE provider = :provider AND day = CURRENT_DATE"
            ),
            {"provider": PROVIDER_B2B_SERPER_PLACES},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        or 0
    )
    return {
        "quota_used_today": used,
        "quota_budget": daily_budget(PROVIDER_B2B_SERPER_PLACES),
    }


# --------------------------------------------------------------------------
# 人工审核
# --------------------------------------------------------------------------
GOOGLE_MAPS_CID_URL = "https://www.google.com/maps?cid="
CHAIN_REVIEWS_THRESHOLD = 800


def maps_url_for(prospect: B2BProspect) -> str | None:
    """拼谷歌地图链接。Serper 不返回网站,但地图页上有——点开还能看店面
    照片、营业时间、卖什么,这是人工审核最有效的一眼。"""
    if not prospect.place_cid:
        return None
    return f"{GOOGLE_MAPS_CID_URL}{prospect.place_cid}"


def chain_hints(db: Session, prospects: list[B2BProspect]) -> dict[UUID, str]:
    """标出疑似连锁,让人工审核能一眼跳过。

    两个信号:同名店出现在多个城市;评价数过千(独立小店很少到这个量级)。
    只是提示,不自动拒绝——判断权始终在人手上。
    """
    names = {p.store_name.strip().lower() for p in prospects if p.store_name}
    if not names:
        return {}
    rows = db.execute(
        text(
            "SELECT lower(trim(store_name)) AS name, "
            "count(DISTINCT city) AS cities "
            "FROM b2b_prospects WHERE lower(trim(store_name)) = ANY(:names) "
            "GROUP BY 1"
        ),
        {"names": list(names)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).all()
    city_counts = {row[0]: int(row[1]) for row in rows}

    hints: dict[UUID, str] = {}
    for prospect in prospects:
        signals: list[str] = []
        cities = city_counts.get(prospect.store_name.strip().lower(), 1)
        if cities > 1:
            signals.append(f"同名店出现在 {cities} 个城市")
        if (prospect.reviews_count or 0) >= CHAIN_REVIEWS_THRESHOLD:
            signals.append(f"评价数 {prospect.reviews_count}")
        if signals:
            hints[prospect.id] = "疑似连锁：" + "、".join(signals)
    return hints


def review_prospect(
    db: Session,
    *,
    prospect_id: UUID,
    approve: bool,
    reject_reason: str | None = None,
    notes: str | None = None,
) -> B2BProspect:
    prospect = db.get(B2BProspect, prospect_id)
    if prospect is None:
        raise ProspectError("客户记录不存在。")
    prospect.status = (
        PROSPECT_STATUS_APPROVED if approve else PROSPECT_STATUS_REJECTED
    )
    prospect.reject_reason = None if approve else (reject_reason or None)
    if notes is not None:
        prospect.notes = notes or None
    db.commit()
    db.refresh(prospect)
    return prospect


def list_prospects(
    db: Session,
    *,
    status: str | None = None,
    country: str | None = None,
    store_type: str | None = None,
    verdict: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[B2BProspect], dict[str, int]]:
    stmt = select(B2BProspect)
    if status:
        stmt = stmt.where(B2BProspect.status == status)
    if country:
        stmt = stmt.where(B2BProspect.country == country)
    if store_type:
        stmt = stmt.where(B2BProspect.store_type == store_type)
    if verdict:
        # 界面默认只看「推荐发的」——用户读结论,不看原始数据。
        stmt = stmt.where(B2BProspect.screen_verdict == verdict)
    rows = list(
        db.scalars(
            stmt.order_by(B2BProspect.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
    )
    counts = {}
    for name in ("new", "approved", "rejected", "contacted", "replied", "customer"):
        counts[f"{name}_count"] = int(
            db.scalar(
                select(func.count())
                .select_from(B2BProspect)
                .where(B2BProspect.status == name)
            )
            or 0
        )
    return rows, counts


# --------------------------------------------------------------------------
# 自动筛选:机器读官网,给人写一句话
# --------------------------------------------------------------------------


def _products_for_store_type(db: Session, store_type: str) -> list[dict]:
    """这个店型实际能拿到哪些货。**谷歌类目树自己回答"这货给谁"。**

    店型 → 类目前缀(内置目录) → 批发目录里落在这些前缀下的产品。
    绝不在提示词里写死产品名:写死过一次,AI 就对着宠物店念"露营装备",
    用户当场看出来。类目已经决定了归属,系统该自己算。
    """
    from ..store_types import service as store_type_service
    from ..wholesale.models import STATUS_ARCHIVED, B2BWholesaleItem

    try:
        prefixes = store_type_service.prefixes_for(db, store_type)
    except store_type_service.StoreTypeError:
        return []
    if not prefixes:
        return []
    out: list[dict] = []
    for item in db.scalars(select(B2BWholesaleItem)):
        if item.status == STATUS_ARCHIVED:
            continue
        if not store_type_service.matches_any_prefix(item.category_path, prefixes):
            continue
        out.append(
            {
                "sku": item.sku,
                "name": item.product_name,
                "category": " > ".join(item.category_path or []),
            }
        )
    return out


def screen_prospects(
    db: Session,
    *,
    limit: int = 20,
    store_type: str | None = None,
    user=None,
) -> dict[str, object]:
    """把待审客户过一遍三层漏斗,结果写回记录。

    用户原话:"我还是不知道应该咋筛选😂这个我没办法通过这点信息确定"。
    所以这里不再要求他判断,只让他读结论。三层顺序按成本从低到高排:
    规则(免费) → 找官网(Serper) → 读官网+AI。前一层能判死就不进下一层。

    **每家店的网络调用(抓官网 12s + AI 十几秒)期间必须完全不碰数据库。**
    先把要用的字段抠成纯字典、结束事务,跑完网络再按 id 取回来写。直接拿着
    ORM 对象跑会触发懒加载 SELECT 开事务,被 8s idle-in-transaction 掐断
    ——2026-07-29 实测炸过一次(和 K 工作流那次同一个根因)。
    """
    stmt = (
        select(B2BProspect)
        .where(B2BProspect.status == PROSPECT_STATUS_NEW)
        .where(B2BProspect.screen_verdict.is_(None))
        .order_by(B2BProspect.created_at)
        .limit(max(1, min(limit, 100)))
    )
    if store_type:
        stmt = stmt.where(B2BProspect.store_type == store_type)
    rows = list(db.scalars(stmt))
    if not rows:
        return {
            "screened": 0,
            "fit": 0,
            "unfit": 0,
            "unsure": 0,
            "quota_stopped": False,
            "quota_used_today": quota_status(db).get("quota_used_today", 0),
            "message": "没有待筛选的客户。",
        }

    hints = chain_hints(db, rows)
    # 抠成纯字典,之后整个网络阶段都不再碰 ORM。
    targets = [
        {
            "id": row.id,
            "name": row.store_name,
            "place_category": row.place_category,
            "place_cid": row.place_cid,
            "phone": row.phone,
            "city": row.city,
            "region": row.region,
            "country": row.country,
            "rating": row.rating,
            "reviews_count": row.reviews_count,
            "website": row.website,
            "store_type": row.store_type,
            "chain_hint": hints.get(row.id),
        }
        for row in rows
    ]
    db.commit()

    # 每个店型的可卖货清单算一次就够。没货的店型整批跳过——对着一个
    # 我们没有任何货可卖的店型筛客户，纯属烧钱(实测 40 家宠物店就是这样)。
    products_by_type: dict[str, list[dict]] = {}
    for key in {t["store_type"] for t in targets}:
        products_by_type[key] = _products_for_store_type(db, key)
    empty_types = sorted(k for k, v in products_by_type.items() if not v)
    skipped = [t for t in targets if not products_by_type[t["store_type"]]]
    targets = [t for t in targets if products_by_type[t["store_type"]]]

    counts = {"fit": 0, "unfit": 0, "unsure": 0}
    quota_stopped = False
    api_key: str | None = None

    for target in targets:
        # 第一层:规则,免费判死,不花任何出网调用
        rejected = screening.rule_reject_reason(
            target, chain_hint=target["chain_hint"]
        )
        if rejected:
            _persist_screen(
                db, target["id"], screening.VERDICT_UNFIT, rejected, {}
            )
            counts["unfit"] += 1
            continue

        # 第二层:补官网(Serper 网页搜索,走额度)
        if not target["website"]:
            if api_key is None:
                api_key = _serper_key(db)
                db.commit()
            try:
                found = screening.search_website(db, api_key, target)
            except screening.ScreeningError:
                quota_stopped = True
                break
            if found:
                target["website"] = found
                _persist_website(db, target["id"], found)

        # 第三层:读官网 + AI 判断。**这一段完全不碰数据库。**
        site_text = (
            screening.fetch_site_text(target["website"])
            if target["website"]
            else None
        )
        parsed = screening.classify_with_ai(
            target,
            site_text,
            our_products=products_by_type[target["store_type"]],
            user=user,
        )
        verdict, reason, signals, personal_line = screening.normalise_verdict(
            parsed, had_site_text=bool(site_text)
        )
        _persist_screen(
            db, target["id"], verdict, reason, signals, personal_line
        )
        counts[verdict] = counts.get(verdict, 0) + 1

    quota = quota_status(db)
    message = ""
    if skipped:
        labels = "、".join(empty_types)
        message = (
            f"跳过 {len(skipped)} 家：店型「{labels}」目前没有可卖的货，"
            "先去 K/P 上架对应类目的产品，它们会自动落进这个店型。"
        )
    return {
        "screened": sum(counts.values()),
        "fit": counts["fit"],
        "unfit": counts["unfit"],
        "unsure": counts["unsure"],
        "quota_stopped": quota_stopped,
        "quota_used_today": quota.get("quota_used_today", 0),
        "message": message,
    }


def _persist_website(db: Session, prospect_id: UUID, website: str) -> None:
    row = db.get(B2BProspect, prospect_id)
    if row is None:
        return
    row.website = website
    row.website_source = "serper_search"
    db.commit()


def _persist_screen(
    db: Session,
    prospect_id: UUID,
    verdict: str,
    reason: str,
    signals: dict,
    personal_line: str = "",
) -> None:
    """网络阶段结束后才回到数据库,开一个短事务写完就提交。"""
    row = db.get(B2BProspect, prospect_id)
    if row is None:
        return
    _write_screen(row, verdict, reason, signals)
    if personal_line:
        row.personal_line = personal_line
    db.commit()


def _write_screen(
    prospect: B2BProspect,
    verdict: str,
    reason: str,
    signals: dict,
) -> None:
    prospect.screen_verdict = verdict
    prospect.screen_reason = reason[:255]
    prospect.screen_signals_json = signals or None
    prospect.screened_at = datetime.now(timezone.utc)
