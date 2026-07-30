"""Serper Places(谷歌地图)客户端。

为什么用 Places 而不是普通网页搜索:地图结果直接带**店名/网址/电话/地址**,
正是找实体零售店需要的字段;网页搜索返回的是博客、亚马逊页面、目录站,
噪音极大。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

SERPER_PLACES_URL = "https://google.serper.dev/places"
REQUEST_TIMEOUT_SECONDS = 25

# Serper 的 gl(国家)和 hl(界面语言)
COUNTRY_LOCALE = {
    "US": ("us", "en"),
    "CA": ("ca", "en"),
    "MX": ("mx", "es"),
}


class SerperPlacesError(RuntimeError):
    """Serper 调用失败(网络、鉴权、限流)。"""


def search_places(
    *,
    api_key: str,
    query: str,
    country: str,
    language: str | None = None,
    num: int = 20,
) -> list[dict[str, Any]]:
    """搜一次地图,返回原始 places 列表。

    刻意不做字段清洗——清洗归 service 层,这里只负责"把数据拿回来",
    方便出问题时对着原始返回排查。
    """
    gl, default_hl = COUNTRY_LOCALE.get(country, ("us", "en"))
    payload = json.dumps(
        {
            "q": query,
            "gl": gl,
            "hl": language or default_hl,
            "num": max(1, min(num, 100)),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        SERPER_PLACES_URL,
        data=payload,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:200]
        except Exception:  # noqa: BLE001 - 读不到错误体也要继续抛
            pass
        raise SerperPlacesError(
            f"Serper places HTTP {exc.code}: {detail}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 网络异常统一成一种错误
        raise SerperPlacesError(f"Serper places request failed: {exc}") from exc

    places = body.get("places")
    return places if isinstance(places, list) else []
