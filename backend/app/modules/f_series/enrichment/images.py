"""F 候选图片代理+磁盘缓存：绕过阿里 CDN 防盗链并给前端提速。

背景（2026-07-14）：候选图直链 cbu01.alicdn.com——浏览器带站点 Referer 会被
403（已用 no-referrer 绕过），但原图 200KB 级且逐张回源国内 CDN，用户体感
"很慢很卡"。方案：后端服务器代拉一次（服务端请求不带 Referer）、落磁盘
永久缓存，前端从本站拿图。

- thumb 变体：alicdn 尺寸后缀 ``_310x310.jpg``（44KB vs 原图 198KB 实测），
  后缀 404 时回退原图
- full 变体：原图（悬浮放大预览用）
- 域名白名单沿用 K 参考图的口径（alicdn/amazon），防 SSRF
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

VARIANTS = ("thumb", "full")
THUMB_SUFFIX = "_310x310.jpg"
_ALLOWED_HOST_SUFFIXES = (
    "alicdn.com",
    "media-amazon.com",
    "ssl-images-amazon.com",
    "images-amazon.com",
)
_DOWNLOAD_TIMEOUT_SECONDS = 15
_MAX_BYTES = 20 * 1024 * 1024


class FImageUnavailableError(RuntimeError):
    """图源缺失/域名不在白名单/回源失败——端点按 404/502 翻译。"""


def _cache_dir() -> Path:
    return Path(
        os.getenv("F_IMAGE_CACHE_DIR", "/var/lib/barong/f-media").strip()
        or "/var/lib/barong/f-media"
    )


def _host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _ALLOWED_HOST_SUFFIXES
    )


def sniff_media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _download(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (barong-f-image-cache)",
            "Accept": "image/*",
        },
    )
    with urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read(_MAX_BYTES + 1)


def _thumb_url(url: str) -> str:
    # alicdn 的缩放后缀只对 jpg/png 原始文件名生效；已带缩放后缀的原样用。
    if re.search(r"_\d{2,4}x\d{2,4}\.(jpg|png)$", url):
        return url
    return f"{url}{THUMB_SUFFIX}"


def get_candidate_image(candidate_id: str, image_url: str, variant: str) -> tuple[bytes, str]:
    """取候选图字节（磁盘缓存优先，未命中回源并落盘）。返回 (bytes, mime)。"""
    if variant not in VARIANTS:
        variant = "thumb"
    url = (image_url or "").strip()
    if not url:
        raise FImageUnavailableError("候选没有图源。")
    if not _host_allowed(url):
        raise FImageUnavailableError("图源域名不在白名单内。")

    cache_dir = _cache_dir()
    cache_file = cache_dir / f"{candidate_id}_{variant}.img"
    if cache_file.is_file():
        data = cache_file.read_bytes()
        if data:
            return data, sniff_media_type(data)

    fetch_url = _thumb_url(url) if variant == "thumb" else url
    try:
        data = _download(fetch_url)
    except (HTTPError, URLError, OSError):
        data = b""
    if (not data or len(data) > _MAX_BYTES) and fetch_url != url:
        # 缩放后缀不被该图支持（404 等）→ 回退原图。
        try:
            data = _download(url)
        except (HTTPError, URLError, OSError) as exc:
            raise FImageUnavailableError(f"图片回源失败：{exc}") from exc
    if not data:
        raise FImageUnavailableError("图片回源失败（空响应）。")
    if len(data) > _MAX_BYTES:
        raise FImageUnavailableError("图片超过 20MB 上限。")

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_bytes(data)
        tmp_file.replace(cache_file)
    except OSError:
        # 缓存写不进（卷属主/磁盘问题）不影响出图——牺牲缓存直接回图。
        pass
    return data, sniff_media_type(data)
