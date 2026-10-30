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
from .constants import MAX_CARDS_PER_DAY, PLAN_CARD_KINDS, USAGE_LABEL, daily_claude_budget_usd

logger = logging.getLogger(__name__)

AI_MODULE_ID = "k.product_knowledge"
PLAN_TIMEOUT_SECONDS = 180.0
CHAT_TIMEOUT_SECONDS = 60.0
CARD_KINDS = PLAN_CARD_KINDS

PLAN_FORMAT = (
    "只输出一个 JSON 对象,不要别的文字:\n"
    '{"plan": "今天的计划,3-6 行,每行一件事,结论先行",\n'
    ' "cards": [{"issue": "快照里这件事的 issue 编号,原样抄",'
    ' "kind": "product_blocker|ops_alert|goal|other",'
    ' "title": "≤30 字", "conclusion": "要老板定的事,一句话", "why": "为什么", "if_not": "不做会怎样",'
    ' "reversible": true, "confidence": "low|medium|high"}]}\n'
    f"cards 最多 {MAX_CARDS_PER_DAY} 张,只放真正需要老板拍板的事;能自己推出来的判断不要做成卡。没有就给空数组。\n"
    "每张卡对应快照里一件带 issue 编号的事,一件事最多一张;already_raised 里的事已经发过卡了,不要再发。"
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


def _execute(role: str, messages: list[dict[str, Any]], *, timeout: float, usage_label: str = USAGE_LABEL) -> dict[str, Any]:
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
            usage_label=usage_label,
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


def issues_in(snapshot: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """快照里每件「可以发卡的事」一个跨天不变的编号,卡按它去重。返回 (今天有的事, 今天读得到的类别)。

    编号:product:<产品 id>:<阶段>、worker:<进程名>、key:<钥匙名>、goal:<目标 id>、content、approvals。
    读不到的类别不算「事情没了」(家规:读不到 ≠ 0),卡就不动。
    10-26:原来去重键是「日期 + AI 起的后缀」,换一天就是新卡——I 系列备用钥匙那件事 10-23、10-24、10-26 各发了一张。
    """
    live: dict[str, dict[str, Any]] = {}
    readable: set[str] = set()
    products = snapshot.get("products")
    if isinstance(products, dict) and "items" in products:
        readable.add("product")
        for item in products["items"]:
            # 她自己流水线在推的品不算「事」:卡由流水线按步骤发(价格卡、审核卡、卡住卡),早上别再重复发一张
            if item.get("stage") != "published" and not item.get("mine"):
                live[f"product:{item['product_id']}:{item['stage']}"] = {"product_id": item["product_id"]}
    workers = snapshot.get("workers")
    if isinstance(workers, dict) and "stale" in workers:
        readable.add("worker")
        live.update({f"worker:{name}": {} for name in workers.get("stale") or []})
    keys = snapshot.get("keys")
    if isinstance(keys, dict) and "failing" in keys:
        readable.add("key")
        live.update({f"key:{item['name']}": {} for item in keys.get("failing") or []})
    goals = snapshot.get("goals")
    if isinstance(goals, list):
        readable.add("goal")
        live.update({f"goal:{goal['id']}": {} for goal in goals})
    content = snapshot.get("content")
    if isinstance(content, dict) and "error" not in content:
        readable.add("content")
        if content.get("pending_review") or content.get("approved_unpublished"):
            live["content"] = {}
    approvals = snapshot.get("approvals")
    if isinstance(approvals, dict) and "pending" in approvals:
        readable.add("approvals")
        if approvals.get("pending"):
            live["approvals"] = {}
    ops = snapshot.get("ops")  # 运营看板(10-30)的规则层异常:ops:<code>;异常消失那天 settle_issues 自动作废卡
    if isinstance(ops, dict) and isinstance(ops.get("findings"), list):
        readable.add("ops")
        live.update({f"ops:{f['code']}": {} for f in ops["findings"] if isinstance(f, dict) and f.get("code") and f.get("severity") == "warn"})
    return live, readable


def _clean_card(raw: Any, live: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    conclusion = str(raw.get("conclusion") or "").strip()
    issue = str(raw.get("issue") or "").strip()
    if not title or not conclusion or issue not in live:
        return None
    kind = str(raw.get("kind") or "other").strip()
    confidence = str(raw.get("confidence") or "medium").strip()
    card: dict[str, Any] = {
        "issue": issue,
        "kind": kind if kind in CARD_KINDS else "other",
        "title": persona.enforce_style(title, max_chars=60),
        "conclusion": persona.enforce_style(conclusion, max_chars=300),
        "why": persona.enforce_style(str(raw.get("why") or ""), max_chars=400) if raw.get("why") else "",
        "if_not": persona.enforce_style(str(raw.get("if_not") or ""), max_chars=300) if raw.get("if_not") else "",
        "reversible": bool(raw.get("reversible", True)),
        "confidence": confidence if confidence in {"low", "medium", "high"} else "medium",
    }
    product_id = live[issue].get("product_id")
    if product_id:
        card["product_id"] = product_id
    return card


def parse_plan(result: Any, live: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]] | None:
    """``live`` = 今天快照里有的事(issues_in)。对不上任何一件事的卡丢掉,同一件事只留第一张。"""
    data = parse_json(result)
    if not isinstance(data, dict):
        return None
    plan_text = str(data.get("plan") or "").strip()
    if not plan_text:
        return None
    cards_raw = data.get("cards") if isinstance(data.get("cards"), list) else []
    cards: list[dict[str, Any]] = []
    for item in cards_raw:
        card = _clean_card(item, live)
        if card is not None and all(card["issue"] != c["issue"] for c in cards):
            cards.append(card)
    return persona.enforce_style(plan_text), cards[:MAX_CARDS_PER_DAY]


def _snapshot_for_prompt(snapshot: dict[str, Any], *, already_raised: set[str] | None = None) -> str:
    """喂给模型的快照:先算好、消好歧义(家规:喂智能体的快照先消歧)。只留卡点产品,省 token。

    能发卡的每件事都带上 issue 编号(issues_in),卡上原样抄回来;already_raised = 已经发过卡、还没了结的事。
    """
    live, _ = issues_in(snapshot)
    products = snapshot.get("products")
    slim_products: Any = products
    if isinstance(products, dict) and "items" in products:
        slim_products = {
            "total": products.get("total"),
            "by_stage": products.get("by_stage"),
            "woo_checked": products.get("woo_checked"),
            "stuck": [
                {
                    "issue": f"product:{item['product_id']}:{item['stage']}",
                    **{k: item.get(k) for k in ("sku", "name", "stage_label", "gate_blockers", "workflow_step")},
                }
                for item in products.get("items", [])
                if item.get("stage") not in {"published"} and not item.get("mine")
            ][:40],
            # 她自己在推的:计划里可以说进度,不用为它们发卡(流水线自己会发)
            "mine_in_progress": [
                {k: item.get(k) for k in ("sku", "name", "stage_label")}
                for item in products.get("items", [])
                if item.get("stage") not in {"published"} and item.get("mine")
            ][:40],
        }
    workers = snapshot.get("workers")
    keys = snapshot.get("keys")
    content = snapshot.get("content")
    approvals = snapshot.get("approvals")
    goals = snapshot.get("goals")
    slim = {
        "date": snapshot.get("date"),
        "headline": snapshot.get("headline"),
        "products": slim_products,
        "content": {"issue": "content", **content} if "content" in live else content,
        "stale_workers": [{"issue": f"worker:{name}", "name": name} for name in workers.get("stale") or []]
        if isinstance(workers, dict) and "stale" in workers
        else workers,
        "failing_keys": [{"issue": f"key:{item['name']}", **item} for item in keys.get("failing") or []]
        if isinstance(keys, dict) and "failing" in keys
        else keys,
        "ai": snapshot.get("ai"),
        "approvals": {"issue": "approvals", **approvals} if "approvals" in live else approvals,
        "goals": [{"issue": f"goal:{goal['id']}", **goal} for goal in goals] if isinstance(goals, list) else goals,
        "already_raised": sorted((already_raised or set()) & set(live)),
    }
    return json.dumps(slim, ensure_ascii=False, default=str)[:12000]


def _decisions_for_prompt(db: Session) -> str:
    rows = memory.recent(db, limit=15, kinds=("decision", "dictation"))
    return "\n".join(f"- {r.created_at:%m-%d} {r.body}" for r in rows if r.created_at) or "(还没有)"


def plan(db: Session, snapshot: dict[str, Any], *, already_raised: set[str] | None = None) -> PlanResult | None:
    role = plan_role(db)
    messages = [
        {"role": "system", "content": persona.system_prompt("影子期:你只出方案和审批卡,不执行。") + "\n\n" + PLAN_FORMAT},
        {
            "role": "user",
            "content": (
                "这是今天早上的全局快照(JSON,数字已经算好,读不到的项标了「读不到」,别把读不到当 0):\n"
                f"{_snapshot_for_prompt(snapshot, already_raised=already_raised)}\n\n老板最近的决定和交代(别跟这些冲突;被驳过的同类建议不要再提):\n"
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
    parsed = parse_plan(result, issues_in(snapshot)[0])
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
