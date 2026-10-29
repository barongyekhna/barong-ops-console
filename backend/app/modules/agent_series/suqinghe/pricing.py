"""第③步:建议售价和运费模板——价格卡(10-26)。

价格卡排在文案前面:K 写文案按变体写(包装数量),颜色变体的主图要变体参考图——变体和售价得先定。
她算、老板批;批了她才去 K 里改成多变体、填价、选运费模板(pipeline 的 apply_price)。

每个规格的到手成本(美元):
  货 = 进价 ÷ 汇率
  运 =(计费重 × 每公斤运费 + 每件挂号费)÷ 汇率;计费重 = 实重和体积重(长×宽×高÷6000)取大
  收款手续费 = 3.49% × (售价 + 买家运费) + $0.49(PayPal)
买家付的运费 $2.99/单(满 $100 免)——按单件订单算,当收入。
毛利 = 售价 + 买家运费 − 货 − 运 − 手续费;毛利率 = 毛利 ÷ 售价。
保底价 = 毛利率刚好到 SQH_MIN_MARGIN(默认 30%)的价,往上取到 .99。

汇率、运费单价是假设(环境变量可改,卡上写明);老板给了真实物流报价就改环境变量。
竞品价:谷歌购物按主关键词搜一次(Serper /shopping,先过额度台账)。
定价:模型在保底价之上、参照竞品价位给每个规格定价,指出不对劲的规格;代码再核一遍,低于保底价的抬到保底价。
"""

from __future__ import annotations

import math
import os
import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

SERPER_SHOPPING_URL = "https://google.serper.dev/shopping"
SHOPPING_LOCALE = {"gl": "us", "hl": "en"}
AXES = ("color", "size", "function", "quantity")
DEFAULT_SHIPPING_CLASS = "cn-direct-standard"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Assumptions:
    usd_cny: float
    ship_cny_per_kg: float
    ship_cny_per_piece: float
    fee_rate: float
    fee_fixed_usd: float
    buyer_shipping_usd: float
    min_margin: float
    volumetric_divisor: float = 6000.0


def assumptions() -> Assumptions:
    """汇率和物流价都是估的:带电专线一般 ¥80–100/公斤 + ¥15–25/件(10-26 按 90 + 20 起步,老板给真实报价就改)。"""
    return Assumptions(
        usd_cny=_env_float("SQH_USD_CNY", 7.2),
        ship_cny_per_kg=_env_float("SQH_SHIP_CNY_PER_KG", 90.0),
        ship_cny_per_piece=_env_float("SQH_SHIP_CNY_PER_PIECE", 20.0),
        fee_rate=_env_float("SQH_PAYMENT_FEE_RATE", 0.0349),
        fee_fixed_usd=_env_float("SQH_PAYMENT_FEE_FIXED_USD", 0.49),
        buyer_shipping_usd=_env_float("SQH_BUYER_SHIPPING_USD", 2.99),
        min_margin=_env_float("SQH_MIN_MARGIN", 0.30),
    )


def charm(price: float) -> float:
    """不低于 price 的最小 x.99:14.20 → 14.99,14.99 → 14.99,15.00 → 15.99。"""
    base = math.floor(price) + 0.99
    return round(base if price <= base + 1e-9 else base + 1, 2)


def chargeable_kg(weight_g: float | None, dims_cm: list[float] | None, divisor: float) -> float | None:
    actual = (weight_g or 0) / 1000 if weight_g else None
    volumetric = None
    if dims_cm and len(dims_cm) == 3 and all(isinstance(d, (int, float)) and d > 0 for d in dims_cm):
        volumetric = dims_cm[0] * dims_cm[1] * dims_cm[2] / divisor
    values = [v for v in (actual, volumetric) if v]
    return max(values) if values else None


def costs(cost_cny: float, kg: float, a: Assumptions) -> tuple[float, float]:
    """(货, 运),美元。"""
    goods = cost_cny / a.usd_cny
    ship = (kg * a.ship_cny_per_kg + a.ship_cny_per_piece) / a.usd_cny
    return goods, ship


def profit_at(price: float, goods: float, ship: float, a: Assumptions) -> tuple[float, float]:
    """(毛利, 毛利率)——单件订单。"""
    revenue = price + a.buyer_shipping_usd
    fee = revenue * a.fee_rate + a.fee_fixed_usd
    profit = revenue - goods - ship - fee
    return profit, (profit / price if price > 0 else 0.0)


def floor_price(goods: float, ship: float, a: Assumptions) -> float:
    """毛利率刚好到 min_margin 的售价(解 profit_at 的线性方程),再取到 .99。"""
    raw = (goods + ship + a.fee_fixed_usd - a.buyer_shipping_usd * (1 - a.fee_rate)) / (1 - a.fee_rate - a.min_margin)
    return charm(max(raw, 0.99))


@dataclass
class Line:
    key: str
    name_zh: str
    name_en: str
    cost_cny: float | None
    weight_g: float | None
    dims_cm: list[float] | None
    weight_note: str = ""
    kg: float | None = None
    goods: float | None = None
    ship: float | None = None
    floor: float | None = None
    # 下面是定价之后填的
    include: bool = True
    price: float | None = None
    profit: float | None = None
    margin: float | None = None
    label_en: str = ""
    axis: str = "function"
    note: str = ""
    image_url: str | None = None
    variant_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("goods", "ship", "floor", "price", "profit"):
            if isinstance(out[key], float):
                out[key] = round(out[key], 2)
        if isinstance(out["margin"], float):
            out["margin"] = round(out["margin"], 3)
        if isinstance(out["kg"], float):
            out["kg"] = round(out["kg"], 3)
        return out


SELLER_SAID = "seller_said"  # 规格的重量尺寸是旺旺里卖家口头说的(B 期,10-29)
SELLER_SAID_NOTE = "卖家口头说的重量尺寸,没有凭证"


def cost_lines(variants: list[dict[str, Any]], a: Assumptions) -> list[Line]:
    """档案里的每个规格 → 到手成本和保底价。缺重量的按同一商品里最重的规格算,并写明。"""
    weights_all = [float(v["weight_g"]) for v in variants if isinstance(v.get("weight_g"), (int, float)) and v["weight_g"] > 0]
    # 「每个规格同一个重量=疑似乱填」只看详情页填的;卖家口头说的(B 期问来的)不算在内
    weights = [float(v["weight_g"]) for v in variants if isinstance(v.get("weight_g"), (int, float)) and v["weight_g"] > 0 and v.get("source") != SELLER_SAID]
    fallback_g = max(weights_all) if weights_all else None
    lines: list[Line] = []
    for index, variant in enumerate(variants, start=1):
        weight = variant.get("weight_g") if isinstance(variant.get("weight_g"), (int, float)) and variant["weight_g"] > 0 else None
        note = ""
        if weight is None and fallback_g:
            weight, note = fallback_g, f"卖家没写这个规格的重量,按 {fallback_g:g}g 算"
        elif weight is not None and variant.get("source") == SELLER_SAID:
            note = SELLER_SAID_NOTE  # 旺旺里问来的,只当估算,永不当认证
        dims = variant.get("dims_cm") if isinstance(variant.get("dims_cm"), list) else None
        cost = variant.get("cost_price_cny") if isinstance(variant.get("cost_price_cny"), (int, float)) else None
        line = Line(
            key=f"v{index}",
            name_zh=str(variant.get("name_zh") or ""),
            name_en=str(variant.get("name_en") or variant.get("name_zh") or ""),
            cost_cny=float(cost) if cost is not None else None,
            weight_g=float(weight) if weight is not None else None,
            dims_cm=dims,
            weight_note=note,
            image_url=variant.get("image") or variant.get("image_url"),
        )
        line.kg = chargeable_kg(line.weight_g, dims, a.volumetric_divisor)
        if line.cost_cny is not None and line.kg is not None:
            line.goods, line.ship = costs(line.cost_cny, line.kg, a)
            line.floor = floor_price(line.goods, line.ship, a)
        lines.append(line)
    if len(weights) >= 2 and len(set(weights)) == 1:
        for line in lines:
            line.weight_note = line.weight_note or f"每个规格卖家都填了 {weights[0]:g}g,可能是乱填的,运费按这个数算"
    return lines


# ---------------------------------------------------------------- 竞品价(谷歌购物)

_PRICE = re.compile(r"(\d[\d,]*\.?\d*)")


def parse_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = _PRICE.search(str(value or ""))
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return number if number > 0 else None


# 几件装:只认标题里写明的(8 Pack / 16 Pcs / 12-Count / Set of 10 / Pack of 6);"10 inch"、"16 Straight Rebar Stakes" 这种数字不算
_PACK = re.compile(
    r"\b(?:pack|set|box|bag|case|bundle|lot)\s+of\s+(\d{1,3})\b"
    r"|\b(\d{1,3})\s*[- ]?(?:pack|packs|pk|pcs|pc|pieces|piece|count|ct|cnt)\b",
    re.IGNORECASE,
)


def pack_count(title: Any) -> int:
    """标题里写明的件数;没写或写得不像(1 件、上千件)都按 1 件。"""
    for match in _PACK.finditer(str(title or "")):
        try:
            n = int(match.group(1) or match.group(2))
        except (TypeError, ValueError):
            continue
        if 2 <= n <= 500:
            return n
    return 1


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    """(p25, 中位, p75)。"""
    if len(values) >= 4:
        q = statistics.quantiles(values, n=4)
        return q[0], statistics.median(values), q[-1]
    return values[0], statistics.median(values), values[-1]


def competitor_stats(items: list[dict[str, Any]], *, query: str) -> dict[str, Any]:
    """谷歌购物的结果 → 价格分布。离中位数太远的(配件、整箱、标错价)先剔掉再算。

    10-28 起每条结果还认几件装(pack)并折成单价(unit_price):同类里单根、12 支装、16 支装混在一起时,
    listing 价的中位数没法和 1688 的单件进价比,所以另给一组按件折算的分布 unit(p25/中位/p75、主流件数、多件装占比)。
    """
    rows = []
    for item in items:
        price = parse_price(item.get("price"))
        if price is not None:
            title = str(item.get("title") or "")[:120]
            pack = pack_count(title)
            rows.append({"title": title, "source": str(item.get("source") or "")[:60], "price": price, "pack": pack, "unit_price": round(price / pack, 2)})
    if not rows:
        return {"query": query, "n": 0}
    mid = statistics.median(r["price"] for r in rows)
    kept = [r for r in rows if mid / 5 <= r["price"] <= mid * 5]
    prices = sorted(r["price"] for r in kept)
    p25, median, p75 = _quartiles(prices)
    units = sorted(r["unit_price"] for r in kept)
    u25, umedian, u75 = _quartiles(units)
    packs = [r["pack"] for r in kept]
    multi = [p for p in packs if p > 1]
    pack_mode = Counter(packs).most_common(1)[0][0]
    if pack_mode == 1 and len(multi) * 2 >= len(packs):
        pack_mode = int(statistics.median(multi))  # 一半以上是多件装但件数各异 → 取多件装的中位件数
    return {
        "query": query,
        "n": len(prices),
        "min": round(prices[0], 2),
        "p25": round(p25, 2),
        "median": round(median, 2),
        "p75": round(p75, 2),
        "max": round(prices[-1], 2),
        "unit": {
            "n": len(units),
            "p25": round(u25, 2),
            "median": round(umedian, 2),
            "p75": round(u75, 2),
            "pack_mode": pack_mode,
            "multi_share": round(len(multi) / len(packs), 2),
        },
        "samples": kept[:15],
    }


def unit_text(unit: Any) -> str:
    """卡上那半句:「按件折算中位 $1.62/件,主流 12 件装(七成是多件装)」;没有多件装就空。"""
    if not isinstance(unit, dict) or not unit.get("multi_share"):
        return ""
    return f"按件折算中位 ${unit.get('median')}/件,主流 {unit.get('pack_mode')} 件装({float(unit['multi_share']):.0%} 是多件装)"


def fetch_shopping(db: Any, *, query: str, org_id: str | None) -> dict[str, Any]:
    """谷歌购物搜一次。先过额度台账(铁律:新出网付费调用当天接台账),出网前放掉事务,失败退额度。"""
    import httpx

    from r_system_v2.core.secret_manager import SecretManager
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_SERPER_SHOPPING, RAQuotaExhaustedError, refund, try_consume

    key = str(SecretManager(db_session=db).get_key("serper", org_id) or "").strip()
    if not key:
        return {"query": query, "n": 0, "error": "Serper 密钥没配,没比上价"}
    try:
        try_consume(db, PROVIDER_SQH_SERPER_SHOPPING, amount=1)
    except RAQuotaExhaustedError as exc:
        db.rollback()
        return {"query": query, "n": 0, "error": str(exc)}
    db.commit()  # 出网前放掉事务
    try:
        response = httpx.post(
            SERPER_SHOPPING_URL,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": 20, **SHOPPING_LOCALE},
            timeout=30.0,
        )
        response.raise_for_status()
        items = response.json().get("shopping") or []
    except Exception as exc:  # noqa: BLE001 —— 比不上价不挡定价,卡上写明
        refund(db, PROVIDER_SQH_SERPER_SHOPPING, amount=1)
        db.commit()
        return {"query": query, "n": 0, "error": f"谷歌购物没搜成:{str(exc)[:120]}"}
    return competitor_stats([i for i in items if isinstance(i, dict)], query=query)


# ---------------------------------------------------------------- 定价(模型出价位,代码核保底)

PRICE_ASK = (
    "你在给独立站(美国买家)一件新品的每个规格定售价。下面给你每个规格的到手成本和保底价(已经算好,不要改),"
    "还有谷歌购物上同类商品的价格。\n"
    "要求:\n"
    "- 每个规格给一个售价(美元,尾数 .99),不得低于它的保底价。\n"
    "- 参照竞品价位,但只跟能比的比:我们是无品牌新店、没有评论,大牌(Milwaukee、DeWalt、Bosch、Makita、Ryobi、"
    "Thermacell 这类)的价格不能直接比——看例子里同类的无牌/白牌/超市自有牌(Hyper Tough、Ozark Trail、Warrior 这类)"
    "卖多少,第一批价放在它们附近或略低;别贴着最低价打价格战。成本高到放不进这个区间的,就给保底价,并在 note 里说明。\n"
    "- 竞品标题写了几件装的,先折成每件的价再比;我们的规格本身是几件装(axis=quantity)的,就按整包比整包。单件进价不能直接对整包售价。\n"
    "- 指出不对劲的规格:不是同一种商品(比如电池里混进了充电器)→ include=false 并说明;"
    "几个规格重量一模一样、缺重量 → note 里提醒。\n"
    "- label_en:这个规格在英文商品页上的选项名(短,比如 2000mAh、Black、Tool Only、Kit with 2 Batteries)。\n"
    "- axis:这个规格按什么分——color(颜色)/ size(容量、尺寸、型号)/ function(套装组合)/ quantity(几件装)。"
    "同一个商品的规格用同一个 axis。\n"
    "- questions:真要老板拍板的事(一条一句,没有就空)。\n"
    'Reply JSON only: {"variants": [{"key": "v1", "include": true, "price": 24.99, "label_en": "2000mAh", "axis": "size", '
    '"note": "一句中文"}], "questions": ["..."], "summary": "一句中文:整体怎么定的"}'
)


def price_prompt_extra(lines: list[Line], competitors: dict[str, Any], a: Assumptions, *, boss_reason: str | None) -> str:
    rows = "\n".join(
        f"- {line.key}:{line.name_zh} / {line.name_en};进价 ¥{line.cost_cny};计费重 {line.kg and round(line.kg, 3)} kg;"
        f"到手成本 ${line.goods and round(line.goods + line.ship, 2)};保底价 ${line.floor}"
        + (f";{line.weight_note}" if line.weight_note else "")
        for line in lines
    )
    if competitors.get("n"):
        samples = "\n".join(
            f"  ${row['price']} | {row['source']} | {row['title'][:80]}" + (f"({row['pack']} 件装,${row['unit_price']}/件)" if int(row.get("pack") or 1) > 1 else "")
            for row in competitors.get("samples", [])[:15]
        )
        unit_line = unit_text(competitors.get("unit"))
        comp = (
            f"谷歌购物「{competitors.get('query')}」{competitors['n']} 个价:最低 ${competitors['min']},"
            f"四分之一 ${competitors['p25']},中位 ${competitors['median']},四分之三 ${competitors['p75']},"
            f"最高 ${competitors['max']}。" + (f"{unit_line}。" if unit_line else "") + f"例子(价格 | 店 | 标题):\n{samples}"
        )
    else:
        comp = f"竞品价没拿到({competitors.get('error') or '没有结果'}),按成本给价并说明。"
    extra = (
        f"规格:\n{rows}\n\n{comp}\n\n"
        f"(保底价按毛利率 {a.min_margin:.0%} 算;买家每单付运费 ${a.buyer_shipping_usd},满 $100 免运。)"
    )
    if boss_reason:
        extra += f"\n\n老板上一版驳回的原因(这次一定照着改):{boss_reason}"
    return extra


def apply_plan(lines: list[Line], result: Any, a: Assumptions) -> tuple[list[Line], list[str], str]:
    """模型的定价 → 每个规格的售价。没给的、低于保底价的一律按保底价;至少留一个规格。"""
    from .brain import parse_json

    data = parse_json(result)
    plan = {str(v.get("key")): v for v in (data or {}).get("variants") or [] if isinstance(v, dict)} if isinstance(data, dict) else {}
    for line in lines:
        item = plan.get(line.key) or {}
        line.include = item.get("include") is not False
        line.label_en = " ".join(str(item.get("label_en") or line.name_en or line.name_zh).split())[:60]
        axis = str(item.get("axis") or "").strip().lower()
        line.axis = axis if axis in AXES else "function"
        line.note = str(item.get("note") or "").strip()[:200]
        price = parse_price(item.get("price"))
        if line.floor is not None:
            if price is None:
                price, line.note = line.floor, (line.note or "模型没给价,按保底价")
            elif price < line.floor:
                price, line.note = line.floor, f"{line.note};低于保底价 ${line.floor},抬到保底价".strip(";")
            line.price = round(charm(price), 2)
            line.profit, line.margin = profit_at(line.price, line.goods, line.ship, a)
        else:
            line.include = False
            line.note = (line.note + ";" if line.note else "") + "缺进价或重量,算不了成本"
    if not any(line.include for line in lines):
        for line in lines:
            line.include = line.price is not None
    # 同一个商品的规格用同一个轴:按多数票统一
    included = [line for line in lines if line.include]
    if included:
        axis = max(AXES, key=lambda name: sum(1 for line in included if line.axis == name))
        for line in lines:
            line.axis = axis
    questions = [str(q).strip()[:200] for q in (data or {}).get("questions") or [] if str(q).strip()] if isinstance(data, dict) else []
    summary = str((data or {}).get("summary") or "").strip()[:300] if isinstance(data, dict) else ""
    return lines, questions[:5], summary


def lines_text(lines: list[Line]) -> str:
    """价格卡上一眼看得懂的那几行(办公室的卡片现在只显示文字,规格表放在这里)。"""
    out = []
    for line in lines:
        name = line.label_en or line.name_en or line.name_zh
        if not line.include:
            out.append(f"✗ {name}({line.name_zh}):不卖 —— {line.note or '算不了成本'}")
            continue
        landed = (line.goods or 0) + (line.ship or 0)
        out.append(
            f"• {name}({line.name_zh}):进价 ¥{line.cost_cny:g},到手成本 ${landed:.2f}(运费 ${line.ship:.2f}),"
            f"建议 ${line.price:.2f},单件毛利 ${line.profit:.2f}({line.margin:.0%})"
            + (f" —— {line.note}" if line.note else "")
            + (f";{line.weight_note}" if line.weight_note else "")
        )
    return "\n".join(out)


def competitors_text(competitors: dict[str, Any]) -> str:
    if not competitors.get("n"):
        return f"竞品价:没拿到({competitors.get('error') or '谷歌购物没有结果'})。"
    return (
        f"竞品价:谷歌购物「{competitors['query']}」{competitors['n']} 个,中位 ${competitors['median']},"
        f"一半在 ${competitors['p25']}–${competitors['p75']} 之间(最低 ${competitors['min']},最高 ${competitors['max']})。"
    )


def assumption_text(a: Assumptions) -> str:
    return (
        f"汇率 1 美元 = {a.usd_cny:g} 元;运费按带电专线估 ¥{a.ship_cny_per_kg:g}/公斤 + ¥{a.ship_cny_per_piece:g}/件"
        f"(计费重取实重和体积重大的);PayPal 手续费 {a.fee_rate:.2%} + ${a.fee_fixed_usd:g};买家付运费 ${a.buyer_shipping_usd:g}/单;"
        f"保底毛利率 {a.min_margin:.0%}。运费单价是估的,你给我真实报价我就按实际算。"
    )


__all__ = [
    "AXES",
    "Assumptions",
    "DEFAULT_SHIPPING_CLASS",
    "Line",
    "PRICE_ASK",
    "apply_plan",
    "assumption_text",
    "assumptions",
    "charm",
    "chargeable_kg",
    "competitor_stats",
    "competitors_text",
    "cost_lines",
    "costs",
    "fetch_shopping",
    "floor_price",
    "lines_text",
    "parse_price",
    "price_prompt_extra",
    "profit_at",
]
