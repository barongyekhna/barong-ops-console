"""苏青禾在 agent_registry 里的登记。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.registry import AgentRegistry
from .constants import AGENT_ID


def agent_spec() -> dict:
    return {
        "agent_id": AGENT_ID,
        "name": "苏青禾 · 独立站运营总管",
        "responsibilities": [
            "每天早上读全局快照(产品卡在哪一步、内容待审、掉线的 worker、坏掉的钥匙、AI 花费),出当天计划",
            "把需要老板拍板的事做成审批卡(说人话、带证据),一天不超过 5 张",
            "在 C19 私聊里接老板的批 / 驳 / 交代,记进硬记忆",
            "每天最多主动提醒一次待审卡,深夜不打扰",
        ],
        "non_responsibilities": [
            "影子期:不改任何业务数据,批了的卡只记账不执行",
            "不碰亚马逊 A 系列(那是殷家五人的事)",
            "不替老板做决定;一次最多递一个需要拍板的事",
        ],
        "input_schema": {"snapshot": "object", "owner_message": "string"},
        "output_schema": {"plan": "string", "cards": "list"},
        "permissions": [],
        "risk_level": "low",
        "version": "v1",
        "status": "foundation",
        "dependencies": ["k.product_knowledge", "p.series"],
        "artifact_types": ["chat_message", "approval_card"],
        "review_types": ["owner_approval"],
        "error_codes": ["AGENT_LOGIN_FAILED", "AGENT_AI_UNAVAILABLE", "AGENT_SNAPSHOT_PARTIAL"],
        "healthcheck_config": {"type": "worker_heartbeat", "target": "suqinghe-worker"},
        "rollback_policy": {"strategy": "none", "reason": "影子期没有业务写入,审批卡只是记录"},
        "allowed_module_ids": [],
        "allowed_workflow_ids": [],
    }


def ensure_suqinghe_agent(db: Session) -> bool:
    existing = db.scalar(select(AgentRegistry).where(AgentRegistry.agent_id == AGENT_ID))
    if existing is not None:
        return False
    db.add(AgentRegistry(**agent_spec()))
    db.flush()
    return True
