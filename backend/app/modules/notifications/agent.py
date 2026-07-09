"""Registration of the P notification agent in ``agent_registry``.

Idempotent: re-running is a no-op if the agent already exists. Seeded manually
(``python -m backend.app.modules.notifications.seed``) the same way migrations
are applied in this deployment.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.registry import AgentRegistry

P_NOTIFICATIONS_AGENT_ID = "p.notifications"


def _agent_spec() -> dict:
    return {
        "agent_id": P_NOTIFICATIONS_AGENT_ID,
        "name": "P 通知 agent",
        "responsibilities": [
            "接收 P 系列上传管线 / n8n 回调事件，落库为可查询的控制台通知",
            "记录外部平台产品 ID、页面 URL 等结果引用（external_refs）",
            "维护通知 未读/已读 状态，供控制台收件箱查询",
        ],
        "non_responsibilities": [
            "不执行上传，不调用外部平台 API",
            "不做审批 / 风控决策",
            "不直接推送 WeCom / 邮件（真实数字人推送后续再接）",
        ],
        "input_schema": {
            "type": "object",
            "required": ["event_type", "title"],
            "properties": {
                "event_type": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "level": {
                    "type": "string",
                    "enum": ["info", "success", "warning", "error"],
                },
                "source": {"type": "string"},
                "org_id": {"type": "string"},
                "product_id": {"type": "string", "format": "uuid"},
                "external_refs": {"type": "object"},
                "payload": {"type": "object"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "notification_id": {"type": "integer"},
                "status": {"type": "string"},
            },
        },
        "permissions": ["notifications.read", "notifications.write"],
        "risk_level": "low",
        "version": "v1",
        "status": "foundation",
        "dependencies": [],
        "artifact_types": ["notification"],
        "review_types": [],
        "error_codes": ["INGEST_DISABLED", "INVALID_INGEST_TOKEN", "VALIDATION_ERROR"],
        "healthcheck_config": {"type": "db_table", "target": "p_notifications"},
        "rollback_policy": {
            "strategy": "none",
            "reason": "append-only notification log; nothing to roll back",
        },
        "allowed_module_ids": [
            "k.product_knowledge",
            "i.image_system",
            "p.upload",
        ],
        "allowed_workflow_ids": [],
    }


def ensure_p_notifications_agent(db: Session) -> bool:
    """Insert the agent if absent. Returns True if it was created."""
    existing = db.scalar(
        select(AgentRegistry).where(
            AgentRegistry.agent_id == P_NOTIFICATIONS_AGENT_ID
        )
    )
    if existing is not None:
        return False
    db.add(AgentRegistry(**_agent_spec()))
    db.flush()
    return True
