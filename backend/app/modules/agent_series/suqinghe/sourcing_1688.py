"""把一个 1688 商品链接读成结构化数据(苏青禾「1688 → K 档案」的抓取段)。

为什么不用官方接口(2026-10-23 实测):`alibaba.cross.productInfo` 返回
``gw.APIACLDecline``——要开寻源通权限组(月采购 12 万门槛)。而不登录用无头浏览器
打开详情页,页面里内嵌的 ``window.context`` 数据就带着标题、属性表、SKU、阶梯价、
每个 SKU 的重量尺寸、主图;详情长图另走 ``detailUrl``(itemcdn.tmall.com),
普通 HTTP 带 1688 的 Referer 就能取到。

分三层,方便测试:
- ``parse_capture`` 纯函数:给 HTML / 页面文本 / 详情描述,吐出 ``Capture``,不联网;
- ``fetch_offer`` 联网:开页面、取详情描述,再交给 ``parse_capture``;
- ``read_detail_images`` 看图:详情长图切段 →(可选分拣)→ 逐段转录;读图档见 ``reader_settings``。

家规:读不到就空着,不猜。页面里没有的字段一律 None,零值(1688 用 0 表示没填)也算没有。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REFERER = "https://detail.1688.com/"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_HOST_SUFFIX = ".alicdn.com"

# 看图花费:预算闸按台账实数算(ai_usage_ledger,每次调用都记 token 和美元)。
# 这几个数只用来预估「下一次调用大概多少钱」,以及台账读不到时兜底——
# 10-26 之前整份花费都按估算记($0.05/次 Opus),是实际的 3 倍多,读到 9/17 段就被自己的估算撞停。
# 实测(10-26 台账,带商品背景的提示词):Haiku 5.5 一段约 $0.0004,Opus 5.5 一段约 $0.012。
CALL_EST_USD = {"fast": 0.001, "judge": 0.02, "writer": 0.02}

# 数字描述的是哪一层:同一个「重量」,单品 200 克和一整盒 2500 克不是矛盾(10-23 首测踩到)。
FACT_SCOPES = ("item", "inner_pack", "carton", "unknown")
# 这条事实说的是谁:this = 这件商品;other = 兼容机型表、同店别的型号、对比图里的别家(10-26 电池那单
# 把一张「18V/21V/24V、4.0Ah/6.0Ah」的别款电池图全当成了本品参数);unsure = 看不出。
FACT_SUBJECTS = ("this", "other", "unsure")

FACT_FIELDS = (
    "material",
    "dimensions",
    "weight",
    "capacity",
    "voltage",
    "power",
    "battery_type",
    "charging",
    "runtime",
    "cycle_life",
    "age_range",
    "package_includes",
    "color_options",
    "certification",
    "other",
)

_OFFER_PATH = re.compile(r"/offer/(\d{6,})(?:\.html)?", re.I)
_BLOCK_URL_MARKERS = ("login.1688.com", "login.taobao.com", "punish", "_____tmd_____", "x5sec", "/sec/", "captcha")
_BLOCK_TITLE_MARKERS = ("验证码", "滑块", "安全验证", "访问被拒绝", "请稍后再试", "拦截", "Access Denied", "登录")
_IMG_URL = re.compile(r"https?://cbu01\.alicdn\.com/img/ibank/[^\"'\s\\)<>]+?\.(?:jpg|jpeg|png|webp)", re.I)


# ---------------------------------------------------------------- 链接


def parse_offer_id(url: str) -> str | None:
    """从各种形态的 1688 链接里取 offer id;不是 1688 商品页(含登录/拦截页)返回 None。"""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not (host == "1688.com" or host.endswith(".1688.com")):
        return None
    if host.startswith("login.") or any(m in raw.lower() for m in ("punish", "_____tmd_____", "x5sec")):
        return None
    match = _OFFER_PATH.search(parsed.path or "")
    if match:
        return match.group(1)
    query = parse_qs(parsed.query or "")
    for key in ("offerId", "offerid", "id"):
        for value in query.get(key, []):
            if re.fullmatch(r"\d{6,}", value.strip()):
                return value.strip()
    return None


def offer_url(offer_id: str) -> str:
    return f"https://detail.1688.com/offer/{offer_id}.html"


# ---------------------------------------------------------------- 数据


@dataclass
class Capture:
    offer_id: str | None
    url: str
    title_zh: str | None = None
    supplier: dict[str, Any] = field(default_factory=dict)
    attributes: list[dict[str, str]] = field(default_factory=list)
    sku_props: list[dict[str, Any]] = field(default_factory=list)
    skus: list[dict[str, Any]] = field(default_factory=list)
    price_tiers: list[dict[str, Any]] = field(default_factory=list)
    moq: int | None = None
    unit: str | None = None
    sold_count: int | None = None
    gallery_images: list[str] = field(default_factory=list)
    detail_url: str | None = None
    detail_images: list[str] = field(default_factory=list)
    # 详情描述取不到时写原因。之前取不到就悄悄当成「卖家没放图」(10-26 电钻一单),老板根本不知道少读了一块。
    detail_error: str | None = None
    category_zh: str | None = None
    # 1688 两种定价:sku = 每个规格各有价(skuInfoMap),页面那两个价只是最低/最高;
    # range = 所有规格同价、按件数分档(阶梯价)。10-26 之前把 sku 定价的区间当成了阶梯价。
    price_mode: str | None = None
    price_range: list[float] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_image_url(url: str) -> str | None:
    value = (url or "").strip()
    if not value:
        return None
    if value.startswith("//"):
        value = "https:" + value
    value = value.replace("http://", "https://", 1)
    # 1688 在原图后面拼尺寸后缀:xxx.jpg_.webp / xxx.jpg_sum.jpg / xxx.jpg_310x310.jpg
    value = re.sub(r"(\.(?:jpg|jpeg|png|webp))_[^/]*$", r"\1", value, flags=re.I)
    return value


def _dedupe_images(urls: list[Any]) -> list[str]:
    out: list[str] = []
    for raw in urls:
        url = normalize_image_url(str(raw or ""))
        if url and url not in out:
            out.append(url)
    return out


def _extract_context(html: str) -> dict[str, Any] | None:
    """``window.context=(function(b,d){...})(window.contextPath,{...})`` 里的第二个参数。

    它是 JS 对象字面量,不是严格 JSON:出现过数字键(``{6282996026795:0.2}``),
    先给数字键补引号再解析;``$ref`` 节点原样保留,用 ``_resolve_ref`` 按需展开。
    """
    start = html.find("window.context=(function")
    if start < 0:
        return None
    marker = "(window.contextPath,"
    arg = html.find(marker, start)
    if arg < 0:
        return None
    body = html[arg + len(marker):]
    candidates = [body, re.sub(r"([{,])(-?\d+):", r'\1"\2":', body)]
    for candidate in candidates:
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate.lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _resolve_ref(root: dict[str, Any], node: Any) -> Any:
    if not (isinstance(node, dict) and isinstance(node.get("$ref"), str)):
        return node
    path = node["$ref"]
    if not path.startswith("$"):
        return None
    current: Any = root
    for part in re.findall(r"\.([A-Za-z0-9_]+)|\[(\d+)\]", path[1:]):
        key, index = part
        try:
            current = current[key] if key else current[int(index)]
        except (KeyError, IndexError, TypeError):
            return None
    return current


def _dig(obj: Any, *path: str) -> Any:
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _positive_number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: Any) -> int | None:
    number = _positive_number(value)
    return int(number) if number is not None else None


def _text_attributes(text: str) -> list[dict[str, str]]:
    """没有页面数据时,从页面文本「商品属性」块里按「键/值」逐行配对。"""
    lines = [line.strip() for line in (text or "").splitlines()]
    # 「商品属性」在页面上出现不止一次(导航标签里也有),取配出最多对的那一段。
    best: list[dict[str, str]] = []
    for start, line in enumerate(lines):
        if line != "商品属性":
            continue
        out: list[dict[str, str]] = []
        pending: str | None = None
        for current in lines[start + 1:]:
            if current in {"包装信息", "商品详情", "热门推荐", "商品属性"}:
                break
            if not current:
                continue
            if pending is None:
                pending = current
            else:
                out.append({"name": pending, "value": current, "source": "page_text"})
                pending = None
        if len(out) > len(best):
            best = out
    return best


def _desc_images(desc_js: str | None) -> list[str]:
    if not desc_js:
        return []
    content = desc_js
    match = re.search(r"offer_details\s*=\s*(\{.*\})\s*;?\s*$", desc_js.strip(), re.S)
    if match:
        try:
            content = str(json.loads(match.group(1)).get("content") or desc_js)
        except json.JSONDecodeError:
            content = desc_js
    return _dedupe_images(_IMG_URL.findall(content.replace("\\/", "/")))


def parse_capture(*, url: str, html: str, text: str, desc_js: str | None) -> Capture:
    """纯函数:页面 HTML + 页面文本 + 详情描述 → Capture。不联网、不调用 AI。"""
    capture = Capture(offer_id=parse_offer_id(url), url=url)
    root = _extract_context(html or "")
    result = _dig(root, "result") if root else None
    data = _dig(result, "data") or {}
    model = _dig(result, "global", "globalData", "model") or {}
    offer = model.get("offerDetail") if isinstance(model, dict) else None
    offer = offer if isinstance(offer, dict) else {}
    trade = model.get("tradeModel") if isinstance(model, dict) else None
    trade = trade if isinstance(trade, dict) else {}

    capture.offer_id = capture.offer_id or (str(offer.get("offerId")) if offer.get("offerId") else None)
    title = offer.get("subject") or _dig(data, "productTitle", "fields", "title")
    if not title:
        match = re.search(r"<title>(.*?)</title>", html or "", re.S)
        title = re.sub(r"\s*-\s*阿里巴巴\s*$", "", match.group(1)).strip() if match else None
    capture.title_zh = str(title).strip() if title else None
    capture.category_zh = str(offer.get("leafCategoryName") or "") or None

    # 供应商
    seller = model.get("sellerModel") if isinstance(model, dict) else None
    shop = _dig(data, "productTitle", "fields", "shopInfo") or {}
    supplier: dict[str, Any] = {}
    name = (seller or {}).get("companyName") or shop.get("companyName")
    if name:
        supplier["name"] = str(name)
    if shop.get("cardType"):
        supplier["type"] = str(shop["cardType"])
    years = re.search(r"入驻(\d+)年", text or "")
    if years:
        supplier["years"] = int(years.group(1))
    location = re.search(r"\n([一-鿿]{2,8})\n送至", text or "")
    if location:
        supplier["location"] = location.group(1)
    if (seller or {}).get("winportUrl"):
        supplier["shop_url"] = str(seller["winportUrl"])
    capture.supplier = supplier

    # 属性:页面数据优先,文本兜底
    attributes: list[dict[str, str]] = []
    for item in offer.get("featureAttributes") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        values = item.get("values") or ([item["value"]] if item.get("value") else [])
        value = "、".join(str(v) for v in values if str(v).strip())
        if value:
            attributes.append({"name": str(item["name"]).strip(), "value": value, "source": "page_json"})
    capture.attributes = attributes or _text_attributes(text)

    # SKU 维度(规格名 + 每个规格的图)
    sku_props: list[dict[str, Any]] = []
    image_by_name: dict[str, str] = {}
    for prop in offer.get("skuProps") or []:
        if not isinstance(prop, dict):
            continue
        values = []
        for value in prop.get("value") or []:
            if not isinstance(value, dict) or not value.get("name"):
                continue
            image = normalize_image_url(str(value.get("imageUrl") or ""))
            values.append({"name": str(value["name"]), "image_url": image})
            if image:
                image_by_name[str(value["name"])] = image
        sku_props.append({"prop": str(prop.get("prop") or ""), "values": values})
    capture.sku_props = sku_props

    # 每个 SKU 的重量尺寸
    pack: dict[str, dict[str, Any]] = {}
    pack_by_id: dict[str, dict[str, Any]] = {}
    pack_info = _dig(data, "productPackInfo", "fields", "pieceWeightScale", "pieceWeightScaleInfo") or []
    for row in pack_info:
        if not isinstance(row, dict):
            continue
        if row.get("skuId"):
            pack_by_id[str(row["skuId"])] = row
        names = [str(row[k]) for k in sorted(row) if re.fullmatch(r"sku\d+", k) and row.get(k)]
        if names:
            pack[">".join(names)] = row
            pack.setdefault(names[0], row)

    # 定价方式 + 每个规格的价:按规格定价的商品,价格在 skuInfoMap(按规格名索引),tradeModel.skuMap 里没有。
    price_model_main = _dig(data, "mainPrice", "fields", "priceModel") or {}
    trade_price_model = trade.get("offerPriceModel") if isinstance(trade.get("offerPriceModel"), dict) else {}
    sku_param = _dig(data, "Root", "fields", "dataJson", "orderParamModel", "orderParam", "skuParam") or {}
    mode_raw = (
        price_model_main.get("priceDisplayType")
        or trade_price_model.get("priceDisplayType")
        or sku_param.get("skuPriceType")
    )
    capture.price_mode = {"skuPrice": "sku", "rangePrice": "range"}.get(str(mode_raw or ""))
    sku_info = _dig(data, "Root", "fields", "dataJson", "skuModel", "skuInfoMap") or {}
    sku_info = sku_info if isinstance(sku_info, dict) else {}

    skus: list[dict[str, Any]] = []
    sku_rows = trade.get("skuMap")
    if isinstance(sku_rows, dict):
        sku_rows = [{"specAttrs": key, **value} for key, value in sku_rows.items() if isinstance(value, dict)]
    for row in sku_rows or []:
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("specAttrs") or "")
        name = raw_name.replace("&gt;", ">").strip()
        if not name:
            continue
        weights = pack_by_id.get(str(row.get("skuId"))) or pack.get(name) or {}
        # 多维规格(颜色>款式)的图挂在某一维上,逐段找。
        image = image_by_name.get(name) or next(
            (image_by_name[part.strip()] for part in name.split(">") if part.strip() in image_by_name), None
        )
        # skuMap 里的 priceAmount 含义不明(实测 12 而阶梯价是 3.30),不当价格用;
        # 只认显式的 price / discountPrice:先看这一行,再看 skuInfoMap 里同名的那条。
        info = sku_info.get(raw_name) or sku_info.get(name) or {}
        info = info if isinstance(info, dict) else {}
        price = (
            _positive_number(row.get("discountPrice"))
            or _positive_number(row.get("price"))
            or _positive_number(info.get("discountPrice"))
            or _positive_number(info.get("price"))
        )
        skus.append(
            {
                "name": name,
                "sku_id": str(row.get("skuId")) if row.get("skuId") else None,
                "price_cny": price,
                "stock": _positive_int(row.get("canBookCount")),
                "weight_g": _positive_number(weights.get("weight")),
                "length_cm": _positive_number(weights.get("length")),
                "width_cm": _positive_number(weights.get("width")),
                "height_cm": _positive_number(weights.get("height")),
                "image_url": image,
            }
        )
    if not skus:
        for name, weights in pack.items():
            skus.append(
                {
                    "name": name,
                    "sku_id": str(weights.get("skuId")) if weights.get("skuId") else None,
                    "price_cny": None,
                    "stock": None,
                    "weight_g": _positive_number(weights.get("weight")),
                    "length_cm": _positive_number(weights.get("length")),
                    "width_cm": _positive_number(weights.get("width")),
                    "height_cm": _positive_number(weights.get("height")),
                    "image_url": image_by_name.get(name),
                }
            )
    capture.skus = skus

    # 价格:按规格定价 → 页面上那两个价是「最低—最高」区间,不是阶梯;阶梯定价 → 按件数分档。
    shown_prices = (
        price_model_main.get("currentPricesWithOnePiece")
        or price_model_main.get("currentPrices")
        or trade_price_model.get("currentPricesWithOnePiece")
        or trade_price_model.get("currentPrices")
        or trade.get("disPriceRanges")
        or []
    )
    entries: list[tuple[int | None, float]] = []
    for entry in shown_prices:
        entry = _resolve_ref(root or {}, entry)
        if not isinstance(entry, dict):
            continue
        price = _positive_number(entry.get("price") or entry.get("discountPrice"))
        if price:
            entries.append((_positive_int(entry.get("beginAmount")), price))
    tiers: list[dict[str, Any]] = []
    if capture.price_mode == "sku":
        sku_prices = [s["price_cny"] for s in skus if s.get("price_cny")]
        pool = sku_prices or [price for _, price in entries]
        capture.price_range = [min(pool), max(pool)] if pool else []
    else:
        for qty, price in entries:
            if qty and not any(t["min_qty"] == qty for t in tiers):
                tiers.append({"min_qty": qty, "price_cny": price})
    capture.price_tiers = sorted(tiers, key=lambda t: t["min_qty"])

    first_qty = next((qty for qty, _ in entries if qty), None)
    capture.moq = (
        _positive_int(trade.get("beginAmount"))
        or (capture.price_tiers[0]["min_qty"] if capture.price_tiers else None)
        or first_qty
    )
    unit = trade.get("unit") or _dig(data, "productTitle", "fields", "unit")
    capture.unit = str(unit) if unit else None
    sold = re.search(r'"saledCount":\s*(\d+)', html or "")
    capture.sold_count = int(sold.group(1)) if sold else None

    gallery = _dig(data, "gallery", "fields", "offerImgList") or []
    if not gallery:
        gallery = [img.get("fullPathImageURI") for img in offer.get("mainImageList") or [] if isinstance(img, dict)]
    capture.gallery_images = _dedupe_images(list(gallery))

    detail_url = offer.get("detailUrl") or _dig(data, "description", "fields", "detailUrl")
    capture.detail_url = str(detail_url) if detail_url else None
    capture.detail_images = _desc_images(desc_js)
    return capture


# ---------------------------------------------------------------- 拦截判断


def detect_blocked(*, final_url: str, title: str, html: str) -> str | None:
    """被 1688 拦了返回原因,正常返回 None。

    正常页面的脚本里本来就有 ``login.taobao``、``baxia`` 这些字样,不能单凭它们判拦截;
    看的是:最终地址、标题里的拦截字样,以及页面里有没有商品数据。
    """
    lowered_url = (final_url or "").lower()
    for marker in _BLOCK_URL_MARKERS:
        if marker in lowered_url:
            return f"redirected:{marker}"
    if parse_offer_id(final_url or "") is None:
        return "not_an_offer_page"
    for marker in _BLOCK_TITLE_MARKERS:
        if marker in (title or ""):
            return f"title:{marker}"
    page = html or ""
    if "window.context" not in page or ('"offerDetail"' not in page and '"skuMap"' not in page):
        if any(m in page for m in ("nc_1_n1z", "baxia-dialog", "punish-component", "验证码", "滑动验证")):
            return "captcha_page"
        return "no_product_data"
    return None


# ---------------------------------------------------------------- 联网


def _http_get_text(url: str, *, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA, "Referer": REFERER})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 —— 只取 1688/tmall 详情描述
        return response.read(4 * 1024 * 1024).decode("utf-8", "replace")


def _render_page(url: str, timeout_s: float) -> tuple[str, str, str, str]:
    """在独立线程里跑同步 Playwright(调用方可能带着事件循环)。返回 (最终地址, 标题, html, 文本)。
    10-27 起通用渲染搬到 common/webpage.render_raw(竞品页也用它);1688 这边保持中文 locale、滚 10 次、多等一会。
    10-28 起开了 SQH_BROWSER 就走她的常驻登录浏览器(browser.py),被拦时页面留着等老板。"""
    from . import browser

    if browser.enabled():
        return browser.get().fetch_offer_html(url, timeout_s)
    from ..common import webpage

    return webpage.render_raw(url, timeout_s=timeout_s, locale="zh-CN", scroll=10, wait_ms=2500)


def capture_from_render(*, offer_id: str, target: str, final_url: str, title: str, html: str, text: str) -> Capture:
    """渲染结果 → Capture:判拦截、解析页面、再去取详情描述。老板过完验证的页面也走这一段。"""
    reason = detect_blocked(final_url=final_url, title=title, html=html)
    if reason:
        return Capture(offer_id=offer_id, url=target, title_zh=title or None, blocked=True, block_reason=reason)
    capture = parse_capture(url=target, html=html, text=text, desc_js=None)
    if capture.detail_url:
        desc, error = fetch_detail_description(capture.detail_url)
        capture.detail_images = _desc_images(desc)
        capture.detail_error = error
    else:
        capture.detail_error = "页面里没找到详情描述的地址"
    return capture



def fetch_offer(url: str, *, timeout_s: float = 25) -> Capture:
    offer_id = parse_offer_id(url)
    if offer_id is None:
        return Capture(offer_id=None, url=url, blocked=True, block_reason="not_a_1688_offer_url")
    target = offer_url(offer_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        # 正常一页 43–48 秒(启动浏览器+滚动+重试取内容);10-26 实测 +40 余量偶发超时,放到 +80。
        final_url, title, html, text = pool.submit(_render_page, target, timeout_s).result(timeout=timeout_s + 80)
    capture = capture_from_render(offer_id=offer_id, target=target, final_url=final_url, title=title, html=html, text=text)
    if capture.blocked and capture.block_reason:
        from . import browser
        from .constants import NEEDS_HUMAN

        if browser.enabled():
            # 页面不关:进 needs_human,办公室面板里老板过滑块/扫码,页面恢复了她自己接着做(dossiers.resume_human)
            browser.get().hold_for_human(capture.block_reason)
            capture.block_reason = NEEDS_HUMAN + capture.block_reason
    return capture


def fetch_detail_description(
    url: str,
    *,
    get: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> tuple[str | None, str | None]:
    """取详情描述(里面是详情长图的地址)。返回 (内容, 取不到的原因)。

    取不到不影响主数据,但**必须说出来**:10-26 电钻那单第一次取失败,被当成「卖家没放图」,
    档案上一个字没提,整块详情图没读。
    """
    get = get or _http_get_text
    last = ""
    for attempt in range(max(1, attempts)):
        try:
            return get(url), None
        except Exception as exc:  # noqa: BLE001 —— 网络抖动重试,最后把原因带回去
            last = f"{exc.__class__.__name__}: {str(exc)[:120]}".strip(": ")
            if attempt + 1 < attempts:
                sleep(2.0 * (attempt + 1))
    return None, f"详情图清单取了 {attempts} 次都没取到({last})"


# ---------------------------------------------------------------- 看图


def slice_image(
    data: bytes,
    *,
    max_width: int = 1000,
    segment_height: int = 1100,
    overlap: int = 80,
    max_segments: int = 24,
) -> list[bytes]:
    """长图切段:先按宽度缩到 max_width,再按高度切,段间重叠 overlap 像素。

    模型会把大图整体缩小再看,一张 790×8000 的详情长图整张送进去字就糊了。
    """
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image = image.convert("RGB")
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * ratio))), Image.LANCZOS)
    step = max(1, segment_height - overlap)
    tops = [0]
    while tops[-1] + segment_height < image.height and len(tops) < max_segments:
        tops.append(tops[-1] + step)
    out: list[bytes] = []
    for top in tops:
        box = (0, top, image.width, min(image.height, top + segment_height))
        buffer = io.BytesIO()
        image.crop(box).save(buffer, "JPEG", quality=85)
        out.append(buffer.getvalue())
    return out


def download_image(url: str, *, timeout: float = 20.0) -> bytes | None:
    """只下 alicdn 的图,带 1688 Referer,超过 20MB 放弃。"""
    host = (urlparse(url).hostname or "").lower()
    if not host.endswith(IMAGE_HOST_SUFFIX):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA, "Referer": REFERER})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 —— 已限定 alicdn
            body = response.read(MAX_IMAGE_BYTES + 1)
    except Exception:  # noqa: BLE001 —— 单张图下不来就跳过,结果里会少这一张
        return None
    if len(body) > MAX_IMAGE_BYTES:
        return None
    return body


_TRIAGE_PROMPT = (
    "这是一个 1688 商品详情页长图的其中一段。判断它是否包含可抄录的商品事实:"
    "参数表、尺寸图、重量、材质、容量/电压/功率/电池、适用年龄、包装清单/配件、颜色款式表、认证。"
    "纯氛围图、模特图、营销口号不算。"
    'Only reply JSON: {"useful": true|false, "kind": "specs|size|package|material|certification|colors|none"}'
)

_EXTRACT_RULES = (
    "你在读一张 1688 商品详情长图的其中一段,任务是抄录图上**印着的、关于这件商品本身**的规格事实。\n\n"
    "规则:\n"
    "1. 只抄图上真实印着的文字和数字;看不清、图上没有的不写;不推测、不换算、不补全。\n"
    "2. 每条事实标 subject:this = 这件商品(或它的某个规格/SKU);other = 别的商品"
    "(兼容机型表、同店其他型号或其他容量、对比图里的别家、示意用的其他产品);unsure = 看不出。\n"
    "3. 事实只属于某一个 SKU 时(比如某个容量、某个颜色),variant 填那个 SKU 的名字(照上面的列表原样写);"
    "适用于整件商品就留空。\n"
    "4. value 只写规格值本身,要短(不超过 30 个字),例如「12V」「2000mAh」「阻燃ABS」「84×48×40」。"
    "广告语、口号、形容词(稳定性高、足容不虚标、超长续航、品质保证、工业级)一律不抄。\n"
    "5. 尺寸:整体外形尺寸作为**一条**事实,长×宽×高写在一起(如「84×48×40」,unit 写 mm 或 cm);"
    "尺寸图上零件的单个标注(按钮直径、接口宽度)不抄。\n"
    "6. 重量和尺寸标 scope:item = 单个产品本身;inner_pack = 一个销售包装(买家收到的那一份);"
    "carton = 批发外箱/装箱信息;unknown = 看不出。例如「一个约200克」是 item,「一大盒约2500克」是 inner_pack 或 carton。\n"
    "7. field 只能是:" + "、".join(FACT_FIELDS) + "。电压写 voltage,容量写 capacity,电芯/电池类型写 battery_type,"
    "充电接口或充电时间写 charging,续航/使用时间写 runtime,循环次数写 cycle_life,认证写 certification,"
    "包装清单/配件写 package_includes,颜色款式写 color_options。\n\n"
    "Transcribe ONLY facts literally printed in this image segment about THIS product. Never guess, convert or infer.\n"
    'Reply JSON only: {"facts": [{"field": "...", "value": "as printed", "unit": "as printed or empty", '
    '"raw_text": "the exact printed text", "subject": "this|other|unsure", "variant": "SKU name or empty", '
    '"scope": "item|inner_pack|carton|unknown", "confidence": "high|medium|low"}]}. Empty list if nothing.'
)


def product_context(capture: Capture | dict[str, Any]) -> str:
    """给读图模型的背景:这件商品是什么、有哪些规格、页面属性表写了什么——它才分得清图上哪些是本品。"""
    data = capture if isinstance(capture, dict) else capture.to_dict()
    title = str(data.get("title_zh") or "").strip() or "(没拿到)"
    skus = [str(s.get("name") or "").strip() for s in data.get("skus") or [] if isinstance(s, dict)]
    attrs = [
        f"{a.get('name')}:{a.get('value')}"
        for a in (data.get("attributes") or [])[:30]
        if isinstance(a, dict) and a.get("name") and a.get("value")
    ]
    return (
        "这件商品(来自 1688 页面数据,帮你判断图上哪些是它、哪些不是):\n"
        f"标题:{title[:120]}\n"
        f"规格选项(SKU):{'、'.join(s for s in skus[:40] if s) or '(只有一个规格)'}\n"
        f"页面属性表:{';'.join(attrs)[:1500] or '(没有)'}"
    )


def extract_prompt(capture: Capture | dict[str, Any]) -> str:
    return product_context(capture) + "\n\n" + _EXTRACT_RULES


# 10-26 三个真链接(电池 / 灭蚊灯 / 电钻,共 65 段)同一批图段对比,标准答案是逐段人工看图定的:
#   Opus 5.5    关键参数 18/18,3 处会造成假标红(电芯隔离膜、挂钩、全铜电机当材质),$0.76
#   Sonnet 5.5  关键参数 17/18(漏纸盒尺寸),0 处,$0.31
#   Haiku 5.5   关键参数 18/18,0 处(小错都自标把握低,合并时不标红),$0.02
# 三个都把「别款电池图」标成了别的商品、都没上「别家工具上的 20V」的当 —— 管用的是提示词里的商品背景。
# 所以默认 fast(Haiku 5.5),不分拣、每段直接读。
DEFAULT_READER_ROLE = "fast"


def reader_settings() -> tuple[str, bool]:
    """读详情图用哪个档、要不要先分拣。换档只改环境变量 SQH_1688_READER_ROLE,不动代码。

    分拣只在读图档比分拣档贵的时候才划算:SQH_1688_TRIAGE=auto(默认)= 读图档不是 fast 才分拣。
    """
    role = os.getenv("SQH_1688_READER_ROLE", DEFAULT_READER_ROLE).strip().lower() or DEFAULT_READER_ROLE
    return role, _triage_for(role)


def _triage_for(role: str) -> bool:
    triage_env = os.getenv("SQH_1688_TRIAGE", "auto").strip().lower()
    return role != "fast" if triage_env in {"", "auto"} else triage_env in {"1", "true", "yes", "on"}


def _data_url(segment: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(segment).decode("ascii")


def _payload(prompt: str, segment: bytes) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _data_url(segment)}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
    }


def _as_json(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and ("facts" in result or "useful" in result):
        return result
    content = result.get("content") if isinstance(result, dict) else result
    if isinstance(content, str):
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _default_router_factory(db: Any) -> Any:
    from ....services.ai_provider_router import AIExecutionRouter

    return AIExecutionRouter(db, timeout_seconds=180.0, total_budget_seconds=240.0)


CostMeter = Callable[[], "float | None"]


def ledger_meter(label: str, since: datetime | None = None) -> CostMeter:
    """台账实数:从 ``since`` 到现在、记在 ``label`` 名下的 AI 花费。读不到返回 None(调用方退回估算)。

    她所有的 AI 调用都在同一个 worker 线程里排队做,读图期间不会混进别的活的花费。
    """
    start = since or datetime.now(UTC)

    def spent() -> float | None:
        from sqlalchemy import text as sql_text

        from ....db.session import SessionLocal

        try:
            with SessionLocal() as session:
                value = session.execute(
                    sql_text("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_usage_ledger WHERE module = :m AND created_at >= :t"),
                    {"m": label, "t": start},
                ).scalar()
            return float(value or 0)
        except Exception:  # noqa: BLE001 —— 台账读不到就按估算走,不挡读图
            return None

    return spent


def _clean_fact(fact: Any, *, image_index: int, segment_index: int) -> dict[str, Any] | None:
    if not isinstance(fact, dict) or not str(fact.get("value") or "").strip():
        return None
    field_name = str(fact.get("field") or "other")
    return {
        "field": field_name if field_name in FACT_FIELDS else "other",
        "value": str(fact.get("value")).strip(),
        "unit": str(fact.get("unit") or "").strip(),
        "raw_text": str(fact.get("raw_text") or "").strip(),
        "subject": fact.get("subject") if fact.get("subject") in FACT_SUBJECTS else "unsure",
        "variant": str(fact.get("variant") or "").strip()[:120],
        "scope": fact.get("scope") if fact.get("scope") in FACT_SCOPES else "unknown",
        "image_index": image_index,
        "segment_index": segment_index,
        "confidence": fact.get("confidence") if fact.get("confidence") in {"high", "medium", "low"} else "low",
    }


def read_detail_images(
    db: Any,
    capture: Capture | dict[str, Any],
    *,
    budget_usd: float = 0.50,
    download: Callable[[str], bytes | None] | None = None,
    router_factory: Callable[[Any], Any] | None = None,
    reader_role: str | None = None,
    triage: bool | None = None,
    meter: CostMeter | None = None,
    usage_label: str | None = None,
    prompt: str | None = None,
    clean: Callable[..., dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """详情长图 → 切段 →(可选分拣)→ 逐段转录。预算闸按台账实数,超预算就停。

    读图档和要不要分拣见 ``reader_settings``;Claude 当天额度用完被降级时立刻停——
    降级档读不了图,读出来的东西不能当事实用。
    默认抄规格事实;``prompt`` + ``clean`` 换掉就是抄别的(卖点素材,见 material.py),回答一律放在 {"facts": [...]} 里。
    """
    from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME

    from .constants import USAGE_LABEL

    label = usage_label or USAGE_LABEL
    role = (reader_role or reader_settings()[0]).strip().lower()
    # 要不要分拣跟着实际用的读图档走(调用方指定了档,就按指定的档算)。
    do_triage = _triage_for(role) if triage is None else triage
    download = download or download_image
    router = (router_factory or _default_router_factory)(db)
    if meter is None:
        meter = ledger_meter(label) if router_factory is None else (lambda: None)
    prompt = prompt or extract_prompt(capture)
    clean = clean or _clean_fact
    facts: list[dict[str, Any]] = []
    seen = read = failed = 0
    estimated = 0.0
    stopped: str | None = None
    basis = "estimate"

    def spent() -> float:
        nonlocal basis
        real = meter()
        if real is None:
            return estimated
        basis = "ledger"
        return real

    def call(call_role: str, text: str, segment: bytes) -> dict[str, Any]:
        nonlocal estimated
        estimated += CALL_EST_USD.get(call_role, CALL_EST_USD["judge"])
        result = router.execute(
            provider=call_role,
            task_type="chat",
            payload=_payload(text, segment),
            org=TARGET_ORGANIZATION_NAME,
            module_id="k.product_knowledge",
            usage_label=label,
        )
        if isinstance(result, dict) and result.get("_ai_degraded"):
            raise _Degraded()
        return _as_json(result)

    # 排队流水线里存库的是 to_dict() 后的字典,直接调用时是 Capture;两种都认。
    detail_images = capture.get("detail_images") if isinstance(capture, dict) else capture.detail_images
    for image_index, url in enumerate(detail_images or []):
        if stopped:
            break
        data = download(url)
        if not data:
            failed += 1  # 图床上没了(404)或者太大;跳过,但要记个数给老板看
            continue
        try:
            segments = slice_image(data)
        except Exception:  # noqa: BLE001 —— 坏图跳过
            failed += 1
            continue
        for segment_index, segment in enumerate(segments):
            next_cost = CALL_EST_USD.get(role, CALL_EST_USD["judge"]) + (CALL_EST_USD["fast"] if do_triage else 0.0)
            if spent() + next_cost > budget_usd:
                stopped = "budget"
                break
            seen += 1
            try:
                if do_triage and not call("fast", _TRIAGE_PROMPT, segment).get("useful"):
                    continue
                extracted = call(role, prompt, segment)
            except _Degraded:
                stopped = "degraded"
                break
            except Exception:  # noqa: BLE001 —— 一段读失败跳过,继续下一段
                continue
            read += 1
            for fact in extracted.get("facts") or []:
                cleaned = clean(fact, image_index=image_index, segment_index=segment_index)
                if cleaned:
                    facts.append(cleaned)
    total = spent()
    return {
        "facts": facts,
        "segments_seen": seen,
        "segments_read": read,
        "images_failed": failed,
        "cost_usd": round(total, 4),
        "cost_basis": basis,
        "reader_role": role,
        "triage": do_triage,
        "stopped_reason": stopped,
    }


class _Degraded(RuntimeError):
    """Claude 额度用完、这次调用被降级了。"""


__all__ = [
    "Capture",
    "FACT_FIELDS",
    "FACT_SCOPES",
    "FACT_SUBJECTS",
    "detect_blocked",
    "download_image",
    "extract_prompt",
    "fetch_detail_description",
    "fetch_offer",
    "ledger_meter",
    "product_context",
    "reader_settings",
    "normalize_image_url",
    "offer_url",
    "parse_capture",
    "parse_offer_id",
    "read_detail_images",
    "slice_image",
]
