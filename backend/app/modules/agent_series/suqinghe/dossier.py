"""1688 抓取结果 → K 档案草稿(10-23 苏青禾的第一项真本事;10-26 第二版)。

规矩(潜水泵教训):
- 每个字段都带来源(页面 JSON / 页面文本 / 第几张详情图第几段),谁说的一眼能查。
- 页面数据(属性表、标题、规格名)是第一手;详情图上的事实用来补缺和佐证。
- 真矛盾才标 conflict:页面自己前后不一,或者页面和图上(本品、把握高/中)说法不一样 → 各方原话都留着,
  不替老板选。拿不准的说法(看不出是不是本品、把握低)放 alternatives,不标红。
- 按规格不同的值(容量 / 电压 / 功率)从规格名里读,每个变体各填各的 —— 这不是矛盾。
- 别的商品(兼容机型表、同店别款)、广告语、尺寸图上零件的单个标注 → 不进规格,只记个数。
- 哪都没有,或者卖家只写了「如图」「其他」「咨询客服」这种占位 → missing,**空着,不猜**。
- 1688 只有进价,没有售价 → retail_price 永远是 needs_owner。
- 英文品名只能从事实里来:让 writer 档改写,不许编参数、不许带品牌。

第二版的起因(10-26 三个真链接):电池那单把一张别款电池的图(18V/21V/24V、4.0Ah)、尺寸图的三个单独
标注(40/48/84mm)、1300~2500mAh 四个规格各自的容量,全判成了「说法不一」,标红一大片、老板看不懂;
电钻那单把「外形尺寸:咨询客服」当成了真尺寸。

AI 调用(英文名 / 包装清单翻译 / 类目)都可以注入,测试不出网。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DRAFT_VERSION = 2
ALLOWED_IMAGE_HOSTS = ("alicdn.com",)

# 卖家常用的占位写法:看着有值,其实什么都没说。
PLACEHOLDERS = {
    "", "如图", "见图", "详见图片", "详见详情", "详情见图", "其他", "其它", "无", "暂无", "不详",
    "/", "-", "—", "--", "n/a", "na", "none", "other", "可定制", "定制", "以实物为准",
}
# 短值里带这些字样也是占位:「咨询客服」「以实际为准」(10-26 电钻:外形尺寸=咨询客服 被当成了真尺寸)。
PLACEHOLDER_MARKERS = ("咨询", "客服", "详询", "以实物为准", "以实际为准", "见详情", "看详情", "见图")

# 中文属性名 → 档案规格键。没列进来的属性留在 other_attributes 里给老板看,不进规格。
# 顺序有讲究:包含匹配按这个顺序找,「电池电压」「电池容量」要先认成电压/容量,不能被「电池」两个字截走。
SPEC_ALIASES: dict[str, tuple[str, ...]] = {
    "material": ("材质", "玩具材质", "产品材质", "材料", "面料", "主要材质", "外壳材质", "material"),
    "dimensions": ("尺寸", "产品尺寸", "规格尺寸", "外形尺寸", "大小", "产品规格尺寸", "dimensions", "size"),
    "weight": ("重量", "产品重量", "净重", "单品重量", "weight", "net weight"),
    "age_range": ("适用年龄", "年龄范围", "适用年龄段", "适合年龄", "age", "age range", "ages"),
    "color": ("颜色", "产品颜色", "颜色分类", "color", "colour"),
    "packaging": ("包装", "包装方式", "包装形式", "packaging", "package type"),
    "voltage": ("电压", "额定电压", "电池电压", "额定电压范围", "voltage"),
    "capacity": ("容量", "电池容量", "额定容量", "capacity"),
    "power": ("功率", "额定功率", "power"),
    "charging": ("充电方式", "充电接口", "充电时间", "charging"),
    "runtime": ("续航", "续航时间", "使用时间", "工作时间", "runtime"),
    "cycle_life": ("循环次数", "循环寿命", "cycle life", "cycle_life"),
    "certification": ("产品认证", "认证", "certification"),
    "battery_type": ("电池类型", "电芯类型", "电芯", "电池", "battery", "battery_type", "battery type"),
    # 「产地:浙江省」和「原产国/地区:大陆」是两个粒度,不是矛盾,分开放。
    "origin_region": ("产地", "发货地"),
    "origin_country": ("原产国/地区", "原产国", "country of origin"),
    "applicable_people": ("适用人群", "target users"),
}
SPEC_LABELS_ZH = {
    "material": "材质", "dimensions": "尺寸(单品)", "weight": "重量(单品)", "age_range": "适用年龄",
    "color": "颜色", "packaging": "包装", "voltage": "电压", "capacity": "容量", "power": "功率",
    "charging": "充电", "runtime": "续航", "cycle_life": "循环次数", "certification": "认证",
    "battery_type": "电池/电芯", "origin_region": "产地", "origin_country": "原产国", "applicable_people": "适用人群",
    "weight_pack": "重量(单个包装)", "dimensions_pack": "尺寸(单个包装)",
    "weight_carton": "外箱重量", "dimensions_carton": "外箱尺寸",
}
FIELD_LABELS_ZH = {
    "name_zh": "中文原标题", "name_en": "英文品名", "category": "谷歌类目", "product_type": "产品类型",
    "moq": "起批量", "retail_price": "美国售价", "package_includes": "包装清单", "detail_images": "详情图",
}
PACKAGE_FIELDS = ("package_includes", "package includes", "包装清单", "包装内含", "配件", "in the box", "包装含")
# 和产品本身无关、或者品牌身份(K 不收品牌当规格)的属性,直接丢。
# 只对批发商有意义的属性(品牌授权、货号、能不能加印 LOGO……),不进档案也不进 K。
# 10-26 加「加印」「定制」:灭蚊灯的「加印LOGO: 可以」「加工定制: 否」漏进了 K 给 AI 读的原始文本。
IGNORED_ATTRIBUTES = ("品牌", "货号", "专利", "主要下游平台", "主要销售地区", "是否", "有可授权", "上市时间", "加工方式", "动漫角色", "加印", "定制")

# 只有这些键会判「说法不一」:单值、上架要用、写错了要出事。其余(电芯、认证、充电方式、颜色……)几种说法并列就行。
STRICT_KEYS = {"material", "dimensions", "weight", "age_range", "voltage", "capacity", "power", "runtime", "cycle_life"}
# 按规格不同的键:从规格名里读得出来(「2000mah」「12V直充充电器」)。
PER_VARIANT_KEYS = ("capacity", "voltage", "power")
# 图上的值超过这么长就是一句话(广告语),不是规格值。包装清单除外。
NARRATIVE_LIMIT = 32

WriterFn = Callable[[dict[str, Any]], dict[str, Any] | None]
ClassifierFn = Callable[[Session, str], Any]


def _field(value: Any = None, *, unit: str | None = None, sources: list[dict[str, Any]] | None = None,
           status: str = "ok", note: str = "") -> dict[str, Any]:
    return {"value": value, "unit": unit, "sources": sources or [], "status": status, "note": note}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_placeholder(value: Any) -> bool:
    text = _clean(value).strip("。.;；,， ").casefold()
    if text in PLACEHOLDERS:
        return True
    return len(text) <= 12 and any(marker in text for marker in PLACEHOLDER_MARKERS)


_CJK_ALIAS = re.compile(r"[㐀-鿿]")


def _spec_key(name: Any) -> str | None:
    """属性名 → 规格键。完全相等优先;中文别名允许包含匹配,英文别名只认整词
    (否则 package_includes 里的 "age" 会被当成年龄 —— 10-23 首测踩到)。"""
    label = _clean(name).casefold()
    if not label or label in PACKAGE_FIELDS:
        return None
    for key, aliases in SPEC_ALIASES.items():
        if any(label == alias.casefold() for alias in aliases):
            return key
    words = set(re.split(r"[^a-z0-9]+", label))
    for key, aliases in SPEC_ALIASES.items():
        for alias in aliases:
            folded = alias.casefold()
            if _CJK_ALIAS.search(folded):
                if len(folded) >= 2 and folded in label:
                    return key
            elif " " in folded:
                if folded in label:
                    return key
            elif folded in words:
                return key
    return None


def ignored_attribute(name: Any) -> bool:
    label = _clean(name)
    return any(term in label for term in IGNORED_ATTRIBUTES)


def _host_ok(url: Any) -> bool:
    text = str(url or "")
    return text.startswith(("http://", "https://")) and any(host in text for host in ALLOWED_IMAGE_HOSTS)


def _image_source(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "image",
        "ref": f"详情图 {int(fact.get('image_index') or 0) + 1} · 第 {int(fact.get('segment_index') or 0) + 1} 段",
        "raw": _clean(fact.get("raw_text") or fact.get("value"))[:300],
    }


# ---------------------------------------------------------------- 值:拆单位、比较


_NUM = re.compile(r"\d+(?:\.\d+)?")
_UNIT_TAIL = re.compile(r"(.*?\d)\s*([a-zA-Z\"]{1,5}|毫米|厘米|千克|公斤|毫安时|毫安|毫升|小时|分钟|克|斤|伏|瓦|米|升|次)\s*$")
# 每种量的单位 → 换算到同一个基准(克 / 毫米 / mAh·毫升 / 伏 / 瓦 / 分钟 / 次)。只用来比较,不改显示。
_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "weight": {"g": 1, "克": 1, "kg": 1000, "千克": 1000, "公斤": 1000, "斤": 500, "lb": 453.6, "lbs": 453.6, "oz": 28.35},
    "dimensions": {"mm": 1, "毫米": 1, "cm": 10, "厘米": 10, "m": 1000, "米": 1000, "in": 25.4, "inch": 25.4, "英寸": 25.4, '"': 25.4},
    "capacity": {"mah": 1, "毫安时": 1, "毫安": 1, "ah": 1000, "ml": 1, "毫升": 1, "l": 1000, "升": 1000},
    "voltage": {"v": 1, "伏": 1, "kv": 1000},
    "power": {"w": 1, "瓦": 1, "kw": 1000},
    "runtime": {"min": 1, "mins": 1, "分钟": 1, "h": 60, "hr": 60, "hrs": 60, "hours": 60, "小时": 60},
    "cycle_life": {"次": 1, "times": 1, "cycles": 1},
}


def _base_key(key: str) -> str:
    for suffix in ("_pack", "_carton"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _split_unit(value: Any, unit: Any) -> tuple[str, str | None]:
    """「166g」→(166, g);「12V」+ 单位 V →(12, V);「12V V」也是(12, V)。看不出单位就原样。"""
    text = _clean(value).strip("。.,，;； ")
    unit_text = _clean(unit) or None
    if unit_text:
        for _ in range(2):
            if len(text) > len(unit_text) and text.casefold().endswith(unit_text.casefold()):
                text = text[: -len(unit_text)].strip()
        return text, unit_text
    match = _UNIT_TAIL.fullmatch(text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, None


def _fmt_number(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


def _display(value: str, unit: str | None) -> str:
    return f"{value} {unit}".strip() if unit else value


def _unit_factor(base: str, unit: str | None, value: str) -> float:
    table = _UNIT_FACTORS.get(base) or {}
    candidates = [unit or ""]
    tail = re.search(r"\d\s*([a-zA-Z\"]+|[一-鿿]+)\s*$", value or "")
    if tail:
        candidates.append(tail.group(1))
    for raw in candidates:
        token = raw.strip().casefold()
        if token in table:
            return table[token]
    return 1.0


def _numbers(base: str, value: str, unit: str | None) -> tuple[float, ...] | None:
    numbers = [float(n) for n in _NUM.findall(value or "")]
    if not numbers:
        return None
    factor = _unit_factor(base, unit, value)
    return tuple(round(n * factor, 3) for n in numbers)


# 「%」不是任何一种量的单位(10-26 电钻:广告图「续航持久」表盘上的 25% 被读成了续航)。
_NOT_A_UNIT = {"%", "％"}
_UNIT_TOKEN_TAIL = re.compile(r"\d\s*([a-zA-Z\"%％]+|[一-鿿]+)\s*$")


def _wrong_unit(key: str, value: Any, unit: str | None) -> bool:
    """读图给的单位属于另一种量(续航「25%」、容量「12V」、重量「84mm」)→ 这条说的不是这个字段。认不出的单位照收。"""
    base = _base_key(key)
    if base not in _UNIT_FACTORS:
        return False
    token = (unit or "").strip().casefold()
    if not token:
        tail = _UNIT_TOKEN_TAIL.search(_clean(value))
        token = tail.group(1).casefold() if tail else ""
    if token in _NOT_A_UNIT:
        return True
    family = next((name for name, table in _UNIT_FACTORS.items() if token in table), None)
    return family is not None and family != base


_DIM_SEPARATOR = re.compile(r"(?<=\d)\s*[*xX×＊]\s*(?=\d)")


def _tidy(key: str, value: str) -> str:
    """尺寸统一写成「153×40×40」(卖家和图上 *、x、X 都有)。"""
    return _DIM_SEPARATOR.sub("×", value) if _base_key(key) == "dimensions" else value


def _close(a: float, b: float, *, rel: float = 0.01, absolute: float = 0.0) -> bool:
    return abs(a - b) <= max(absolute, rel * max(abs(a), abs(b)), 1e-9)


_FILLER_WORDS = ("全新", "优质", "高品质", "高性能", "材料", "材质", "外壳", "制成", "环保", "内置", "纯")
# 认证这一类,「UN38.3」和「UN38.3 Test Report」说的是同一个东西。
_CERT_FILLER = re.compile(r"test\s*report|report|certificate|certification|测试报告|检测报告|报告|认证|证书|检测", re.I)


def _text_parts(value: Any, *, key: str = "") -> list[str]:
    text = _clean(value).casefold().replace("（", "(").replace("）", ")")
    text = re.sub(r"\bages?\b", " ", text)
    if key == "certification":
        text = _CERT_FILLER.sub(" ", text)
    parts: list[str] = []
    for part in re.split(r"[、,，/;；+&|\s]+|和|及", text):
        for filler in _FILLER_WORDS:
            part = part.replace(filler, "")
        part = re.sub(r"[()\[\]【】:：.。*\-—_\"'“”岁]", "", part)
        if part:
            parts.append(part)
    return parts


def _text_tokens(value: Any, *, key: str = "") -> frozenset[str]:
    """拆词、去掉「全新」「材料」这类虚词、每个词按字排序(「阻燃ABS」和「ABS阻燃」算同一个)。"""
    return frozenset("".join(sorted(part)) for part in _text_parts(value, key=key))


def _text_same(a: Any, b: Any, *, key: str = "") -> bool:
    ta, tb = _text_tokens(a, key=key), _text_tokens(b, key=key)
    if not ta or not tb:
        return False
    if ta <= tb or tb <= ta:
        return True
    # 各自只有一个词时,短的整个包含在长的里面也算(「type-c」和「type-c快充接口」)。
    pa, pb = _text_parts(a, key=key), _text_parts(b, key=key)
    if len(pa) == 1 and len(pb) == 1:
        short, long_ = sorted((pa[0], pb[0]), key=len)
        return len(short) >= 2 and short in long_
    return False


@dataclass
class _Obs:
    """一条说法:值、单位、出处,是不是页面数据(第一手),是不是有把握的本品事实。"""

    value: str
    unit: str | None
    source: dict[str, Any]
    primary: bool
    strong: bool


def _same(key: str, a: _Obs, b: _Obs) -> bool:
    base = _base_key(key)
    if base in _UNIT_FACTORS:
        na, nb = _numbers(base, a.value, a.unit), _numbers(base, b.value, b.unit)
        if na is None or nb is None:
            return _text_same(a.value, b.value, key=base)
        if base == "dimensions":
            sa, sb = sorted(na, reverse=True), sorted(nb, reverse=True)
            if len(sa) == len(sb):
                return all(_close(x, y, rel=0.02, absolute=1.0) for x, y in zip(sa, sb, strict=True))
            short, long_ = (sa, sb) if len(sa) < len(sb) else (sb, sa)
            return all(any(_close(x, y, rel=0.02, absolute=1.0) for y in long_) for x in short)
        return any(_close(x, y) for x in na for y in nb)
    return _text_same(a.value, b.value, key=base)


# ---------------------------------------------------------------- 规格合并


# 只有重量和尺寸按层级分开记:单品 / 单个销售包装 / 批发外箱。其它字段(材质、年龄……)不分层。
_SCOPED_SPEC_KEYS = {"weight", "dimensions"}
_SCOPE_SUFFIX = {"inner_pack": "_pack", "carton": "_carton"}


def _scoped_key(key: str, scope: Any) -> str:
    if key in _SCOPED_SPEC_KEYS:
        return key + _SCOPE_SUFFIX.get(str(scope or ""), "")
    return key


_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "voltage": re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d)?)\s*(v|伏)(?![a-z])", re.I),
    "capacity": re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mah|毫安时|毫安|ah)(?![a-z])", re.I),
    "power": re.compile(r"(?<![\d.])(\d{1,5}(?:\.\d)?)\s*(w|瓦)(?![a-z])", re.I),
}
_UNIT_DISPLAY = {"v": "V", "伏": "V", "mah": "mAh", "毫安": "mAh", "毫安时": "mAh", "ah": "Ah", "w": "W", "瓦": "W"}


def _values_in(text: str) -> dict[str, list[str]]:
    """一段文字(标题、规格名)里出现的电压/容量/功率,写成「12V」「2000mAh」。"""
    out: dict[str, list[str]] = {}
    for key, pattern in _VALUE_PATTERNS.items():
        for number, unit in pattern.findall(text or ""):
            shown = f"{_fmt_number(float(number))}{_UNIT_DISPLAY.get(unit.casefold(), unit)}"
            out.setdefault(key, [])
            if shown not in out[key]:
                out[key].append(shown)
    return out


def variant_spec_values(variants: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """{规格键: {规格名: 值}}:每个规格名里读得出的电压/容量/功率(一个规格名里同一种量只有一个值才算)。"""
    out: dict[str, dict[str, str]] = {}
    for variant in variants or []:
        name = _clean(variant.get("name_zh"))
        for key, values in _values_in(name).items():
            if len(values) == 1:
                out.setdefault(key, {})[name] = values[0]
    return out


def _attr_value(key: str, value: str) -> str:
    if key == "color":
        # 「AH06光棍驱蚊露营灯[黑色]、AH06光棍驱蚊露营灯[绿色]」→「黑色、绿色」
        inside = re.findall(r"[\[【(（]([^\]】)）]{1,16})[\]】)）]", value)
        if len(inside) >= 2:
            return "、".join(dict.fromkeys(_clean(v) for v in inside))
    return value


def _prepare_image_facts(facts: list[dict[str, Any]], stats: dict[str, int]) -> list[dict[str, Any]]:
    """读图事实进合并之前先过三道:别的商品、广告语(太长,或者量的字段里没有数)、尺寸图上的单个标注。"""
    kept: list[dict[str, Any]] = []
    single_dims: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    full_dims_segments: set[tuple[Any, Any, Any]] = set()
    for fact in facts or []:
        # 旧版读图没有 subject 字段:当作本品(和当时的规矩一致)。
        if (fact.get("subject") or "this") == "other":
            stats["ignored_other"] += 1
            continue
        field_name = _clean(fact.get("field")).casefold()
        value = _clean(fact.get("value"))
        if field_name not in PACKAGE_FIELDS and len(value) > NARRATIVE_LIMIT:
            stats["ignored_narrative"] += 1
            continue
        # 续航、容量、电压、重量、尺寸……这些量没有数就是广告语(10-26 电钻:卖点拼图配字「电力强劲 持久续航」被读成续航)
        if _base_key(_spec_key(field_name) or "") in _UNIT_FACTORS and not _NUM.search(value):
            stats["ignored_narrative"] += 1
            continue
        if _spec_key(field_name) == "dimensions":
            segment = (fact.get("image_index"), fact.get("segment_index"), fact.get("scope") or "unknown")
            if len(_NUM.findall(value)) == 1:
                single_dims.setdefault(segment, []).append(fact)
                continue
            full_dims_segments.add(segment)
        kept.append(fact)
    for segment, group in single_dims.items():
        if segment in full_dims_segments:
            stats["ignored_drawing"] += len(group)  # 同一段已经有完整的长×宽×高,单个标注是多余的
        elif len(group) == 1:
            kept.append(group[0])
        elif len(group) <= 3:
            # 尺寸图上分开标的长、宽、高(10-26 电池:40mm / 48mm / 84mm)→ 合成一条。
            parts = [_split_unit(f.get("value"), f.get("unit")) for f in group]
            unit = next((u for _, u in parts if u), None)
            numbers = sorted((float(_NUM.findall(v)[0]) for v, _ in parts), reverse=True)
            kept.append(
                {
                    **group[0],
                    "value": "×".join(_fmt_number(n) for n in numbers),
                    "unit": unit or "",
                    "raw_text": " / ".join(_clean(f.get("raw_text") or f.get("value")) for f in group)[:300],
                }
            )
        else:
            stats["ignored_drawing"] += len(group)  # 四个以上的单独标注 = 零件尺寸,不是外形
    return kept


def _sources(group: list[_Obs]) -> list[dict[str, Any]]:
    ordered = sorted(group, key=lambda o: (not o.primary, not o.strong))
    return [o.source for o in ordered]


def _rep(group: list[_Obs]) -> _Obs:
    return next((o for o in group if o.primary), None) or next((o for o in group if o.strong), None) or group[0]


def _candidate(group: list[_Obs]) -> dict[str, Any]:
    rep = _rep(group)
    return {"value": rep.value, "unit": rep.unit, "sources": _sources(group)}


def _group(key: str, observations: list[_Obs]) -> list[list[_Obs]]:
    groups: list[list[_Obs]] = []
    for obs in observations:
        for group in groups:
            if _same(key, group[0], obs):
                group.append(obs)
                break
        else:
            groups.append([obs])
    return groups


def _with_alternatives(field: dict[str, Any], groups: list[list[_Obs]], why: str) -> dict[str, Any]:
    if groups:
        field["alternatives"] = [{**_candidate(g), "why": why} for g in groups]
    return field


def _decide_strict(key: str, observations: list[_Obs]) -> dict[str, Any]:
    groups = _group(key, observations)
    primary = [g for g in groups if any(o.primary for o in g)]
    if primary:
        contenders = primary + [g for g in groups if g not in primary and any(o.strong for o in g)]
    else:
        contenders = [g for g in groups if any(o.strong for o in g)] or groups
    weak = [g for g in groups if g not in contenders]
    if len(contenders) == 1:
        rep = _rep(contenders[0])
        field = _field(rep.value, unit=rep.unit, sources=_sources(contenders[0]))
        return _with_alternatives(field, weak, "把握不大,或看不出是不是本品")
    shown = " / ".join(_display(_rep(g).value, _rep(g).unit) for g in contenders[:4])
    field = _field(None, sources=[s for g in contenders for s in _sources(g)], status="conflict", note=f"说法不一:{shown}")
    field["candidates"] = [_candidate(g) for g in contenders]
    return _with_alternatives(field, weak, "把握不大,或看不出是不是本品")


UNION_SHOWN = 4


def _decide_union(key: str, observations: list[_Obs]) -> dict[str, Any]:
    """几种说法并列(电芯、认证、充电方式……):页面的排前面,其余按出现次数,最多列 4 种,多的放「其他说法」。"""
    groups = _group(key, observations)
    main = [g for g in groups if any(o.primary or o.strong for o in g)] or groups
    main.sort(key=lambda g: (not any(o.primary for o in g), -len(g)))
    shown_groups, extra = main[:UNION_SHOWN], main[UNION_SHOWN:]
    weak = [g for g in groups if g not in main]
    if len(shown_groups) == 1:
        rep = _rep(shown_groups[0])
        field = _field(rep.value, unit=rep.unit, sources=_sources(shown_groups[0]))
    else:
        shown = "、".join(_display(_rep(g).value, _rep(g).unit) for g in shown_groups)
        field = _field(shown, sources=[s for g in shown_groups for s in _sources(g)])
    _with_alternatives(field, extra, "还有这种说法")
    if weak:
        field.setdefault("alternatives", []).extend({**_candidate(g), "why": "把握不大,或看不出是不是本品"} for g in weak)
    return field


def _decide_per_variant(key: str, observations: list[_Obs], per_variant: dict[str, str]) -> dict[str, Any]:
    base = _base_key(key)

    def magnitude(value: str) -> float:
        numbers = _numbers(base, value, None)
        return numbers[0] if numbers else 0.0

    values = sorted(dict.fromkeys(per_variant.values()), key=magnitude)
    sku_source = {"kind": "page_json", "ref": "规格(SKU)名称", "raw": "、".join(per_variant)[:300]}
    anchors = [_Obs(*_split_unit(v, None), source=sku_source, primary=True, strong=True) for v in values]
    supporting: list[dict[str, Any]] = []
    others: list[_Obs] = []
    for obs in observations:
        if any(_same(key, anchor, obs) for anchor in anchors):
            supporting.append(obs.source)
        else:
            others.append(obs)
    field = _field(" / ".join(values), sources=[sku_source, *supporting], note="按规格不同,见变体表")
    field["per_variant"] = dict(per_variant)
    return _with_alternatives(field, _group(key, others), "对不上任何一个规格")


def merge_specs(
    capture: dict[str, Any],
    facts: list[dict[str, Any]],
    *,
    variants: list[dict[str, Any]] | None = None,
    stats: dict[str, int] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """属性表 + 标题 + 规格名 + 详情图事实 → {规格键: 字段}。返回 (specs, other_attributes)。

    ``stats`` 传进来会被填上:扔掉了几条别的商品 / 广告语 / 零件尺寸标注 / 单位对不上的。
    """
    stats = stats if stats is not None else {}
    for name in ("ignored_other", "ignored_narrative", "ignored_drawing", "ignored_unit"):
        stats.setdefault(name, 0)
    observations: dict[str, list[_Obs]] = {}
    placeholders: dict[str, list[dict[str, Any]]] = {}
    other: list[dict[str, str]] = []

    for attr in capture.get("attributes") or []:
        name, value = _clean(attr.get("name")), _clean(attr.get("value"))
        if not name or ignored_attribute(name):
            continue
        key = _spec_key(name)
        kind = "page_json" if attr.get("source") == "page_json" else "page_text"
        source = {"kind": kind, "ref": f"属性「{name}」", "raw": value[:300]}
        if key is None:
            if value and not is_placeholder(value):
                other.append({"name": name, "value": value[:300]})
            continue
        if is_placeholder(value):
            placeholders.setdefault(key, []).append(source)
            continue
        number, unit = _split_unit(_attr_value(key, value), None)
        observations.setdefault(key, []).append(_Obs(_tidy(key, number), unit, source, primary=True, strong=True))

    title = _clean(capture.get("title_zh"))
    for key, values in _values_in(title).items():
        if len(values) == 1:  # 标题里同一种量出现两个值(「12V/21V 通用」)就不算数
            number, unit = _split_unit(values[0], None)
            source = {"kind": "page_text", "ref": "商品标题", "raw": title[:300]}
            observations.setdefault(key, []).append(_Obs(number, unit, source, primary=True, strong=True))

    per_variant_all = variant_spec_values(variants or [])
    per_variant = {k: m for k, m in per_variant_all.items() if len(set(m.values())) > 1}
    for key, mapping in per_variant_all.items():
        if key not in per_variant:  # 所有规格同一个值 → 就是一条普通的页面事实
            number, unit = _split_unit(next(iter(mapping.values())), None)
            source = {"kind": "page_json", "ref": "规格(SKU)名称", "raw": "、".join(mapping)[:300]}
            observations.setdefault(key, []).append(_Obs(number, unit, source, primary=True, strong=True))

    for fact in _prepare_image_facts(facts, stats):
        key = _spec_key(fact.get("field"))
        if key is None:
            continue
        key = _scoped_key(key, fact.get("scope"))
        number, unit = _split_unit(fact.get("value"), fact.get("unit"))
        if not number or is_placeholder(number):
            continue
        if _wrong_unit(key, fact.get("value"), unit):
            stats["ignored_unit"] += 1
            continue
        strong = (fact.get("subject") or "this") == "this" and (fact.get("confidence") or "high") in {"high", "medium"}
        observations.setdefault(key, []).append(_Obs(_tidy(key, number), unit, _image_source(fact), primary=False, strong=strong))

    specs: dict[str, dict[str, Any]] = {}
    for key in [*SPEC_LABELS_ZH, *(k for k in observations if k not in SPEC_LABELS_ZH)]:
        items = observations.get(key, [])
        if key in per_variant:
            specs[key] = _decide_per_variant(key, items, per_variant[key])
        elif items:
            specs[key] = _decide_strict(key, items) if _base_key(key) in STRICT_KEYS else _decide_union(key, items)
        elif key in placeholders:
            raw = placeholders[key][0].get("raw") or "如图"
            specs[key] = _field(None, sources=placeholders[key], status="missing",
                                note=f"卖家只写了「{raw}」这类占位,要问供应商或看图")
    return specs, other


# ---------------------------------------------------------------- 变体 / 价格


def build_variants(capture: dict[str, Any]) -> list[dict[str, Any]]:
    images: dict[str, str] = {}
    for prop in capture.get("sku_props") or []:
        for item in prop.get("values") or []:
            if item.get("name") and _host_ok(item.get("image_url")):
                images[_clean(item["name"])] = item["image_url"]
    variants = []
    for sku in capture.get("skus") or []:
        name = _clean(sku.get("name"))
        dims = [sku.get("length_cm"), sku.get("width_cm"), sku.get("height_cm")]
        variants.append(
            {
                "sku_id": sku.get("sku_id"),
                "name_zh": name,
                "name_en": None,
                "cost_price_cny": sku.get("price_cny"),
                # 1688「包装信息」里每个规格的重量和长宽高 = 一件的发货包装,不是产品本身。
                "weight_g": sku.get("weight_g") or None,
                "dims_cm": dims if all(isinstance(d, (int, float)) and d > 0 for d in dims) else None,
                "image_url": sku.get("image_url") if _host_ok(sku.get("image_url")) else images.get(name),
                "specs": {},
            }
        )
    for key, mapping in variant_spec_values(variants).items():
        for variant in variants:
            if variant["name_zh"] in mapping:
                variant["specs"][key] = mapping[variant["name_zh"]]
    return variants


def pricing_summary(capture: dict[str, Any], variants: list[dict[str, Any]]) -> dict[str, Any]:
    mode = capture.get("price_mode")
    tiers = [t for t in capture.get("price_tiers") or [] if t.get("price_cny") not in (None, "")]
    prices = sorted({float(v["cost_price_cny"]) for v in variants if isinstance(v.get("cost_price_cny"), (int, float))})
    price_range = list(capture.get("price_range") or []) or ([prices[0], prices[-1]] if prices else [])
    if mode == "sku" or (not tiers and prices):
        text = (
            f"按规格 ¥{_fmt_number(price_range[0])}–¥{_fmt_number(price_range[1])}"
            if price_range and price_range[0] != price_range[1]
            else (f"¥{_fmt_number(price_range[0])}" if price_range else "页面上没拿到进价")
        )
    elif tiers:
        text = "、".join(f"≥{t.get('min_qty')}件 ¥{_fmt_number(float(t['price_cny']))}" for t in tiers)
    else:
        text = "页面上没拿到进价"
    return {
        "mode": mode or ("tiers" if tiers else None),
        "tiers": tiers,
        "range_cny": price_range,
        "moq": capture.get("moq"),
        "unit": capture.get("unit"),
        "text": text,
    }


# ---------------------------------------------------------------- AI:英文名 / 包装清单


_WRITER_INSTRUCTION = (
    "You prepare an English product name for a US online store from verified 1688 supplier facts. "
    "Use ONLY the facts given. Never invent specifications, materials, quantities or certifications. "
    "No brand names, no marketing claims (best, premium, #1), no Chinese characters. "
    "product name: at most 75 characters, plain and descriptive, must end on a complete word or phrase. "
    "variant_names: same order and count as the given variant names, short English (max 60 chars each). "
    "package_includes: translate the given package-content facts into short English item lines; empty list if none given. "
    'Reply with JSON: {"name_en": str, "variant_names": [str], "package_includes": [str]}'
)


def _default_writer(payload: dict[str, Any]) -> dict[str, Any] | None:
    from ....db.session import SessionLocal
    from ....services.ai_provider_router import AIExecutionRouter
    from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME
    from .constants import USAGE_LABEL

    db = SessionLocal()
    try:
        return AIExecutionRouter(db, timeout_seconds=120.0, total_budget_seconds=180.0).execute(
            provider="writer",
            task_type="generate",
            payload={
                "messages": [
                    {"role": "system", "content": _WRITER_INSTRUCTION},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            },
            org=TARGET_ORGANIZATION_NAME,
            module_id="k.product_knowledge",
            usage_label=USAGE_LABEL,
        )
    finally:
        db.close()


_CJK = re.compile(r"[㐀-鿿]")


def _english_ok(text: Any, limit: int) -> str | None:
    value = _clean(text)
    if not value or _CJK.search(value):
        return None
    if len(value) > limit:
        cut = value[:limit].rsplit(" ", 1)[0].strip(" ,-")
        value = cut or value[:limit]
    return value


# ---------------------------------------------------------------- 类目


def _default_classifier(db: Session, text: str) -> Any:
    from ..yinchengyue.classifier import classify

    return classify(db, text)


# 英文名里拿来找先例的词:5 个字母以上,去掉这些泛词。
_PRECEDENT_STOP = {
    "with", "for", "and", "the", "toy", "toys", "kids", "adults", "relief", "stress", "set", "pack", "piece",
    "pieces", "gift", "cute", "mini", "new", "box", "blind", "colorful", "style", "random",
}
_HEAD_SPLIT = re.compile(r"\s+(?:with|for|and|includes?|including)\s+|[,(–—/|]", re.I)


def head_noun(name_en: Any) -> str | None:
    """英文品名的中心词:第一个「with / for / 逗号」之前的最后一个词(单复数归一)。

    「3-in-1 Outdoor Mosquito Repellent Camping Light with Flashlight」→ light;
    「Portable Camping Shower, 5 Gallon」→ shower。先例必须中心词相同 —— 10-26 灭蚊露营灯就因为
    英文名里有 camping / outdoor,被照着店里的露营淋浴器判成了「便携淋浴」。
    """
    head = _HEAD_SPLIT.split(str(name_en or ""), maxsplit=1)[0]
    words = re.findall(r"[A-Za-z]+", head)
    if not words:
        return None
    word = words[-1].lower()
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def precedent_from_rows(name_en: Any, rows: list[tuple[Any, Any, Any]]) -> tuple[str, int, str] | None:
    """店里候选产品 [(类目, 英文名, SKU)] → (类目, 个数, 例子 SKU)。中心词相同的 ≥2 个、类目一致才算先例。"""
    head = head_noun(name_en)
    if not head:
        return None
    counts: dict[str, list[str]] = {}
    for category, name, sku in rows:
        if category in (None, "") or head_noun(name) != head:
            continue
        counts.setdefault(str(category), []).append(str(sku or ""))
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda item: len(item[1]), reverse=True)
    top_category, skus = ranked[0]
    if len(skus) < 2 or (len(ranked) > 1 and len(ranked[1][1]) >= len(skus)):
        return None
    return top_category, len(skus), sorted(skus)[0]


def _precedent_category(db: Session, name_en: Any) -> dict[str, Any] | None:
    """店里中心词相同、已经绑了谷歌类目的产品 ≥2 个且类目一致 → 沿用。读不到就返回 None 交给分类器。"""
    text = str(name_en or "")
    head = head_noun(text)
    tokens = sorted({t.lower() for t in re.findall(r"[A-Za-z]{5,}", text)} - _PRECEDENT_STOP)
    if head and head not in tokens:
        tokens.append(head)
    if not tokens or not head or db is None:
        return None
    try:
        from sqlalchemy import or_, select

        from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
        from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

        rows = db.execute(
            select(P.google_product_category, P.product_name_en, P.sku)
            .where(
                P.google_product_category.is_not(None),
                or_(*[P.product_name_en.ilike(f"%{t}%") for t in tokens[:8]]),
            )
            .limit(500),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).all()
    except Exception as exc:  # noqa: BLE001 —— 先例查不到不影响整份档案,退回分类器
        db.rollback()
        logger.warning("dossier precedent lookup failed: %s", exc)
        return None
    found = precedent_from_rows(text, [tuple(row) for row in rows])
    if found is None:
        return None
    category_id, count, example_sku = found
    name = path = ""
    try:
        from sqlalchemy import text as sql_text

        row = db.execute(
            sql_text("SELECT name, full_path FROM k_category_google WHERE id = :id"), {"id": category_id}
        ).first()
        if row is not None:
            name, path = str(row[0] or ""), str(row[1] or "")
    except Exception:  # noqa: BLE001
        db.rollback()
    value = {"google_category_id": category_id, "name": name, "path": path, "name_zh": "", "confidence": "medium"}
    source = {
        "kind": "precedent",
        "ref": f"店里同类先例 {count} 个(如 {example_sku})",
        "raw": f"中心词都是「{head}」的产品绑在这个类目",
    }
    return _field(value, sources=[source], note="沿用店里同类产品的类目")


def _category_field(db: Session, text: str, classifier: ClassifierFn) -> dict[str, Any]:
    try:
        verdict = classifier(db, text)
    except Exception as exc:  # noqa: BLE001 —— 类目判不出来不拖垮整份档案,标出来给老板
        logger.warning("dossier category classify failed: %s", exc)
        return _field(None, status="missing", note="类目判定没接通,等老板选")
    chosen = getattr(verdict, "chosen", None)
    status = getattr(verdict, "status", None)
    if status != "ok" or chosen is None:
        # 「没接通」和「真没有合适的」要分开说——之前一律写成后者,把分类器的 bug 藏了起来。
        if status == "offline":
            note = "类目判定这一步没接通(AI 没回话),等老板选"
        else:
            keywords = ", ".join(getattr(getattr(verdict, "hint", None), "keywords_en", None) or [])
            shortlist = getattr(verdict, "shortlist_size", None)
            note = f"没找到合适的谷歌类目(关键词:{keywords or '无'};候选 {shortlist if shortlist is not None else '?'} 个),等老板选"
        return _field(None, status="missing", note=note)
    confidence = str(getattr(verdict, "confidence", "low") or "low")
    value = {
        "google_category_id": str(chosen.id),
        "name": chosen.name,
        "path": " > ".join(getattr(verdict, "path", None) or [chosen.full_path]),
        "name_zh": getattr(chosen, "name_zh", ""),
        "confidence": confidence,
    }
    source = {"kind": "classifier", "ref": "殷承岳的类目判定", "raw": _clean(getattr(verdict, "reason_zh", ""))[:300]}
    if confidence == "low":
        return _field(value, sources=[source], status="needs_owner", note="把握不大,老板确认一下类目")
    return _field(value, sources=[source])


# ---------------------------------------------------------------- 读图情况 → 标红


def _image_read_summary(capture: dict[str, Any], image_read: dict[str, Any] | None, stats: dict[str, int]) -> dict[str, Any]:
    read = image_read or {}
    return {
        "images": len(capture.get("detail_images") or []),
        "segments_seen": read.get("segments_seen"),
        "segments_read": read.get("segments_read"),
        "images_failed": read.get("images_failed") or 0,
        "stopped_reason": read.get("stopped_reason"),
        "reader_role": read.get("reader_role"),
        "cost_usd": read.get("cost_usd"),
        "cost_basis": read.get("cost_basis"),
        "facts": len(read.get("facts") or []),
        "ignored_other": stats.get("ignored_other", 0),
        "ignored_narrative": stats.get("ignored_narrative", 0),
        "ignored_drawing": stats.get("ignored_drawing", 0),
        "ignored_unit": stats.get("ignored_unit", 0),
        "detail_error": capture.get("detail_error"),
    }


def _image_read_flag(summary: dict[str, Any]) -> dict[str, str] | None:
    """详情图没读全要说出来:取不到、被预算截停、额度用完被降级。卖家本来就没放图不算问题。"""
    if summary.get("detail_error"):
        note = f"{summary['detail_error']};这份档案的规格只来自页面数据,可以点「重新整理」再试"
    elif summary.get("stopped_reason") == "budget":
        note = f"详情图只读了 {summary.get('segments_seen')} 段就到了单份预算上限,后面的没读"
    elif summary.get("stopped_reason") == "degraded":
        note = "读图时 Claude 当天额度用完了,后面的图没读;明天点「重新整理」"
    else:
        return None
    return {"path": "detail_images", "label": FIELD_LABELS_ZH["detail_images"], "status": "missing", "note": note}


# ---------------------------------------------------------------- 主入口


def build_draft(
    db: Session,
    capture: dict[str, Any],
    image_read: dict[str, Any] | None,
    *,
    writer: WriterFn | None = None,
    classifier: ClassifierFn | None = None,
) -> dict[str, Any]:
    writer = writer or _default_writer
    classifier = classifier or _default_classifier
    facts = list((image_read or {}).get("facts") or [])
    title_zh = _clean(capture.get("title_zh"))

    variants = build_variants(capture)
    stats: dict[str, int] = {}
    specs, other = merge_specs(capture, facts, variants=variants, stats=stats)
    # 批发外箱的装箱信息(「一箱 12 盒 144 个」)不是买家收到的东西,不进包装清单;别的商品的配件也不算。
    package_facts = [
        f for f in facts
        if _clean(f.get("field")).casefold() in PACKAGE_FIELDS
        and f.get("scope") != "carton"
        and (f.get("subject") or "this") != "other"
    ]

    fields: dict[str, dict[str, Any]] = {}
    fields["name_zh"] = (
        _field(title_zh, sources=[{"kind": "page_text", "ref": "商品标题", "raw": title_zh[:300]}])
        if title_zh
        else _field(None, status="missing", note="页面上没拿到标题")
    )

    # 一次 writer 调用:英文品名 + 变体英文名 + 包装清单英文。
    writer_payload = {
        "title_zh": title_zh,
        "facts": {k: v["value"] for k, v in specs.items() if v["status"] == "ok"},
        "other_attributes": other[:20],
        "variant_names": [v["name_zh"] for v in variants],
        "package_facts": [f"{_clean(f.get('value'))} {_clean(f.get('raw_text'))}".strip() for f in package_facts],
    }
    written: dict[str, Any] | None = None
    if title_zh:
        try:
            written = writer(writer_payload)
        except Exception as exc:  # noqa: BLE001 —— 英文名写不出来就空着,标 missing,不编
            logger.warning("dossier writer failed: %s", exc)
            written = None
    # 提示词要求 ≤75 字;硬上限放到 120——模型偶尔超一点,宁可长一点也别在半截处截断(10-23 首测出现「…, 12」)。
    name_en = _english_ok((written or {}).get("name_en"), 120)
    writer_source = {"kind": "writer", "ref": "据事实改写", "raw": ""}
    fields["name_en"] = (
        _field(name_en, sources=[writer_source]) if name_en
        else _field(None, status="missing", note="英文品名没写出来,等老板或下一轮补")
    )
    names = (written or {}).get("variant_names")
    if isinstance(names, list) and len(names) == len(variants):
        for variant, name in zip(variants, names, strict=True):
            variant["name_en"] = _english_ok(name, 60)

    is_variable = len(variants) > 1
    fields["product_type"] = _field(
        "variable_product" if is_variable else "simple_product",
        sources=[{"kind": "page_json", "ref": "SKU 列表", "raw": f"{len(variants)} 个 SKU"}],
    )

    moq = capture.get("moq")
    fields["moq"] = _field(moq, unit=_clean(capture.get("unit")) or None,
                           sources=[{"kind": "page_json", "ref": "起批量", "raw": str(moq)}]) if moq else _field(None, status="missing")
    pricing = pricing_summary(capture, variants)
    fields["retail_price"] = _field(
        None, unit="USD", status="needs_owner",
        note=f"1688 只有进价({pricing['text']}),美国售价请老板定",
    )

    package_en = [item for item in ((written or {}).get("package_includes") or []) if _english_ok(item, 120)]
    if package_en and package_facts:
        fields["package_includes"] = _field([_english_ok(i, 120) for i in package_en],
                                            sources=[_image_source(f) for f in package_facts])
    else:
        fields["package_includes"] = _field(None, status="missing", note="页面和详情图里都没找到包装清单")

    category_text = " ".join(
        part for part in [title_zh, *(f"{SPEC_LABELS_ZH.get(k, k)} {v['value']}" for k, v in specs.items() if v["status"] == "ok")] if part
    )
    if not title_zh:
        fields["category"] = _field(None, status="missing")
    else:
        precedent = _precedent_category(db, (fields.get("name_en") or {}).get("value"))
        fields["category"] = precedent or _category_field(db, category_text, classifier)

    reference_images: list[str] = []
    for url in [*(capture.get("gallery_images") or [])[:3], *(v["image_url"] for v in variants if v.get("image_url"))]:
        if _host_ok(url) and url not in reference_images:
            reference_images.append(url)
    reference_images = reference_images[:8]

    reading = _image_read_summary(capture, image_read, stats)
    flagged: list[dict[str, str]] = []
    for name, item in fields.items():
        if item["status"] != "ok":
            flagged.append({"path": name, "label": FIELD_LABELS_ZH.get(name, name), "status": item["status"], "note": item["note"]})
    for key, item in specs.items():
        if item["status"] != "ok":
            flagged.append({"path": f"specs.{key}", "label": SPEC_LABELS_ZH.get(key, key), "status": item["status"], "note": item["note"]})
    reading_flag = _image_read_flag(reading)
    if reading_flag:
        flagged.append(reading_flag)

    conflicts = sum(1 for f in flagged if f["status"] == "conflict")
    missing = sum(1 for f in flagged if f["status"] == "missing")
    owner = sum(1 for f in flagged if f["status"] == "needs_owner")
    summary = (
        f"{title_zh[:30] or '这个品'}:{len(variants)} 个规格,整理出规格 {sum(1 for v in specs.values() if v['status'] == 'ok')} 项;"
        f"标红 {len(flagged)} 项(说法不一 {conflicts}、没找到 {missing}、要老板定 {owner})。"
    )
    return {
        "version": DRAFT_VERSION,
        "offer_id": capture.get("offer_id"),
        "source_url": capture.get("url"),
        "fields": fields,
        "specs": specs,
        "variants": variants,
        "pricing": pricing,
        "price_tiers": pricing["tiers"],
        "reference_images": reference_images,
        "other_attributes": other,
        "supplier": capture.get("supplier") or {},
        "image_read": reading,
        "flagged": flagged,
        "flagged_count": len(flagged),
        "summary_zh": summary,
    }
