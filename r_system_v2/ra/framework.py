"""Read-only framework state for R-A.

This module builds the R-A skeleton status without starting analysis jobs or
calling external providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.skill_loader import load_ra_skill_manifest


RA_REQUIRED_TABLES: tuple[tuple[str, str], ...] = (
    ("ra_selection_runs", "R-A 分析任务批次"),
    ("ra_candidates", "R-A 候选产品池"),
    ("ra_ai_evaluations", "三层 AI 审计记录"),
    ("ra_supplier_searches", "Serper / 1688 搜索任务"),
    ("ra_supplier_offers", "供应商报价候选"),
    ("ra_profit_snapshots", "利润与成本快照"),
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
        "id": "deepseek",
        "label": "DeepSeek 第一层",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "结构化量化分析；后续接入真实调用。",
    },
    {
        "id": "gpt",
        "label": "GPT 第二层",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "通过 4sapi 验证 listing、评论和差异化缺口。",
    },
    {
        "id": "opus",
        "label": "Opus 第三层",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "通过 4sapi 做最终小卖家决策与路线判断。",
    },
    {
        "id": "supplier_cost",
        "label": "供货商与成本",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "Serper 发现 1688，Playwright 抓供应商与报价。",
    },
    {
        "id": "profit_engine",
        "label": "利润引擎",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "确定性公式计算 landed cost、净利、ROI。",
    },
    {
        "id": "final_report",
        "label": "最终报告",
        "owner": "R-A",
        "status": "pending_integration",
        "description": "持久化最终选品判断与人工下一步动作。",
    },
)

NEXT_STEPS: tuple[str, ...] = (
    "接入 R-W 候选导入接口。",
    "接入 DeepSeek 第一层 R-A 分析，不复用 R-W 实时筛选逻辑。",
    "接入 4sapi GPT / Opus 角色路由。",
    "接入 Serper 手动搜索与 1688 Playwright 抓取。",
    "接入确定性利润计算引擎。",
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
    return {
        "module": "r.analysis",
        "label": "R-A 产品分析中心",
        "organization_id": org_id,
        "status": "framework_ready",
        "runtime_mode": "framework_only",
        "execution_enabled": False,
        "external_calls_enabled": False,
        "manual_trigger_only": True,
        "data_boundary": {
            "reads": ["products_rw"],
            "writes": [name for name, _label in RA_REQUIRED_TABLES],
            "cross_module_writes": False,
        },
        "candidate_source": _load_candidate_source(db),
        "tables": [item.to_dict() for item in _load_table_statuses(db)],
        "skill": load_ra_skill_manifest(),
        "providers": RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        ).status(),
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

