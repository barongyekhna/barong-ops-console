"""A1 补齐:有 SP-API 凭据的店每天拉四样——FBA 库存、自家 listing、财务交易、请求留评。

- 库存(FBA Inventory summaries,直接接口不用等报表)→ amz_inventory_daily。库存天数 / 断货规则和跨店需求合成的底数。
- listing(商家 listing 报表拿 SKU/价格/状态 + Catalog Items 拿买家看到的标题/五点/描述)→ amz_listing_snapshots;
  内容一变就写一条殷笑笑的工作日志(「谁在后台改了 listing」她必须知道,不允许失忆)。
- 财务(Finances API 财务事件;「交易一览」日期范围报表亚马逊不让 API 要)→ amz_transactions,
  拆成和种子同形状的行;只收种子最后一刻之后的,免得和种子重复。
- 请求留评(Solicitations「Request a Review」,亚马逊官方按钮)→ amz_solicitations。
  **影子期只查资格、记 would_request,不发**;店铺总闸 metadata.solicitations_enabled 由 owner 打开后才真发。
  绝不刷单、绝不激励评论——这是亚马逊自己的模板邮件,买家收到的内容我们改不了。

出网前一律 commit(worker 8 秒 idle-in-transaction 上限)。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import work_log
from .constants import EMPLOYEE_A
from .models import AmzInventoryDaily, AmzListingSnapshot, AmzProduct, AmzReportRun, AmzSolicitation, AmzStore, AmzTransaction

_LOGGER = logging.getLogger("amz.ops_sync")

REPORT_LISTINGS = "GET_MERCHANT_LISTINGS_ALL_DATA"
FINANCE_LOOKBACK_DAYS = 14
SOLICIT_MIN_DAYS = 5
SOLICIT_MAX_DAYS = 30
SOLICIT_PER_RUN = 60
ORDER_TYPES = ("Order", "Bestellung")


# ---------------------------------------------------------------- 库存


def parse_inventory(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for s in summaries:
        sku = str(s.get("sellerSku") or "").strip()
        if not sku:
            continue
        d = s.get("inventoryDetails") or {}
        inbound = sum(int(d.get(k) or 0) for k in ("inboundWorkingQuantity", "inboundShippedQuantity", "inboundReceivingQuantity"))
        rows.append(
            {
                "sku": sku[:128],
                "asin": (str(s.get("asin") or "")[:16]) or None,
                "fnsku": (str(s.get("fnSku") or "")[:16]) or None,
                "fulfillable": int(d.get("fulfillableQuantity") or 0),
                "inbound": inbound,
                "reserved": int((d.get("reservedQuantity") or {}).get("totalReservedQuantity") or 0),
                "unfulfillable": int((d.get("unfulfillableQuantity") or {}).get("totalUnfulfillableQuantity") or 0),
                "raw_json": {"total": s.get("totalQuantity"), "condition": s.get("condition")},
            }
        )
    return rows


def sync_inventory(db: Session, client: Any, store: AmzStore, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    db.commit()
    summaries: list[dict[str, Any]] = []
    token: str | None = None
    for _page in range(50):
        params = {"details": "true", "granularityType": "Marketplace", "granularityId": store.marketplace_id, "marketplaceIds": store.marketplace_id}
        if token:
            params["nextToken"] = token
        body = client.request("GET", "/fba/inventory/v1/summaries", params=params)
        payload = body.get("payload") or {}
        summaries.extend(payload.get("inventorySummaries") or [])
        token = (body.get("pagination") or {}).get("nextToken")
        if not token:
            break
    rows = parse_inventory(summaries)
    if rows:
        stmt = pg_insert(AmzInventoryDaily).values([{**r, "store_code": store.store_code, "snap_date": today} for r in rows])
        db.execute(stmt.on_conflict_do_update(constraint="uq_amz_inventory_daily_store_day_sku", set_={c: getattr(stmt.excluded, c) for c in ("asin", "fnsku", "fulfillable", "inbound", "reserved", "unfulfillable", "raw")}))
    db.commit()
    return {"skus": len(rows), "fulfillable": sum(r["fulfillable"] for r in rows), "inbound": sum(r["inbound"] for r in rows)}


# ---------------------------------------------------------------- listing


def _tsv(raw: Any) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    return [dict(r) for r in csv.DictReader(io.StringIO(text), delimiter="\t")]


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01")) if str(value or "").strip() else None
    except (InvalidOperation, ValueError):
        return None


def parse_catalog(item: dict[str, Any]) -> dict[str, Any]:
    """Catalog Items 2022-04-01(includedData=attributes)→ 买家看到的标题 / 五点 / 描述。"""
    attrs = item.get("attributes") or {}

    def values(key: str) -> list[str]:
        return [str(v.get("value") or "").strip() for v in attrs.get(key) or [] if isinstance(v, dict) and str(v.get("value") or "").strip()]

    titles = values("item_name")
    descs = values("product_description")
    return {"title": titles[0] if titles else None, "bullets": values("bullet_point"), "description": descs[0] if descs else None}


def content_hash(title: str | None, bullets: list[str], description: str | None, price: Decimal | None) -> str:
    return hashlib.sha256(json.dumps([title or "", bullets, description or "", str(price or "")], ensure_ascii=False).encode("utf-8")).hexdigest()


def listing_changes(prev: AmzListingSnapshot | Any, now: dict[str, Any]) -> list[str]:
    out = []
    if (prev.title or "") != (now.get("title") or ""):
        out.append("标题")
    before, after = list(prev.bullets_json or []), list(now.get("bullets") or [])
    changed = [i + 1 for i in range(max(len(before), len(after))) if (before[i] if i < len(before) else "") != (after[i] if i < len(after) else "")]
    if changed:
        out.append("五点第 " + "、".join(str(i) for i in changed) + " 条")
    if (prev.description or "") != (now.get("description") or ""):
        out.append("描述")
    if (prev.price or None) != (now.get("price") or None):
        out.append(f"价格 {prev.price} → {now.get('price')}")
    if (prev.status or "") != (now.get("status") or ""):
        out.append(f"状态 {prev.status} → {now.get('status')}")
    return out


def sync_listings(db: Session, client: Any, store: AmzStore, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    db.commit()
    _report_id, raw = client.run_report(REPORT_LISTINGS, start=today - timedelta(days=1), end=today)
    listings = _tsv(raw)
    written = changed = 0
    for row in listings:
        sku = (row.get("seller-sku") or "").strip()
        asin = (row.get("asin1") or "").strip().upper() or None
        if not sku:
            continue
        content = {"title": (row.get("item-name") or "").strip() or None, "bullets": [], "description": None}
        if asin:
            try:
                item = client.request("GET", f"/catalog/2022-04-01/items/{asin}", params={"marketplaceIds": store.marketplace_id, "includedData": "attributes"})
                parsed = parse_catalog(item)
                content = {k: parsed[k] or content[k] for k in content}
            except Exception as exc:  # noqa: BLE001 — 单个 ASIN 取不到详情,至少把报表里的标题价格记下
                _LOGGER.warning("catalog item %s failed: %s", asin, exc)
        price = _money(row.get("price"))
        status = (row.get("status") or "").strip() or None
        snap = {"asin": asin, "status": status, "title": content["title"], "bullets": content["bullets"], "description": content["description"], "price": price}
        digest = content_hash(snap["title"], snap["bullets"], snap["description"], price)
        prev = db.scalar(select(AmzListingSnapshot).where(AmzListingSnapshot.store_code == store.store_code, AmzListingSnapshot.sku == sku, AmzListingSnapshot.snap_date < today).order_by(AmzListingSnapshot.snap_date.desc()).limit(1))
        stmt = pg_insert(AmzListingSnapshot).values(store_code=store.store_code, sku=sku[:128], snap_date=today, asin=asin, status=status, title=snap["title"], bullets_json=snap["bullets"], description=snap["description"], price=price, content_hash=digest)
        db.execute(stmt.on_conflict_do_update(constraint="uq_amz_listing_snap_day", set_={c: getattr(stmt.excluded, c) for c in ("asin", "status", "title", "bullets", "description", "price", "content_hash")}))
        written += 1
        if prev is not None and prev.content_hash != digest:
            what = listing_changes(prev, snap)
            if what:
                work_log.record(
                    db,
                    employee=EMPLOYEE_A,
                    kind="observation",
                    title=f"{store.store_code} {sku} 的 listing 改了:{'、'.join(what)}",
                    why=f"每日快照对比 {prev.snap_date.isoformat()} → {today.isoformat()} 发现的;如果不是通过控制台放行的建议改的,就是有人直接在后台改了。",
                    store_code=store.store_code,
                    subject=f"listing|{sku}",
                    asin=asin,
                    sku=sku,
                    detail={"changed": what, "before": {"title": prev.title, "bullets": prev.bullets_json, "price": float(prev.price) if prev.price is not None else None}, "after": {"title": snap["title"], "bullets": snap["bullets"], "price": float(price) if price is not None else None}},
                    source="api",
                )
                changed += 1
        db.commit()
    return {"listings": written, "changed": changed}


# ---------------------------------------------------------------- 财务交易


FEE_FBA_PREFIX = "FBA"
PAGE_LIMIT = 40


def _amount(node: Any) -> Decimal:
    try:
        return Decimal(str((node or {}).get("CurrencyAmount") or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _posted(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def event_rows(events: dict[str, Any], *, store: AmzStore) -> list[dict[str, Any]]:
    """Finances API 的 FinancialEvents → 与「交易一览」同形状的行(订单 / 退款按 SKU 一行,其余费用一行)。"""
    rows: list[dict[str, Any]] = []

    def item_row(kind: str, event: dict[str, Any], item: dict[str, Any], charges_key: str, fees_key: str, promos_key: str) -> dict[str, Any] | None:
        posted = _posted(event.get("PostedDate"))
        if posted is None:
            return None
        charges = {c.get("ChargeType"): _amount(c.get("ChargeAmount")) for c in item.get(charges_key) or []}
        fees = [(f.get("FeeType") or "", _amount(f.get("FeeAmount"))) for f in item.get(fees_key) or []]
        promos = sum((_amount(p.get("PromotionAmount")) for p in item.get(promos_key) or []), Decimal(0))
        fba = sum((v for k, v in fees if k.startswith(FEE_FBA_PREFIX)), Decimal(0))
        selling = sum((v for k, v in fees if not k.startswith(FEE_FBA_PREFIX)), Decimal(0))
        principal = charges.get("Principal", Decimal(0))
        tax = sum((v for k, v in charges.items() if k and "Tax" in k), Decimal(0))
        shipping = charges.get("ShippingCharge", Decimal(0))
        total = sum(charges.values(), Decimal(0)) + promos + fba + selling
        qty = int(item.get("QuantityShipped") or 0)
        return {"posted_at": posted, "txn_type": kind, "order_id": event.get("AmazonOrderId"), "sku": item.get("SellerSKU"), "quantity": qty if kind == "Order" else -qty, "product_sales": principal, "product_sales_tax": tax, "shipping_credits": shipping, "promotional_rebates": promos, "selling_fees": selling, "fba_fees": fba, "total": total, "description": kind}

    for event in events.get("ShipmentEventList") or []:
        for item in event.get("ShipmentItemList") or []:
            row = item_row("Order", event, item, "ItemChargeList", "ItemFeeList", "PromotionList")
            if row:
                rows.append(row)
    for event in events.get("RefundEventList") or []:
        for item in event.get("ShipmentItemAdjustmentList") or []:
            row = item_row("Refund", event, item, "ItemChargeAdjustmentList", "ItemFeeAdjustmentList", "PromotionAdjustmentList")
            if row:
                rows.append(row)
    for event in events.get("ServiceFeeEventList") or []:
        fees = sum((_amount(f.get("FeeAmount")) for f in event.get("FeeList") or []), Decimal(0))
        if fees:
            rows.append({"posted_at": None, "txn_type": "Service Fee", "order_id": event.get("AmazonOrderId"), "sku": event.get("SellerSKU"), "quantity": 0, "other_transaction_fees": fees, "total": fees, "description": event.get("FeeReason") or "Service Fee"})
    for event in events.get("AdjustmentEventList") or []:
        amount = _amount(event.get("AdjustmentAmount"))
        posted = _posted(event.get("PostedDate"))
        if amount and posted:
            rows.append({"posted_at": posted, "txn_type": "Adjustment", "order_id": None, "sku": None, "quantity": 0, "other": amount, "total": amount, "description": event.get("AdjustmentType") or "Adjustment"})
    out = []
    for r in rows:
        if r["posted_at"] is None:
            continue  # 服务费事件没有日期,等它进结算再说
        r.setdefault("other", Decimal(0))
        r.setdefault("other_transaction_fees", Decimal(0))
        for key in ("product_sales", "product_sales_tax", "shipping_credits", "promotional_rebates", "selling_fees", "fba_fees"):
            r.setdefault(key, Decimal(0))
        r["store_code"] = store.store_code
        r["currency"] = store.currency
        r["order_id"] = (r["order_id"] or "")[:32] or None
        r["sku"] = (r["sku"] or "")[:128] or None
        r["row_key"] = hashlib.sha256("|".join(str(x) for x in ("fin", store.store_code, r["posted_at"].isoformat(), r["txn_type"], r["order_id"], r["sku"], r["quantity"], r["total"])).encode("utf-8")).hexdigest()
        out.append(r)
    return out


def sync_finances(db: Session, client: Any, store: AmzStore, *, today: date | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Finances API(listFinancialEvents)→ amz_transactions。只收种子最后一刻之后的事件,免得和种子重复。

    「交易一览」那份日期范围报表亚马逊不让用 API 要(report type 1202 not allowed),所以走财务事件接口,
    拆成和种子同形状的行:订单 / 退款按 SKU 一行(销售额、佣金、FBA 费、促销分列),服务费 / 调整各一行。
    """
    from .fx import usd_factor  # noqa: PLC0415
    from .seed_import import _bulk_insert  # noqa: PLC0415

    now = now or datetime.now(UTC)
    seed_last = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store.store_code, AmzTransaction.source == "seed"))
    api_last = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store.store_code, AmzTransaction.source == "sp_api"))
    # 接着已有数据往后拉,不留缝:有 API 行就从它往前 3 天(晚到的事件)重叠拉,靠 row_key 去重;
    # 还没有就从种子最后一刻开始;都没有才看最近 14 天。亚马逊最多回溯 180 天。
    api_first = db.scalar(select(func.min(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store.store_code, AmzTransaction.source == "sp_api"))
    if api_first is not None and seed_last is not None and api_first - seed_last > timedelta(days=1):
        after = seed_last  # 种子和 API 之间有缝(第一次拉得太晚),补上
    elif api_last is not None:
        after = api_last - timedelta(days=3)
    elif seed_last is not None:
        after = seed_last
    else:
        after = now - timedelta(days=FINANCE_LOOKBACK_DAYS)
    after = max(after, now - timedelta(days=179))
    factor = usd_factor(db, store.currency)
    db.commit()
    events_all: dict[str, list[Any]] = {}
    params: dict[str, Any] = {"PostedAfter": after.strftime("%Y-%m-%dT%H:%M:%SZ"), "PostedBefore": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "MaxResultsPerPage": 100}
    pages = 0
    while pages < PAGE_LIMIT:
        body = client.request("GET", "/finances/v0/financialEvents", params=params)
        payload = body.get("payload") or {}
        for key, value in (payload.get("FinancialEvents") or {}).items():
            if isinstance(value, list):
                events_all.setdefault(key, []).extend(value)
        pages += 1
        token = payload.get("NextToken")
        if not token:
            break
        params = {"NextToken": token}
    rows = [r for r in event_rows(events_all, store=store) if seed_last is None or r["posted_at"] > seed_last]
    for r in rows:
        rate = factor(r["posted_at"].date())
        r["fx_rate"] = rate
        r["fx_source"] = "native" if store.currency == "USD" else "ecb"
        r["total_usd"] = (Decimal(r["total"]) * rate).quantize(Decimal("0.01"))
        r["source"] = "sp_api"
    inserted = _bulk_insert(db, AmzTransaction, rows)
    db.commit()
    return {"pages": pages, "event_types": {k: len(v) for k, v in events_all.items() if v}, "rows": len(rows), "inserted": inserted}


# ---------------------------------------------------------------- 请求留评


def solicitations_enabled(store: AmzStore) -> bool:
    return bool((store.metadata_json or {}).get("solicitations_enabled"))


def eligible_orders(db: Session, store_code: str, *, today: date) -> list[tuple[str, str | None, date]]:
    """发货后 5–30 天、还没处理过的订单(亚马逊只允许这个窗口请求)。"""
    T = AmzTransaction
    rows = db.execute(
        select(T.order_id, func.max(T.sku), func.min(func.date(T.posted_at)))
        .where(T.store_code == store_code, T.txn_type.in_(ORDER_TYPES), T.order_id.is_not(None), func.date(T.posted_at) <= today - timedelta(days=SOLICIT_MIN_DAYS), func.date(T.posted_at) >= today - timedelta(days=SOLICIT_MAX_DAYS))
        .group_by(T.order_id)
        .order_by(func.min(T.posted_at))
    ).all()
    done = set(db.scalars(select(AmzSolicitation.order_id).where(AmzSolicitation.store_code == store_code, AmzSolicitation.status.in_(("sent", "would_request", "not_eligible_final")))))
    return [(o, s, d) for o, s, d in rows if o not in done]


def run_solicitations(db: Session, client: Any, store: AmzStore, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    send = solicitations_enabled(store)
    todo = eligible_orders(db, store.store_code, today=today)[:SOLICIT_PER_RUN]
    db.commit()
    counts = {"checked": 0, "would_request": 0, "sent": 0, "not_eligible": 0, "send_enabled": send}
    now = datetime.now(UTC)
    for order_id, sku, ordered_on in todo:
        body = client.request("GET", f"/solicitations/v1/orders/{order_id}", params={"marketplaceIds": store.marketplace_id})
        actions = [str(a.get("name") or "") for a in ((body.get("_links") or {}).get("actions") or [])]
        available = "productReviewAndSellerFeedback" in actions
        counts["checked"] += 1
        if not available:
            # 窗口快过了还不行就不再查
            status = "not_eligible_final" if ordered_on and (today - ordered_on).days >= SOLICIT_MAX_DAYS - 2 else "not_eligible"
            counts["not_eligible"] += 1
            detail = "亚马逊说这单现在不能请求(可能已请求过 / 退款了 / 还没送达)"
        elif send:
            client.request("POST", f"/solicitations/v1/orders/{order_id}/solicitations/productReviewAndSellerFeedback", params={"marketplaceIds": store.marketplace_id})
            status, detail = "sent", "已通过亚马逊官方 Request a Review 发出"
            counts["sent"] += 1
        else:
            status, detail = "would_request", "影子期:可以请求,但店铺总闸没开,没发"
            counts["would_request"] += 1
        stmt = pg_insert(AmzSolicitation).values(store_code=store.store_code, order_id=order_id, sku=sku, ordered_on=ordered_on, status=status, detail=detail, checked_at=now, sent_at=now if status == "sent" else None)
        db.execute(stmt.on_conflict_do_update(constraint="uq_amz_solicitations_store_order", set_={"status": stmt.excluded.status, "detail": stmt.excluded.detail, "checked_at": stmt.excluded.checked_at, "sent_at": stmt.excluded.sent_at}))
        db.commit()
    return counts


def solicitation_summary(db: Session, store_code: str) -> dict[str, Any]:
    rows = dict(db.execute(select(AmzSolicitation.status, func.count()).where(AmzSolicitation.store_code == store_code).group_by(AmzSolicitation.status)).all())
    return {k: int(v) for k, v in rows.items()}


__all__ = [
    "REPORT_LISTINGS",
    "content_hash",
    "event_rows",
    "eligible_orders",
    "listing_changes",
    "parse_catalog",
    "parse_inventory",
    "run_solicitations",
    "solicitation_summary",
    "solicitations_enabled",
    "sync_finances",
    "sync_inventory",
    "sync_listings",
]
