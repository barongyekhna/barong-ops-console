"""种子数据导入:``python -m backend.app.modules.amz_series.seed_import <seed_root>``

读 ``<seed_root>/csv/`` 下的文件(由 xlsx/原始 csv 预先转成统一 UTF-8 CSV):
- ``ads__<store>.csv``            每日口径 SP 搜索词报表(后台中文列名)
- ``txn__<store>__<YYYY-MM>.csv`` 交易一览(美国英文列名 / 德国德文列名,德国数字 1.234,56)

幂等:文件 sha256 记进 ``amz_seed_imports``,同一份文件绝不导两遍;行级 ``row_key`` 唯一,
重跑只补缺行。欧元行按当天 ``amz_fx_rates`` 折美元,没有当天汇率时用
``AMZ_SEED_FX_EUR_USD``(默认 1.08)并标 ``fx_source=seed_fixed``,A1 的汇率作业到位后可重算。
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...db.session import managed_session
from .catalog import store_spec
from .constants import SEED_KIND_ADS_SEARCH_TERMS, SEED_KIND_TRANSACTIONS
from .models import AmzAdSearchTerm, AmzFxRate, AmzSeedImport, AmzStore, AmzTransaction

ADS_FILE = re.compile(r"^ads__(?P<store>0\d(?:us|de))\.csv$")
TXN_FILE = re.compile(r"^txn__(?P<store>0\d(?:us|de))__(?P<month>\d{4}-\d{2})\.csv$")
DEFAULT_EUR_USD = Decimal("1.08")


class SeedImportError(RuntimeError):
    pass


# ---------------------------------------------------------------- 工具


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row_key(*parts: Any) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _dec(value: Any, *, german: bool = False) -> Decimal:
    text = str(value if value is not None else "").strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return Decimal(0)
    if german:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    text = text.replace("€", "").replace("$", "").replace("%", "").strip()
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(0)


def _int(value: Any, *, german: bool = False) -> int:
    dec = _dec(value, german=german)
    try:
        return int(dec)
    except (ValueError, InvalidOperation):
        return 0


def _dec_or_none(value: Any, *, german: bool = False) -> Decimal | None:
    text = str(value if value is not None else "").strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return None
    return _dec(value, german=german)


def _fx_for(db: Session, *, day: date, currency: str, cache: dict[tuple[date, str], tuple[Decimal, str]]) -> tuple[Decimal, str]:
    if currency == "USD":
        return Decimal(1), "native"
    key = (day, currency)
    if key in cache:
        return cache[key]
    row = db.get(AmzFxRate, (day, currency, "USD"))
    if row is not None:
        cache[key] = (Decimal(row.rate), row.source)
    else:
        fallback = Decimal(os.getenv("AMZ_SEED_FX_EUR_USD", str(DEFAULT_EUR_USD)))
        cache[key] = (fallback, "seed_fixed")
    return cache[key]


def _read_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    # 交易报表前面有说明行;真正的表头以 "date/time" 或 "Datum/Uhrzeit" 开头。
    start = 0
    for index, line in enumerate(lines[:20]):
        if line.startswith('"date/time"') or line.startswith('"Datum/Uhrzeit"') or line.startswith("date/time") or line.startswith("Datum/Uhrzeit"):
            start = index
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    rows = [dict(row) for row in reader]
    return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------- 广告搜索词


ADS_COLUMNS = {
    "date": "日期",
    "portfolio": "广告组合名称",
    "currency": "货币",
    "campaign": "广告活动名称",
    "adgroup": "广告组名称",
    "targeting": "投放",
    "match_type": "匹配类型",
    "search_term": "客户搜索词",
    "impressions": "展示量",
    "clicks": "点击量",
    "cpc": "单次点击成本 (CPC)",
    "spend": "花费",
    "sales": "7天总销售额",
    "orders": "7天总订单数(#)",
    "units": "7天总销售量(#)",
    "same_units": "7天内广告SKU销售量(#)",
    "other_units": "7天内其他SKU销售量(#)",
    "same_sales": "7天内广告SKU销售额",
    "other_sales": "7天内其他SKU销售额",
}


def _ads_rows(store: AmzStore, rows: Iterable[dict[str, str]]) -> Iterable[dict[str, Any]]:
    c = ADS_COLUMNS
    for row in rows:
        day_text = (row.get(c["date"]) or "").strip()[:10]
        if not day_text:
            continue
        day = date.fromisoformat(day_text)
        campaign = (row.get(c["campaign"]) or "").strip()
        adgroup = (row.get(c["adgroup"]) or "").strip()
        targeting = (row.get(c["targeting"]) or "").strip()
        match_type = (row.get(c["match_type"]) or "").strip()
        search_term = (row.get(c["search_term"]) or "").strip()
        yield {
            "store_code": store.store_code,
            "report_date": day,
            "portfolio_name": (row.get(c["portfolio"]) or "").strip() or None,
            "campaign_name": campaign[:255],
            "adgroup_name": adgroup[:255],
            "targeting": targeting[:255],
            "match_type": match_type[:32],
            "search_term": search_term,
            "impressions": _int(row.get(c["impressions"])),
            "clicks": _int(row.get(c["clicks"])),
            "cpc": _dec_or_none(row.get(c["cpc"])),
            "spend": _dec(row.get(c["spend"])),
            "sales_7d": _dec(row.get(c["sales"])),
            "orders_7d": _int(row.get(c["orders"])),
            "units_7d": _int(row.get(c["units"])),
            "same_sku_units_7d": _int(row.get(c["same_units"])),
            "other_sku_units_7d": _int(row.get(c["other_units"])),
            "same_sku_sales_7d": _dec(row.get(c["same_sales"])),
            "other_sku_sales_7d": _dec(row.get(c["other_sales"])),
            "currency": ((row.get(c["currency"]) or store.currency).strip() or store.currency)[:3],
            "source": "seed",
            "row_key": _row_key("ads", store.store_code, day.isoformat(), campaign, adgroup, targeting, match_type, search_term),
        }


# ---------------------------------------------------------------- 交易一览


TXN_EN = {
    "posted": "date/time",
    "settlement": "settlement id",
    "type": "type",
    "order": "order id",
    "sku": "sku",
    "description": "description",
    "quantity": "quantity",
    "marketplace": "marketplace",
    "fulfillment": "fulfillment",
    "product_sales": "product sales",
    "product_sales_tax": "product sales tax",
    "shipping_credits": "shipping credits",
    "promotional_rebates": "promotional rebates",
    "withheld_tax": "marketplace withheld tax",
    "selling_fees": "selling fees",
    "fba_fees": "fba fees",
    "other_fees": "other transaction fees",
    "other": "other",
    "total": "total",
}
TXN_DE = {
    "posted": "Datum/Uhrzeit",
    "settlement": "Abrechnungsnummer",
    "type": "Typ",
    "order": "Bestellnummer",
    "sku": "SKU",
    "description": "Beschreibung",
    "quantity": "Menge",
    "marketplace": "Marketplace",
    "fulfillment": "Versand",
    "product_sales": "Umsätze",
    "product_sales_tax": "Produktumsatzsteuer",
    "shipping_credits": "Gutschrift für Versandkosten",
    "promotional_rebates": "Rabatte aus Werbeaktionen",
    "withheld_tax": "Einbehaltene Steuer auf Marketplace",
    "selling_fees": "Verkaufsgebühren",
    "fba_fees": "Gebühren zu Versand durch Amazon",
    "other_fees": "Andere Transaktionsgebühren",
    "other": "Andere",
    "total": "Gesamt",
}
_EN_TIME = re.compile(r"^(?P<body>[A-Za-z]{3} \d{1,2}, \d{4} \d{1,2}:\d{2}:\d{2} [AP]M) (?P<tz>[A-Z]{2,4})$")
_TZ_OFFSET_HOURS = {"PDT": -7, "PST": -8, "MESZ": 2, "MEZ": 1, "CEST": 2, "CET": 1, "UTC": 0, "GMT": 0}
_DE_MONTHS = {
    "Jan.": 1, "Feb.": 2, "März": 3, "Apr.": 4, "Mai": 5, "Juni": 6, "Juli": 7, "Aug.": 8,
    "Sept.": 9, "Okt.": 10, "Nov.": 11, "Dez.": 12,
}


def _parse_posted(text: str, *, german: bool) -> datetime | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if not german:
        match = _EN_TIME.match(raw)
        if match:
            naive = datetime.strptime(match.group("body"), "%b %d, %Y %I:%M:%S %p")
            offset = _TZ_OFFSET_HOURS.get(match.group("tz"), 0)
            return naive.replace(tzinfo=timezone.utc) - timedelta(hours=offset)
        return None
    # 德文导出实际是 "31.07.2026 23:35:56 UTC";旧版后台还有 "1. Aug. 2026 08:15:22 MESZ",两种都认。
    parts = raw.split()
    if len(parts) >= 2 and re.match(r"^\d{2}\.\d{2}\.\d{4}$", parts[0]):
        try:
            naive = datetime.strptime(f"{parts[0]} {parts[1]}", "%d.%m.%Y %H:%M:%S")
        except ValueError:
            return None
        offset = _TZ_OFFSET_HOURS.get(parts[2] if len(parts) > 2 else "", 0)
        return naive.replace(tzinfo=timezone.utc) - timedelta(hours=offset)
    if len(parts) < 4:
        return None
    try:
        day = int(parts[0].rstrip("."))
        month = _DE_MONTHS.get(parts[1])
        year = int(parts[2])
        hh, mm, ss = (int(x) for x in parts[3].split(":"))
    except (ValueError, KeyError, AttributeError):
        return None
    if month is None:
        return None
    naive = datetime(year, month, day, hh, mm, ss)
    offset = _TZ_OFFSET_HOURS.get(parts[4] if len(parts) > 4 else "", 0)
    return naive.replace(tzinfo=timezone.utc) - timedelta(hours=offset)


def _txn_rows(db: Session, store: AmzStore, rows: Iterable[dict[str, str]], *, headers: list[str]) -> Iterable[dict[str, Any]]:
    german = "Datum/Uhrzeit" in headers
    cols = TXN_DE if german else TXN_EN
    fx_cache: dict[tuple[date, str], tuple[Decimal, str]] = {}
    for row in rows:
        posted = _parse_posted(row.get(cols["posted"]) or "", german=german)
        if posted is None:
            continue
        txn_type = (row.get(cols["type"]) or "").strip()
        order_id = (row.get(cols["order"]) or "").strip() or None
        sku = (row.get(cols["sku"]) or "").strip() or None
        description = (row.get(cols["description"]) or "").strip() or None
        total = _dec(row.get(cols["total"]), german=german)
        currency = store.currency
        rate, fx_source = _fx_for(db, day=posted.date(), currency=currency, cache=fx_cache)
        yield {
            "store_code": store.store_code,
            "posted_at": posted,
            "settlement_id": (row.get(cols["settlement"]) or "").strip()[:32] or None,
            "txn_type": txn_type[:64],
            "order_id": (order_id or "")[:32] or None,
            "sku": (sku or "")[:128] or None,
            "description": description,
            "quantity": _int(row.get(cols["quantity"]), german=german),
            "marketplace": ((row.get(cols["marketplace"]) or "").strip() or None),
            "fulfillment": ((row.get(cols["fulfillment"]) or "").strip() or None),
            "product_sales": _dec(row.get(cols["product_sales"]), german=german),
            "product_sales_tax": _dec(row.get(cols["product_sales_tax"]), german=german),
            "shipping_credits": _dec(row.get(cols["shipping_credits"]), german=german),
            "promotional_rebates": _dec(row.get(cols["promotional_rebates"]), german=german),
            "marketplace_withheld_tax": _dec(row.get(cols["withheld_tax"]), german=german),
            "selling_fees": _dec(row.get(cols["selling_fees"]), german=german),
            "fba_fees": _dec(row.get(cols["fba_fees"]), german=german),
            "other_transaction_fees": _dec(row.get(cols["other_fees"]), german=german),
            "other": _dec(row.get(cols["other"]), german=german),
            "total": total,
            "currency": currency,
            "fx_rate": rate,
            "fx_source": fx_source,
            "total_usd": (total * rate).quantize(Decimal("0.01")),
            "source": "seed",
            "row_key": _row_key(
                "txn", store.store_code, posted.isoformat(), row.get(cols["settlement"]), txn_type, order_id, sku,
                description, row.get(cols["quantity"]), row.get(cols["total"]),
            ),
        }


# ---------------------------------------------------------------- 落库


def _bulk_insert(db: Session, model: type, payloads: list[dict[str, Any]]) -> int:
    if not payloads:
        return 0
    if db.get_bind().dialect.name == "postgresql":
        inserted = 0
        for start in range(0, len(payloads), 500):
            chunk = payloads[start : start + 500]
            # psycopg 对多行 INSERT … ON CONFLICT 的 rowcount 报 -1;用 RETURNING 数真插进去的行。
            result = db.execute(
                pg_insert(model).values(chunk).on_conflict_do_nothing(index_elements=["row_key"]).returning(model.row_key)
            )
            inserted += len(result.fetchall())
        return inserted
    existing = set(db.scalars(select(model.row_key).where(model.row_key.in_([p["row_key"] for p in payloads]))))
    fresh = [p for p in payloads if p["row_key"] not in existing]
    db.bulk_insert_mappings(model, fresh)
    return len(fresh)


def import_file(db: Session, path: Path) -> dict[str, Any]:
    name = path.name
    raw = path.read_bytes()
    checksum = _sha256(raw)
    already = db.scalar(select(AmzSeedImport).where(AmzSeedImport.checksum == checksum))
    if already is not None:
        return {"file": name, "skipped": "already_imported", "rows": already.rows}

    ads_match = ADS_FILE.match(name)
    txn_match = TXN_FILE.match(name)
    if not ads_match and not txn_match:
        return {"file": name, "skipped": "unrecognized_name"}
    store_code = (ads_match or txn_match).group("store")  # type: ignore[union-attr]
    if store_spec(store_code) is None:
        raise SeedImportError(f"{name}: store {store_code} 不在名单里")
    store = db.get(AmzStore, store_code)
    if store is None:
        raise SeedImportError(f"{name}: amz_stores 里没有 {store_code},先跑 bootstrap")

    headers, rows = _read_csv(raw)
    if ads_match:
        kind = SEED_KIND_ADS_SEARCH_TERMS
        payloads = list(_ads_rows(store, rows))
        inserted = _bulk_insert(db, AmzAdSearchTerm, payloads)
        details = {
            "first_date": min((p["report_date"] for p in payloads), default=None),
            "last_date": max((p["report_date"] for p in payloads), default=None),
            "spend": str(sum((p["spend"] for p in payloads), Decimal(0))),
            "sales_7d": str(sum((p["sales_7d"] for p in payloads), Decimal(0))),
            "orders_7d": sum(p["orders_7d"] for p in payloads),
        }
    else:
        kind = SEED_KIND_TRANSACTIONS
        payloads = list(_txn_rows(db, store, rows, headers=headers))
        inserted = _bulk_insert(db, AmzTransaction, payloads)
        details = {
            "month": txn_match.group("month"),  # type: ignore[union-attr]
            "total_native": str(sum((p["total"] for p in payloads), Decimal(0))),
            "total_usd": str(sum((p["total_usd"] for p in payloads), Decimal(0))),
            "fx_sources": sorted({p["fx_source"] for p in payloads}),
        }
    details = {key: (value.isoformat() if isinstance(value, date) else value) for key, value in details.items()}
    db.add(
        AmzSeedImport(
            file_name=name,
            store_code=store_code,
            kind=kind,
            rows=len(payloads),
            checksum=checksum,
            details_json={**details, "inserted": inserted, "parsed": len(payloads), "source_rows": len(rows)},
        )
    )
    db.flush()
    return {"file": name, "store": store_code, "kind": kind, "parsed": len(payloads), "inserted": inserted, **details}


def import_directory(db: Session, seed_root: Path) -> list[dict[str, Any]]:
    csv_dir = seed_root / "csv"
    if not csv_dir.is_dir():
        raise SeedImportError(f"{csv_dir} 不存在;先把 xlsx/原始 csv 转成统一 CSV 放进去")
    results = []
    for path in sorted(csv_dir.iterdir()):
        if path.suffix.lower() != ".csv":
            continue
        results.append(import_file(db, path))
    return results


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m backend.app.modules.amz_series.seed_import <seed_root>", file=sys.stderr)
        return 2
    seed_root = Path(args[0]).expanduser().resolve()
    with managed_session() as db:
        results = import_directory(db, seed_root)
        db.commit()
    for item in results:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
