"""把一个 1688 商品链接读成结构化数据(苏青禾「1688 → K 档案」的抓取段)。

为什么不用官方接口(2026-10-23 实测):`alibaba.cross.productInfo` 返回
``gw.APIACLDecline``——要开寻源通权限组(月采购 12 万门槛)。而不登录用无头浏览器
打开详情页,页面里内嵌的 ``window.context`` 数据就带着标题、属性表、SKU、阶梯价、
每个 SKU 的重量尺寸、主图;详情长图另走 ``detailUrl``(itemcdn.tmall.com),
普通 HTTP 带 1688 的 Referer 就能取到。

分三层,方便测试:
- ``parse_capture`` 纯函数:给 HTML / 页面文本 / 详情描述,吐出 ``Capture``,不联网;
- ``fetch_offer`` 联网:开页面、取详情描述,再交给 ``parse_capture``;
- ``read_detail_images`` 看图:详情长图切段 → Haiku 分拣 → Opus 逐段转录。

家规:读不到就空着,不猜。页面里没有的字段一律 None,零值(1688 用 0 表示没填)也算没有。
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REFERER = "https://detail.1688.com/"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_HOST_SUFFIX = ".alicdn.com"

# 看图费用的保守估算(路由不回传 token 用量,这里按单次调用估):
# fast(Haiku 5.5)分拣一段 ≈ 1.6k 输入 + 少量输出,按 $0.001 记(实际约 $0.0003);
# judge(Opus 5.5)转录一段 ≈ 1.6k 输入 + 思考与输出约 2k,按 $0.05 记。
FAST_CALL_EST_USD = 0.001
JUDGE_CALL_EST_USD = 0.05

# 数字描述的是哪一层:同一个「重量」,单品 200 克和一整盒 2500 克不是矛盾(10-23 首测踩到)。
FACT_SCOPES = ("item", "inner_pack", "carton", "unknown")

FACT_FIELDS = (
    "material",
    "dimensions",
    "weight",
    "capacity",
    "power",
    "battery",
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
    category_zh: str | None = None
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

    skus: list[dict[str, Any]] = []
    sku_rows = trade.get("skuMap")
    if isinstance(sku_rows, dict):
        sku_rows = [{"specAttrs": key, **value} for key, value in sku_rows.items() if isinstance(value, dict)]
    for row in sku_rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("specAttrs") or "").replace("&gt;", ">").strip()
        if not name:
            continue
        weights = pack_by_id.get(str(row.get("skuId"))) or pack.get(name) or {}
        # 多维规格(颜色>款式)的图挂在某一维上,逐段找。
        image = image_by_name.get(name) or next(
            (image_by_name[part.strip()] for part in name.split(">") if part.strip() in image_by_name), None
        )
        # skuMap 里的 priceAmount 含义不明(实测 12 而阶梯价是 3.30),不当价格用;
        # 只认显式的 price / discountPrice。
        price = _positive_number(row.get("discountPrice")) or _positive_number(row.get("price"))
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

    # 阶梯价
    tiers: list[dict[str, Any]] = []
    price_model = trade.get("offerPriceModel") if isinstance(trade.get("offerPriceModel"), dict) else {}
    raw_tiers = price_model.get("currentPricesWithOnePiece") or price_model.get("currentPrices") or trade.get("disPriceRanges") or []
    for entry in raw_tiers:
        entry = _resolve_ref(root or {}, entry)
        if not isinstance(entry, dict):
            continue
        qty = _positive_int(entry.get("beginAmount"))
        price = _positive_number(entry.get("price") or entry.get("discountPrice"))
        if qty and price and not any(t["min_qty"] == qty for t in tiers):
            tiers.append({"min_qty": qty, "price_cny": price})
    capture.price_tiers = sorted(tiers, key=lambda t: t["min_qty"])

    capture.moq = _positive_int(trade.get("beginAmount")) or (capture.price_tiers[0]["min_qty"] if capture.price_tiers else None)
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
    """在独立线程里跑同步 Playwright(调用方可能带着事件循环)。返回 (最终地址, 标题, html, 文本)。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="zh-CN", viewport={"width": 1366, "height": 900}, user_agent=DESKTOP_UA)
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            page.wait_for_timeout(2500)
            for _ in range(10):
                try:
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(500)
                except Exception:  # noqa: BLE001 —— 滚动时页面可能在重渲染,滚不了就停
                    break
            html, text = "", ""
            for _ in range(3):
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    html = page.content()
                    text = page.inner_text("body")
                    break
                except Exception:  # noqa: BLE001 —— "page is navigating" 时等一下再取
                    page.wait_for_timeout(1000)
            return page.url, page.title(), html, text
        finally:
            browser.close()


def fetch_offer(url: str, *, timeout_s: float = 25) -> Capture:
    offer_id = parse_offer_id(url)
    if offer_id is None:
        return Capture(offer_id=None, url=url, blocked=True, block_reason="not_a_1688_offer_url")
    target = offer_url(offer_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        # 正常一页 43–48 秒(启动浏览器+滚动+重试取内容);10-26 实测 +40 余量偶发超时,放到 +80。
        final_url, title, html, text = pool.submit(_render_page, target, timeout_s).result(timeout=timeout_s + 80)
    reason = detect_blocked(final_url=final_url, title=title, html=html)
    if reason:
        return Capture(offer_id=offer_id, url=target, title_zh=title or None, blocked=True, block_reason=reason)
    capture = parse_capture(url=target, html=html, text=text, desc_js=None)
    if capture.detail_url:
        try:
            desc = _http_get_text(capture.detail_url)
        except Exception:  # noqa: BLE001 —— 详情描述取不到不影响主数据,只是没有详情图
            desc = None
        capture.detail_images = _desc_images(desc)
    return capture


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
    "参数表、尺寸图、重量、材质、容量/功率/电池、适用年龄、包装清单/配件、颜色款式表、认证。"
    "纯氛围图、模特图、营销口号不算。"
    'Only reply JSON: {"useful": true|false, "kind": "specs|size|package|material|certification|colors|none"}'
)

_EXTRACT_PROMPT = (
    "你在抄录 1688 商品详情图里**印着的**商品事实。只抄图上真实出现的文字和数字,"
    "看不清、图上没有的一律不写,绝不推测、不换算、不补全。\n"
    "Transcribe ONLY facts literally printed in this image segment. Never guess, convert or infer.\n"
    'Reply JSON only: {"facts": [{"field": one of '
    + json.dumps(list(FACT_FIELDS))
    + ', "value": "as printed", "unit": "as printed or empty", "raw_text": "the exact printed text", '
    '"scope": "item|inner_pack|carton|unknown", "confidence": "high|medium|low"}]}. Empty list if nothing.\n'
    "scope 说明数字描述的是哪一层:item=单个产品本身;inner_pack=一个销售包装(单盒/单袋,买家收到的那一份);"
    "carton=批发外箱/装箱信息;unknown=图上看不出。例如「一个约200克」是 item,「一大盒约2500克」是 inner_pack 或 carton。"
)


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


def read_detail_images(
    db: Any,
    capture: Capture | dict[str, Any],
    *,
    budget_usd: float = 0.50,
    download: Callable[[str], bytes | None] | None = None,
    router_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """详情长图 → 切段 → Haiku 分拣 → Opus 转录。费用按单次调用保守估算,超预算就停。"""
    from ...k_series.product_knowledge.constants import TARGET_ORGANIZATION_NAME

    from .constants import USAGE_LABEL

    download = download or download_image
    router = (router_factory or _default_router_factory)(db)
    facts: list[dict[str, Any]] = []
    seen = read = 0
    cost = 0.0
    stopped: str | None = None

    def call(role: str, prompt: str, segment: bytes) -> dict[str, Any]:
        result = router.execute(
            provider=role,
            task_type="chat",
            payload=_payload(prompt, segment),
            org=TARGET_ORGANIZATION_NAME,
            module_id="k.product_knowledge",
            usage_label=USAGE_LABEL,
        )
        return _as_json(result)

    # 排队流水线里存库的是 to_dict() 后的字典,直接调用时是 Capture;两种都认。
    detail_images = capture.get("detail_images") if isinstance(capture, dict) else capture.detail_images
    for image_index, url in enumerate(detail_images or []):
        if stopped:
            break
        data = download(url)
        if not data:
            continue
        try:
            segments = slice_image(data)
        except Exception:  # noqa: BLE001 —— 坏图跳过
            continue
        for segment_index, segment in enumerate(segments):
            if cost + FAST_CALL_EST_USD > budget_usd:
                stopped = "budget"
                break
            seen += 1
            cost += FAST_CALL_EST_USD
            try:
                triage = call("fast", _TRIAGE_PROMPT, segment)
            except Exception:  # noqa: BLE001 —— 分拣失败当作没用,继续下一段
                continue
            if not triage.get("useful"):
                continue
            if cost + JUDGE_CALL_EST_USD > budget_usd:
                stopped = "budget"
                break
            cost += JUDGE_CALL_EST_USD
            try:
                extracted = call("judge", _EXTRACT_PROMPT, segment)
            except Exception:  # noqa: BLE001
                continue
            read += 1
            for fact in extracted.get("facts") or []:
                if not isinstance(fact, dict) or not str(fact.get("value") or "").strip():
                    continue
                field_name = str(fact.get("field") or "other")
                facts.append(
                    {
                        "field": field_name if field_name in FACT_FIELDS else "other",
                        "value": str(fact.get("value")).strip(),
                        "unit": str(fact.get("unit") or "").strip(),
                        "raw_text": str(fact.get("raw_text") or "").strip(),
                        "scope": fact.get("scope") if fact.get("scope") in FACT_SCOPES else "unknown",
                        "image_index": image_index,
                        "segment_index": segment_index,
                        "confidence": fact.get("confidence") if fact.get("confidence") in {"high", "medium", "low"} else "low",
                    }
                )
    return {
        "facts": facts,
        "segments_seen": seen,
        "segments_read": read,
        "cost_usd": round(cost, 4),
        "stopped_reason": stopped,
    }


__all__ = [
    "Capture",
    "FACT_FIELDS",
    "FACT_SCOPES",
    "detect_blocked",
    "download_image",
    "fetch_offer",
    "normalize_image_url",
    "offer_url",
    "parse_capture",
    "parse_offer_id",
    "read_detail_images",
    "slice_image",
]
