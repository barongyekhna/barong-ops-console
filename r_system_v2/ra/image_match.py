"""Image comparison for 1688 keyword-first supplier discovery.

主判：AI 看图（gpt-4o-mini via 4sapi）——1688 工厂图和亚马逊精修图几乎
不可能是同一张图，感知哈希认不出"重拍的同款"，必须由视觉模型判断
"是不是同一个产品"。一次调用带 1 张亚马逊图 + 最多 5 张 1688 图。

降级：AI 调用失败时回退 dHash 感知哈希（认"同图"不认"同物"，宁漏不冤），
再不行走图搜兜底——链路永不因比对器故障而停。
"""

from __future__ import annotations

from io import BytesIO
import os
from typing import Any
from urllib.request import Request, urlopen


VERDICT_SAME = "same_product"
VERDICT_SIMILAR = "similar_product"
VERDICT_DIFFERENT = "different"


DEFAULT_MATCH_THRESHOLD = 0.70
DEFAULT_DOWNLOAD_TIMEOUT = 8.0
MAX_IMAGE_BYTES = 3 * 1024 * 1024
_HASH_SIZE = 8  # dHash: 9x8 灰度 → 64 bit 指纹


class ImageMatchError(RuntimeError):
    pass


def match_threshold() -> float:
    try:
        value = float(os.getenv("RA_IMAGE_MATCH_THRESHOLD", str(DEFAULT_MATCH_THRESHOLD)))
    except ValueError:
        return DEFAULT_MATCH_THRESHOLD
    return min(0.95, max(0.5, value))


def _download(url: str) -> bytes:
    cleaned = str(url or "").strip()
    if not cleaned.startswith(("http://", "https://")):
        raise ImageMatchError(f"非法图片地址：{cleaned[:80]}")
    request = Request(
        cleaned,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Accept": "image/*,*/*;q=0.8",
        },
    )
    timeout = _timeout_seconds()
    with urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageMatchError("图片超过大小限制。")
    if not data:
        raise ImageMatchError("图片内容为空。")
    return data


def _timeout_seconds() -> float:
    try:
        return max(3.0, min(float(os.getenv("RA_IMAGE_MATCH_TIMEOUT_SECONDS", "8")), 30.0))
    except ValueError:
        return DEFAULT_DOWNLOAD_TIMEOUT


def dhash_bits(image_bytes: bytes) -> int:
    """64-bit difference hash（对缩放/压缩/轻度色差鲁棒）。"""
    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as img:
        gray = img.convert("L").resize(
            (_HASH_SIZE + 1, _HASH_SIZE),
            Image.Resampling.LANCZOS,
        )
        pixels = list(gray.getdata())
    bits = 0
    width = _HASH_SIZE + 1
    for row in range(_HASH_SIZE):
        for col in range(_HASH_SIZE):
            left = pixels[row * width + col]
            right = pixels[row * width + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_similarity(hash_a: int, hash_b: int) -> float:
    distance = bin(hash_a ^ hash_b).count("1")
    return 1.0 - distance / 64.0


def vision_model_name() -> str:
    return os.getenv("RA_VISION_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def ai_compare_amazon_to_offers(
    db: Any,
    *,
    org_id: str,
    amazon_image_url: str | None,
    offer_image_urls: list[str | None],
    product_title: str | None = None,
    is_seasonal: bool = False,
) -> dict[str, Any]:
    """AI 看图主判：逐张判定 1688 商品图与亚马逊图是否同一/同类产品。

    返回 {"available", "verdicts": {url: {"verdict","confidence"}},
          "provider_mode": "ai_vision", "model", "error"}
    任何失败 available=False，调用方降级 dHash。
    """
    result: dict[str, Any] = {
        "available": False,
        "verdicts": {},
        "provider_mode": "ai_vision",
        "model": vision_model_name(),
        "is_seasonal": is_seasonal,
        "error": None,
    }
    urls: list[str] = []
    for url in offer_image_urls:
        cleaned = str(url or "").strip()
        if cleaned.startswith(("http://", "https://")) and cleaned not in urls:
            urls.append(cleaned)
    urls = urls[:5]
    if not amazon_image_url or not urls:
        result["error"] = "missing_images"
        return result

    try:
        from r_system_v2.core.secret_manager import SecretManager
        from r_system_v2.ra.ai_selection import (
            ProviderConfig,
            _execute_chat_request,
            _provider_config,
            _try_parse_model_json,
        )
        from r_system_v2.ra.providers import RAnalysisProviderBinding

        binding = RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        )
        provider = _provider_config(
            role="vision",
            service="4sapi",
            secret=binding.vision_config(),
            env_base_url="FOURSAPI_BASE_URL",
            default_base_url="https://api.4sapi.com/v1",
            env_model="RA_VISION_MODEL",
            fallback_model="gpt-4o-mini",
        )
        # 视觉调用要几秒：先结束打开的 SQL 事务，避免 idle-in-transaction 超时。
        try:
            db.rollback()
        except Exception:
            pass

        seasonal_rule = (
            "注意：这是节日主题产品——图案、文字、主题元素不同就绝不能判 same_product。"
            if is_seasonal
            else ""
        )
        prompt = (
            "你是电商产品图片比对员。第 1 张图是亚马逊在售产品"
            + (f"（标题：{str(product_title or '')[:80]}）" if product_title else "")
            + f"，随后 {len(urls)} 张图是 1688 供应商的商品图。\n"
            "逐张判断每张 1688 图与第 1 张亚马逊图的关系：\n"
            "- same_product：同一个产品（同一设计/模具；仅颜色或数量不同的变体也算）\n"
            "- similar_product：同类同用途产品但设计不同（价格可作参考）\n"
            "- different：不同的产品\n"
            f"{seasonal_rule}\n"
            '只输出 JSON：{"results":[{"index":1,"verdict":"same_product|similar_product|different",'
            '"confidence":0.0}]}，index 从 1 开始对应 1688 图的顺序。'
        )
        detail = os.getenv("RA_VISION_IMAGE_DETAIL", "auto").strip() or "auto"
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.append(
            {"type": "image_url", "image_url": {"url": amazon_image_url, "detail": detail}}
        )
        for url in urls:
            content.append(
                {"type": "image_url", "image_url": {"url": url, "detail": detail}}
            )
        response = _execute_chat_request(
            provider,
            spec={
                "endpoint": "/v1/chat/completions",
                "label": "vision_match",
                "payload": {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 500,
                },
            },
        )
        output = _try_parse_model_json(response.get("content")) or {}
        entries = output.get("results")
        if not isinstance(entries, list):
            raise ValueError("模型未返回 results 数组")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("index")) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(urls):
                continue
            verdict = str(entry.get("verdict") or "").strip().lower()
            if verdict not in {VERDICT_SAME, VERDICT_SIMILAR, VERDICT_DIFFERENT}:
                verdict = VERDICT_DIFFERENT
            try:
                confidence = max(0.0, min(1.0, float(entry.get("confidence"))))
            except (TypeError, ValueError):
                confidence = 0.5
            result["verdicts"][urls[index]] = {
                "verdict": verdict,
                "confidence": confidence,
            }
        result["available"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)[:200]
        return result


def compare_amazon_to_offers(
    amazon_image_url: str | None,
    offer_image_urls: list[str | None],
) -> dict[str, Any]:
    """一次下载亚马逊主图，逐个比对 offer 图。

    返回 {"available": bool, "scores": {offer_url: score|None}, "matched_count": int,
          "threshold": float, "error": str|None}
    任何失败都不致命——图片比不了就交给标题对齐守门 + 图搜兜底。
    """
    threshold = match_threshold()
    result: dict[str, Any] = {
        "available": False,
        "scores": {},
        "matched_count": 0,
        "threshold": threshold,
        "error": None,
    }
    if not amazon_image_url:
        result["error"] = "amazon_image_missing"
        return result
    try:
        amazon_hash = dhash_bits(_download(amazon_image_url))
    except Exception as exc:
        result["error"] = f"amazon_image_failed:{str(exc)[:120]}"
        return result
    result["available"] = True
    for url in offer_image_urls:
        cleaned = str(url or "").strip()
        if not cleaned:
            continue
        if cleaned in result["scores"]:
            continue
        try:
            score = hamming_similarity(amazon_hash, dhash_bits(_download(cleaned)))
        except Exception:
            result["scores"][cleaned] = None
            continue
        result["scores"][cleaned] = round(score, 4)
        if score >= threshold:
            result["matched_count"] += 1
    return result
