"""Framework and manual execution state for R-A.

This module builds the R-A status without starting background analysis jobs.
External providers are only called by explicit R-A action endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.profit_service import profit_formula_config
from r_system_v2.ra.skill_loader import load_ra_skill_manifest


RA_REQUIRED_TABLES: tuple[tuple[str, str], ...] = (
    ("ra_selection_runs", "R-A 分析任务批次"),
    ("ra_candidates", "R-A 候选产品池"),
    ("ra_ai_evaluations", "三层 AI 审计记录"),
    ("ra_supplier_searches", "1688 官方 API / Mock 搜索任务"),
    ("ra_supplier_offers", "供应商报价候选"),
    ("ra_profit_snapshots", "利润与成本快照"),
    ("ra_competition_snapshots", "Rainforest 竞争快照"),
    ("ra_channel_signals", "Amazon / DTC广告 / DTC SEO 渠道信号"),
    ("ra_final_decisions", "最终选品决策"),
    ("ra_reports", "最终报告"),
    ("ra_alerts", "告警与通知记录"),
)

RA_CHANNELS: tuple[dict[str, object], ...] = (
    {
        "id": "amazon",
        "label": "亚马逊",
        "description": "稳定需求、可攻竞争、FBA 利润结构。",
        "manual_trigger": True,
    },
    {
        "id": "dtc_seo",
        "label": "独立站 SEO",
        "description": "Keepa 需求验证 + Serper 弱 SERP 机会。",
        "manual_trigger": True,
    },
    {
        "id": "dtc_ad",
        "label": "独立站广告",
        "description": "3 秒钩子、广告承接和高毛利结构。",
        "manual_trigger": True,
    },
    {
        "id": "both",
        "label": "双平台",
        "description": "Amazon 验证需求，DTC 承接长期品牌与流量。",
        "manual_trigger": True,
    },
)

RA_STAGES: tuple[dict[str, object], ...] = (
    {
        "id": "candidate_pool",
        "label": "候选池",
        "owner": "R-A",
        "status": "framework_ready",
        "description": "从 R-W 读取通过产品，导入 R-A 自有候选池。",
    },
    {
        "id": "skill_loader",
        "label": "Skill Loader",
        "owner": "R-A",
        "status": "framework_ready",
        "description": "按 Amazon / DTC / both 加载 R 系列选品手册。",
    },
    {
        "id": "channel_routing",
        "label": "三路选品分类",
        "owner": "R-A",
        "status": "framework_ready",
        "description": "利润通过后按亚马逊、独立站广告、独立站 SEO 三条路径生成结构化信号；Google Ads 审核前只记录待审核状态。",
    },
    {
        "id": "google_ads_keyword_planner",
        "label": "Google Ads Keyword Planner",
        "owner": "R-A",
        "status": "pending_basic_review",
        "description": "已接入 R-A 密钥解析与 DTC SEO 搜索量/CPC 证据位；Basic 审核完成前不发起真实调用。",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek 第一层",
        "owner": "R-A",
        "status": "real_provider_ready",
        "description": "真实 DeepSeek 结构化量化分析，利润通过后自动运行。",
    },
    {
        "id": "gpt",
        "label": "GPT 第二层",
        "owner": "R-A",
        "status": "real_provider_ready",
        "description": "真实 GPT 通过 4sapi 验证 listing、竞争和供应商匹配。",
    },
    {
        "id": "opus",
        "label": "Opus 第三层",
        "owner": "R-A",
        "status": "real_provider_ready",
        "description": "真实 Opus 通过 4sapi 做最终小卖家选品决策。",
    },
    {
        "id": "rainforest_competition",
        "label": "Rainforest 竞争数据",
        "owner": "R-A",
        "status": "real_provider_ready",
        "description": "利润通过后抓取 Amazon 页一搜索数据，计算评论墙、品牌集中度和新品占比。",
    },
    {
        "id": "supplier_cost",
        "label": "供货商与成本",
        "owner": "R-A",
        "status": "framework_ready",
        "description": "默认使用 1688 官方 API mock；真实 1688 API 到位后直接切换 provider。",
    },
    {
        "id": "profit_engine",
        "label": "利润引擎",
        "owner": "R-A",
        "status": "framework_ready",
        "description": "按美国站公式计算体积重、头程、佣金、FBA、毛利润和 ROI。",
    },
    {
        "id": "final_report",
        "label": "最终报告",
        "owner": "R-A",
        "status": "real_provider_ready",
        "description": "真实多 AI 流程会持久化最终选品判断与人工下一步动作。",
    },
)

NEXT_STEPS: tuple[str, ...] = (
    "继续接入人工确认队列与 R-A 到下一模块的交接动作。",
)


@dataclass(frozen=True)
class RATableStatus:
    name: str
    label: str
    exists: bool
    row_count: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "exists": self.exists,
            "row_count": self.row_count,
        }


def load_ra_framework_overview(db: Session, *, org_id: str) -> dict[str, Any]:
    providers = RAnalysisProviderBinding(
        org_id=org_id,
        secret_manager=SecretManager(db_session=db),
    ).status()
    return {
        "module": "r.analysis",
        "label": "R-A 产品分析中心",
        "organization_id": org_id,
        "status": "framework_ready",
        "runtime_mode": "manual_execution_ready",
        "execution_enabled": True,
        "external_calls_enabled": bool(providers.get("external_calls_enabled")),
        "manual_trigger_only": True,
        "data_boundary": {
            "reads": ["products_rw"],
            "writes": [name for name, _label in RA_REQUIRED_TABLES],
            "cross_module_writes": False,
        },
        "candidate_source": _load_candidate_source(db),
        "tables": [item.to_dict() for item in _load_table_statuses(db)],
        "skill": load_ra_skill_manifest(),
        "providers": providers,
        "profit_formula": profit_formula_config(),
        "channels": list(RA_CHANNELS),
        "stages": list(RA_STAGES),
        "next_steps": list(NEXT_STEPS),
    }


def _load_candidate_source(db: Session) -> dict[str, object]:
    if not _table_exists(db, "products_rw"):
        return {
            "status": "warehouse_table_missing",
            "total_products": 0,
            "ra_eligible": 0,
            "deepseek_passed": 0,
            "rule_passed": 0,
            "rejected": 0,
            "source_table": "products_rw",
        }

    try:
        row = db.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total_products,
                  COALESCE(SUM(CASE WHEN state = 'ai1_passed' THEN 1 ELSE 0 END), 0) AS deepseek_passed,
                  COALESCE(SUM(CASE WHEN state = 'rule_passed' THEN 1 ELSE 0 END), 0) AS rule_passed,
                  COALESCE(SUM(CASE WHEN state IN ('rejected', 'ai1_rejected') THEN 1 ELSE 0 END), 0) AS rejected,
                  COALESCE(SUM(CASE WHEN state IN ('ai1_passed', 'rule_passed') THEN 1 ELSE 0 END), 0) AS ra_eligible
                FROM products_rw
                """
            )
        ).mappings().first()
    except SQLAlchemyError:
        return {
            "status": "warehouse_query_failed",
            "total_products": 0,
            "ra_eligible": 0,
            "deepseek_passed": 0,
            "rule_passed": 0,
            "rejected": 0,
            "source_table": "products_rw",
        }

    return {
        "status": "ready",
        "total_products": int(row["total_products"] or 0) if row else 0,
        "ra_eligible": int(row["ra_eligible"] or 0) if row else 0,
        "deepseek_passed": int(row["deepseek_passed"] or 0) if row else 0,
        "rule_passed": int(row["rule_passed"] or 0) if row else 0,
        "rejected": int(row["rejected"] or 0) if row else 0,
        "source_table": "products_rw",
    }


def _load_table_statuses(db: Session) -> list[RATableStatus]:
    statuses: list[RATableStatus] = []
    for table_name, label in RA_REQUIRED_TABLES:
        exists = _table_exists(db, table_name)
        statuses.append(
            RATableStatus(
                name=table_name,
                label=label,
                exists=exists,
                row_count=_row_count(db, table_name) if exists else None,
            )
        )
    return statuses


def _table_exists(db: Session, table_name: str) -> bool:
    try:
        return bool(inspect(db.get_bind()).has_table(table_name))
    except SQLAlchemyError:
        return False


def _row_count(db: Session, table_name: str) -> int | None:
    try:
        row = db.execute(text(f"SELECT COUNT(*) AS count FROM {table_name}")).mappings().first()
    except SQLAlchemyError:
        return None
    return int(row["count"] or 0) if row else 0
