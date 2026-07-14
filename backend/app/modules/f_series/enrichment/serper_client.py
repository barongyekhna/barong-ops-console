"""Serper 关键词收割客户端。

一个类目节点一次搜索：用节点名（带父级语境）搜 Google，收割
relatedSearches / peopleAlsoAsk / organic 标题三路关键词。
调用方负责：额度记账（quota_ledger）+ 调用前结束打开的 SQL 事务
（Serper 最长 12s，避免 idle-in-transaction 超时——R-A 踩过的坑）。
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_IMAGES_URL = "https://google.serper.dev/images"
_TIMEOUT_SECONDS = 12

# 每路关键词的收割上限（一个类目 ~20 词以内，防洪）
_MAX_RELATED = 8
_MAX_PAA = 8
_MAX_ORGANIC = 6


def serper_search(*, api_key: str, query: str) -> dict[str, Any]:
    payload = {"q": query, "gl": "us", "hl": "en", "num": 10}
    request = Request(
        os.getenv("F_SERPER_SEARCH_URL", SERPER_SEARCH_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-KEY": api_key},
        method="POST",
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def serper_images(*, api_key: str, query: str, num: int = 100) -> dict[str, Any]:
    """谷歌图片搜索（图搜接力的种子图来源）：一次调用最多回 100 张。"""
    payload = {"q": query, "num": max(10, min(int(num or 100), 100))}
    request = Request(
        os.getenv("F_SERPER_IMAGES_URL", SERPER_IMAGES_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-KEY": api_key},
        method="POST",
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def extract_image_urls(raw: dict[str, Any], *, limit: int) -> list[str]:
    """种子图清单：http(s) 直链、去重、太小的缩略不要（<200px 多为图标）。"""
    urls: list[str] = []
    seen: set[str] = set()
    images = raw.get("images")
    if not isinstance(images, list):
        return urls
    for entry in images:
        if len(urls) >= max(1, limit):
            break
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("imageUrl") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        width = entry.get("imageWidth")
        if isinstance(width, (int, float)) and width < 200:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def extract_keywords(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """把 Serper 原始响应拍成 [{keyword_text, keyword_type, rank}]（已去重）。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(text: object, keyword_type: str, rank: int) -> None:
        keyword = str(text or "").strip()
        key = keyword.lower()
        if not keyword or len(keyword) > 512 or key in seen:
            return
        seen.add(key)
        items.append(
            {"keyword_text": keyword, "keyword_type": keyword_type, "rank": rank}
        )

    related = raw.get("relatedSearches")
    if isinstance(related, list):
        for rank, entry in enumerate(related[:_MAX_RELATED], start=1):
            if isinstance(entry, dict):
                _push(entry.get("query"), "related", rank)

    paa = raw.get("peopleAlsoAsk")
    if isinstance(paa, list):
        for rank, entry in enumerate(paa[:_MAX_PAA], start=1):
            if isinstance(entry, dict):
                _push(entry.get("question"), "people_also_ask", rank)

    organic = raw.get("organic")
    if isinstance(organic, list):
        for rank, entry in enumerate(organic[:_MAX_ORGANIC], start=1):
            if isinstance(entry, dict):
                _push(entry.get("title"), "organic_title", rank)

    return items
