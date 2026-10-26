"""规格的英文(第②步,10-26):建档写进 K 的规格行只有中文,K 给买家看的规格表一行都出不来。

K 的买家规格表(buyer_display.buyer_spec_rows)只收带英文的行:additional_specs 每行要有 label_en、value_en,
单位单独放在 unit 里它才会换算成英制(克 → 盎司、毫米 → 英寸);缺英文的整行跳过(10-26 预演日志里三个品全被跳过)。
写文案、做规格表都从这张表取数,所以这一步要在卖点之前做——改规格会让 K 作废已批的卖点和文案(invalidate_evidence_outputs)。

- label_en:按规格键写死(不用模型),和档案的规格键一一对应。
- value_en:数字照抄、单位单独放;尺寸「84×48×40」连单位写成一串(K 自己会整串换算);中文的值让 Haiku 翻(一个品一次)。
- 只对买家有用的才给英文:产地省份、外箱重量尺寸这种不给(K 就不展示)。
"""

from __future__ import annotations

import re
from typing import Any

from .dossier import SPEC_LABELS_ZH

LABELS_EN = {
    "material": "Material",
    "dimensions": "Item Dimensions",
    "weight": "Item Weight",
    "age_range": "Age Range",
    "color": "Color",
    "packaging": "Packaging",
    "voltage": "Voltage",
    "capacity": "Capacity",
    "power": "Power",
    "charging": "Charging",
    "runtime": "Runtime",
    "cycle_life": "Cycle Life",
    "certification": "Certifications",
    "battery_type": "Battery Type",
    "origin_country": "Country of Origin",
    "applicable_people": "Intended Users",
    "weight_pack": "Package Weight",
    "dimensions_pack": "Package Dimensions",
}
# 买家不需要看的:产地到省、外箱(批发装箱)
NOT_FOR_BUYERS = {"origin_region", "weight_carton", "dimensions_carton"}
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
_RANGE = re.compile(r"^\s*\d+(?:\.\d+)?\s*[-–~]\s*\d+(?:\.\d+)?\s*$")


def has_cjk(text: Any) -> bool:
    return bool(_CJK.search(str(text or "")))


def _spec_key(row: dict[str, Any]) -> str:
    key = str(row.get("key") or "")
    return key[4:] if key.startswith("sqh_") else key


def plan(structured_specs: Any, dossier_specs: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """每行要补的英文 → (补好的 additional_specs, 还要翻译的 {键: 中文值})。

    数字/范围:value_en = 数字,unit 单独放;尺寸和带单位的长串:整串进 value_en、不放 unit;中文值先占位等翻译。
    """
    rows = list((structured_specs or {}).get("additional_specs") or []) if isinstance(structured_specs, dict) else []
    out: list[dict[str, Any]] = []
    to_translate: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        key = _spec_key(row)
        if not str(row.get("key") or "").startswith("sqh_") or key in NOT_FOR_BUYERS or key not in LABELS_EN:
            out.append(row)
            continue
        source = dossier_specs.get(key) if isinstance(dossier_specs.get(key), dict) else {}
        value = source.get("value", row.get("value"))
        unit = str(source.get("unit") or "").strip()
        text = " ".join(str(value if value is not None else "").split())
        row["label_en"] = LABELS_EN[key]
        if not text:
            out.append(row)
            continue
        if has_cjk(text):
            to_translate[key] = text + (f" {unit}" if unit else "")
            row.pop("value_en", None)
        elif unit and (_NUMBER.match(text) or _RANGE.match(text)):
            row["value_en"], row["unit"] = text, unit
        else:
            row["value_en"] = f"{text} {unit}".strip() if unit and unit not in text else text
            row.pop("unit", None)
        out.append(row)
    return out, to_translate


TRANSLATE_ASK = (
    "把下面这些商品规格值翻成美国买家看的英文:简短、照原意,数字和单位照抄,不加原文没有的东西,不夸张。\n"
    'Reply JSON only: {"values": {"键": "English"}}'
)


def apply_translations(rows: list[dict[str, Any]], translated: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """把翻好的值填回去;没翻出来、翻完还带中文的,这行就不给英文(K 不展示它,也不编)。返回 (行, 没翻成的键)。"""
    missed: list[str] = []
    out: list[dict[str, Any]] = []
    for row in rows:
        key = _spec_key(row)
        if row.get("label_en") and "value_en" not in row and key in LABELS_EN and key not in NOT_FOR_BUYERS:
            english = " ".join(str(translated.get(key) or "").split())[:200]
            if english and not has_cjk(english):
                row = {**row, "value_en": english}
            else:
                missed.append(key)
                row = {k: v for k, v in row.items() if k != "label_en"}
        out.append(row)
    return out, missed


def done(structured_specs: Any) -> bool:
    """买家用得上的 sqh_ 行都有英文了。"""
    rows = (structured_specs or {}).get("additional_specs") if isinstance(structured_specs, dict) else None
    for row in rows or []:
        if not isinstance(row, dict) or not str(row.get("key") or "").startswith("sqh_"):
            continue
        key = _spec_key(row)
        if key in NOT_FOR_BUYERS or key not in LABELS_EN:
            continue
        if not row.get("label_en") or not row.get("value_en"):
            return False
    return True


__all__ = ["LABELS_EN", "NOT_FOR_BUYERS", "SPEC_LABELS_ZH", "TRANSLATE_ASK", "apply_translations", "done", "has_cjk", "plan"]
