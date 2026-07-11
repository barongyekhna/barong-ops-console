"""1688 类目扩品：一次选品 = 一个垂直类目。

分组里每个已验证产品都是一个「类目锚点」。点击「1688 扩品」后：
1. CPS 分销图搜多页（按销量倒序）+ fenxiao 词搜多词多页 → 汇总同类候选池；
2. 规则粗筛（有价、有图、起批量友好）；
3. DeepSeek 多家对比（价格/已售/六维评分/历史成交/服务标签/包邮）精选
   10-20 个优质款并给出角色建议（主推/跑量/试款）——供垂直类目海量上架。

自发货打法：同类目产品共享关键词与受众，一个广告组打全类目，
表现好的再拿出来备货冲刺。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.quota_ledger import (
    PROVIDER_1688_APP_CALLS,
    PROVIDER_1688_CPS_IMAGE_SEARCH,
    PROVIDER_1688_IMAGE_SEARCH,
    RAQuotaExhaustedError,
    try_consume,
)


EXPANSION_VERSION = "ra_category_expansion_v1"


class RAExpansionError(RuntimeError):
    pass


def ensure_expansion_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ra_category_expansions (
              id TEXT PRIMARY KEY,
              org_id TEXT NOT NULL,
              report_id TEXT NOT NULL,
              asin TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              anchor JSONB NOT NULL DEFAULT '{}',
              candidates JSONB NOT NULL DEFAULT '[]',
              selected JSONB NOT NULL DEFAULT '[]',
              counts JSONB NOT NULL DEFAULT '{}',
              error TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_expansions_report
            ON ra_category_expansions (org_id, report_id, created_at DESC)
            """
        )
    )


def create_expansion_job(
    db: Session,
    *,
    org_id: str,
    report_id: str,
) -> dict[str, Any]:
    """幂等创建：已有进行中的任务直接返回现状。"""
    ensure_expansion_schema(db)
    existing = get_latest_expansion(db, org_id=org_id, report_id=report_id)
    if existing and str(existing.get("status")) in {"pending", "running"}:
        return existing
    report = db.execute(
        text(
            """
            SELECT report_id, asin FROM ra_reports
            WHERE report_id = :report_id AND org_id = :org_id
            LIMIT 1
            """
        ),
        {"report_id": report_id, "org_id": org_id},
    ).mappings().first()
    if report is None:
        raise RAExpansionError("R-A 报告不存在。")
    job_id = str(uuid4())
    db.execute(
        text(
            """
            INSERT INTO ra_category_expansions (id, org_id, report_id, asin, status)
            VALUES (:id, :org_id, :report_id, :asin, 'pending')
            """
        ),
        {
            "id": job_id,
            "org_id": org_id,
            "report_id": report_id,
            "asin": report["asin"],
        },
    )
    db.commit()
    return get_latest_expansion(db, org_id=org_id, report_id=report_id) or {}


def get_latest_expansion(
    db: Session,
    *,
    org_id: str,
    report_id: str,
) -> dict[str, Any] | None:
    ensure_expansion_schema(db)
    row = db.execute(
        text(
            """
            SELECT id, report_id, asin, status, anchor, candidates, selected,
                   counts, error, created_at, updated_at
            FROM ra_category_expansions
            WHERE org_id = :org_id AND report_id = :report_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id, "report_id": report_id},
    ).mappings().first()
    return dict(row) if row else None


def claim_next_expansion(db: Session, *, org_id: str) -> dict[str, Any] | None:
    ensure_expansion_schema(db)
    row = db.execute(
        text(
            """
            SELECT id, report_id, asin
            FROM ra_category_expansions
            WHERE org_id = :org_id AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"org_id": org_id},
    ).mappings().first()
    if row is None:
        db.rollback()
        return None
    db.execute(
        text(
            """
            UPDATE ra_category_expansions
            SET status = 'running', updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {"id": row["id"]},
    )
    db.commit()
    return dict(row)


def mark_expansion_failed(db: Session, *, job_id: str, error: str) -> None:
    ensure_expansion_schema(db)
    db.execute(
        text(
            """
            UPDATE ra_category_expansions
            SET status = 'failed', error = :error, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {"id": job_id, "error": str(error)[:500]},
    )
    db.commit()


def run_expansion(
    db: Session,
    *,
    org_id: str,
    job: dict[str, Any],
) -> None:
    from r_system_v2.ra.supplier_discovery import _supplier_api_provider
    from r_system_v2.ra.supplier_keyword_skill import build_supplier_keyword_profile
    from r_system_v2.ra.supplier_api import (
        _extract_offer_items,
        _keyword_search_candidates,
        _product_image_url,
    )

    job_id = str(job["id"])
    asin = str(job.get("asin") or "").strip().upper()
    product_row = db.execute(
        text(
            """
            SELECT asin, title, title_zh, category, category_path, brand,
                   price, features, image_url, source_query
            FROM products_rw
            WHERE UPPER(CAST(asin AS TEXT)) = :asin
            LIMIT 1
            """
        ),
        {"asin": asin},
    ).mappings().first()
    if product_row is None:
        raise RAExpansionError(f"{asin} 不在 R-W 仓库中。")
    product = dict(product_row)
    provider = _supplier_api_provider(db, org_id=org_id)
    if getattr(provider, "provider_name", "") == "mock_1688_api":
        raise RAExpansionError("1688 官方 API 未绑定，无法扩品。")
    keyword_profile = build_supplier_keyword_profile(db, org_id=org_id, product=product)
    keywords = _keyword_search_candidates(product=product, keyword_profile=keyword_profile)

    image_pages = _env_int("RA_EXPANSION_IMAGE_PAGES", 2, 1, 4)
    keyword_pages = _env_int("RA_EXPANSION_KEYWORD_PAGES", 2, 1, 3)
    keyword_terms = keywords[: _env_int("RA_EXPANSION_KEYWORD_TERMS", 2, 1, 3)]
    estimated_calls = image_pages + len(keyword_terms) * keyword_pages
    # App 总闸预扣（词搜+图搜都吃 App 配额）。
    try_consume(db, PROVIDER_1688_APP_CALLS, amount=estimated_calls + 2)

    anchor = {
        "asin": asin,
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "amazon_price_usd": _number(product.get("price")),
        "image_url": _product_image_url(product),
        "keywords": keywords,
        "category": product.get("category"),
    }
    _update_job(db, job_id=job_id, anchor=anchor)

    raw_candidates: dict[str, dict[str, Any]] = {}
    counts = {
        "image_pages": 0,
        "keyword_calls": 0,
        "raw_candidates": 0,
        "after_rule_filter": 0,
        "version": EXPANSION_VERSION,
    }

    # ① CPS 分销图搜多页（按销量倒序）；CPS 通道额度记账，尽了自动切跨境。
    amazon_image = _product_image_url(product)
    if amazon_image:
        for page in range(1, image_pages + 1):
            try:
                try:
                    try_consume(db, PROVIDER_1688_CPS_IMAGE_SEARCH)
                    payload = provider._call_cps_image_search(
                        image_url=amazon_image, limit=20, page=page
                    )
                    items = _cps_items(payload)
                except RAQuotaExhaustedError:
                    try_consume(db, PROVIDER_1688_IMAGE_SEARCH)
                    payload = provider._call_image_search(
                        image_url=amazon_image,
                        keyword_profile=keyword_profile,
                        limit=20,
                    )
                    items = _extract_offer_items(payload)
                counts["image_pages"] += 1
                for item in items:
                    candidate = _candidate_from_item(item, source="image_search")
                    if candidate:
                        raw_candidates.setdefault(candidate["offer_id"], candidate)
            except RAQuotaExhaustedError:
                break
            except Exception:
                pass
            time.sleep(0.6)

    # ② fenxiao 词搜多词多页（免费通道，只吃 App 总闸）。
    for term in keyword_terms:
        for page in range(1, keyword_pages + 1):
            try:
                payload = provider._call_openapi(
                    namespace=os.getenv(
                        "RA_1688_KEYWORD_SEARCH_NAMESPACE", "com.alibaba.fenxiao"
                    ).strip(),
                    api_name=os.getenv(
                        "RA_1688_KEYWORD_SEARCH_API_NAME", "product.keywords.search"
                    ).strip(),
                    params={
                        "param": {
                            "keywords": term,
                            "pageNum": page,
                            "pageSize": 20,
                        }
                    },
                    error_label="1688 扩品词搜",
                    allow_business_error=True,
                )
                counts["keyword_calls"] += 1
                for item in _extract_offer_items(payload):
                    candidate = _candidate_from_item(item, source="keyword_search")
                    if candidate:
                        raw_candidates.setdefault(candidate["offer_id"], candidate)
            except Exception:
                pass
            time.sleep(0.6)

    counts["raw_candidates"] = len(raw_candidates)
    candidates = [
        candidate
        for candidate in raw_candidates.values()
        if candidate.get("price_cny") and (candidate.get("moq") or 1) <= 10
    ]
    candidates.sort(key=lambda item: item.get("sale_amount") or 0, reverse=True)
    candidates = candidates[:80]
    counts["after_rule_filter"] = len(candidates)

    # ③ DeepSeek 多家对比精选（结构化中文对比任务：便宜、快、中文品类理解好）。
    selected = _deepseek_select(
        db,
        org_id=org_id,
        anchor=anchor,
        candidates=candidates,
    )
    counts["selected"] = len(selected)

    _update_job(
        db,
        job_id=job_id,
        status="completed",
        candidates=candidates,
        selected=selected,
        counts=counts,
    )


def _cps_items(payload: dict[str, Any]) -> list[Any]:
    result_block = payload.get("result")
    if isinstance(result_block, dict):
        inner = result_block.get("result")
        if isinstance(inner, list):
            return inner
    from r_system_v2.ra.supplier_api import _extract_offer_items

    return _extract_offer_items(payload)


def _candidate_from_item(item: Any, *, source: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    offer_id = str(item.get("offerId") or item.get("offer_id") or "").strip()
    detail_url = str(item.get("detailUrl") or item.get("detail_url") or "").strip()
    if not offer_id and detail_url:
        offer_id = detail_url
    if not offer_id:
        return None
    if not detail_url:
        detail_url = f"https://detail.1688.com/offer/{offer_id}.html"
    price = _price_cny(item)
    quality = item.get("qualityEvaluation")
    quality = quality if isinstance(quality, dict) else {}
    trade_info = {}
    for entry in item.get("offerHistoryTradeInfo") or []:
        if isinstance(entry, dict) and entry.get("historyTradeKey"):
            trade_info[str(entry["historyTradeKey"])] = entry.get("historyTradeValue")
    image_url = item.get("imageUrl") or (
        item.get("offerImage", {}).get("imageUrl")
        if isinstance(item.get("offerImage"), dict)
        else None
    )
    return {
        "offer_id": offer_id,
        "title": str(item.get("subject") or item.get("title") or "")[:120],
        "detail_url": detail_url,
        "image_url": image_url,
        "price_cny": price,
        "moq": item.get("quantityBegin"),
        "sale_amount": item.get("saleAmount"),
        "want_buy": item.get("wantBuy"),
        "delivery_free": item.get("deliveryFree") is True,
        "best_shop": item.get("best") is True,
        "shili_supplier": item.get("shili") is True,
        "supply_amount": item.get("supplyAmount"),
        "services": item.get("services"),
        "composite_score": quality.get("compositeScore"),
        "goods_score": quality.get("goodsScore"),
        "logistics_score": quality.get("logisticsScore"),
        "return_score": quality.get("returnScore"),
        "gmv_30d": trade_info.get("GmvValue30DaysFuzzify"),
        "sales_90d": trade_info.get("Sales90Fuzzify"),
        "city": item.get("city")
        or (
            item.get("companyInfo", {}).get("city")
            if isinstance(item.get("companyInfo"), dict)
            else None
        ),
        "source": source,
    }


def _price_cny(item: dict[str, Any]) -> float | None:
    """CPS 价格为分(Long)；fenxiao 词搜价格为元(字符串小数)。按格式自适应。"""
    for key in ("price", "consignPrice", "oldPrice"):
        value = item.get(key)
        if value is None and isinstance(item.get("offerPrice"), dict):
            value = item["offerPrice"].get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if not raw:
            continue
        try:
            parsed = float(raw)
        except ValueError:
            continue
        if parsed <= 0:
            continue
        return round(parsed if "." in raw else parsed / 100, 2)
    return None


def _deepseek_select(
    db: Session,
    *,
    org_id: str,
    anchor: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    from r_system_v2.ra.ai_selection import (
        _execute_chat_request,
        _load_provider_configs,
        _try_parse_model_json,
    )

    provider = _load_provider_configs(db, org_id=org_id)["deepseek"]
    compact = [
        {
            "id": index,
            "title": item.get("title"),
            "price": item.get("price_cny"),
            "moq": item.get("moq"),
            "sold": item.get("sale_amount"),
            "score": item.get("composite_score"),
            "gmv30d": item.get("gmv_30d"),
            "free_ship": item.get("delivery_free"),
            "best": item.get("best_shop"),
            "shili": item.get("shili_supplier"),
            "services": item.get("services"),
        }
        for index, item in enumerate(candidates[:60])
    ]
    prompt = (
        "你是跨境电商垂直类目选品专家。锚点产品已通过利润与竞争验证：\n"
        f"{json.dumps({k: anchor.get(k) for k in ('title', 'title_zh', 'amazon_price_usd', 'category')}, ensure_ascii=False)}\n\n"
        "下面是 1688 同类目候选池（价格为人民币，sold=已售，score=综合评分，"
        "gmv30d=30天成交额，shili=实力商家）。目标：为「同一垂直类目海量自发货上架」"
        "精选 10-20 个优质款——同类目、受众一致、可共用关键词和广告组。\n"
        "选择标准：① 有真实销量/成交记录优先；② 综合评分高、退货分不差；③ 价格带"
        "与锚点利润结构兼容（换算约 7.2 汇率后，1688成本 ≤ 亚马逊售价的 35%）；"
        "④ 起批量小、包邮优先；⑤ 款式互补覆盖类目（不要 20 个长得一样的）。\n"
        f"候选池：{json.dumps(compact, ensure_ascii=False)}\n\n"
        '只输出 JSON：{"selected":[{"id":0,"score":0-100,"role":"主推|跑量|试款",'
        '"reason":"一句话理由"}]}，10-20 个，按优先级排序。'
    )
    db.rollback()  # AI 调用前结束事务。
    try:
        response = _execute_chat_request(
            provider,
            spec={
                "endpoint": "/v1/chat/completions",
                "label": "expansion_select",
                "payload": {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            },
        )
        output = _try_parse_model_json(response.get("content")) or {}
    except Exception:
        # AI 失败降级：按已售×评分规则排序取前 15。
        ranked = sorted(
            candidates,
            key=lambda item: (
                (item.get("sale_amount") or 0),
                (item.get("composite_score") or 0),
            ),
            reverse=True,
        )[:15]
        return [
            {**item, "ai_score": None, "role": "跑量", "reason": "AI 不可用，按销量评分规则入选。"}
            for item in ranked
        ]
    selected: list[dict[str, Any]] = []
    for entry in output.get("selected") or []:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(candidates):
            continue
        selected.append(
            {
                **candidates[index],
                "ai_score": entry.get("score"),
                "role": str(entry.get("role") or "跑量")[:10],
                "reason": str(entry.get("reason") or "")[:200],
            }
        )
    return selected[:20]


def _update_job(
    db: Session,
    *,
    job_id: str,
    status: str | None = None,
    anchor: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    selected: list[dict[str, Any]] | None = None,
    counts: dict[str, Any] | None = None,
) -> None:
    sets = ["updated_at = CURRENT_TIMESTAMP"]
    params: dict[str, Any] = {"id": job_id}
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if anchor is not None:
        sets.append(f"anchor = {_json_bind(db, 'anchor')}")
        params["anchor"] = json.dumps(anchor, ensure_ascii=False, default=str)
    if candidates is not None:
        sets.append(f"candidates = {_json_bind(db, 'candidates')}")
        params["candidates"] = json.dumps(candidates, ensure_ascii=False, default=str)
    if selected is not None:
        sets.append(f"selected = {_json_bind(db, 'selected')}")
        params["selected"] = json.dumps(selected, ensure_ascii=False, default=str)
    if counts is not None:
        sets.append(f"counts = {_json_bind(db, 'counts')}")
        params["counts"] = json.dumps(counts, ensure_ascii=False, default=str)
    db.execute(
        text(f"UPDATE ra_category_expansions SET {', '.join(sets)} WHERE id = :id"),
        params,
    )
    db.commit()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None
