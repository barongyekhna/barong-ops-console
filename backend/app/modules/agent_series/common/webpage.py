"""通用网页读取(10-27):数字员工看别人家的商品页用。

- render_raw():同步 Playwright 渲染一页,返回 (最终地址, 标题, html, 正文文字)。从苏青禾读 1688 的 _render_page 抽出来,
  1688 那边改成调它(zh-CN、滚 10 次、等 2.5 秒);看英文店页用 en-US、少滚几次、超时短。
- read():在独立线程里跑 render_raw(调用方可能带着事件循环),渲染不成退回纯 HTTP 抓静态 HTML;结果是 Page。
- jsonld_products():从页面里的 JSON-LD 抽 Product(名字、描述、品牌、价格、图数)——确定性的,先于模型抽取。
- html_to_text():去标签的兜底文本(静态页用)。
- looks_blocked():验证码 / 人机校验 / 拒绝访问的页面,不当成内容。

节流不在这里(调用方按台账和间隔管),这里只负责「一页」。原文不落库。
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_STATIC_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
_BLOCK_TITLE_MARKERS = (
    "captcha", "verify you are human", "just a moment", "access denied", "attention required", "are you a robot",
    "security check", "enable javascript", "403 forbidden", "please verify", "验证码", "访问被拒绝",
)
_BLOCK_URL_MARKERS = ("captcha", "/challenge", "cf_chl", "/blocked", "/sec/", "x5sec")


@dataclass
class Page:
    url: str
    final_url: str = ""
    title: str = ""
    html: str = ""
    text: str = ""
    ok: bool = False
    error: str | None = None
    blocked: bool = False
    via: str = ""  # render / static
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return registrable_domain(self.final_url or self.url)


def registrable_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host


def render_raw(url: str, *, timeout_s: float, locale: str = "en-US", scroll: int = 3, wait_ms: int = 1500) -> tuple[str, str, str, str]:
    """同步 Playwright 渲染一页(调用方放到线程里跑)。返回 (最终地址, 标题, html, 文本)。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale=locale, viewport={"width": 1366, "height": 900}, user_agent=DESKTOP_UA)
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            page.wait_for_timeout(wait_ms)
            for _ in range(max(0, scroll)):
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
            if html and not text:
                try:
                    text = page.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                except Exception:  # noqa: BLE001 —— 文字只是兜底来源,取不到不挡主数据
                    text = ""
            return page.url, page.title(), html, text
        finally:
            browser.close()


def fetch_static(url: str, *, timeout: float = 12.0) -> Page:
    """纯 HTTP 抓静态 HTML(渲染不成时的兜底,只认 HTML)。"""
    page = Page(url=url, via="static")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA, "Accept": "text/html,*/*;q=0.5", "Accept-Language": "en-US,en;q=0.8"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 —— 只抓调用方给的商品页
            ctype = str(response.headers.get("Content-Type") or "")
            if "html" not in ctype.lower():
                page.error = f"not_html:{ctype[:40]}"
                return page
            raw = response.read(MAX_STATIC_BYTES)
            page.final_url = str(response.geturl() or url)
        page.html = raw.decode("utf-8", "replace")
        page.title = _title_of(page.html)
        page.text = html_to_text(page.html)
        page.ok = bool(page.text)
    except Exception as exc:  # noqa: BLE001 —— 抓不到就是抓不到,原因带回去
        page.error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
    page.blocked = looks_blocked(final_url=page.final_url, title=page.title, text=page.text[:2000])
    if page.blocked:
        page.ok = False
    return page


def read(url: str, *, timeout_s: float = 20.0, locale: str = "en-US", scroll: int = 3, wait_ms: int = 1500, allow_static: bool = True) -> Page:
    """渲染一页;渲染失败(没装浏览器、超时)退回静态抓取。永不抛。"""
    page = Page(url=url, via="render")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(render_raw, url, timeout_s=timeout_s, locale=locale, scroll=scroll, wait_ms=wait_ms)
            final_url, title, html, text = future.result(timeout=timeout_s + 40)
        page.final_url, page.title, page.html, page.text = str(final_url or url), str(title or ""), html or "", (text or "")[:MAX_TEXT_CHARS]
        if page.html and not page.text:
            page.text = html_to_text(page.html)
        page.ok = bool(page.text)
    except Exception as exc:  # noqa: BLE001 —— 渲染不成退回静态
        page.error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
        if allow_static:
            static = fetch_static(url, timeout=min(timeout_s, 15.0))
            static.meta["render_error"] = page.error
            return static
    page.blocked = looks_blocked(final_url=page.final_url, title=page.title, text=page.text[:2000])
    if page.blocked:
        page.ok = False
    return page


def looks_blocked(*, final_url: str, title: str, text: str) -> bool:
    url_l, title_l, text_l = (final_url or "").lower(), (title or "").lower(), (text or "").lower()
    if any(m in url_l for m in _BLOCK_URL_MARKERS):
        return True
    if any(m in title_l for m in _BLOCK_TITLE_MARKERS):
        return True
    head = text_l[:600]
    return any(m in head for m in ("verify you are human", "are you a robot", "enable javascript and cookies", "access denied"))


_TAG_SCRIPT = re.compile(r"<(script|style|noscript|svg|template|head)[^>]*>.*?</\1>", re.I | re.S)
_TAG_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|td|th|section|article|header|footer|dt|dd|table)[^>]*>", re.I)
_TAG_ANY = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def html_to_text(html: str, *, limit: int = MAX_TEXT_CHARS) -> str:
    """去标签的正文文字:head/脚本/样式整块去掉(标题另取),块级标签换成换行,其余去掉,实体解码,空白压缩。"""
    if not html:
        return ""
    text = _TAG_SCRIPT.sub(" ", html)
    text = _TAG_BLOCK.sub("\n", text)
    text = _TAG_ANY.sub(" ", text)
    text = html_lib.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out = "\n".join(line for line in lines if line)
    return out[:limit]


def _title_of(html: str) -> str:
    match = _TITLE.search(html or "")
    return " ".join(html_lib.unescape(match.group(1)).split())[:300] if match else ""


_JSONLD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)


def jsonld_products(html: str) -> list[dict[str, Any]]:
    """页面 JSON-LD 里的 Product(含 @graph 里的):名字、描述、品牌、价格、币种、图数、SKU。解析不了的块跳过。"""
    out: list[dict[str, Any]] = []
    for block in _JSONLD.findall(html or ""):
        try:
            data = json.loads(html_lib.unescape(block).strip())
        except (ValueError, TypeError):
            continue
        for node in _walk_nodes(data):
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(str(t or "").lower() == "product" for t in types):
                continue
            out.append(_product_node(node))
    return out


def _walk_nodes(data: Any) -> list[Any]:
    if isinstance(data, list):
        return [n for item in data for n in _walk_nodes(item)]
    if isinstance(data, dict):
        nodes = [data]
        graph = data.get("@graph")
        if isinstance(graph, list):
            nodes.extend(n for item in graph for n in _walk_nodes(item))
        return nodes
    return []


def _product_node(node: dict[str, Any]) -> dict[str, Any]:
    offers = node.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers if isinstance(offers, dict) else {}
    price = offer.get("price") if isinstance(offer, dict) else None
    if isinstance(offer, dict) and price is None and isinstance(offer.get("priceSpecification"), dict):
        price = offer["priceSpecification"].get("price")
    if isinstance(offer, dict) and price is None and offer.get("lowPrice") is not None:
        price = offer.get("lowPrice")
    brand = node.get("brand")
    brand_name = brand.get("name") if isinstance(brand, dict) else brand
    images = node.get("image")
    image_count = len(images) if isinstance(images, list) else (1 if isinstance(images, (str, dict)) else 0)
    return {
        "name": " ".join(str(node.get("name") or "").split())[:300],
        "description": " ".join(str(node.get("description") or "").split())[:2000],
        "brand": " ".join(str(brand_name or "").split())[:100],
        "price": _number(price),
        "currency": str((offer.get("priceCurrency") if isinstance(offer, dict) else "") or "")[:8],
        "image_count": image_count,
        "sku": str(node.get("sku") or "")[:80],
        "rating": _number((node.get("aggregateRating") or {}).get("ratingValue") if isinstance(node.get("aggregateRating"), dict) else None),
        "review_count": _number((node.get("aggregateRating") or {}).get("reviewCount") if isinstance(node.get("aggregateRating"), dict) else None),
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:[.,]\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def image_count(html: str) -> int:
    """粗数页面里的 <img>(去掉明显的图标/像素点);JSON-LD 没给图时用。"""
    tags = re.findall(r"<img\b[^>]*>", html or "", re.I)
    n = 0
    for tag in tags:
        low = tag.lower()
        if any(m in low for m in ("icon", "logo", "pixel", "1x1", "sprite", "tracking", "badge", "flag")):
            continue
        n += 1
    return n


__all__ = ["DESKTOP_UA", "Page", "fetch_static", "html_to_text", "image_count", "jsonld_products", "looks_blocked", "read", "registrable_domain", "render_raw"]
