"""苏青禾的脑子:早上把快照变成计划 + 审批卡;和老板聊天。

- 计划用「judge」档(Opus);她自己今天的 Claude 花费到了 SQH_DAILY_CLAUDE_USD 就改用「bulk」档。
  全局 $6.4 总闸在路由里,两道闸各管各的。
- 聊天用「fast」档(Haiku)。
- 钥匙用 K 模块的(用户拍板:数字员工共用 K 的钥匙),台账记在 ``suqinghe`` 名下。
- 模型输出一律过 ``persona.enforce_style``;解析不出 JSON 就当没出计划,绝不硬编。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from . import memory, persona
from .constants import MAX_CARDS_PER_DAY, USAGE_LABEL, daily_claude_budget_usd

logger = logging.getLogger(__name__)

AI_MODULE_ID = "k.product_knowledge"
PLAN_TIMEOUT_SECONDS = 180.0
CHAT_TIMEOUT_SECONDS = 60.0
CARD_KINDS = ("product_blocker", "plan", "ops_alert", "goal", "other")

PLAN_FORMAT = (
    "只输出一个 JSON 对象,不要别的文字:\n"
    '{"plan": "今天的计划,3-6 行,每行一件事,结论先行",\n'
    ' "cards": [{"dedupe_key_suffix": "英文短串,同一件事每天一样",'
    ' "kind": "product_blocker|ops_alert|goal|other",'
    ' "title": "≤30 字", "conclusion": "要老板定的事,一句话", "why": "为什么", "if_not": "不做会怎样",'
    ' "reversible": true, "confidence": "low|medium|high", "product_id": "快照里的 product_id 或省略"}]}\n'
    f"cards 最多 {MAX_CARDS_PER_DAY} 张,只放真正需要老板拍板的事;能自己推出来的判断不要做成卡。没有就给空数组。"
)

CHAT_FORMAT = (
    "只输出一个 JSON 对象:"
    '{"reply": "回老板的话", "dictation": "老板交代给你要记住的事,没有就空字符串", "mute_days": 0}\n'
    "mute_days:老板明确让你这几天别主动提醒时填天数(最多 30),否则 0。"
)


@dataclass
class PlanResult:
    plan: str
    cards: list[dict[str, Any]] = field(default_factory=list)
    role: str = "judge"
    degraded: bool = False


@dataclass
class ChatResult:
    reply: str
    dictation: str = ""
    mute_days: int = 0


def own_claude_spend_today(db: Session) -> float | None:
    from .office import _claude_spend_today  # noqa: PLC0415

    return _claude_spend_today(db)


def plan_role(db: Session) -> str:
    spent = own_claude_spend_today(db)
    if spent is None or spent >= daily_claude_budget_usd():
        return "bulk"
    return "judge"


def _execute(role: str, messages: list[dict[str, Any]], *, timeout: float) -> dict[str, Any]:
    from ....db.session import SessionLocal
    from ....services.ai_provider_router import AIExecutionRouter
    from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME

    provider_db = SessionLocal()
    try:
        return AIExecutionRouter(provider_db, timeout_seconds=timeout, total_budget_seconds=timeout + 30).execute(
            provider=role,
            task_type="agent_chat",
            payload={"messages": messages, "response_format": {"type": "json_object"}},
            org=TARGET_ORGANIZATION_NAME,
            module_id=AI_MODULE_ID,
            usage_label=USAGE_LABEL,
        )
    finally:
        provider_db.close()


def parse_json(result: Any) -> dict[str, Any] | None:
    """路由已经尽量解析过;没解析成功时结果是 {"content": "..."},这里再试一次(去代码块围栏)。"""
    if isinstance(result, dict) and "content" not in result:
        return result
    raw = result.get("content") if isinstance(result, dict) else result
    if not isinstance(raw, str):
        return None
    from ....services.ai_provider_router import _parse_json_text

    return _parse_json_text(raw)


def _clean_card(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    conclusion = str(raw.get("conclusion") or "").strip()
    suffix = str(raw.get("dedupe_key_suffix") or "").strip()
    if not title or not conclusion or not suffix:
        return None
    kind = str(raw.get("kind") or "other").strip()
    confidence = str(raw.get("confidence") or "medium").strip()
    card: dict[str, Any] = {
        "dedupe_key_suffix": suffix[:100],
        "kind": kind if kind in CARD_KINDS else "other",
        "title": persona.enforce_style(title, max_chars=60),
        "conclusion": persona.enforce_style(conclusion, max_chars=300),
        "why": persona.enforce_style(str(raw.get("why") or ""), max_chars=400) if raw.get("why") else "",
        "if_not": persona.enforce_style(str(raw.get("if_not") or ""), max_chars=300) if raw.get("if_not") else "",
        "reversible": bool(raw.get("reversible", True)),
        "confidence": confidence if confidence in {"low", "medium", "high"} else "medium",
    }
    product_id = str(raw.get("product_id") or "").strip()
    if product_id:
        card["product_id"] = product_id
    return card


def parse_plan(result: Any) -> tuple[str, list[dict[str, Any]]] | None:
    data = parse_json(result)
    if not isinstance(data, dict):
        return None
    plan_text = str(data.get("plan") or "").strip()
    if not plan_text:
        return None
    cards_raw = data.get("cards") if isinstance(data.get("cards"), list) else []
    cards = [c for c in (_clean_card(item) for item in cards_raw) if c is not None][:MAX_CARDS_PER_DAY]
    return persona.enforce_style(plan_text), cards


def _snapshot_for_prompt(snapshot: dict[str, Any]) -> str:
    """喂给模型的快照:先算好、消好歧义(家规:喂智能体的快照先消歧)。只留卡点产品,省 token。"""
    products = snapshot.get("products")
    slim_products: Any = products
    if isinstance(products, dict) and "items" in products:
        slim_products = {
            "total": products.get("total"),
            "by_stage": products.get("by_stage"),
            "woo_checked": products.get("woo_checked"),
            "stuck": [
                {k: item.get(k) for k in ("product_id", "sku", "name", "stage_label", "gate_blockers", "workflow_step")}
                for item in products.get("items", [])
                if item.get("stage") not in {"published"}
            ][:40],
        }
    slim = {
        "date": snapshot.get("date"),
        "headline": snapshot.get("headline"),
        "products": slim_products,
        "content": snapshot.get("content"),
        "stale_workers": (snapshot.get("workers") or {}).get("stale") if isinstance(snapshot.get("workers"), dict) else snapshot.get("workers"),
        "failing_keys": (snapshot.get("keys") or {}).get("failing") if isinstance(snapshot.get("keys"), dict) else snapshot.get("keys"),
        "ai": snapshot.get("ai"),
        "approvals": snapshot.get("approvals"),
        "goals": snapshot.get("goals"),
    }
    return json.dumps(slim, ensure_ascii=False, default=str)[:12000]


def _decisions_for_prompt(db: Session) -> str:
    rows = memory.recent(db, limit=15, kinds=("decision", "dictation"))
    return "\n".join(f"- {r.created_at:%m-%d} {r.body}" for r in rows if r.created_at) or "(还没有)"


def plan(db: Session, snapshot: dict[str, Any]) -> PlanResult | None:
    role = plan_role(db)
    messages = [
        {"role": "system", "content": persona.system_prompt("影子期:你只出方案和审批卡,不执行。") + "\n\n" + PLAN_FORMAT},
        {
            "role": "user",
            "content": (
                "这是今天早上的全局快照(JSON,数字已经算好,读不到的项标了「读不到」,别把读不到当 0):\n"
                f"{_snapshot_for_prompt(snapshot)}\n\n老板最近的决定和交代(别跟这些冲突;被驳过的同类建议不要再提):\n"
                f"{_decisions_for_prompt(db)}\n\n出今天的计划和需要老板拍板的卡。"
            ),
        },
    ]
    db.commit()  # 出网前放掉读事务
    try:
        result = _execute(role, messages, timeout=PLAN_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 —— 没接通就不出计划,下一轮再试
        logger.exception("plan call failed role=%s", role)
        return None
    parsed = parse_plan(result)
    if parsed is None:
        logger.warning("plan output unparseable role=%s", role)
        return None
    plan_text, cards = parsed
    degraded = bool(isinstance(result, dict) and result.get("_ai_degraded")) or role == "bulk"
    return PlanResult(plan=plan_text, cards=cards, role=role, degraded=degraded)


def parse_chat(result: Any) -> ChatResult | None:
    data = parse_json(result)
    if not isinstance(data, dict):
        raw = result.get("content") if isinstance(result, dict) else None
        if isinstance(raw, str) and raw.strip():
            return ChatResult(reply=persona.enforce_style(raw))
        return None
    reply = str(data.get("reply") or "").strip()
    if not reply:
        return None
    try:
        mute = max(0, min(30, int(data.get("mute_days") or 0)))
    except (TypeError, ValueError):
        mute = 0
    return ChatResult(reply=persona.enforce_style(reply), dictation=str(data.get("dictation") or "").strip()[:1000], mute_days=mute)


def chat(db: Session, text: str, *, context: str = "") -> ChatResult:
    related = memory.relevant(db, text, limit=8)
    recalled = "\n".join(f"- {r.created_at:%m-%d} [{r.kind}] {r.body}" for r in related if r.created_at) or "(没有相关记忆)"
    messages = [
        {"role": "system", "content": persona.system_prompt(context) + "\n\n" + CHAT_FORMAT},
        {"role": "user", "content": f"相关旧记忆:\n{recalled}\n\n老板刚才说:{text}"},
    ]
    db.commit()
    try:
        result = _execute("fast", messages, timeout=CHAT_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001
        logger.exception("chat call failed")
        return ChatResult(reply="老板,我这边脑子暂时没接通,你说的我先记下了,接通后马上处理。", dictation=text[:1000])
    return parse_chat(result) or ChatResult(reply="老板,这句我没理解透,能换个说法吗?")
