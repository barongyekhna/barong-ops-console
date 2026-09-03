"""霓旌在 agent_registry 里的登记。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.registry import AgentRegistry
from .constants import AGENT_ID


def agent_spec() -> dict:
    return {
        "agent_id": AGENT_ID,
        "name": "霓旌 · 库管员",
        "responsibilities": [
            "在 C19 通讯里听懂入库 / 生产 / 发货 / 盘点调整,替说话人开 M 系列单据",
            "每一笔写入先出确认卡,说话人确认后才落单",
            "回答库存与单据查询",
            "撤销 = 反向盘点调整,并注明冲销哪张单",
        ],
        "non_responsibilities": [
            "不新建/修改/归档物料与成品主档,不改配件清单(红灯,去控制台)",
            "不用自己的身份做任何库存操作——全部按说话人的权限算",
            "不处理一句话里的多个操作,让用户分开说",
            "不主动开口",
            "不碰 K / P 系列",
        ],
        "input_schema": {"message": "string", "conversation_id": "string", "speaker_user_id": "string"},
        "output_schema": {"reply": "string", "documents": "list[string]"},
        "permissions": [],
        "risk_level": "medium",
        "version": "v1",
        "status": "foundation",
        "dependencies": ["mfg.inventory"],
        "artifact_types": ["chat_message", "mfg_document"],
        "review_types": [],
        "error_codes": ["AGENT_LOGIN_FAILED", "AGENT_AI_UNAVAILABLE", "AGENT_REPLY_FAILED"],
        "healthcheck_config": {"type": "db_table", "target": "mfg_documents"},
        "rollback_policy": {
            "strategy": "none",
            "reason": "单据不可删；错单用反向盘点调整冲销",
        },
        "allowed_module_ids": ["mfg.inventory"],
        "allowed_workflow_ids": [],
    }


def ensure_nijing_agent(db: Session) -> bool:
    existing = db.scalar(select(AgentRegistry).where(AgentRegistry.agent_id == AGENT_ID))
    if existing is not None:
        return False
    db.add(AgentRegistry(**agent_spec()))
    db.flush()
    return True
