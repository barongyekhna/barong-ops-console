"""她先自己看图,再决定要不要问卖家「无标货」「实拍图」(10-31 老板拍板)。

老板的口径:1688 大多是白牌,**不是每个品都问**。她看档案里的参考图(1688 主图 + 规格图,最多 5 张):
- 产品本身或包装上看得到牌子 / logo / 厂名 / 印字 → 问「能发没有印字、没有 logo 的中性货和中性包装吗？」;
- 一张实拍都没有(全是渲染图 / 效果图 / 合成海报) → 问「方便发几张产品实拍照片吗？手机随手拍就行，不要效果图。」;
- 都没问题就不问。本来要问重量尺寸的,顺带加上需要的那句(见 seller_chat.build_question)。

看不出来(下载失败 / 读图档额度降级 / 出错)就写「没看成」,下一轮再看,最多 3 次;**看不成不算「无标」**——
作图那边没确认无标的一律当「有牌子」处理、不许圈掉(09 交接)。结果放 draft["photo_audit"],没有迁移。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_IMAGES = 5
MAX_ATTEMPTS = 3
USAGE_LABEL = "sqh_photo_check"
PROMPT = (
    "This is one product image from a 1688 (Chinese wholesale) listing. Answer two questions about it. "
    "1) real_photo: is this an actual camera photograph of the physical product? true for any real photo (studio, phone, "
    "white background, in use). false for 3D renders, CG, illustrations, or heavily composited marketing posters where the "
    "product itself is rendered. Text or stickers overlaid on a real photo do not make it false. "
    "2) branding: is any brand name, logo, factory name, or printed lettering visible ON THE PRODUCT ITSELF or on its retail "
    "packaging (molded, printed, embossed, label, sticker on the item)? Do NOT count watermarks, shop names, price tags, or "
    "marketing text the seller overlaid on the picture. Purely functional markings (e.g. ON/OFF, + / -, unit scales) do not count. "
    'Reply JSON only: {"real_photo": true|false, "branding": true|false, "brand_text": "<what is printed, or empty>"}.'
)


def _read(db: Session, prompt: str, image: bytes) -> Any:
    from . import brain
    from .sourcing_1688 import _payload

    db.commit()  # 出网前放掉事务
    return brain._execute("fast", _payload(prompt, image)["messages"], timeout=60, usage_label=USAGE_LABEL)


def summarize(images: list[dict[str, Any]]) -> dict[str, Any]:
    """逐张结果 → 两个结论。branded:任何一张看到牌子就是 True;all_renders:看成了至少 2 张、而且一张实拍都没有。
    看成的张数为 0 → 两个都是 None(没看成)。"""
    seen = [i for i in images if isinstance(i, dict) and i.get("ok")]
    if not seen:
        return {"branded": None, "all_renders": None, "brand_text": ""}
    branded = any(i.get("branding") for i in seen)
    texts = [str(i.get("brand_text") or "").strip() for i in seen if i.get("branding")]
    return {
        "branded": branded,
        "all_renders": len(seen) >= 2 and not any(i.get("real_photo") for i in seen),
        "brand_text": "、".join(t for t in dict.fromkeys(texts) if t)[:120],
    }


def audit(
    db: Session,
    urls: list[str],
    *,
    download: Callable[[str], bytes | None] | None = None,
    reader: Callable[[Session, str, bytes], Any] | None = None,
    now: datetime | None = None,
    attempts: int = 0,
) -> dict[str, Any]:
    from .brain import parse_json
    from .sourcing_1688 import download_image

    download = download or download_image
    reader = reader or _read
    now = now or datetime.now(UTC)
    images: list[dict[str, Any]] = []
    error: str | None = None
    for url in [u for u in urls if isinstance(u, str) and u][:MAX_IMAGES]:
        data = download(url)
        if not data:
            images.append({"url": url, "ok": False, "error": "图下不来"})
            continue
        try:
            result = reader(db, PROMPT, data)
        except Exception as exc:  # noqa: BLE001 —— 一张看失败跳过
            images.append({"url": url, "ok": False, "error": str(exc)[:120]})
            continue
        if isinstance(result, dict) and result.get("_ai_degraded"):
            error = "读图档今天额度用完,图先看不了"
            break
        parsed = parse_json(result) or {}
        if not isinstance(parsed.get("real_photo"), bool) or not isinstance(parsed.get("branding"), bool):
            images.append({"url": url, "ok": False, "error": "没读懂回答"})
            continue
        images.append({
            "url": url,
            "ok": True,
            "real_photo": parsed["real_photo"],
            "branding": parsed["branding"],
            "brand_text": str(parsed.get("brand_text") or "")[:80],
        })
    out = {"checked_at": now.isoformat(), "attempts": attempts + 1, "images": images, **summarize(images)}
    if out["branded"] is None:
        out["error"] = error or "一张都没看成"
    return out


def done(draft: Any) -> bool:
    """看成了,或者已经试满 3 次 → 不再看。"""
    current = (draft or {}).get("photo_audit") if isinstance(draft, dict) else None
    if not isinstance(current, dict):
        return False
    return current.get("branded") is not None or int(current.get("attempts") or 0) >= MAX_ATTEMPTS


def ensure(db: Session, dossier: Any, **kwargs: Any) -> dict[str, Any] | None:
    """档案还没看过图就看一遍,结果写回 draft["photo_audit"]。已看过直接返回。"""
    draft = dict(dossier.draft) if isinstance(dossier.draft, dict) else {}
    if done(draft):
        return draft.get("photo_audit")
    urls = [u for u in draft.get("reference_images") or [] if isinstance(u, str)]
    if not urls:
        return None
    previous = draft.get("photo_audit") if isinstance(draft.get("photo_audit"), dict) else {}
    dossier_id = dossier.id
    result = audit(db, urls, attempts=int(previous.get("attempts") or 0), **kwargs)
    from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
    from .models import SqhDossier

    fresh = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION) or dossier
    draft = dict(fresh.draft) if isinstance(fresh.draft, dict) else {}
    draft["photo_audit"] = result
    fresh.draft = draft
    db.add(fresh)
    db.flush()
    return result


def topics(draft: Any) -> dict[str, bool]:
    """看图的结论 → 要不要问「无标货」「实拍图」。没看成 = 不问(也不算无标)。"""
    current = (draft or {}).get("photo_audit") if isinstance(draft, dict) else None
    if not isinstance(current, dict):
        return {"neutral": False, "photos": False}
    return {"neutral": current.get("branded") is True, "photos": current.get("all_renders") is True}
