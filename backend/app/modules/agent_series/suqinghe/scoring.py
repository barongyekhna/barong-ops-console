"""选品评分卡(10-27):每个候选按六个维度打分,每项有分、有依据、有出处;红线一票否决。纯函数,不连库不出网。

维度(满分 100):
- 红线(否决,不计分):标题/画像/类目命中红线词、带别人的品牌,或她初筛时标的 液体/气罐/定制/EPA·FDA/刀具/儿童/大件。锂电只扣分不否决(家规)。
- 账算得过 30:进价换美元 + 按估计重量算运费(光看列表没有真重量,卡上写明是估的)→ 保底价(30% 毛利)和美国同类 p25 比:
  保底 ≤ p25×0.8 满分,≥ p25 零分,中间线性。没拿到同类价给一半分并标「没拿到」。
- 有人买 20:亚马逊前三名月销之和(log 刻度,1000 件满 14 分)+ 谷歌购物卖家数(≥15 加 6,≥8 加 3)。
- 竞争 20:亚马逊首页评论壁垒(前三名最高评论数 ≤300 满 12,≥3000 零)、单品牌占比 >0.5 减半、新进入者比例 ≥0.3 加 4、≥0.15 加 2。快照无效给一半分并标「没拿到」。
- 和工厂的关系 15:她按工厂能力描述判(能自己组装/换外观/做套装 15,只能转卖 5),理由上卡。
- 合规物流 15:带电 -4、带磁 -3、带压 -4、易碎 -4、季节性 -3,不低于 0。

调用方(picks.py)负责取数据;这里只算分和写依据,好测。
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from . import pricing

MAX_TOTAL = 100
WEIGHT_CLASSES = ("light", "medium", "heavy")
WEIGHT_CLASS_LABEL = {"light": "轻小件", "medium": "中等", "heavy": "大件重件"}
VETO_FLAGS = {
    "liquid": "液体",
    "gas": "气罐/压缩气体",
    "custom": "定制/加印/定做",
    "epa_fda": "需要 EPA/FDA 的功效或入口/医疗品",
    "knife": "刀具/防身/武器",
    "child": "儿童用品(CPSC/CPSIA)",
    "brand": "带别人的品牌或型号",
    "oversize": "大件重件(运费吃掉毛利)",
}
DEDUCT_FLAGS = {"battery": 4, "magnet": 3, "pressure": 4, "fragile": 4, "seasonal": 3}
FLAG_LABEL = {**VETO_FLAGS, "battery": "带电/锂电池", "magnet": "带磁", "pressure": "带压", "fragile": "易碎", "seasonal": "季节性"}
# 标题/画像/类目里一眼就能定的红线词(中英文),配一句中文原因。锂电、配件、"灭蚊灯"这类设备不在这里——它们不是红线。
RED_TERMS: tuple[tuple[str, str], ...] = (
    # 只放一眼就能定、不会误伤的词:"spray""blade""药"这种泛词会把花洒、风扇叶、药箱一起误杀,交给她初筛标 flag
    ("knife", "刀具"), ("knives", "刀具"), ("machete", "刀具"), ("axe", "斧具"), ("hatchet", "斧具"),
    ("weapon", "武器"), ("firearm", "枪械"), ("ammunition", "弹药"), ("pepper spray", "防身喷雾"), ("stun gun", "防身电击"), ("crossbow", "武器"),
    ("刀具", "刀具"), ("砍刀", "刀具"), ("斧头", "斧具"), ("弓弩", "武器"), ("防身", "防身器材"),
    ("insecticide", "杀虫剂(EPA)"), ("pesticide", "杀虫剂(EPA)"), ("repellent spray", "驱虫喷雾(EPA)"), ("repellent mat", "驱蚊片(EPA)"),
    ("杀虫", "杀虫剂(EPA)"), ("驱蚊片", "驱蚊片(EPA)"), ("驱蚊液", "驱蚊液(EPA)"), ("蚊香", "蚊香(EPA)"), ("农药", "农药(EPA)"),
    ("aerosol", "气雾剂"), ("butane", "气罐"), ("propane", "气罐"), ("gas canister", "气罐"), ("gas cartridge", "气罐"),
    ("气罐", "气罐"), ("气瓶", "气罐"), ("丁烷", "气罐"),
    ("supplement", "入口/保健品(FDA)"), ("edible", "入口(FDA)"), ("medical", "医疗(FDA)"), ("medicine", "药品(FDA)"), ("first aid kit", "急救包(FDA 管的药品)"),
    ("药品", "药品(FDA)"), ("药片", "药品(FDA)"), ("食品", "食品(FDA)"), ("保健", "保健品(FDA)"),
    ("baby", "婴童用品(CPSC)"), ("infant", "婴童用品(CPSC)"), ("toddler", "婴童用品(CPSC)"), ("car seat", "儿童安全座椅"), ("婴儿", "婴童用品(CPSC)"), ("儿童", "儿童用品(CPSC)"),
    ("custom logo", "定制加印"), ("customized", "定制"), ("personalized", "定制"), ("定制", "定制"), ("来图", "定制"), ("加印", "定制加印"), ("刻字", "定制"), ("定做", "定制"),
    ("helmet", "头盔(强制认证)"), ("头盔", "头盔(强制认证)"), ("smoke detector", "烟感(强制认证)"), ("电动车", "电动车"), ("e-bike", "电动车"), ("scooter", "滑板车"),
)
BRAND_TERMS: tuple[str, ...] = (
    "coleman", "stanley", "thermacell", "yeti", "ozark trail", "jetboil", "msr", "snow peak", "naturehike", "black diamond", "petzl",
    "nalgene", "hydro flask", "igloo", "rtic", "lifestraw", "sawyer", "garmin", "gerber", "leatherman", "zippo", "lodge", "gsi outdoors",
    "sea to summit", "therm-a-rest", "big agnes", "kelty", "osprey", "decathlon", "quechua", "camelbak", "solo stove", "blackstone", "weber",
    "biolite", "goal zero", "anker", "jackery", "ecoflow", "bluetti", "dewalt", "milwaukee", "makita", "bosch", "ryobi", "stanley",
    "fire-maple", "fire maple", "bulin", "bisgear", "etekcity", "overmont", "odoland",
)


@dataclass(frozen=True)
class Dim:
    key: str
    label: str
    pts: int
    max: int
    why: str
    source: str
    missing: bool = False


def _haystack(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def red_lines(*, title: str, category_path: str | None, profile_en: str | None, flags: list[str] | tuple[str, ...], weight_class: str | None) -> list[str]:
    """一票否决的原因清单(空 = 过)。"""
    text = _haystack(title, category_path, profile_en)
    reasons: list[str] = []
    for term, why in RED_TERMS:
        if _term_in(term, text):
            reasons.append(f"{why}(命中「{term}」)")
            break
    for brand in BRAND_TERMS:
        if _term_in(brand, text):
            reasons.append(f"带别人的品牌「{brand}」")
            break
    for flag in flags:
        if flag in VETO_FLAGS:
            reasons.append(f"她判:{VETO_FLAGS[flag]}")
    if weight_class == "heavy" and "oversize" not in flags:
        reasons.append("她判:大件重件,运费吃掉毛利")
    return list(dict.fromkeys(reasons))


def _term_in(term: str, text: str) -> bool:
    if re.search(r"[一-鿿]", term):
        return term in text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def economics(*, price_cny: float | None, weight_class: str | None, p25: float | None, a: pricing.Assumptions, kg_by_class: dict[str, float]) -> Dim:
    if price_cny is None or price_cny <= 0:
        return Dim("economics", "账算得过", 0, 30, "没有进价,算不了", "1688 列表", missing=True)
    kg = kg_by_class.get(weight_class or "", kg_by_class.get("medium", 1.0))
    goods, ship = pricing.costs(float(price_cny), kg, a)
    floor = pricing.floor_price(goods, ship, a)
    basis = f"进价 ¥{price_cny:g}≈${goods:.2f},按{WEIGHT_CLASS_LABEL.get(weight_class or '', '估计')} {kg:g} 公斤估运费 ${ship:.2f},保底价(30% 毛利)${floor:.2f}"
    if not p25 or p25 <= 0:
        return Dim("economics", "账算得过", 15, 30, basis + ";美国同类价没拿到,先给一半分", "进价+估算运费;谷歌购物没结果", missing=True)
    ratio = floor / p25
    if ratio <= 0.8:
        pts = 30
    elif ratio >= 1.0:
        pts = 0
    else:
        pts = round(30 * (1.0 - ratio) / 0.2)
    return Dim("economics", "账算得过", pts, 30, basis + f";美国同类 p25 ${p25:.2f},保底价是它的 {ratio:.0%}", "进价+估算运费 vs 谷歌购物 p25")


def demand(*, keepa: list[dict[str, Any]], shopping_n: int | None, keepa_error: str | None = None) -> Dim:
    sales = [int(k["monthly_sales"]) for k in keepa if isinstance(k, dict) and isinstance(k.get("monthly_sales"), (int, float)) and not isinstance(k.get("monthly_sales"), bool) and k["monthly_sales"] > 0]
    n = int(shopping_n or 0)
    pts = 0
    parts: list[str] = []
    missing = False
    if sales:
        total = sum(sales)
        sales_pts = min(14, round(14 * math.log10(total + 1) / 3))
        pts += sales_pts
        parts.append(f"亚马逊前 {len(sales)} 名月销合计约 {total} 件({sales_pts}/14)")
    else:
        missing = True
        parts.append("亚马逊月销没拿到" + (f"({keepa_error})" if keepa_error else ""))
    if n >= 15:
        pts += 6
        parts.append(f"谷歌购物 {n} 个卖家在卖(+6)")
    elif n >= 8:
        pts += 3
        parts.append(f"谷歌购物 {n} 个卖家在卖(+3)")
    elif n > 0:
        parts.append(f"谷歌购物只有 {n} 个卖家(+0)")
    else:
        parts.append("谷歌购物没查到卖家")
    return Dim("demand", "有人买", min(20, pts), 20, ";".join(parts), "Keepa 月销 + 谷歌购物", missing=missing)


def competition(*, snapshot: dict[str, Any] | None) -> Dim:
    snap = snapshot if isinstance(snapshot, dict) else {}
    if not snap or snap.get("error") or snap.get("valid") is False:
        why = "亚马逊首页快照没拿到" + (f"({snap.get('error')})" if snap.get("error") else "(结果和关键词对不上)" if snap else "")
        return Dim("competition", "竞争", 10, 20, why + ",先给一半分", "Rainforest 亚马逊搜索", missing=True)
    wall = snap.get("review_wall_max")
    parts: list[str] = []
    if isinstance(wall, (int, float)) and not isinstance(wall, bool):
        if wall <= 300:
            base = 12
        elif wall >= 3000:
            base = 0
        else:
            base = round(12 * (math.log10(3000) - math.log10(max(wall, 1))) / (math.log10(3000) - math.log10(300)))
        parts.append(f"前三名最高评论 {int(wall)} 条({base}/12)")
    else:
        base = 6
        parts.append("评论数没拿到(6/12)")
    share = snap.get("single_brand_share")
    if isinstance(share, (int, float)) and not isinstance(share, bool) and share > 0.5:
        base = base // 2
        parts.append(f"单一品牌占首页 {share:.0%}({snap.get('dominant_brand') or '?'}),减半")
    bonus = 0
    ratio = snap.get("new_entrant_ratio_est")
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
        bonus = 4 if ratio >= 0.3 else 2 if ratio >= 0.15 else 0
        parts.append(f"新进入者(评论少的)占 {ratio:.0%}(+{bonus})")
    return Dim("competition", "竞争", min(20, base + bonus), 20, ";".join(parts), "Rainforest 亚马逊搜索首页")


def factory_fit(*, pts: Any, why: str) -> Dim:
    try:
        value = int(round(float(pts)))
    except (TypeError, ValueError):
        value = 5
    value = max(0, min(15, value))
    return Dim("factory", "和工厂的关系", value, 15, (why or "").strip()[:200] or "她没说理由", "她按工厂能力判")


def logistics(*, flags: list[str] | tuple[str, ...]) -> Dim:
    pts = 15
    hits: list[str] = []
    for flag in flags:
        cut = DEDUCT_FLAGS.get(flag)
        if cut:
            pts -= cut
            hits.append(f"{FLAG_LABEL.get(flag, flag)} -{cut}")
    pts = max(0, pts)
    return Dim("logistics", "合规物流", pts, 15, ";".join(hits) if hits else "没有带电/带磁/带压/易碎/季节性的问题", "她初筛时标的")


def scorecard(
    *,
    title: str,
    category_path: str | None,
    profile_en: str | None,
    price_cny: float | None,
    weight_class: str | None,
    flags: list[str] | tuple[str, ...],
    factory_pts: Any,
    factory_why: str,
    shopping: dict[str, Any] | None,
    amazon: dict[str, Any] | None,
    keepa: list[dict[str, Any]] | None,
    keepa_error: str | None,
    a: pricing.Assumptions,
    kg_by_class: dict[str, float],
) -> dict[str, Any]:
    """整张评分卡。vetoed 非空就不该发卡。"""
    flags = tuple(str(f) for f in flags)
    vetoed = red_lines(title=title, category_path=category_path, profile_en=profile_en, flags=flags, weight_class=weight_class)
    shop = shopping if isinstance(shopping, dict) else {}
    dims = [
        economics(price_cny=price_cny, weight_class=weight_class, p25=_num(shop.get("p25")), a=a, kg_by_class=kg_by_class),
        demand(keepa=list(keepa or []), shopping_n=int(shop.get("n") or 0), keepa_error=keepa_error),
        competition(snapshot=amazon),
        factory_fit(pts=factory_pts, why=factory_why),
        logistics(flags=flags),
    ]
    total = sum(d.pts for d in dims)
    return {
        "total": total,
        "max": MAX_TOTAL,
        "dims": [asdict(d) for d in dims],
        "missing": [d.label for d in dims if d.missing],
        "vetoed": vetoed,
        "weight_class": weight_class,
        "flags": list(flags),
    }


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def confidence(card: dict[str, Any]) -> str:
    total, missing = int(card.get("total") or 0), len(card.get("missing") or [])
    if total >= 75 and missing == 0:
        return "high"
    if total < 60 or missing >= 2:
        return "low"
    return "medium"


def lines(card: dict[str, Any]) -> list[str]:
    """卡上「为什么」里的六行:维度 分/满分:依据。"""
    out = [f"{d['label']} {d['pts']}/{d['max']}:{d['why']}" for d in card.get("dims") or []]
    out.append(f"合计 {card.get('total')}/{card.get('max')}" + (f"(没拿到:{'、'.join(card['missing'])})" if card.get("missing") else ""))
    return out


__all__ = ["BRAND_TERMS", "DEDUCT_FLAGS", "Dim", "FLAG_LABEL", "RED_TERMS", "VETO_FLAGS", "WEIGHT_CLASSES", "competition", "confidence", "demand", "economics", "factory_fit", "lines", "logistics", "red_lines", "scorecard"]
