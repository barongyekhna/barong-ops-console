"""霓旌的脑子:一次 flash 调用,只做意图抽取,输出 JSON。

她不需要聪明,需要听话:找物料、算数、开单全在代码里。所以用最便宜的
deepseek-v4-flash,短超时,JSON 模式。
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
from .intents import Intent, parse_intent

_LOGGER = logging.getLogger("nijing.brain")

# 「json」这个词必须出现在提示词里,否则 DeepSeek 的 json_object 模式直接报错。
SYSTEM_PROMPT = """你是制造工厂的库管员助手「霓旌」。你的唯一任务:把用户这句话翻译成一个 JSON 对象,描述他想对库存做什么。你不执行任何操作,也不回答问题——后面的程序会做。

只输出一个 JSON 对象,字段:
- intent: 下列之一
  receipt      采购/自产入库(物料或成品数量增加)
  production   生产成品(按配件清单扣物料,成品增加)
  shipment     发货成品(成品减少)
  adjustment   盘点调整/账实不符修正(可正可负)
  query_stock  问库存/还剩多少/有多少
  query_documents 问单据/记录/流水/最近发了什么
  undo         撤销/冲销刚才的某张单
  create_item  新建物料或成品
  edit_bom     修改/设置配件清单(BOM)
  archive      归档/删除物料或成品
  chitchat     打招呼/闲聊/感谢
  multi        一句话里包含两个及以上不同的库存操作
  unsupported  听不懂或与库存无关
- item: 用户提到的物料/成品名称或编码,原样抄,没有则 null
- qty: 数量(数字,不要单位),没有则 null。调整时减少用负数
- unit: 用户说的单位(条/个/套/米/箱…),没有则 null
- note: 用户顺带说的备注(供应商/客户/批次),没有则 null
- reason: 盘点调整的原因,没有则 null
- doc_ref: 用户提到的单号(如 PR-000002),没有则 null

规则:
- 一句话里有多个操作(如"入库 100 条桌腿,再生产 10 套") → intent=multi
- "今天/刚才/一批"这类词不是备注
- 不要推测用户没说的数量或物料
- 只输出 json,不要解释"""

FEW_SHOTS: list[tuple[str, dict[str, Any]]] = [
    ("今天入库一千条桌腿", {"intent": "receipt", "item": "桌腿", "qty": 1000, "unit": "条", "note": None, "reason": None, "doc_ref": None}),
    ("生产500套折叠桌", {"intent": "production", "item": "折叠桌", "qty": 500, "unit": "套", "note": None, "reason": None, "doc_ref": None}),
    ("发货 20 套 TBL-001 给王老板", {"intent": "shipment", "item": "TBL-001", "qty": 20, "unit": "套", "note": "王老板", "reason": None, "doc_ref": None}),
    ("盘点发现纸箱少了 5 个", {"intent": "adjustment", "item": "纸箱", "qty": -5, "unit": "个", "note": None, "reason": "盘点少了", "doc_ref": None}),
    ("桌腿还剩多少", {"intent": "query_stock", "item": "桌腿", "qty": None, "unit": None, "note": None, "reason": None, "doc_ref": None}),
    ("入库100条桌腿,再生产10套桌子", {"intent": "multi", "item": None, "qty": None, "unit": None, "note": None, "reason": None, "doc_ref": None}),
    ("新建一个物料叫螺丝", {"intent": "create_item", "item": "螺丝", "qty": None, "unit": None, "note": None, "reason": None, "doc_ref": None}),
    ("刚才那笔入库弄错了,撤销", {"intent": "undo", "item": None, "qty": None, "unit": None, "note": None, "reason": None, "doc_ref": None}),
]


def build_messages(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user, answer in FEW_SHOTS:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": text})
    return messages


def extract_intent(text: str) -> Intent:
    """跑一次 flash。任何异常往上抛——调用方负责回「没接通,什么都没做」。"""
    from r_system_v2.ra.quota_ledger import (  # noqa: PLC0415
        PROVIDER_AGENT_CHAT_NIJING,
        refund,
        try_consume,
    )

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AGENT_CHAT_NIJING)
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
            payload={
                "messages": build_messages(text),
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            org=TARGET_ORGANIZATION_NAME,
            module_id=K_MODULE_KEY,
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AGENT_CHAT_NIJING)
            except Exception:  # noqa: BLE001
                pass
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()
    return parse_intent(result)
