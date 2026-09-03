"""白苏婉的脑子:提示词 + 一次 deepseek-v4-flash 调用。

第一版刻意**不做工具调用循环**:收到消息前先把内容链的只读快照全部取好,
连同她的记忆一起喂进去,一次调用出答案。理由有两条 ——
1. 路由器的 _PASSTHROUGH_PARAMS 不含 `tools`,标准 function calling 传不过去;
2. 聊天要低延迟,一次调用比多轮往返快得多,而第一版她能看的东西本来就固定。

用 flash 不用 pro,是因为护栏在代码里(动作白名单 + 权限位),不在模型脑子里。
模型判断错了也点不动任何东西,所以不需要为"聪明"付钱。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ....db.session import SessionLocal
from ....services.ai_provider_router import AIExecutionRouter
from ...k_series.product_knowledge.constants import (
    MODULE_KEY as K_MODULE_KEY,
    TARGET_ORGANIZATION_NAME,
)
from .constants import ai_timeout_seconds

_LOGGER = logging.getLogger("baisuwan.brain")

SYSTEM_PROMPT = """你是白苏婉,Barong Yekhna 控制台的数字员工,岗位是内容专员。

你管三件事:GEO 指南、SEO 文章、内链网。你在公司内部通讯里跟同事对话。

## 你现在能做什么

**你只能看,不能动。** 你没有任何按钮的权限——不能生成内容、不能发布、
不能审核、不能定选题、不能建内容簇。这是第一阶段的刻意安排,不是故障。

有人让你去做这些事时,照实说你现在还没有这个权限,并且说清楚「这件事在
控制台的哪里、他自己点哪个按钮能做」。不要假装做了,不要说"我已经安排了"。

## 你的口气

温柔是外壳,诊断是内核。这两件事不冲突,都要。

- **开头不堆压力**:「今天不急」「真要动的就一件」优先于「今天 5 件事」。
- **中段一个字都不能含糊**:不说「有问题」,要说是什么问题、为什么、
  是不是重复出现过、你的判断是什么。把问题说清楚本身就是减压,含糊才是加压。
- **收尾留余地**:「不看也行,我先放着」——把决定权还给对方,不催。
- **没事就闭嘴**:不刷屏、不问好、不汇报「一切正常」。

老板压力大,你的存在是为了让他不用记住流程——他问你,你答。不是让他多
一件要管的事。

## 铁律

- **不许编数字。** 快照里没有的数据就说「这个我看不到」。宁可承认盲区,
  也绝不编一个看起来合理的数字——你说的数字他会拿去做决定。
- 快照里标了 unavailable 的部分,如实说那块你取不到。
- 用中文,说人话,不要贴 JSON、不要贴报错堆栈、不要用「根据系统数据显示」
  这种腔调。
- 面向美国买家的内容一律英制单位(ft/in/oz/lb/°F),这是死规矩。

## 输出格式

只输出一个 JSON 对象,不要有别的字:

{
  "reply": "你要说的话(中文,直接就是发到聊天窗里的内容)",
  "memory": null 或 {"slug": "短横线小写英文", "description": "一句话", "body": "值得长期记住的内容"},
  "note": "这轮对话值得记进这个人的笔记的一句话,没有就空字符串",
  "mute_days": null 或 数字
}

**mute_days**:只在对方明确表示「这几天别主动找我 / 别烦我 / 让我静静」时才填
天数(没说几天就填 2)。填了之后你在这段时间里不会再主动开口 —— 他问你还是
会答。他没这个意思就填 null,**不要自作主张替他关掉**。

memory 只在真的出现「值得长期记住」的东西时才写,判断标准:
- 对方否决了什么、**为什么**(最值钱)
- 对方的偏好:用词、口气、忌讳
- 反复出现的批评(同一条第三次出现 = 该改写作规范了)
- 哪类选题试过打不动

**不要**记数据库里已经有的东西(产品、文章、监测数字)——那些你随时能查,
记下来只会过期骗人。绝大多数轮次 memory 都应该是 null。"""


def _snapshot_text(snapshot: dict[str, Any]) -> str:
    try:
        return json.dumps(snapshot, ensure_ascii=False, default=str)[:12000]
    except (TypeError, ValueError):
        return "{}"


def build_messages(
    *,
    user_message: str,
    speaker_name: str,
    snapshot: dict[str, Any],
    memory_digest: str,
    conversation_notes: str,
    recent_turns: list[dict[str, str]],
) -> list[dict[str, str]]:
    context_parts = [f"## 内容链当前快照(只读)\n{_snapshot_text(snapshot)}"]
    if memory_digest.strip():
        context_parts.append(f"## 你的长期记忆\n{memory_digest.strip()}")
    if conversation_notes.strip():
        context_parts.append(
            f"## 你跟 {speaker_name} 之前聊过的要点\n{conversation_notes.strip()}"
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "\n\n".join(context_parts)},
    ]
    messages.extend(recent_turns[-6:])
    messages.append({"role": "user", "content": user_message})
    return messages


PATROL_PROMPT = """你现在是**主动开口**,不是回答提问。对方没有问你任何事,
是你自己发现了一件事,决定打断他一次。

这跟被问话完全不同,规矩更严:

- **今天你只能说这一件事。** 说完就不再说了。别顺带提第二件——他得当场做
  三个决定,那正是压垮他的东西。
- **短。** 三到五句话。他在忙别的。
- **说清楚是什么事、要他做什么、在哪做。** 含糊等于白打断。
- **给他一条退路。** 「不想动我下次不再提」——这不是客套,是真的:同一件事
  你永远不会说第二遍。
- **不要开场白。** 不要「早上好」「打扰一下您现在方便吗」。直接说事。
- 不许编。下面给你的事实之外的数字一个都不许出现。

输出格式跟平时一样,只输出一个 JSON 对象:

{
  "reply": "你要说的话(中文)",
  "memory": null,
  "note": ""
}
"""


def build_patrol_messages(
    *,
    headline: str,
    facts: dict[str, Any],
    memory_digest: str,
) -> list[dict[str, str]]:
    """主动开口用的提示。

    刻意**不喂整份快照** —— 只给这一件事的事实。快照里的别的数字一旦出现在
    她眼前,她就会忍不住"顺带一提",而"顺带一提"正是主动消息退化成刷屏的
    第一步。看不见就带不出来。
    """
    fact_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
    context = f"## 你发现的这件事\n{headline}\n\n### 事实(只有这些,别的一律不许说)\n{fact_lines}"
    if memory_digest.strip():
        context += f"\n\n## 你的长期记忆\n{memory_digest.strip()[:2000]}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": PATROL_PROMPT},
        {"role": "system", "content": context},
        {"role": "user", "content": "（无人提问，这是你主动开口。把上面这一件事说给他听。）"},
    ]


def think(messages: list[dict[str, str]]) -> dict[str, Any]:
    """跑一次 flash。返回 {reply, memory, note}。"""
    from r_system_v2.ra.quota_ledger import (  # noqa: PLC0415
        PROVIDER_AGENT_CHAT,
        refund,
        try_consume,
    )

    # 台账先记账再花钱(死规矩:新出网付费调用当天接台账)。预算 0 = 不限量,
    # 所以这里只会记数不会拦人。ledger 自己 commit,用独立 session。
    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AGENT_CHAT)
        charged = True
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("台账记账失败(不拦调用): %s", exc)
    finally:
        ledger_db.close()

    provider_db = SessionLocal()
    try:
        timeout = ai_timeout_seconds()
        result = AIExecutionRouter(
            provider_db,
            timeout_seconds=timeout,
            total_budget_seconds=timeout * 1.5,
        ).execute(
            provider="deepseek",
            task_type="agent_chat",
            payload={"messages": messages},
            org=TARGET_ORGANIZATION_NAME,
            module_id=K_MODULE_KEY,
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AGENT_CHAT)
            except Exception:  # noqa: BLE001
                pass
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()

    return _parse_reply(result)


def _parse_reply(result: Any) -> dict[str, Any]:
    """路由器解析得出 JSON 就返回 dict,否则返回 {"content": 原文}。两种都要接住。"""
    payload: Any = result
    if isinstance(result, dict) and "content" in result and "reply" not in result:
        raw = result["content"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            # 模型没按格式输出。它写的仍然是给人看的话,直接当回复用,
            # 总比把一段有效回答丢掉、回一句"出错了"强。
            return {"reply": str(raw).strip(), "memory": None, "note": "", "mute_days": None}

    if not isinstance(payload, dict):
        return {"reply": str(payload).strip(), "memory": None, "note": "", "mute_days": None}

    reply = payload.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return {"reply": json.dumps(payload, ensure_ascii=False)[:1500], "memory": None, "note": "", "mute_days": None}

    memory = payload.get("memory")
    if not isinstance(memory, dict) or not str(memory.get("slug") or "").strip():
        memory = None

    note = payload.get("note")
    mute_days: int | None = None
    raw_mute = payload.get("mute_days")
    if isinstance(raw_mute, bool):
        raw_mute = None
    if isinstance(raw_mute, (int, float)) and raw_mute > 0:
        mute_days = int(raw_mute)

    return {
        "reply": reply.strip(),
        "memory": memory,
        "note": note.strip() if isinstance(note, str) else "",
        "mute_days": mute_days,
    }
