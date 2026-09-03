"""白苏婉在 ``agent_registry`` 里的登记。

幂等:重复跑是 no-op。由 ``app/cli/bootstrap_bot.py`` 调用。

``non_responsibilities`` 抄自 docs/AGENT_BAISUWAN_V1.md 第三节 —— 那一栏比
``responsibilities`` 重要:数字员工最要紧的不是能干什么,是明确不许碰什么。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.registry import AgentRegistry
from .constants import AGENT_ID, AGENT_PERMISSIONS


def _agent_spec() -> dict:
    return {
        "agent_id": AGENT_ID,
        "name": "白苏婉 · 内容专员",
        "responsibilities": [
            "在 C19 通讯里跟人对话,回答内容链路的当前状态",
            "读 GEO 簇 / 指南 / 批评汇总 / 阵地监测,汇总成人话",
            "读 SEO 工艺事实 / 选题 / 待审条目 / 内容健康",
            "按重要性排出「今天该看什么」,而不是流水账",
            "把自己的观察写进只属于她的记忆文件,越用越准",
        ],
        "non_responsibilities": [
            "不碰产品(K)、上架(P)、找货(F/R)、开发信(B2B)、网站设置(W/H)",
            "不碰品牌门 —— 品牌审查的放行永远是人的事",
            "进不了 WordPress 后台 —— 只有控制台账号,够不着",
            "不定选题、不建内容簇、不批准工艺事实、不审核文章(全是红灯)",
            "第一版连绿灯动作都没有:只能读,一个写端点都调不了",
        ],
        "input_schema": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "description": "真人在 C19 里说的话"},
                "conversation_id": {"type": "string"},
                "speaker_user_id": {"type": "integer"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "memory_written": {"type": "boolean"},
            },
        },
        "permissions": list(AGENT_PERMISSIONS),
        "risk_level": "low",
        "version": "v1",
        "status": "foundation",
        "dependencies": ["geo.content", "seo.content"],
        "artifact_types": ["chat_message", "agent_memory"],
        "review_types": [],
        "error_codes": [
            "AGENT_LOGIN_FAILED",
            "AGENT_AI_UNAVAILABLE",
            "AGENT_CONSOLE_UNREACHABLE",
        ],
        "healthcheck_config": {"type": "db_table", "target": "c19_conversations"},
        "rollback_policy": {
            "strategy": "none",
            "reason": "read-only agent; it emits chat messages and its own memory files only",
        },
        "allowed_module_ids": ["geo.content", "seo.content"],
        "allowed_workflow_ids": [],
    }


def ensure_baisuwan_agent(db: Session) -> bool:
    """Insert the agent if absent. Returns True if it was created."""
    existing = db.scalar(
        select(AgentRegistry).where(AgentRegistry.agent_id == AGENT_ID)
    )
    if existing is not None:
        return False
    db.add(AgentRegistry(**_agent_spec()))
    db.flush()
    return True
