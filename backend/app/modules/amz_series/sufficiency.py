"""「够不够」:按下游用途逐项对清单,输出「缺什么」而不是分数;另抓矛盾、按品类常见预期追问。

三层,前两层在代码里、fail-closed,第三层是模型、只做加法:
1. **清单**(硬):写标题五点 / 出图 brief / 答差评 FAQ / 算损益表,各自要哪些字段——缺一项就是不够,员工不写不画;
2. **矛盾与品类预期**(硬,关键词):IPX7 vs「别入水」这种;泵类必问「加热吗 / 有没有电量显示 / 水压多大」;
3. **模型**(软):DeepSeek flash 再读一遍,补它看出来的矛盾和追问。模型挂了只记一条错,判定不变。

家规:人的命令高于程序——放行按钮在人手里;这里只负责把「缺什么」说清楚。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from .constants import MODULE_KEY

_LOGGER = logging.getLogger("amz.sufficiency")

USES: tuple[str, ...] = ("copy", "image", "faq", "pnl")
USE_LABELS = {"copy": "写标题五点", "image": "出图 brief", "faq": "答差评 FAQ", "pnl": "算损益表"}

FIELD_LABELS = {
    "is": "它是什么",
    "how_it_works": "怎么工作",
    "is_not": "它不是什么",
    "specs": "参数(至少三项)",
    "specs.dimensions_cm": "参数:尺寸(cm)",
    "specs.weight_g": "参数:重量(g)",
    "indicators": "指示(灯 / 屏 / 声音各代表什么)",
    "package": "包装内含",
    "audience": "人群与场景",
    "misreadings": "已知误解(差评来源)",
    "cost.factory_cny": "成本:出厂价(元)",
    "cost.freight_cny": "成本:头程(元)",
    "cost.price_usd": "售价(美元)",
    "competitor_asins": "对手 ASIN(至少一个)",
}

# 每种用途的硬清单。
CHECKLISTS: dict[str, tuple[str, ...]] = {
    "copy": ("is", "how_it_works", "is_not", "specs", "indicators", "package", "audience", "misreadings"),
    "image": ("is", "specs.dimensions_cm", "package", "indicators", "audience", "competitor_asins"),
    "faq": ("is", "is_not", "how_it_works", "indicators", "misreadings"),
    "pnl": ("cost.factory_cny", "cost.freight_cny", "cost.price_usd", "specs.weight_g", "specs.dimensions_cm"),
}

# 品类常见预期:文本里没提到这些关键词 → 追问。买家默认会以为有,不说清楚就是差评。
CATEGORY_EXPECTATIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "pump": (
        ("加热吗?买家最常见的误解,必须写在「它不是什么」里", r"加热|heat|warm|hot water|温水"),
        ("有没有电量 / 水温显示?显示的是什么单位", r"显示|屏|display|lcd|led|电量"),
        ("水压 / 流量多大,几档", r"水压|流量|压力|pressure|flow|档"),
        ("整机入水还是只泵头入水?怎么放才抽得上水", r"入水|浸|submers|泵头|整机"),
        ("一次充电能洗几分钟", r"续航|分钟|min|runtime|洗.{0,3}次"),
    ),
    "heater": (
        ("多少瓦,多少升水多久烧到多少度", r"瓦|w\b|watt|升|加热时间|分钟"),
        ("有没有干烧 / 过热保护,离水会不会烧坏", r"干烧|过热|保护|auto.?off|离水"),
        ("能用在什么容器,塑料桶行不行,水位要没过哪里", r"容器|塑料|桶|水位|没过|container|bucket"),
        ("线多长,插头是什么规格", r"线长|米|ft|插头|plug|cord"),
    ),
    "flash": (
        ("最高多少流明,几个档位", r"流明|lumen|档|mode"),
        ("太阳能充满要多久,USB 充满要多久", r"太阳能|solar|充满|小时|hour"),
        ("防水等级,能不能淋雨", r"防水|ip|waterproof|淋雨"),
        ("最亮档能亮多久", r"续航|小时|hour|runtime"),
    ),
    "nail": (
        ("适合哪些人:婴儿 / 老人 / 宠物,各自用哪个头", r"婴儿|宝宝|老人|宠物|baby|senior|pet"),
        ("有没有防夹伤的安全护罩", r"护罩|安全|guard|safe"),
        ("噪音大不大,会不会吓到孩子", r"噪音|分贝|db|静音|quiet|noise"),
        ("怎么充电,充一次用多久", r"充电|usb|电池|battery|续航"),
    ),
    "bundle": (
        ("套装含哪几件,每件的事实表都填了吗", r"含|包括|套装|bundle|kit"),
        ("套装价对比单买价省多少", r"省|优惠|单买|价格|price"),
    ),
}

# 硬矛盾:两边同时命中就是矛盾。
CONTRADICTIONS: tuple[tuple[str, str, str], ...] = (
    ("参数写了 IPX7/IPX8 或防水,但别处又说不能入水 / 不防水", r"ipx?[5-8]|防水|waterproof", r"不能入水|别入水|不可浸|不防水|不要浸|勿浸"),
    ("一边说能加热,一边说不加热", r"能加热|可加热|带加热|自带加热", r"不加热|不能加热|没有加热|无加热"),
    ("一边说静音,一边写了噪音大", r"静音|低噪|quiet", r"噪音大|很吵|loud"),
)


def _get(facts: dict[str, Any], dotted: str) -> Any:
    node: Any = facts
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _present(facts: dict[str, Any], field: str) -> bool:
    value = _get(facts, field)
    if field == "specs":
        return isinstance(value, dict) and len([k for k, v in value.items() if str(v or "").strip()]) >= 3
    if field == "competitor_asins":
        return isinstance(value, list) and any(str(v or "").strip() for v in value)
    if isinstance(value, (int, float)):
        return value > 0
    return bool(str(value or "").strip())


def _all_text(facts: dict[str, Any]) -> str:
    return json.dumps(facts, ensure_ascii=False).lower()


def judge_code(facts: dict[str, Any], *, product_line: str) -> dict[str, Any]:
    """代码层判定:每种用途缺什么、矛盾、追问。缺 = 不够 = 不放行。"""
    facts = facts or {}
    uses: dict[str, Any] = {}
    for use in USES:
        missing = [FIELD_LABELS.get(f, f) for f in CHECKLISTS[use] if not _present(facts, f)]
        uses[use] = {"label": USE_LABELS[use], "ok": not missing, "missing": missing}
    text = _all_text(facts)
    contradictions = [label for label, a, b in CONTRADICTIONS if re.search(a, text) and re.search(b, text)]
    questions = [q for q, pattern in CATEGORY_EXPECTATIONS.get(product_line, ()) if not re.search(pattern, text)]
    return {"uses": uses, "contradictions": contradictions, "questions": questions}


MODEL_PROMPT = """你是亚马逊运营团队的事实核对员。下面是一份产品事实表(中文,人手填)。你的任务不是打分,是找三样东西:
1. contradictions:表里前后矛盾、或者与物理常识矛盾的地方(每条一句,指出是哪两处);
2. questions:买家在这个品类里一定会问、而表里没说清的事(每条一句,问句);
3. missing_hints:分别对「写标题五点 / 出图 brief / 答差评 FAQ / 算损益表」四个用途,还缺哪些具体信息(每条一句)。
不要复述表里已经有的内容,不要客套。只输出一个 json 对象:
{"contradictions": [..], "questions": [..], "missing_hints": {"copy": [..], "image": [..], "faq": [..], "pnl": [..]}}"""


def _call_model(messages: list[dict[str, str]], *, org_id: str) -> Any:
    from ...db.session import SessionLocal  # noqa: PLC0415
    from ...services.ai_provider_router import AIExecutionRouter  # noqa: PLC0415
    from r_system_v2.ra.quota_ledger import PROVIDER_AMZ_SUFFICIENCY, refund, try_consume  # noqa: PLC0415

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AMZ_SUFFICIENCY)
        charged = True
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("台账记账失败(不拦调用): %s", exc)
    finally:
        ledger_db.close()
    provider_db = SessionLocal()
    try:
        return AIExecutionRouter(provider_db, timeout_seconds=60.0, total_budget_seconds=90.0).execute(
            provider="deepseek",
            task_type="agent_chat",
            payload={"messages": messages, "response_format": {"type": "json_object"}, "temperature": 0},
            org=org_id,
            module_id=MODULE_KEY,
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AMZ_SUFFICIENCY)
            except Exception:  # noqa: BLE001
                pass
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()


def _parse_model(result: Any) -> dict[str, Any]:
    payload: Any = result
    if isinstance(result, dict) and "content" in result and "contradictions" not in result:
        raw = result["content"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise ValueError("model output is not an object")
    hints = payload.get("missing_hints") if isinstance(payload.get("missing_hints"), dict) else {}
    return {
        "contradictions": [str(x) for x in (payload.get("contradictions") or []) if str(x).strip()][:10],
        "questions": [str(x) for x in (payload.get("questions") or []) if str(x).strip()][:10],
        "missing_hints": {use: [str(x) for x in (hints.get(use) or []) if str(x).strip()][:8] for use in USES},
    }


def judge_model(facts: dict[str, Any], *, product_line: str, title: str, org_id: str, call=None) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": MODEL_PROMPT},
        {"role": "user", "content": f"产品线:{product_line}\n名称:{title}\n事实表(json):\n{json.dumps(facts, ensure_ascii=False)}"},
    ]
    return _parse_model((call or _call_model)(messages, org_id=org_id))


def judge(facts: dict[str, Any], *, product_line: str, title: str, org_id: str, with_model: bool, call=None) -> dict[str, Any]:
    """合并结果。ready 只看代码层——模型只能多提问,不能把「缺」判成「够」。"""
    code = judge_code(facts, product_line=product_line)
    out: dict[str, Any] = {
        "judged_at": datetime.now(UTC).isoformat(),
        "code": code,
        "model": None,
        "model_error": None,
        "ready": {use: code["uses"][use]["ok"] for use in USES},
    }
    if with_model:
        try:
            out["model"] = judge_model(facts, product_line=product_line, title=title, org_id=org_id, call=call)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("事实表模型核对失败: %s", exc)
            out["model_error"] = str(exc)[:300]
    return out


def is_ready(sufficiency: dict[str, Any] | None, use: str) -> bool:
    return bool(((sufficiency or {}).get("ready") or {}).get(use))


__all__ = ["CATEGORY_EXPECTATIONS", "CHECKLISTS", "USES", "USE_LABELS", "is_ready", "judge", "judge_code", "judge_model"]
