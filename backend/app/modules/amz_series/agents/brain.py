"""四名员工的脑子:人物档案(persona)进 system,一次 deepseek-flash,出口再过 ``enforce_style``。

三道门,缺一不可,也绕不开:
1. ``system_prompt(employee)`` 永远是第一条 system 消息——名字、性别、口吻、禁语、硬边界全在里面;
2. 模型只拿到「这名员工、这位说话人能看的店铺」的快照;快照里没有的数字不许说(提示词 + 人设硬规矩);
3. ``think()`` 返回之前必过 ``enforce_style``——表情配额、禁语、称呼、长度由代码兜底,模型演不像也会被修成像。

用 flash 不用 pro:护栏在代码里(影子期没有任何写端点),模型判断错了也点不动任何东西。
DeepSeek 一律 thinking disabled(路由器统一加,见 model_config.deepseek_thinking_extras)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ....db.session import SessionLocal
from ....services.ai_provider_router import AIExecutionRouter
from ..constants import MODULE_KEY
from ..persona import enforce_style, persona_for, system_prompt
from ..prompt_skills import skills_for
from .config import ai_timeout_seconds

_LOGGER = logging.getLogger("amz-agents.brain")

# 「json」这个词必须出现在提示词里(DeepSeek 的要求);格式与白苏婉一致,便于复用解析。
CHAT_FORMAT_PROMPT = """## 你现在能做什么

影子期:你只能看、只能建议,**不能改亚马逊上的任何东西**,也没有任何按钮权限。有人让你去改,
照实说你现在还不能动手,并说清楚「这件事在控制台的哪里、他自己点哪里」:
控制台 → 亚马逊 → 总览 → 点你的员工卡 → 浮窗里「放行 / 驳回 / 稍后」。不要假装做了。

## 你的记忆是怎么来的
快照里「我的工作日志」是数据库里的硬记录:你提过的建议、老板放行 / 驳回的决定和原因、老板口述让你记的事。
问到「哪个店 / 哪个 ASIN 最近做了什么、为什么」,就照日志答,带日期;日志里没有的就说「我这里没有记录」,不要猜。
老板告诉你一件你业务范围内已经发生的事(比如「01us 的 B0XXXXXXXX 标题上周改成了…,因为…」),
或者明确说「记下来」,就把它填进 log 字段,并在回复里说「记下了」。不是你业务范围的事不记,转给对的人。

## 铁律
- 不许编数字。快照里没有的数据就说「这个我看不到」;引用数字要带店铺和数据截至日。
- 不贴 JSON、不贴报错、不用「根据系统数据显示」这种腔调,说人话。
- 别人的活(文案 / 图片 / 竞品 / 广告)转给对的人,并说明转给了谁。

## 输出格式
只输出一个 json 对象,不要有别的字:
{
  "reply": "你要说的话(中文,直接就是发到聊天窗里的内容)",
  "note": "这轮对话值得记进这个人的笔记的一句话,没有就空字符串",
  "mute_days": null 或 数字,
  "log": null 或 {"store_code": "01us 这样的店铺码,不确定就 null", "subject": "ASIN / SKU / 关键词 / 活动名", "title": "发生了什么(一句)", "why": "为什么(一句,没说就空)"}
}
mute_days 只在对方明确说「这几天别主动找我 / 别烦我」时才填(没说几天就填 2);他没这个意思就填 null。
log 只在对方陈述了一件你业务范围内**已经发生**的事、或明确要你记住时才填;绝大多数轮次是 null。"""

SPEAK_PROMPT = """你现在是**主动开口**,不是回答提问。对方没有问你,是你自己发现了一件要他拍板的事。

规矩比被问话更严:
- 今天你只能说这一件事。别顺带提第二件。
- 短,三到五句。他在忙别的。
- 说清楚是什么事、你建议怎么做、他去哪里点(控制台 → 亚马逊 → 总览 → 你的员工卡 → 浮窗)。
- 给他退路:不想动可以「稍后」,你不会再提第二遍。
- 不要开场白(不要「早上好」「打扰了」),直接说事;但要保持你自己的性格和习惯。
- 不许编。下面给你的事实之外的数字一个都不许出现。

只输出一个 json 对象:{"reply": "你要说的话(中文)", "note": "", "mute_days": null}"""


def _compact(value: Any, limit: int = 20000) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except (TypeError, ValueError):
        return "{}"


def build_chat_messages(
    employee: str,
    *,
    user_message: str,
    speaker_name: str,
    snapshot: dict[str, Any],
    memory_digest: str = "",
    conversation_notes: str = "",
    recent_turns: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    context_parts = [f"## 你手上的快照(只读;只有这些,别的一律说看不到)\n{_compact(snapshot)}"]
    if memory_digest.strip():
        context_parts.append(f"## 你的长期记忆\n{memory_digest.strip()[:3000]}")
    if conversation_notes.strip():
        context_parts.append(f"## 你跟 {speaker_name} 之前聊过的要点\n{conversation_notes.strip()}")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt(employee)},
        {"role": "system", "content": skills_for(employee)},
        {"role": "system", "content": CHAT_FORMAT_PROMPT},
        {"role": "system", "content": "\n\n".join(context_parts)},
    ]
    messages.extend((recent_turns or [])[-6:])
    messages.append({"role": "user", "content": user_message})
    return messages


def build_speak_messages(
    employee: str,
    *,
    suggestion: dict[str, Any],
    memory_digest: str = "",
) -> list[dict[str, str]]:
    """主动开口:刻意只喂这一条建议,不喂整份快照——看不见别的就带不出「顺带一提」。"""
    facts = {
        "店铺": suggestion.get("store_code"),
        "事情": suggestion.get("title"),
        "为什么": suggestion.get("why"),
        "预计": suggestion.get("prediction"),
        "严重度": suggestion.get("severity"),
        "数据截至": suggestion.get("as_of"),
        "证据": suggestion.get("evidence"),
    }
    context = f"## 你发现的这一件事\n{_compact(facts, 4000)}"
    if memory_digest.strip():
        context += f"\n\n## 你的长期记忆\n{memory_digest.strip()[:1500]}"
    return [
        {"role": "system", "content": system_prompt(employee)},
        {"role": "system", "content": skills_for(employee)},
        {"role": "system", "content": SPEAK_PROMPT},
        {"role": "system", "content": context},
        {"role": "user", "content": "(无人提问,这是你主动开口。把上面这一件事说给他听。)"},
    ]


def _call_model(messages: list[dict[str, str]], *, org_id: str) -> Any:
    """真正出网的那一下。台账先记账再花钱(死规矩);ledger 自己 commit,用独立 session。"""
    from r_system_v2.ra.quota_ledger import (  # noqa: PLC0415
        PROVIDER_AGENT_CHAT_AMZ,
        refund,
        try_consume,
    )

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AGENT_CHAT_AMZ)
        charged = True
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("台账记账失败(不拦调用): %s", exc)
    finally:
        ledger_db.close()

    provider_db = SessionLocal()
    try:
        timeout = ai_timeout_seconds()
        return AIExecutionRouter(
            provider_db,
            timeout_seconds=timeout,
            total_budget_seconds=timeout * 1.5,
        ).execute(
            provider="deepseek",
            task_type="agent_chat",
            payload={"messages": messages},
            org=org_id,
            module_id=MODULE_KEY,
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AGENT_CHAT_AMZ)
            except Exception:  # noqa: BLE001
                pass
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()


def parse_reply(result: Any) -> dict[str, Any]:
    """路由器解析出 JSON 就用 dict;模型没按格式写就把原文当回复——一段有效的话比一句「出错了」强。"""
    payload: Any = result
    if isinstance(result, dict) and "content" in result and "reply" not in result:
        raw = result["content"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return {"reply": str(raw).strip(), "note": "", "mute_days": None, "log": None}
    if not isinstance(payload, dict):
        return {"reply": str(payload).strip(), "note": "", "mute_days": None, "log": None}
    reply = payload.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return {"reply": json.dumps(payload, ensure_ascii=False)[:1500], "note": "", "mute_days": None, "log": None}
    note = payload.get("note")
    raw_mute = payload.get("mute_days")
    mute_days = int(raw_mute) if isinstance(raw_mute, (int, float)) and not isinstance(raw_mute, bool) and raw_mute > 0 else None
    log = payload.get("log")
    if not isinstance(log, dict) or not str(log.get("title") or "").strip():
        log = None
    else:
        log = {
            "store_code": (str(log.get("store_code") or "").strip().lower() or None),
            "subject": str(log.get("subject") or "").strip()[:255],
            "title": str(log.get("title") or "").strip()[:512],
            "why": str(log.get("why") or "").strip(),
        }
    return {"reply": reply.strip(), "note": note.strip() if isinstance(note, str) else "", "mute_days": mute_days, "log": log}


def think(employee: str, messages: list[dict[str, str]], *, org_id: str, call=None) -> dict[str, Any]:
    """跑一次 flash,返回 {reply, note, mute_days}。reply 已过人设硬门——调用方拿到的就是能发的。"""
    persona_for(employee)  # 员工代号不对就在这里炸,别带着错身份出网
    result = (call or _call_model)(messages, org_id=org_id)
    reply = parse_reply(result)
    reply["reply"] = enforce_style(employee, reply["reply"])
    return reply


__all__ = [
    "CHAT_FORMAT_PROMPT",
    "SPEAK_PROMPT",
    "build_chat_messages",
    "build_speak_messages",
    "parse_reply",
    "think",
]
