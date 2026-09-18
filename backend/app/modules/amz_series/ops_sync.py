"""A1 补齐:有 SP-API 凭据的店每天拉四样——FBA 库存、自家 listing、财务交易、请求留评。

- 库存(FBA Inventory summaries,直接接口不用等报表)→ amz_inventory_daily。库存天数 / 断货规则和跨店需求合成的底数。
- listing(商家 listing 报表拿 SKU/价格/状态 + Catalog Items 拿买家看到的标题/五点/描述)→ amz_listing_snapshots;
  内容一变就写一条殷笑笑的工作日志(「谁在后台改了 listing」她必须知道,不允许失忆)。
- 财务(GET_DATE_RANGE_FINANCIAL_TRANSACTION_DATA,就是后台「交易一览」那份)→ amz_transactions,
  解析和种子导入共用;只收种子最后一天之后的行,免得和种子重复。
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
REPORT_FINANCE = "GET_DATE_RANGE_FINANCIAL_TRANSACTION_DATA"
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


def sync_finances(db: Session, client: Any, store: AmzStore, *, today: date | None = None) -> dict[str, Any]:
    from .seed_import import _bulk_insert, _read_csv, _txn_rows  # noqa: PLC0415 — 与种子导入共用解析

    today = today or datetime.now(UTC).date()
    seed_last = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store.store_code, AmzTransaction.source == "seed"))
    start = today - timedelta(days=FINANCE_LOOKBACK_DAYS)
    db.commit()
    _report_id, raw = client.run_report(REPORT_FINANCE, start=start, end=today)
    raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")
    headers, rows = _read_csv(raw_bytes)
    if not rows and b"\t" in raw_bytes[:4000]:
        headers, rows = _read_tsv_with_preamble(raw_bytes)
    payloads = [p for p in _txn_rows(db, store, rows, headers=headers) if seed_last is None or p["posted_at"] > seed_last]
    for p in payloads:
        p["source"] = "sp_api"
    inserted = _bulk_insert(db, AmzTransaction, payloads)
    db.commit()
    return {"rows": len(rows), "new_after_seed": len(payloads), "inserted": inserted}


def _read_tsv_with_preamble(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines[:20]) if line.lower().startswith("date/time") or line.startswith("Datum/Uhrzeit")), 0)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter="\t")
    rows = [dict(r) for r in reader]
    return list(reader.fieldnames or []), rows


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
    "REPORT_FINANCE",
    "REPORT_LISTINGS",
    "content_hash",
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
