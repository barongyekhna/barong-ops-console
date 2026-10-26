"""卖点素材:第②步的头一件事(10-26)。

K 写卖点只认证据:结构化规格、包装清单、K 属性表里来源可信的行、运营给的事实。档案只把规格
(电压、容量、重量……)写进了 K;详情图上印着的功能点(「无刷电机」「21+1 档扭力」「LED 照明」)
K 写卖点时看不到,写出来的卖点就只剩参数。

所以把详情图再读一遍,这回只抄卖点,分三种:
- feature:具体、能核对的功能或结构 → 写进 K 属性,写卖点时当证据用
- claim:主观但说得过去的好处(续航持久、小巧便携)→ 也写进 K:可以当卖点写,不能当参数写(用户 10-26)
- hype:夸张、绝对化、没法核实的(超强动力、秒杀同类、永不损坏、工业级)→ 不进 K,审核卡里列给老板,用哪条老板定
说的不是这件商品的(兼容机型、别款、对比图里的别家)、把握低的,都不要;同一句话在好几段图里出现只留一条。

读图走档案那一套(sourcing_1688.read_detail_images:同样的切段、同样的商品背景、台账预算闸),默认 Haiku,一份不到 1 美分。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from .sourcing_1688 import product_context, read_detail_images

CLAIM_KINDS = ("feature", "claim", "hype")
# K 的卖点证据只认可信来源(selling_points_service._feature_source_is_trusted:前缀 1688/supplier…,
# 而且整串里不能含 ai/model/generated 这些字样——「detail」里就藏着「ai」,别起那种名字)。
MATERIAL_SOURCE = "1688_image"
MATERIAL_GROUP = "卖点素材(1688 详情图)"
MATERIAL_BUDGET_USD = 0.10
_CONFIDENCE = {"high": 0.9, "medium": 0.7}

_CLAIM_RULES = (
    "你在读一张 1688 商品详情长图的其中一段,任务是抄录图上印着的、关于这件商品本身的**卖点说法**。\n\n"
    "规则:\n"
    "1. 只抄图上真实印着的说法,照原话写(不超过 30 个字);看不清、图上没有的不写;不推测、不翻译、不补全。\n"
    "2. 纯规格数值(电压、容量、重量、尺寸、功率,比如「12V」「2000mAh」)别人已经抄过了,这里不要;"
    "带功能的说法要(比如「21+1 档扭力调节」「三种灯光模式」「Type-C 快充」)。\n"
    "3. 每条标 kind:\n"
    "   feature = 具体、能核对的功能或结构(无刷电机、LED 照明灯、正反转、自锁夹头、Type-C 充电、可挂可立);\n"
    "   claim = 主观但说得过去的好处(续航持久、光线柔和、握感舒适、小巧便携、操作简单);\n"
    "   hype = 夸张、绝对化、比较、没法核实的(超强动力、秒杀同类、永不损坏、工业级、100% 防水、全网最低、行业第一)。\n"
    "4. 每条标 subject:this = 这件商品(或它的某个规格);other = 别的商品(兼容机型表、同店别的型号、对比图里的别家);"
    "unsure = 看不出。\n\n"
    "Transcribe ONLY selling claims literally printed in this image segment. Never guess or translate.\n"
    'Reply JSON only: {"facts": [{"text": "as printed", "kind": "feature|claim|hype", '
    '"subject": "this|other|unsure", "confidence": "high|medium|low"}]}. Empty list if nothing.'
)
# 纯规格值(「12V」「2000mAh」「84×48×40mm」)读图那一步已经抄过了,混进来就是重复
_SPEC_ONLY = re.compile(r"^[\d.\s×xX*/+~-]+(v|mah|ah|w|wh|g|kg|mm|cm|m|h|min|分钟|小时|度|°)?$", re.I)


def claims_prompt(capture: dict[str, Any]) -> str:
    return product_context(capture) + "\n\n" + _CLAIM_RULES


def clean_claim(fact: Any, *, image_index: int, segment_index: int) -> dict[str, Any] | None:
    if not isinstance(fact, dict):
        return None
    text = " ".join(str(fact.get("text") or "").split())
    if not text or len(text) > 40 or _SPEC_ONLY.match(text):
        return None
    kind = fact.get("kind")
    return {
        "text": text,
        # 说不清是哪种的按 hype 算:不进 K,让老板看(fail-closed)
        "kind": kind if kind in CLAIM_KINDS else "hype",
        "subject": fact.get("subject") if fact.get("subject") in {"this", "other", "unsure"} else "unsure",
        "confidence": fact.get("confidence") if fact.get("confidence") in {"high", "medium", "low"} else "low",
        "image_index": image_index,
        "segment_index": segment_index,
    }


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def summarize(read: dict[str, Any]) -> dict[str, Any]:
    """读出来的一条条说法 → 三个清单(各自去重,保留第一次出现的原话)+ 扔掉了多少。

    同一句话被读成两种 kind 时按更保守的算(hype > claim > feature)。
    """
    order = {"feature": 0, "claim": 1, "hype": 2}
    kept: dict[str, dict[str, Any]] = {}
    dropped = {"other_product": 0, "low_confidence": 0}
    for item in read.get("facts") or []:
        if item.get("subject") != "this":
            dropped["other_product"] += 1
            continue
        if item.get("confidence") == "low":
            dropped["low_confidence"] += 1
            continue
        key = _norm(item["text"])
        if not key:
            continue
        seen = kept.get(key)
        if seen is None:
            kept[key] = dict(item)
        elif order[item["kind"]] > order[seen["kind"]]:
            seen["kind"] = item["kind"]
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in CLAIM_KINDS}
    for item in kept.values():
        by_kind[item["kind"]].append(
            {"text": item["text"], "confidence": item["confidence"], "image_index": item["image_index"], "segment_index": item["segment_index"]}
        )
    return {
        "features": by_kind["feature"],
        "claims": by_kind["claim"],
        "hype": by_kind["hype"],
        "dropped": dropped,
        "segments_read": read.get("segments_read", 0),
        "images_failed": read.get("images_failed", 0),
        "stopped_reason": read.get("stopped_reason"),
        "cost_usd": read.get("cost_usd", 0),
    }


def attribute_items(material: dict[str, Any]) -> list[dict[str, Any]]:
    """要写进 K 属性表的行:feature 和 claim,hype 不写。键按顺序编号,K 的卖点证据按键引用。"""
    items: list[dict[str, Any]] = []
    for prefix, rows in (("sqh_feature", material.get("features") or []), ("sqh_claim", material.get("claims") or [])):
        for index, row in enumerate(rows, start=1):
            items.append(
                {
                    "attribute_key": f"{prefix}_{index:02d}",
                    "attribute_value_text": row["text"],
                    "attribute_group": MATERIAL_GROUP,
                    "source": MATERIAL_SOURCE,
                    "confidence": _CONFIDENCE.get(row.get("confidence"), 0.7),
                    "requires_review": False,
                }
            )
    return items


def collect(db: Any, capture: dict[str, Any], **reader: Any) -> dict[str, Any]:
    """读详情图 → 三个清单。``reader`` 原样转给 read_detail_images(测试打桩用)。"""
    read = read_detail_images(
        db,
        capture,
        budget_usd=MATERIAL_BUDGET_USD,
        prompt=claims_prompt(capture),
        clean=clean_claim,
        **reader,
    )
    material = summarize(read)
    material["read_at"] = datetime.now(UTC).isoformat()
    return material


__all__ = [
    "CLAIM_KINDS",
    "MATERIAL_GROUP",
    "MATERIAL_SOURCE",
    "attribute_items",
    "claims_prompt",
    "clean_claim",
    "collect",
    "summarize",
]
