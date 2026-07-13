"""F 类目产品画像：DeepSeek 生成「这个类目通常包含哪些产品」，一次生成永久缓存。

点开类目 → 右栏展示该类目典型产品清单（中英文对照 + 一句用途）。谷歌树比
亚马逊粗（一个谷歌类目装得下亚马逊一串细分），画像负责回答"这个类目里
应该铺哪些产品"。成本：每类目一次 DeepSeek 调用（几分钱），缓存后零成本。
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError

from .models import FCategoryProfile

_TIMEOUT_SECONDS = 45
_MAX_PRODUCTS = 15


class FProfileUnavailableError(RuntimeError):
    """DeepSeek 密钥缺失或调用失败。"""


def get_profile(db: Session, category_id: str) -> FCategoryProfile | None:
    return db.scalar(
        select(FCategoryProfile).where(FCategoryProfile.category_id == category_id)
    )


def ensure_profile(
    db: Session,
    *,
    category_id: str,
    category_path: str,
    name_zh: str | None,
    org_id: str,
) -> FCategoryProfile:
    """有缓存直接回；没有就调 DeepSeek 生成并落库。"""
    cached = get_profile(db, category_id)
    if cached is not None:
        return cached

    try:
        api_key = SecretManager(db_session=db).get_key("deepseek", org_id)
    except SecretManagerError as exc:
        raise FProfileUnavailableError(f"DeepSeek 密钥未绑定：{exc}") from exc
    if not (api_key or "").strip():
        raise FProfileUnavailableError("DeepSeek 密钥未绑定（密钥管理里绑一把即可）。")

    # DeepSeek 最长 45s：先结束打开的 SQL 事务（防 idle-in-transaction）。
    db.rollback()
    products = _call_deepseek_profile(
        api_key=api_key,
        category_path=category_path,
        name_zh=name_zh,
    )
    profile = FCategoryProfile(
        id=uuid4(),
        category_id=category_id,
        products_json=products,
        provider="deepseek",
    )
    db.add(profile)
    db.flush()
    return profile


def _call_deepseek_profile(
    *,
    api_key: str,
    category_path: str,
    name_zh: str | None,
) -> list[dict[str, str]]:
    prompt = {
        "category_path_en": category_path,
        "category_name_zh": name_zh or "",
        "instruction": (
            "这是谷歌商品分类（Google product taxonomy）中的一个类目。请列出"
            "这个类目在独立站/电商语境下通常包含的典型产品 8 到 15 种。每种给"
            "英文名 en、中文名 zh、一句中文用途说明 note_zh（不超过 20 字）。"
            '只返回严格 JSON：{"products":[{"en":"...","zh":"...","note_zh":"..."}]}'
        ),
    }
    body = {
        "model": os.getenv("F_DEEPSEEK_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat")),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是跨境电商类目专家。只返回 JSON，不要 Markdown。",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FProfileUnavailableError(f"DeepSeek 调用失败：{str(exc)[:160]}") from exc

    return _parse_products(payload)


def _parse_products(payload: dict[str, Any]) -> list[dict[str, str]]:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FProfileUnavailableError("DeepSeek 响应结构异常。") from exc
    content = str(content).strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[4:] if content.startswith("json") else content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise FProfileUnavailableError("DeepSeek 未返回合法 JSON。") from exc

    items = parsed.get("products") if isinstance(parsed, dict) else None
    if not isinstance(items, list) or not items:
        raise FProfileUnavailableError("DeepSeek 未给出产品清单。")
    output: list[dict[str, str]] = []
    for item in items[:_MAX_PRODUCTS]:
        if not isinstance(item, dict):
            continue
        en = str(item.get("en") or "").strip()[:200]
        zh = str(item.get("zh") or "").strip()[:200]
        note = str(item.get("note_zh") or "").strip()[:100]
        if en or zh:
            output.append({"en": en, "zh": zh, "note_zh": note})
    if not output:
        raise FProfileUnavailableError("DeepSeek 产品清单为空。")
    return output
