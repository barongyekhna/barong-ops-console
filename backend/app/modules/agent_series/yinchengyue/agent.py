"""殷承岳在 agent_registry 里的登记。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.registry import AgentRegistry
from .constants import AGENT_ID


def agent_spec() -> dict:
    return {
        "agent_id": AGENT_ID,
        "name": "殷承岳 · 产品助理",
        "responsibilities": [
            "在 C19 通讯里回答「这个产品属于谷歌类目树里的哪个类目」",
            "给出英文类目名(叶子优先)、完整路径、中文名和判定理由,附最多两个备选",
            "只从 k_category_google 里真实存在的候选中选;候选外的答案一律作废",
        ],
        "non_responsibilities": [
            "不新建 / 修改类目,不改 K 系列产品的类目绑定,不做任何写入",
            "不回答类目判定以外的问题",
            "不主动开口",
            "不区分说话人身份——本来就没有需要权限的动作",
        ],
        "input_schema": {"message": "string", "conversation_id": "string", "speaker_user_id": "string"},
        "output_schema": {"reply": "string", "google_category_id": "string|null"},
        "permissions": [],
        "risk_level": "low",
        "version": "v1",
        "status": "foundation",
        "dependencies": ["k.product_knowledge"],
        "artifact_types": ["chat_message"],
        "review_types": [],
        "error_codes": ["AGENT_LOGIN_FAILED", "AGENT_AI_UNAVAILABLE", "AGENT_REPLY_FAILED"],
        "healthcheck_config": {"type": "db_table", "target": "k_category_google"},
        "rollback_policy": {
            "strategy": "none",
            "reason": "只读问答,没有可回滚的写入",
        },
        "allowed_module_ids": [],
        "allowed_workflow_ids": [],
    }


def ensure_yinchengyue_agent(db: Session) -> bool:
    existing = db.scalar(select(AgentRegistry).where(AgentRegistry.agent_id == AGENT_ID))
    if existing is not None:
        return False
    db.add(AgentRegistry(**agent_spec()))
    db.flush()
    return True
