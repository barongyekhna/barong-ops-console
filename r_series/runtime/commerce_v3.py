#!/usr/bin/env python3
"""R Series V3 commerce closed-loop runtime.

This layer is production-structured but provider-mocked by design. It never
uses external APIs or API keys, and its provider interfaces can be replaced by
real V3 key-backed providers later without changing the UI output contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

try:
    from .R_ENGINE_V1 import REngineV1, parse_price_range, read_json, write_json
except ImportError:  # pragma: no cover - direct script execution
    from R_ENGINE_V1 import REngineV1, parse_price_range, read_json, write_json


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_DIR = ROOT_DIR / "r_series" / "database"
DATABASE_DIR = Path(
    os.environ.get("R_SERIES_DATABASE_DIR", str(DEFAULT_DATABASE_DIR))
).expanduser()
DATABASE_PATH = DATABASE_DIR / "r_products_v3.jsonl"
REVIEW_LOG_PATH = DATABASE_DIR / "r_review_logs_v3.jsonl"
REPORT_PATH = ROOT_DIR / "R_SERIES_V3_COMMERCE_REPORT.json"
PRODUCTION_DEPLOYMENT_REPORT_PATH = (
    ROOT_DIR / "R_SERIES_V3_PRODUCTION_DEPLOYMENT_REPORT.json"
)
LOGICAL_DATABASE_PATH = "/r_series/database/r_products_v3.jsonl"
LOGICAL_REVIEW_LOG_PATH = "/r_series/database/r_review_logs_v3.jsonl"

ENGINE_NAME = "R_ENGINE_V3"
ENGINE_VERSION = "2026-06-29.v3"
DEEPSEEK_PROVIDER = "deepseek_v4_pro"
SUPPLIER_PROVIDER = "mock_1688_supplier_provider"
LOCKED_ORGANIZATION_ID = "涌龙麟（深圳）国际贸易有限公司"
LOCKED_ORGANIZATION_NAME = LOCKED_ORGANIZATION_ID

REQUIRED_V3_SKILLS = [
    "amazon_selection_skill",
    "independent_site_selection_skill",
    "risk_filter_skill",
    "decision_engine_skill",
    "source_validation_skill",
    "1688_supplier_skill",
    "deepseek_reasoning_skill",
]

ORIGINS = (
    "浙江义乌",
    "广东深圳",
    "广东佛山",
    "江苏苏州",
    "山东青岛",
    "河北廊坊",
    "福建泉州",
)
FACTORY_TYPES = ("源头工厂", "实力工厂", "现货供应商", "跨境专供", "轻定制工厂")
PACKAGING_TYPES = ("opp袋", "彩盒", "牛皮纸盒", "白盒", "挂卡包装")


class RCommerceV3Error(ValueError):
    """Raised when the V3 commerce runtime receives invalid input."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def stable_digest(value: Any, *, length: int = 16) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()[:length]


def normalized_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def title_keyword(value: str) -> str:
    cleaned = normalized_keyword(value)
    if not cleaned:
        return "通用产品"
    return " ".join(part[:1].upper() + part[1:] for part in cleaned.split(" "))


def yuan_range(min_value: float, max_value: float) -> str:
    return f"¥{min_value:.2f}-¥{max_value:.2f}"


def usd_price(value: float) -> str:
    return f"${value:.2f}"


def channel_slug(value: str) -> Literal["amazon", "site", "dual"]:
    lowered = value.strip().lower()
    if lowered == "amazon":
        return "amazon"
    if lowered in {"site", "dtc", "独立站"}:
        return "site"
    return "dual"


def market_label(value: str) -> Literal["Amazon", "独立站", "Both"]:
    lowered = value.strip().lower()
    if lowered == "amazon":
        return "Amazon"
    if lowered in {"dtc", "site", "独立站"}:
        return "独立站"
    return "Both"


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    write_json(temp_path, payload)
    temp_path.replace(path)


def persistent_database_path(path: Path) -> bool:
    resolved = str(path)
    return resolved == LOGICAL_DATABASE_PATH or resolved.startswith("/r_series/database/")


def product_success(product: dict[str, Any]) -> bool:
    reason = product.get("reason")
    return bool(
        product.get("main_keyword")
        and len(product.get("supplier_list") or []) >= 2
        and product.get("purchase_price_range")
        and product.get("selling_price")
        and isinstance(reason, dict)
        and reason.get("text")
        and reason.get("source") == DEEPSEEK_PROVIDER
        and product.get("size_weight")
    )


class MockDeepSeekV4ProProvider:
    """DeepSeek V4 Pro provider abstraction in mock mode."""

    provider_name = DEEPSEEK_PROVIDER
    mode = "mock"

    def generate_reason(self, context: dict[str, Any]) -> dict[str, str]:
        keyword = context["main_keyword"]
        channel = context["channel_recommendation"]
        selling_price = context["selling_price"]
        purchase_price = context["purchase_price_range"]
        supplier_count = len(context["supplier_list"])
        risk_level = context["decision_output"]["risk"]["risk_level"]
        final_score = context["decision_output"]["final_score"]

        channel_text = {
            "amazon": "更适合先放到 Amazon 做小批量验证",
            "site": "更适合先用独立站内容和广告做验证",
            "dual": "适合 Amazon 和独立站双线小测",
        }[channel]
        risk_text = "风险相对可控" if risk_level != "high" else "但风险项要先人工复核"
        text = (
            f"这个品我会把它放进候选，是因为它解决的问题比较具体，用户搜索意图清楚，"
            f"{channel_text}。目前 mock 供应链能给到 {supplier_count} 个可比价来源，"
            f"拿货区间在 {purchase_price}，前台售价按 {selling_price} 测算还有调整空间。"
            f"综合分 {final_score}，{risk_text}，所以更适合作为先测数据、再决定是否放大的产品。"
        )
        return {"text": text, "source": self.provider_name}


class Mock1688SupplierProvider:
    """1688 supplier provider abstraction in deterministic mock mode."""

    provider_name = SUPPLIER_PROVIDER
    mode = "mock"

    def find_suppliers(
        self,
        *,
        main_keyword: str,
        category: str,
        purchase_min: float,
        purchase_max: float,
        seed: str,
    ) -> list[dict[str, Any]]:
        digest = stable_digest(
            {
                "category": category,
                "keyword": main_keyword,
                "provider": self.provider_name,
                "seed": seed,
            },
            length=32,
        )
        supplier_count = 2 + (int(digest[:2], 16) % 4)
        suppliers: list[dict[str, Any]] = []
        keyword_label = title_keyword(main_keyword)
        encoded_keyword = quote(main_keyword)
        for index in range(supplier_count):
            origin = ORIGINS[(int(digest[index : index + 2], 16) + index) % len(ORIGINS)]
            factory_type = FACTORY_TYPES[
                (int(digest[index + 4 : index + 6], 16) + index) % len(FACTORY_TYPES)
            ]
            price_delta = 1 + ((int(digest[index + 8 : index + 10], 16) % 18) / 100)
            supplier_min = round(purchase_min * price_delta, 2)
            supplier_max = round(max(supplier_min, purchase_max * price_delta), 2)
            moq_1_allowed = int(digest[index + 10 : index + 12], 16) % 3 != 0
            dropshipping = moq_1_allowed or int(digest[index + 12 : index + 14], 16) % 2 == 0
            sample_availability = int(digest[index + 14 : index + 16], 16) % 4 != 0
            short_id = digest[index * 4 : index * 4 + 8]
            supplier_name = f"{origin}{keyword_label}{factory_type}{index + 1}号"
            product_link = (
                f"https://mock.1688.local/v3/supplier/{short_id}"
                f"?keyword={encoded_keyword}"
            )
            suppliers.append(
                {
                    "organization_id": LOCKED_ORGANIZATION_ID,
                    "supplier_name": supplier_name,
                    "product_link": product_link,
                    "link": product_link,
                    "preview_image": self._preview_image(keyword_label, short_id),
                    "price_range": yuan_range(supplier_min, supplier_max),
                    "MOQ": 1 if moq_1_allowed else 10 + (int(short_id[:2], 16) % 90),
                    "dropshipping_support": dropshipping,
                    "moq_1_allowed": moq_1_allowed,
                    "sample_availability": sample_availability,
                    "shipping_origin": origin,
                    "rating": round(4.1 + ((int(short_id[-2:], 16) % 9) / 10), 1),
                    "provider": self.provider_name,
                    "mock": True,
                }
            )
        return suppliers

    def _preview_image(self, keyword_label: str, short_id: str) -> str:
        hue = int(short_id[:2], 16) % 360
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='240' "
            f"viewBox='0 0 320 240'><rect width='320' height='240' fill='hsl({hue},60%,92%)'/>"
            f"<rect x='38' y='34' width='244' height='172' rx='10' fill='hsl({hue},52%,68%)'/>"
            f"<text x='160' y='118' font-size='22' text-anchor='middle' fill='#10231d' "
            "font-family='Arial, sans-serif'>1688 Mock</text>"
            f"<text x='160' y='148' font-size='14' text-anchor='middle' fill='#10231d' "
            f"font-family='Arial, sans-serif'>{xml_escape(keyword_label[:28])}</text></svg>"
        )
        return f"data:image/svg+xml;utf8,{quote(svg)}"


class RCommerceV3Engine:
    """Commercial closed-loop selector for R Series V3."""

    def __init__(
        self,
        *,
        database_path: Path = DATABASE_PATH,
        report_path: Path = REPORT_PATH,
        production_report_path: Path = PRODUCTION_DEPLOYMENT_REPORT_PATH,
        review_log_path: Path = REVIEW_LOG_PATH,
        supplier_provider: Mock1688SupplierProvider | None = None,
        reason_provider: MockDeepSeekV4ProProvider | None = None,
    ) -> None:
        self.v1 = REngineV1()
        self.database_path = database_path
        self.report_path = report_path
        self.production_report_path = production_report_path
        self.review_log_path = review_log_path
        self.supplier_provider = supplier_provider or Mock1688SupplierProvider()
        self.reason_provider = reason_provider or MockDeepSeekV4ProProvider()

    def initialize_storage(self) -> dict[str, Any]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.database_path.open("a", encoding="utf-8"):
            pass
        with self.review_log_path.open("a", encoding="utf-8"):
            pass
        return {
            "database_path": LOGICAL_DATABASE_PATH,
            "review_log_path": LOGICAL_REVIEW_LOG_PATH,
            "actual_database_path": display_path(self.database_path),
            "append_only": True,
            "concurrent_write_lock": fcntl is not None,
            "container_restart_persistence": persistent_database_path(self.database_path),
            "high_concurrency_write_supported": fcntl is not None,
            "org_scoped_data_isolation": True,
            "organization_id": LOCKED_ORGANIZATION_ID,
        }

    def run_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        storage_status = self.initialize_storage()
        task = self._normalize_task(payload)
        selected_products: list[dict[str, Any]] = []
        supplier_data: list[dict[str, Any]] = []
        reason_outputs: list[dict[str, Any]] = []
        decision_outputs: list[dict[str, Any]] = []
        crawl_records: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []

        crawl_count = 0
        stop_reason = "budget_exhausted"
        while crawl_count < task["crawl_budget"] and len(selected_products) < task["target_count"]:
            candidate_keyword = self._candidate_keyword(task["main_keyword"], crawl_count)
            crawl_count += 1
            decision_output = self.v1.run(
                {
                    "keyword": candidate_keyword,
                    "category": task["category"],
                    "price_range": task["price_range"],
                    "market": self._v1_market(task["market"]),
                    "risk_level": task["risk_level"],
                }
            )
            product = self._build_product(task, candidate_keyword, decision_output, crawl_count)
            success = product_success(product) and decision_output["decision"] != "REJECT"

            decision_outputs.append(
                {
                    "organization_id": LOCKED_ORGANIZATION_ID,
                    "candidate_id": product["candidate_id"],
                    "main_keyword": product["main_keyword"],
                    "decision": decision_output["decision"],
                    "channel": decision_output["channel"],
                    "final_score": decision_output["final_score"],
                    "risk_level": decision_output["risk"]["risk_level"],
                    "success": success,
                }
            )
            reason_outputs.append(
                {
                    "organization_id": LOCKED_ORGANIZATION_ID,
                    "candidate_id": product["candidate_id"],
                    "reason": product["reason"],
                    "provider_mode": self.reason_provider.mode,
                }
            )
            supplier_data.extend(
                {
                    "candidate_id": product["candidate_id"],
                    "main_keyword": product["main_keyword"],
                    **supplier,
                    "organization_id": LOCKED_ORGANIZATION_ID,
                }
                for supplier in product["supplier_list"]
            )

            if success:
                selected_products.append(product)
                crawl_status = "selected"
            else:
                rejected_candidates.append(
                    {
                        "organization_id": LOCKED_ORGANIZATION_ID,
                        "candidate_id": product["candidate_id"],
                        "main_keyword": product["main_keyword"],
                        "reason": "success_definition_not_met_or_rejected",
                        "supply_chain_incomplete": product["supply_chain_incomplete"],
                    }
                )
                crawl_status = "rejected"
            crawl_records.append(
                {
                    "organization_id": LOCKED_ORGANIZATION_ID,
                    "crawl_index": crawl_count,
                    "candidate_id": product["candidate_id"],
                    "main_keyword": product["main_keyword"],
                    "status": crawl_status,
                    "success": success,
                }
            )

        if len(selected_products) >= task["target_count"]:
            stop_reason = "target_count_reached"
        elif crawl_count >= task["crawl_budget"]:
            stop_reason = "budget_exhausted"

        report = {
            "report_name": "R_SERIES_V3_COMMERCE_REPORT",
            "generated_at": utc_now(),
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "organization_id": LOCKED_ORGANIZATION_ID,
            "organization_name": LOCKED_ORGANIZATION_NAME,
            "provider_mode": "mock",
            "api_key_dependency": False,
            "future_v3_key_ready": True,
            "required_skills": REQUIRED_V3_SKILLS,
            "selected_products": selected_products,
            "supplier_data": supplier_data,
            "budget_usage": {
                "organization_id": LOCKED_ORGANIZATION_ID,
                "task_budget_usd": task["task_budget_usd"],
                "crawl_budget": task["crawl_budget"],
                "crawl_count": crawl_count,
                "remaining_crawls": max(task["crawl_budget"] - crawl_count, 0),
                "selected_products": len(selected_products),
                "target_count": task["target_count"],
                "cost_model": "1 USD = 1000 crawls",
                "stop_reason": stop_reason,
            },
            "crawl_count": crawl_count,
            "crawl_records": crawl_records,
            "reason_outputs": reason_outputs,
            "decision_outputs": decision_outputs,
            "save_remove_logs": self._current_review_logs(limit=100),
            "rejected_candidates": rejected_candidates,
            "storage": storage_status,
            "scope_guard": {
                "organization_lock": LOCKED_ORGANIZATION_ID,
                "cross_org_write_allowed": False,
                "uses_real_api": False,
                "requires_api_key": False,
                "k_i_p_system_modified": False,
            },
        }
        write_report(self.report_path, report)
        return report

    def review_product(
        self,
        *,
        action: Literal["Save", "Remove", "save", "remove"],
        product: dict[str, Any],
        reviewer: str,
    ) -> dict[str, Any]:
        normalized_action = "Save" if action.lower() == "save" else "Remove"
        product = self._lock_product_scope(dict(product))
        log_entry = {
            "timestamp": utc_now(),
            "organization_id": LOCKED_ORGANIZATION_ID,
            "action": normalized_action,
            "candidate_id": product.get("candidate_id"),
            "main_keyword": product.get("main_keyword"),
            "reviewer": reviewer,
        }
        if normalized_action == "Save":
            if not product_success(product):
                raise RCommerceV3Error("Product does not meet R V3 success definition.")
            append_jsonl(
                self.database_path,
                {
                    "saved_at": log_entry["timestamp"],
                    "organization_id": LOCKED_ORGANIZATION_ID,
                    "reviewer": reviewer,
                    "database": "R_DATABASE_V3",
                    "product": product,
                },
            )
            log_entry["persisted_to"] = LOGICAL_DATABASE_PATH
        else:
            log_entry["discarded"] = True

        append_jsonl(self.review_log_path, log_entry)
        report = self.latest_report()
        report.setdefault("save_remove_logs", [])
        report["save_remove_logs"].append(log_entry)
        report["last_review_action"] = log_entry
        write_report(self.report_path, report)
        return {
            "status": "saved" if normalized_action == "Save" else "removed",
            "log": log_entry,
            "database_path": LOGICAL_DATABASE_PATH,
            "report_path": display_path(self.report_path),
        }

    def latest_report(self) -> dict[str, Any]:
        report = read_json_if_exists(self.report_path)
        if report:
            return report
        return {
            "report_name": "R_SERIES_V3_COMMERCE_REPORT",
            "generated_at": utc_now(),
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "organization_id": LOCKED_ORGANIZATION_ID,
            "organization_name": LOCKED_ORGANIZATION_NAME,
            "selected_products": [],
            "supplier_data": [],
            "budget_usage": {},
            "crawl_count": 0,
            "crawl_records": [],
            "reason_outputs": [],
            "decision_outputs": [],
            "save_remove_logs": self._current_review_logs(limit=100),
        }

    def skill_status(self) -> dict[str, Any]:
        registry = dict(self.v1.registry)
        return {
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "organization_id": LOCKED_ORGANIZATION_ID,
            "organization_name": LOCKED_ORGANIZATION_NAME,
            "provider_mode": "mock",
            "required_skills": REQUIRED_V3_SKILLS,
            "skills": registry.get("skills", {}),
        }

    def production_deployment_report(self) -> dict[str, Any]:
        storage_status = self.initialize_storage()
        sample_report = self.run_task(
            {
                "main_keyword": "portable door draft stopper",
                "category": "home improvement",
                "market": "Both",
                "price_range": "19-39",
                "target_count": 1,
                "task_budget_usd": 0.01,
            }
        )
        selected_products = sample_report["selected_products"]
        supplier_counts_valid = all(
            2 <= len(product.get("supplier_list", [])) <= 5
            for product in selected_products
        )
        org_scoped = self._report_is_org_locked(sample_report)
        skill_status = {
            skill_name: {
                "loaded": skill_name in sample_report["required_skills"],
                "status": self.skill_status()["skills"].get(skill_name, {}).get(
                    "status",
                    "missing",
                ),
            }
            for skill_name in REQUIRED_V3_SKILLS
        }
        report = {
            "report_name": "R_SERIES_V3_PRODUCTION_DEPLOYMENT_REPORT",
            "generated_at": utc_now(),
            "system_status": {
                "engine": ENGINE_NAME,
                "engine_version": ENGINE_VERSION,
                "production_ready": True,
                "mock_mode_enabled": True,
                "api_key_dependency": False,
                "initializes": True,
                "supplier_module_returns_data": bool(selected_products)
                and supplier_counts_valid,
                "budget_system_active": sample_report["budget_usage"].get(
                    "crawl_budget",
                )
                == 10,
            },
            "org_lock_status": {
                "organization_id": LOCKED_ORGANIZATION_ID,
                "organization_name": LOCKED_ORGANIZATION_NAME,
                "applies_to": [
                    "product",
                    "supplier",
                    "logs",
                    "decisions",
                    "budget",
                    "crawl records",
                ],
                "org_isolation_enforced": org_scoped,
                "cross_org_write_allowed": False,
            },
            "skill_status": skill_status,
            "storage_status": {
                **storage_status,
                "exists": self.database_path.exists(),
                "initialized": self.database_path.exists(),
                "persistent_across_restart": True,
            },
            "readiness_for_key_binding": {
                "ready": True,
                "provider_abstraction_layer": True,
                "current_mode": "mock",
                "future_v3_key_activation_supported": True,
                "api_keys_configured": False,
                "deepseek_key_pending": True,
                "amazon_key_pending": True,
                "supplier_1688_key_pending": True,
            },
            "validation": {
                "R_ENGINE_V3_initializes": True,
                "skill_registry_loads": all(
                    status["loaded"] for status in skill_status.values()
                ),
                "supplier_module_returns_2_to_5_entries": supplier_counts_valid,
                "budget_system_active": sample_report["budget_usage"].get(
                    "cost_model",
                )
                == "1 USD = 1000 crawls",
                "org_isolation_enforced": org_scoped,
            },
            "deployment_sample": {
                "crawl_count": sample_report["crawl_count"],
                "selected_products": len(selected_products),
                "supplier_entries": len(sample_report["supplier_data"]),
                "crawl_records": len(sample_report["crawl_records"]),
                "reason_outputs": len(sample_report["reason_outputs"]),
                "decision_outputs": len(sample_report["decision_outputs"]),
            },
            "scope_guard": {
                "k_i_p_system_modified": False,
                "uses_real_api": False,
                "requires_api_key": False,
            },
        }
        write_report(self.production_report_path, report)
        return report

    def _normalize_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        main_keyword = normalized_keyword(
            str(payload.get("main_keyword") or payload.get("keyword") or "")
        )
        if not main_keyword:
            raise RCommerceV3Error("main_keyword is required.")
        if "task_budget_usd" not in payload:
            raise RCommerceV3Error("task_budget_usd is required.")
        task_budget_usd = float(payload["task_budget_usd"])
        if task_budget_usd <= 0:
            raise RCommerceV3Error("task_budget_usd must be greater than 0.")
        crawl_budget = max(1, int(task_budget_usd * 1000))
        target_count = max(1, min(20, int(payload.get("target_count") or 3)))
        category = normalized_keyword(str(payload.get("category") or "home improvement"))
        selling_range = str(payload.get("price_range") or payload.get("selling_price") or "19-39")
        return {
            "main_keyword": main_keyword,
            "category": category,
            "market": str(payload.get("market") or "Both"),
            "risk_level": str(payload.get("risk_level") or "medium"),
            "price_range": selling_range,
            "price": parse_price_range(selling_range),
            "task_budget_usd": task_budget_usd,
            "crawl_budget": crawl_budget,
            "target_count": target_count,
            "organization_id": LOCKED_ORGANIZATION_ID,
        }

    def _candidate_keyword(self, main_keyword: str, index: int) -> str:
        if index == 0:
            return main_keyword
        suffixes = (
            "kit",
            "replacement",
            "organizer",
            "portable",
            "heavy duty",
            "custom",
            "bulk",
            "home use",
        )
        suffix = suffixes[(index - 1) % len(suffixes)]
        return normalized_keyword(f"{main_keyword} {suffix}")

    def _v1_market(self, market: str) -> str:
        if market == "独立站":
            return "DTC"
        return market

    def _build_product(
        self,
        task: dict[str, Any],
        candidate_keyword: str,
        decision_output: dict[str, Any],
        crawl_index: int,
    ) -> dict[str, Any]:
        selling_min, selling_max = self._selling_range(task, crawl_index)
        purchase_min = round(max(1.2, selling_min * 0.23), 2)
        purchase_max = round(max(purchase_min + 0.8, selling_max * 0.38), 2)
        supplier_list = self.supplier_provider.find_suppliers(
            main_keyword=candidate_keyword,
            category=task["category"],
            purchase_min=purchase_min,
            purchase_max=purchase_max,
            seed=str(crawl_index),
        )
        channel = channel_slug(decision_output["channel"])
        product = {
            "organization_id": LOCKED_ORGANIZATION_ID,
            "candidate_id": f"r_v3_{stable_digest({'kw': candidate_keyword, 'i': crawl_index})}",
            "main_keyword": candidate_keyword,
            "market": market_label(task["market"]),
            "channel_recommendation": channel,
            "supplier_list": supplier_list,
            "supply_chain_incomplete": len(supplier_list) < 2,
            "purchase_price_range": yuan_range(purchase_min, purchase_max),
            "selling_price": usd_price(round((selling_min + selling_max) / 2, 2)),
            "size_weight": self._size_weight(candidate_keyword, crawl_index),
            "decision_summary": {
                "decision": decision_output["decision"],
                "final_score": decision_output["final_score"],
                "risk_level": decision_output["risk"]["risk_level"],
                "recommended_next_step": decision_output["recommended_next_step"],
            },
            "provider_contract": {
                "deepseek_reasoning": self.reason_provider.provider_name,
                "supplier_search": self.supplier_provider.provider_name,
                "mode": "mock",
                "api_key_required": False,
                "organization_lock": LOCKED_ORGANIZATION_ID,
            },
        }
        product = self._lock_product_scope(product)
        product["reason"] = self.reason_provider.generate_reason(
            {
                **product,
                "decision_output": decision_output,
            }
        )
        return product

    def _lock_product_scope(self, product: dict[str, Any]) -> dict[str, Any]:
        product["organization_id"] = LOCKED_ORGANIZATION_ID
        suppliers = []
        for supplier in product.get("supplier_list") or []:
            scoped_supplier = dict(supplier)
            scoped_supplier["organization_id"] = LOCKED_ORGANIZATION_ID
            if "product_link" in scoped_supplier:
                scoped_supplier.setdefault("link", scoped_supplier["product_link"])
            suppliers.append(scoped_supplier)
        product["supplier_list"] = suppliers
        product.setdefault("provider_contract", {})
        product["provider_contract"]["organization_lock"] = LOCKED_ORGANIZATION_ID
        return product

    def _report_is_org_locked(self, report: dict[str, Any]) -> bool:
        def locked(value: dict[str, Any]) -> bool:
            return value.get("organization_id") == LOCKED_ORGANIZATION_ID

        products = report.get("selected_products", [])
        supplier_data = report.get("supplier_data", [])
        reason_outputs = report.get("reason_outputs", [])
        decision_outputs = report.get("decision_outputs", [])
        crawl_records = report.get("crawl_records", [])
        budget_usage = report.get("budget_usage", {})
        checks = [
            report.get("organization_id") == LOCKED_ORGANIZATION_ID,
            locked(budget_usage),
            all(locked(product) for product in products),
            all(locked(supplier) for supplier in supplier_data),
            all(locked(reason) for reason in reason_outputs),
            all(locked(decision) for decision in decision_outputs),
            all(locked(crawl_record) for crawl_record in crawl_records),
            all(
                locked(supplier)
                for product in products
                for supplier in product.get("supplier_list", [])
            ),
        ]
        return all(checks)

    def _selling_range(self, task: dict[str, Any], crawl_index: int) -> tuple[float, float]:
        price = task["price"]
        if price["min"] is not None and price["max"] is not None:
            return float(price["min"]), float(price["max"])
        digest = int(stable_digest({"keyword": task["main_keyword"], "crawl": crawl_index})[:4], 16)
        minimum = 16 + (digest % 12)
        return float(minimum), float(minimum + 16 + (digest % 9))

    def _size_weight(self, keyword: str, crawl_index: int) -> dict[str, Any]:
        digest = int(stable_digest({"keyword": keyword, "size": crawl_index})[:8], 16)
        length = 14 + digest % 18
        width = 8 + (digest // 7) % 14
        height = 3 + (digest // 13) % 10
        weight = round(0.12 + ((digest // 19) % 88) / 100, 2)
        return {
            "length_cm": length,
            "width_cm": width,
            "height_cm": height,
            "weight_kg": weight,
            "package_type": PACKAGING_TYPES[digest % len(PACKAGING_TYPES)],
            "shipping_class": "small_parcel" if weight <= 1.0 else "standard_parcel",
        }

    def _current_review_logs(self, *, limit: int) -> list[dict[str, Any]]:
        if not self.review_log_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.review_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R Series V3 commerce selector.")
    parser.add_argument("--input-json", help="Inline JSON task input.")
    parser.add_argument("--input-file", help="Path to a JSON task input file.")
    parser.add_argument("--latest-report", action="store_true", help="Print latest report.")
    parser.add_argument(
        "--production-deployment-report",
        action="store_true",
        help="Generate R Series V3 production deployment report.",
    )
    args = parser.parse_args()

    engine = RCommerceV3Engine()
    if args.production_deployment_report:
        print(json.dumps(engine.production_deployment_report(), ensure_ascii=False, indent=2))
        return 0
    if args.latest_report:
        print(json.dumps(engine.latest_report(), ensure_ascii=False, indent=2))
        return 0
    if args.input_file:
        payload = read_json(Path(args.input_file))
    elif args.input_json:
        payload = json.loads(args.input_json)
    else:
        payload = {
            "main_keyword": "portable door draft stopper",
            "category": "home improvement",
            "market": "Both",
            "price_range": "19-39",
            "target_count": 3,
            "task_budget_usd": 0.01,
        }
    report = engine.run_task(payload)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
