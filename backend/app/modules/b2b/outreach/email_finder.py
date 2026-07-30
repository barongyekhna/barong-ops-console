"""从店铺官网上捞联系邮箱。**免费,不走任何付费接口。**

小零售店的邮箱基本都明写在联系页上——先抓页面正则捞,捞不到再考虑
Hunter 这类工具。**LinkedIn 按规矩碰都不碰**(条款禁止 + 封号 + GDPR)。

礼貌约束:一家店最多试 4 个常见路径、每个 10 秒超时、不重试、不深爬。
查一家店的公开联系方式而已,别把人家服务器当爬虫目标。
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urljoin, urlparse

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# 联系页的常见路径,按命中概率排。首页放第一个:很多小店首页页脚就写着。
CONTACT_PATHS = (
    "",
    "/contact",
    "/contact-us",
    "/pages/contact",
    "/pages/contact-us",
    "/about",
    "/contact.html",
)

# 这些不是人能回信的地址:第三方服务、占位、图片文件名误匹配。
_JUNK_MARKERS = (
    "sentry.",
    "wixpress.",
    "wix.com",
    "squarespace.",
    "shopify.",
    "godaddy.",
    "example.com",
    "yourdomain",
    "domain.com",
    "email.com",
    "sentry.io",
    "cloudflare",
    "jquery",
    "@2x",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
)

# 一个都不该发的角色地址(发过去也是石沉大海或惹人烦)。
_UNUSABLE_LOCAL_PARTS = (
    "noreply",
    "no-reply",
    "donotreply",
    "postmaster",
    "abuse",
    "webmaster",
    "privacy",
    "unsubscribe",
)

# 越靠前越优先——小店老板最可能真正在看的信箱。
_PREFERRED_LOCAL_PARTS = (
    "hello",
    "info",
    "shop",
    "sales",
    "orders",
    "contact",
    "wholesale",
)


def _is_usable(email: str) -> bool:
    lowered = email.lower()
    if any(marker in lowered for marker in _JUNK_MARKERS):
        return False
    local = lowered.split("@", 1)[0]
    if any(local.startswith(bad) for bad in _UNUSABLE_LOCAL_PARTS):
        return False
    if len(lowered) > 254:
        return False
    return True


def extract_emails(text: str) -> list[str]:
    """从一段网页文本里捞出可用邮箱,去重并保持出现顺序。"""
    seen: list[str] = []
    for match in _EMAIL_RE.findall(text or ""):
        cleaned = match.strip(".,;:()<>[]'\"").lower()
        if not _is_usable(cleaned):
            continue
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def pick_best_email(emails: list[str], website: str | None) -> str | None:
    """挑一个最可能有人看的。

    优先同域名的(店自己的信箱,不是他家用的第三方平台地址),再按
    hello/info/shop 这种常见门店信箱排序。
    """
    if not emails:
        return None
    host = ""
    if website:
        host = (urlparse(website).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]

    def rank(email: str) -> tuple[int, int]:
        domain = email.split("@", 1)[1]
        same_domain = 0 if (host and host in domain) else 1
        local = email.split("@", 1)[0]
        try:
            preference = _PREFERRED_LOCAL_PARTS.index(local)
        except ValueError:
            preference = len(_PREFERRED_LOCAL_PARTS)
        return (same_domain, preference)

    return sorted(emails, key=rank)[0]


_MAILTO_RE = re.compile(r"mailto:\s*([^\"'?\s>]+)", re.I)
# "info [at] shop [dot] com" 这种反爬写法,小店挺常见。
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*"
    r"([A-Za-z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*([A-Za-z]{2,})",
    re.I,
)


def emails_from_html(html: str) -> list[str]:
    """从**原始 HTML**捞邮箱。

    绝不能拿剥完标签的纯文本来捞:`<a href="mailto:hello@x.com">Contact</a>`
    剥完只剩 "Contact",邮箱连同 href 一起没了。实测 6 家店只捞到 1 家,
    就是栽在这上面(2026-07-29)。
    """
    candidates: list[str] = []
    # mailto 优先——那是店家明确公布的联系方式。
    # **必须 URL 解码**:href 里常写成 "mailto:%20shop@x.com",不解码会存成
    # "%20shop@x.com" 这种发不出去的地址(2026-07-29 实测 Zamzows 中招)。
    for raw in _MAILTO_RE.findall(html or ""):
        candidates.append(unquote(raw))
    for local, domain, tld in _OBFUSCATED_RE.findall(html or ""):
        candidates.append(f"{local}@{domain}.{tld}")
    candidates.extend(_EMAIL_RE.findall(html or ""))

    seen: list[str] = []
    for match in candidates:
        cleaned = unquote(str(match)).strip().strip(".,;:()<>[]'\"").lower()
        # 解码后可能还残留空白/不可见字符,再洗一遍
        cleaned = "".join(ch for ch in cleaned if not ch.isspace())
        if "@" not in cleaned or not _is_usable(cleaned):
            continue
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _fetch_html(url: str) -> str | None:
    """抓原始 HTML。一页一次请求,超时就放弃,不重试。"""
    import urllib.request

    from ..prospects.screening import _USER_AGENT

    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "html" not in content_type:
                return None
            return response.read(400_000).decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - 抓不到就换下一个路径
        logger.debug("Contact page fetch failed for %s: %s", url, error)
        return None


def find_email_on_site(website: str | None) -> tuple[str | None, str | None]:
    """抓官网找邮箱。返回 (邮箱, 来源路径)。

    免费:直接 HTTP,不消耗任何额度。按路径挨个试,找到就停。
    """
    if not website:
        return None, None
    for path in CONTACT_PATHS:
        url = urljoin(website, path) if path else website
        html = _fetch_html(url)
        if not html:
            continue
        best = pick_best_email(emails_from_html(html), website)
        if best:
            return best, (path or "/")
    return None, None
