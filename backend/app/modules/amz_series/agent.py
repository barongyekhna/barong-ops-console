"""亚马逊数字员工在 agent_registry 里的登记(A/B/C/D/E)。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.registry import AgentRegistry
from .constants import EMPLOYEE_AGENT_ID_PREFIX, EMPLOYEE_USERNAMES, EMPLOYEES, MODULE_KEY
from .persona import display_name

_RESPONSIBILITIES: dict[str, list[str]] = {
    "A": [
        "诊断五个店铺的标题 / 五点 / 后台词 / A+ 文案,按事实表写草稿",
        "同一个词、同一款货、三店对照:谁接得住,差在哪",
        "只出建议,改动永远由人放行",
    ],
    "B": [
        "给主图 / 副图 / A+ 图写带证据的 brief,排进 Codex 队列",
        "同屏门:候选图与竞品缩略图同屏比较",
        "兄弟店同款图文差异化检查",
    ],
    "C": [
        "维护每条产品线的对手名单,每天一张快照,只报变化",
        "Brand Analytics 份额每周一句:掉给了谁、大概因为什么",
        "发现转给 A / B / D",
    ],
    "D": [
        "收割赢家词、否词(含需求储备例外)、竞价与广告位、预算、活动稳定性",
        "库存天数、断货、季节倒计时告警",
        "跨店组合:三店同词的主场分配",
    ],
    "E": [
        "每家店、每个 SKU 每天的真实利润(销售额 − 亚马逊费用 − 商品成本 − 广告费)",
        "广告本身的盈亏;亏卖线、单件毛利跌破底线、退款突增、FBA 费变动预警",
        "成本只用人在财务页填的;缺成本就说缺,不猜",
    ],
}
_NON_RESPONSIBILITIES: list[str] = [
    "不碰 K / I / M 系列的任何表",
    "不自动履约,不刷单,不做浏览器自动化",
    "影子期只建议不落笔;所有对亚马逊的写都走梯子与护栏",
    "不主动开口,除非卡住;一天最多一条;同一件事永不重提",
]


def agent_id_for(employee: str) -> str:
    return f"{EMPLOYEE_AGENT_ID_PREFIX}{EMPLOYEE_USERNAMES[employee]}"


def agent_spec(employee: str) -> dict:
    return {
        "agent_id": agent_id_for(employee),
        "name": display_name(employee),
        "responsibilities": _RESPONSIBILITIES[employee],
        "non_responsibilities": _NON_RESPONSIBILITIES,
        "input_schema": {"message": "string", "conversation_id": "string", "speaker_user_id": "string"},
        "output_schema": {"reply": "string", "suggestions": "list[string]"},
        "permissions": [],
        "risk_level": "medium",
        "version": "v1",
        "status": "foundation",
        "dependencies": [MODULE_KEY],
        "artifact_types": ["chat_message", "amz_suggestion"],
        "review_types": [],
        "error_codes": ["AGENT_LOGIN_FAILED", "AGENT_AI_UNAVAILABLE", "AGENT_REPLY_FAILED"],
        "healthcheck_config": {"type": "db_table", "target": "amz_stores"},
        "rollback_policy": {"strategy": "ledger", "reason": "每笔动作有台账,可按台账反向撤销"},
        "allowed_module_ids": [MODULE_KEY],
        "allowed_workflow_ids": [],
    }


def ensure_amz_agents(db: Session) -> list[str]:
    created: list[str] = []
    for employee in EMPLOYEES:
        agent_id = agent_id_for(employee)
        existing = db.scalar(select(AgentRegistry).where(AgentRegistry.agent_id == agent_id))
        if existing is not None:
            if existing.name != display_name(employee):
                existing.name = display_name(employee)
                db.add(existing)
            continue
        db.add(AgentRegistry(**agent_spec(employee)))
        created.append(agent_id)
    db.flush()
    return created


__all__ = ["agent_id_for", "agent_spec", "ensure_amz_agents"]
