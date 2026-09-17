"""A5 图片通道的业务:brief(带证据)→ 参考图 → 交稿 → 四道门 → 人选定 → 上线 → 14/28 天回看。

家规:
- 图片线永远 L1:这里没有任何「上传到亚马逊」的代码,选定只是记录,上线是人手动做完再来点「已上线」。
- 事实表在「出图 brief」上不够就不建 brief(不够不画)。
- 每个位置最多 max_rounds 轮,到顶交人挑;门可以判「不过」,但人可以选它(人的命令高于程序)。
- 素材在 A 自己的目录(AMZ_MEDIA_ROOT),与 K 零交集。

四道门(每次交稿都跑,结果落 review_json):
1. 格式门(纯代码):能解码、JPEG/PNG/WebP、主图要 ≥1000px 且近似正方形;
2. 兄弟店差异化门(纯代码):与 sibling_main 参考图的 dHash 汉明距离 ≥ 阈值——三店同款不能长得一样;
3. 同屏门(看图模型):候选缩成缩略图,与 competitor_thumb / sibling_main 排一行,问「会不会被点」和为什么;
4. 事实门(看图模型):必须出现的都在、禁止出现的都没有、主图无文字水印。
看图模型不通 → 该门 unknown,不算过也不拦人。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models.user import User
from ...services.media_store import ensure_image_derivative, storage_path, write_media_file
from . import fact_sheets, work_log
from .catalog import store_spec
from .constants import EMPLOYEE_B, MODULE_KEY
from .models import AmzAdSearchTerm, AmzImageAsset, AmzImageBrief, AmzProduct, AmzSqp, AmzStore, AmzSuggestion
from .rules import PRODUCT_LINE_LABELS, product_line_of
from .rules_cross import ACTION_SCREEN_CTR_GAP
from .service import AmzServiceError

_LOGGER = logging.getLogger("amz.images")

DEFAULT_MEDIA_ROOT = "/var/lib/barong/amz-media"
MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAIN_MIN_SIDE = 1000
MAIN_ASPECT_TOLERANCE = 0.08
SIBLING_MIN_HAMMING = 12  # 64 位 dHash;<12 = 看起来是同一张图
POSITIONS: tuple[str, ...] = ("main", "angle", "benefit", "detail", "scale", "lifestyle", "package", "aplus")
POSITION_LABELS = {"main": "主图", "angle": "多角度", "benefit": "核心卖点信息图", "detail": "功能细节", "scale": "尺寸参照", "lifestyle": "生活场景", "package": "包装内含", "aplus": "A+ 图"}
REFERENCE_KINDS: tuple[str, ...] = ("product_photo", "current_main", "sibling_main", "competitor_thumb")
REFERENCE_LABELS = {"product_photo": "实拍图", "current_main": "现在的主图", "sibling_main": "兄弟店主图", "competitor_thumb": "对手缩略图"}
KIND_SUBMISSION = "submission"
BRIEF_STATUSES: tuple[str, ...] = ("queued", "in_review", "approved", "live", "closed")
LOOKBACK_DAYS = (14, 28)


def media_root() -> Path:
    return Path(os.getenv("AMZ_MEDIA_ROOT", DEFAULT_MEDIA_ROOT))


# ---------------------------------------------------------------- 图片工具(纯函数)


def validate_image(contents: bytes) -> tuple[str, int, int]:
    if not contents:
        raise AmzServiceError("图片内容为空", status_code=422, code="amz_image_empty")
    if len(contents) > MAX_IMAGE_BYTES:
        raise AmzServiceError(f"单张图超过 {MAX_IMAGE_BYTES // (1024 * 1024)}MB", status_code=413, code="amz_image_too_large")
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(contents)) as img:
            img.verify()
        with Image.open(io.BytesIO(contents)) as img:
            fmt = (img.format or "").lower()
            width, height = img.size
    except Exception as exc:  # noqa: BLE001
        raise AmzServiceError(f"图片解码失败({type(exc).__name__})", status_code=422, code="amz_image_unreadable") from exc
    if fmt not in {"png", "webp", "jpeg"}:
        raise AmzServiceError(f"不接受 {fmt or 'unknown'} 格式,请交 PNG / WebP / JPEG", status_code=422, code="amz_image_format")
    return fmt, width, height


def dhash(contents: bytes, size: int = 8) -> str:
    """差分哈希:缩成 9×8 灰度,相邻像素比大小 → 64 位。同一张图缩放 / 轻微调色后距离很小。"""
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(contents)) as img:
        gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def thumbnail_bytes(contents: bytes, max_side: int = 200) -> bytes:
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(contents)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()


# ---------------------------------------------------------------- 存取


def _object_key(brief: AmzImageBrief, kind: str, fmt: str) -> str:
    ext = {"jpeg": "jpg"}.get(fmt, fmt)
    return f"briefs/{brief.store_code}/{brief.id}/{kind}/{uuid4().hex}.{ext}"


def asset_path(asset: AmzImageAsset) -> Path:
    return storage_path(media_root(), asset.object_key)


def asset_bytes(asset: AmzImageAsset) -> bytes | None:
    path = asset_path(asset)
    return path.read_bytes() if path.is_file() else None


def derivative_path(asset: AmzImageAsset, *, kind: str, max_side: int) -> Path:
    path, _, _ = ensure_image_derivative(root=media_root(), object_key=asset.object_key, kind=kind, max_side=max_side)
    return path


def _store_asset(db: Session, *, brief: AmzImageBrief, kind: str, contents: bytes, note: str | None, submitted_via: str, actor_user_id: int | None, round_no: int = 0) -> AmzImageAsset:
    fmt, width, height = validate_image(contents)
    key = _object_key(brief, kind, fmt)
    write_media_file(media_root(), key, contents)
    try:
        digest = dhash(contents)
    except Exception:  # noqa: BLE001
        digest = None
    asset = AmzImageAsset(
        brief_id=brief.id,
        kind=kind,
        round=round_no,
        object_key=key,
        mime_type=f"image/{fmt}",
        width=width,
        height=height,
        bytes=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        dhash=digest,
        note=(note or "").strip()[:500] or None,
        submitted_via=submitted_via,
        status="available",
        created_by_user_id=actor_user_id,
    )
    db.add(asset)
    db.flush()
    return asset


# ---------------------------------------------------------------- brief


def sibling_stores(db: Session, store: AmzStore, product_line: str) -> list[str]:
    """同币种、卖同一条产品线的兄弟店(按名册)。"""
    codes = list(db.scalars(select(AmzStore.store_code).where(AmzStore.currency == store.currency, AmzStore.store_code != store.store_code, AmzStore.status == "active")))
    if not codes:
        return []
    selling = set(db.scalars(select(AmzProduct.store_code).where(AmzProduct.store_code.in_(codes), AmzProduct.product_line == product_line, AmzProduct.status == "active").distinct()))
    return sorted(selling)


def _top_sku(db: Session, store_code: str, product_line: str) -> AmzProduct | None:
    rows = list(db.scalars(select(AmzProduct).where(AmzProduct.store_code == store_code, AmzProduct.product_line == product_line, AmzProduct.status == "active")))
    rows.sort(key=lambda p: -int((p.metadata_json or {}).get("units_total") or 0))
    return rows[0] if rows else None


def build_brief_md(*, store: AmzStore, position: str, product_line: str, sku: str | None, asin: str | None, facts: dict[str, Any], evidence: dict[str, Any], siblings: list[str], must_have: list[str], forbidden: list[str]) -> str:
    label = PRODUCT_LINE_LABELS.get(product_line, product_line)
    pos_label = POSITION_LABELS.get(position, position)
    lines = [
        f"# 图片 brief · {store.display_name}({store.store_code})· {label} · {pos_label}",
        "",
        "## 证据(为什么要改这张图)",
    ]
    if evidence.get("term"):
        mine, best = evidence.get("mine") or {}, evidence.get("best") or {}
        lines.append(f"- 搜索词「{evidence['term']}」近 {evidence.get('window_days', 60)} 天:我们曝光 {mine.get('impressions')} 次点 {mine.get('clicks')} 次(CTR {mine.get('ctr_pct')}%);兄弟店 {best.get('store')} 曝光 {best.get('impressions')} 次点 {best.get('clicks')} 次(CTR {best.get('ctr_pct')}%)。同一款货、同一个词,买家在搜索页只看主图和标题前半句。")
    if evidence.get("reason"):
        lines.append(f"- {evidence['reason']}")
    lines += [
        "",
        "## 产品事实(必须照着画,不许脑补)",
        f"- 它是什么:{facts.get('is', '')}",
        f"- 怎么工作:{facts.get('how_it_works', '')}",
        f"- 它不是什么:{facts.get('is_not', '')}",
        f"- 参数:{'; '.join(f'{k}: {v}' for k, v in (facts.get('specs') or {}).items())}",
        f"- 指示:{facts.get('indicators', '')}",
        f"- 包装内含:{facts.get('package', '')}",
        f"- 人群与场景:{facts.get('audience', '')}",
        "",
        "## 这个位置的职责",
        _position_duty(position),
        "",
        "## 必须出现",
        *[f"- {m}" for m in must_have],
        "",
        "## 禁止出现",
        *[f"- {f}" for f in forbidden],
        "",
        "## 差异化(硬线)",
        (f"- 兄弟店 {', '.join(siblings)} 卖的是同一批货;你的图不能和它们的主图长得一样(构图 / 角度 / 背景 / 配色至少两处不同)。参考图里有它们现在的主图。" if siblings else "- 这条产品线只有这一家店在卖,不用做兄弟店差异化。"),
        "",
        "## 交稿",
        f"- 位置:{position};格式 PNG/JPEG;主图 ≥ 1000×1000 且正方形;其余位置竖版优先(手机端)。",
        f"- 每个位置最多 4 轮;每轮交稿后看审核结果(同屏门 / 事实门 / 差异化门 / 格式门),只改被指出的那一块。",
        "- 你交的图不会自动上线;人在控制台选定后手动上传到亚马逊。",
    ]
    if sku or asin:
        lines.insert(1, f"SKU:{sku or '—'} · ASIN:{asin or '—'}")
    return "\n".join(lines)


def _position_duty(position: str) -> str:
    return {
        "main": "- 主图:白底、产品占画面 85% 以上、无文字无水印;它是在搜索页跟旁边 5–15 张图同屏比的,目标是被点,不是拍得好看。光线 / 角度 / 构图决定点击。",
        "angle": "- 多角度:背面 / 侧面 / 底部 / 内部,消除「长什么样」的不确定。",
        "benefit": "- 核心卖点信息图:一张图一个卖点,最多 2–3 个;图标 + 短句 + 引导线;标题字号至少占短边 5%。",
        "detail": "- 功能细节:材质特写、界面细节、结构分解;标注线和放大框。",
        "scale": "- 尺寸参照:和手 / 手机并列,或精确尺寸图;回答「到底多大」。",
        "lifestyle": "- 生活场景:真实使用场景,人和环境匹配目标人群。",
        "package": "- 包装内含:盒子和所有配件一目了然。",
        "aplus": "- A+ 图:首屏全宽 + 一句价值主张,重点放左上;移动优先。",
    }.get(position, "- 按七图职责画。")


def _must_and_forbidden(facts: dict[str, Any], position: str) -> tuple[list[str], list[str]]:
    must: list[str] = []
    forbidden: list[str] = []
    if facts.get("is"):
        must.append(f"产品本体与事实一致:{facts['is'][:120]}")
    if position == "package" and facts.get("package"):
        must.append(f"包装内含全部出现:{facts['package'][:160]}")
    if position in ("detail", "benefit") and facts.get("indicators"):
        must.append(f"指示灯 / 屏幕按事实画:{facts['indicators'][:160]}")
    dims = (facts.get("specs") or {}).get("dimensions_cm")
    if dims and position == "scale":
        must.append(f"尺寸标注:{dims} cm")
    if position == "main":
        forbidden += ["任何文字、logo、水印、徽章、促销贴纸", "非白底、道具、模特手以外的干扰物"]
    if facts.get("is_not"):
        forbidden.append(f"暗示它不是的功能:{facts['is_not'][:160]}")
    if facts.get("misreadings"):
        forbidden.append(f"会加深已知误解的画面:{facts['misreadings'][:160]}")
    forbidden += ["别人的品牌名或商标", "与事实表参数不符的接口 / 按键 / 配件"]
    return must, forbidden


def create_brief(
    db: Session,
    *,
    store_code: str,
    position: str,
    actor: User,
    product_line: str | None = None,
    sku: str | None = None,
    asin: str | None = None,
    title: str | None = None,
    reason: str | None = None,
    suggestion: AmzSuggestion | None = None,
) -> AmzImageBrief:
    store = db.get(AmzStore, (store_code or "").lower())
    if store is None:
        raise AmzServiceError(f"unknown store {store_code}", status_code=404, code="amz_store_not_found")
    position = (position or "main").lower()
    if position not in POSITIONS:
        raise AmzServiceError(f"unknown position {position}", status_code=422, code="amz_position_invalid")
    evidence: dict[str, Any] = {}
    if suggestion is not None:
        evidence = dict(suggestion.evidence_json or {})
        product_line = product_line or str(evidence.get("product_line") or "other")
    if sku and not product_line:
        product = db.get(AmzProduct, (store.store_code, sku))
        product_line = product.product_line if product is not None else product_line_of(sku)
    product_line = (product_line or "other").lower()
    if not sku:
        top = _top_sku(db, store.store_code, product_line)
        sku = top.sku if top is not None else None
        asin = asin or (top.asin if top is not None else None)
    if reason:
        evidence["reason"] = reason.strip()[:500]
    # 事实表门:出图 brief 这个用途不够就不建。
    sheet = fact_sheets.ready_for(db, product_line=product_line, use="image", store_code=store.store_code, sku=sku)
    if sheet is None:
        raise AmzServiceError(f"「{PRODUCT_LINE_LABELS.get(product_line, product_line)}」的事实表在「出图 brief」这个用途上还不够(或没有),殷熊不画。先去管理页把事实表填够。", status_code=409, code="amz_fact_sheet_not_ready")
    facts = sheet.facts_json or {}
    siblings = sibling_stores(db, store, product_line)
    must, forbidden = _must_and_forbidden(facts, position)
    brief = AmzImageBrief(
        store_code=store.store_code,
        sku=sku,
        asin=(asin or "").upper() or None,
        product_line=product_line,
        position=position,
        title=(title or "").strip()[:255] or f"{store.store_code} {PRODUCT_LINE_LABELS.get(product_line, product_line)} {POSITION_LABELS.get(position, position)}" + (f"「{evidence['term']}」" if evidence.get("term") else ""),
        status="queued",
        evidence_json=evidence,
        must_have_json=must,
        forbidden_json=forbidden,
        source_suggestion_id=suggestion.id if suggestion is not None else None,
        fact_sheet_id=sheet.id,
        created_by_user_id=int(actor.id),
    )
    brief.brief_md = build_brief_md(store=store, position=position, product_line=product_line, sku=sku, asin=brief.asin, facts=facts, evidence=evidence, siblings=siblings, must_have=must, forbidden=forbidden)
    db.add(brief)
    db.flush()
    work_log.record(db, employee=EMPLOYEE_B, kind="observation", title=f"建了图片 brief:{brief.title}", why=str(evidence.get("reason") or (f"「{evidence['term']}」同屏输给 {(evidence.get('best') or {}).get('store')}" if evidence.get("term") else "")), store_code=store.store_code, subject=f"image|{position}|{sku or ''}", asin=brief.asin, sku=sku, detail={"brief_id": str(brief.id), "siblings": siblings}, source="human", actor_user_id=int(actor.id))
    return brief


def create_brief_from_suggestion(db: Session, *, suggestion_id: UUID, actor: User) -> AmzImageBrief:
    row = db.get(AmzSuggestion, suggestion_id)
    if row is None:
        raise AmzServiceError("suggestion not found", status_code=404, code="amz_suggestion_not_found")
    if row.action_type != ACTION_SCREEN_CTR_GAP:
        raise AmzServiceError("只有殷熊的「同屏输了」建议能直接生成 brief", status_code=422, code="amz_suggestion_not_image")
    existing = db.scalar(select(AmzImageBrief).where(AmzImageBrief.source_suggestion_id == row.id, AmzImageBrief.status.in_(("queued", "in_review", "approved"))))
    if existing is not None:
        return existing
    return create_brief(db, store_code=row.store_code, position="main", actor=actor, suggestion=row)


# ---------------------------------------------------------------- 参考图 / 交稿 / 四道门


def add_reference(db: Session, *, brief: AmzImageBrief, kind: str, contents: bytes, note: str | None, actor: User) -> AmzImageAsset:
    if kind not in REFERENCE_KINDS:
        raise AmzServiceError(f"unknown reference kind {kind}", status_code=422, code="amz_reference_kind_invalid")
    return _store_asset(db, brief=brief, kind=kind, contents=contents, note=note, submitted_via="upload", actor_user_id=int(actor.id))


def references(db: Session, brief: AmzImageBrief) -> list[AmzImageAsset]:
    return list(db.scalars(select(AmzImageAsset).where(AmzImageAsset.brief_id == brief.id, AmzImageAsset.kind.in_(REFERENCE_KINDS), AmzImageAsset.status != "removed").order_by(AmzImageAsset.created_at)))


def submissions(db: Session, brief: AmzImageBrief) -> list[AmzImageAsset]:
    return list(db.scalars(select(AmzImageAsset).where(AmzImageAsset.brief_id == brief.id, AmzImageAsset.kind == KIND_SUBMISSION).order_by(AmzImageAsset.round.desc(), AmzImageAsset.created_at.desc())))


def gate_format(asset: AmzImageAsset, *, position: str) -> dict[str, Any]:
    problems = []
    if position == "main":
        if min(asset.width, asset.height) < MAIN_MIN_SIDE:
            problems.append(f"主图短边 {min(asset.width, asset.height)}px < {MAIN_MIN_SIDE}px")
        ratio = asset.width / asset.height if asset.height else 0
        if abs(ratio - 1.0) > MAIN_ASPECT_TOLERANCE:
            problems.append(f"主图不是正方形({asset.width}×{asset.height})")
    return {"name": "格式门", "passed": not problems, "problems": problems}


def gate_sibling(asset: AmzImageAsset, refs: list[AmzImageAsset]) -> dict[str, Any]:
    siblings = [r for r in refs if r.kind == "sibling_main" and r.dhash]
    if not siblings or not asset.dhash:
        return {"name": "兄弟店差异化门", "passed": True, "skipped": "没有兄弟店主图参考" if not siblings else "无法算指纹", "distances": []}
    distances = [{"reference_id": str(r.id), "note": r.note, "hamming": hamming(asset.dhash, r.dhash)} for r in siblings]
    too_close = [d for d in distances if d["hamming"] < SIBLING_MIN_HAMMING]
    return {"name": "兄弟店差异化门", "passed": not too_close, "distances": distances, "problems": [f"与兄弟店主图({d['note'] or d['reference_id'][:8]})指纹距离 {d['hamming']} < {SIBLING_MIN_HAMMING},看起来是同一张图" for d in too_close]}


def _data_url(contents: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(contents).decode('ascii')}"


def _vision(messages: list[dict[str, Any]], *, org_id: str) -> dict[str, Any]:
    from ...db.session import SessionLocal  # noqa: PLC0415
    from ...services.ai_provider_router import AIExecutionRouter  # noqa: PLC0415
    from r_system_v2.ra.quota_ledger import PROVIDER_AMZ_IMAGE_GATES, refund, try_consume  # noqa: PLC0415

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AMZ_IMAGE_GATES)
        charged = True
    finally:
        ledger_db.close()
    provider_db = SessionLocal()
    try:
        result = AIExecutionRouter(provider_db, timeout_seconds=90.0, total_budget_seconds=120.0).execute(
            provider="chatgpt", task_type="chat", payload={"messages": messages, "response_format": {"type": "json_object"}, "temperature": 0}, org=org_id, module_id=MODULE_KEY
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AMZ_IMAGE_GATES)
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()
    payload: Any = result
    if isinstance(result, dict) and "content" in result and "passed" not in result:
        raw = result["content"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise ValueError("vision output is not an object")
    return payload


SAME_SCREEN_PROMPT = """你是亚马逊搜索结果页的买家。第一张是候选主图,后面几张是同一个搜索结果页里旁边的图(对手和兄弟店)。
只回答一个 json:{"passed": true/false, "click_rank": 1..N(候选在这一排里你会第几个点), "stands_out": "一句话说它凭什么被点或为什么不被点", "fix": ["只改这一块:…", …](最多三条,具体到构图/角度/背景/光线/颜色)}
passed 的标准:候选在这一排缩略图里能一眼被区分出来、并且不比多数对手差。"""

FACTS_PROMPT = """你是产品事实核对员。看这张图,对照下面的清单,只回答一个 json:
{"passed": true/false, "must_have_missing": [清单里没出现的], "forbidden_found": [清单里禁止但出现了的], "text_or_logo": true/false(图上有没有文字/logo/水印), "notes": ["其它明显与事实不符的地方"]}
清单:
必须出现:<<MUST>>
禁止出现:<<FORBIDDEN>>
产品事实:<<FACTS>>"""


def gate_same_screen(*, candidate: bytes, refs: list[tuple[str, bytes]], org_id: str, call=None) -> dict[str, Any]:
    if not refs:
        return {"name": "同屏门", "passed": True, "skipped": "没有对手 / 兄弟店缩略图参考,无法比"}
    content: list[dict[str, Any]] = [{"type": "text", "text": SAME_SCREEN_PROMPT}, {"type": "text", "text": "候选:"}, {"type": "image_url", "image_url": {"url": _data_url(thumbnail_bytes(candidate))}}]
    for label, blob in refs[:8]:
        content.append({"type": "text", "text": f"旁边的图({label}):"})
        content.append({"type": "image_url", "image_url": {"url": _data_url(thumbnail_bytes(blob))}})
    try:
        out = (call or _vision)([{"role": "user", "content": content}], org_id=org_id)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("同屏门看图模型没接通: %s", exc)
        return {"name": "同屏门", "passed": None, "unknown": str(exc)[:200]}
    return {"name": "同屏门", "passed": bool(out.get("passed")), "click_rank": out.get("click_rank"), "stands_out": str(out.get("stands_out") or "")[:300], "fix": [str(x)[:200] for x in (out.get("fix") or [])][:3], "compared_with": [label for label, _ in refs[:8]]}


def gate_facts(*, candidate: bytes, brief: AmzImageBrief, facts: dict[str, Any], org_id: str, call=None) -> dict[str, Any]:
    prompt = (
        FACTS_PROMPT.replace("<<MUST>>", "; ".join(brief.must_have_json or []) or "(无)")
        .replace("<<FORBIDDEN>>", "; ".join(brief.forbidden_json or []) or "(无)")
        .replace("<<FACTS>>", json.dumps({k: facts.get(k) for k in ("is", "how_it_works", "is_not", "specs", "indicators", "package")}, ensure_ascii=False)[:2500])
    )
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": _data_url(thumbnail_bytes(candidate, max_side=1024))}}]
    try:
        out = (call or _vision)([{"role": "user", "content": content}], org_id=org_id)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("事实门看图模型没接通: %s", exc)
        return {"name": "事实门", "passed": None, "unknown": str(exc)[:200]}
    missing = [str(x)[:200] for x in (out.get("must_have_missing") or [])]
    found = [str(x)[:200] for x in (out.get("forbidden_found") or [])]
    text_logo = bool(out.get("text_or_logo")) and brief.position == "main"
    passed = bool(out.get("passed")) and not missing and not found and not text_logo
    return {"name": "事实门", "passed": passed, "must_have_missing": missing, "forbidden_found": found, "text_or_logo": text_logo, "notes": [str(x)[:200] for x in (out.get("notes") or [])][:5]}


def review_submission(db: Session, *, brief: AmzImageBrief, asset: AmzImageAsset, contents: bytes, call=None) -> dict[str, Any]:
    refs = references(db, brief)
    sheet = db.get(fact_sheets.AmzFactSheet, brief.fact_sheet_id) if brief.fact_sheet_id else None
    facts = (sheet.facts_json if sheet is not None else {}) or {}
    org_id = store_spec(brief.store_code).company.org_id if store_spec(brief.store_code) else ""
    screen_refs: list[tuple[str, bytes]] = []
    for r in refs:
        if r.kind in ("competitor_thumb", "sibling_main"):
            blob = asset_bytes(r)
            if blob:
                screen_refs.append((f"{REFERENCE_LABELS[r.kind]}{'·' + r.note if r.note else ''}", blob))
    gates = [gate_format(asset, position=brief.position), gate_sibling(asset, refs)]
    if brief.position == "main":
        gates.append(gate_same_screen(candidate=contents, refs=screen_refs, org_id=org_id, call=call))
    gates.append(gate_facts(candidate=contents, brief=brief, facts=facts, org_id=org_id, call=call))
    verdict = "passed" if all(g.get("passed") is True for g in gates) else ("failed" if any(g.get("passed") is False for g in gates) else "unknown")
    fixes: list[str] = []
    for g in gates:
        fixes += g.get("problems") or []
        fixes += g.get("fix") or []
        fixes += [f"缺:{m}" for m in g.get("must_have_missing") or []]
        fixes += [f"去掉:{f}" for f in g.get("forbidden_found") or []]
        if g.get("text_or_logo"):
            fixes.append("主图上不能有文字 / logo / 水印")
    return {"verdict": verdict, "gates": gates, "fix": fixes[:8], "reviewed_at": datetime.now(UTC).isoformat()}


def submit(db: Session, *, brief: AmzImageBrief, contents: bytes, note: str | None, submitted_via: str, actor_user_id: int, call=None) -> AmzImageAsset:
    if brief.status in ("live", "closed"):
        raise AmzServiceError("这份 brief 已经上线或关闭,不再收稿", status_code=409, code="amz_brief_closed")
    if brief.rounds >= brief.max_rounds:
        raise AmzServiceError(f"这个位置已经改了 {brief.rounds} 轮,到顶了——交给人从已有的几张里挑,不再画", status_code=409, code="amz_brief_rounds_exhausted")
    round_no = brief.rounds + 1
    asset = _store_asset(db, brief=brief, kind=KIND_SUBMISSION, contents=contents, note=note, submitted_via=submitted_via, actor_user_id=actor_user_id, round_no=round_no)
    asset.review_json = review_submission(db, brief=brief, asset=asset, contents=contents, call=call)
    asset.status = "staged"
    brief.rounds = round_no
    brief.status = "in_review"
    db.add(asset)
    db.add(brief)
    db.flush()
    work_log.record(db, employee=EMPLOYEE_B, kind="observation", title=f"第 {round_no} 轮交稿:{brief.title} → {asset.review_json['verdict']}", why="; ".join(asset.review_json.get("fix") or [])[:500], store_code=brief.store_code, subject=f"image|{brief.position}|{brief.sku or ''}", asin=brief.asin, sku=brief.sku, detail={"brief_id": str(brief.id), "asset_id": str(asset.id), "via": submitted_via}, source="api" if submitted_via == "mcp" else "human", actor_user_id=actor_user_id)
    return asset


def decide_asset(db: Session, *, asset: AmzImageAsset, decision: str, reason: str | None, actor: User) -> AmzImageAsset:
    if decision not in ("choose", "reject"):
        raise AmzServiceError("decision 只能是 choose / reject", status_code=422, code="amz_decision_invalid")
    brief = db.get(AmzImageBrief, asset.brief_id)
    if brief is None:
        raise AmzServiceError("brief not found", status_code=404, code="amz_brief_not_found")
    if decision == "reject" and not (reason or "").strip():
        raise AmzServiceError("驳回要写一句原因", status_code=422, code="amz_reject_reason_required")
    asset.status = "chosen" if decision == "choose" else "rejected"
    asset.decided_by_user_id = int(actor.id)
    asset.decided_at = datetime.now(UTC)
    asset.review_json = {**(asset.review_json or {}), "human": {"decision": decision, "reason": (reason or "").strip()[:500] or None}}
    if decision == "choose":
        brief.chosen_asset_id = asset.id
        brief.status = "approved"
        brief.decided_by_user_id = int(actor.id)
        brief.decided_at = datetime.now(UTC)
        db.add(brief)
    db.add(asset)
    db.flush()
    work_log.record(db, employee=EMPLOYEE_B, kind="approved" if decision == "choose" else "rejected", title=f"{'选定' if decision == 'choose' else '驳回'}第 {asset.round} 轮的图:{brief.title}", why=(reason or "").strip(), store_code=brief.store_code, subject=f"image|{brief.position}|{brief.sku or ''}", asin=brief.asin, sku=brief.sku, detail={"brief_id": str(brief.id), "asset_id": str(asset.id), "gates": (asset.review_json or {}).get("verdict")}, source="human", actor_user_id=int(actor.id))
    return asset


# ---------------------------------------------------------------- 上线与回看


def term_ctr(db: Session, *, store_code: str, term: str, start: date, end: date) -> dict[str, Any]:
    T = AmzAdSearchTerm
    row = db.execute(select(func.sum(T.impressions), func.sum(T.clicks)).where(T.store_code == store_code, func.lower(func.trim(T.search_term)) == term.lower().strip(), T.report_date >= start, T.report_date <= end)).one()
    impressions, clicks = int(row[0] or 0), int(row[1] or 0)
    return {"start": start.isoformat(), "end": end.isoformat(), "impressions": impressions, "clicks": clicks, "ctr_pct": round(clicks / impressions * 100, 2) if impressions else None}


def sqp_click_share(db: Session, *, store_code: str, asin: str | None, term: str, start: date, end: date) -> float | None:
    if not asin:
        return None
    rows = list(db.scalars(select(AmzSqp.clicks_share_pct).where(AmzSqp.store_code == store_code, AmzSqp.asin == asin, func.lower(AmzSqp.search_query) == term.lower().strip(), AmzSqp.period_start >= start, AmzSqp.period_start <= end)))
    vals = [float(v) for v in rows if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def mark_live(db: Session, *, brief: AmzImageBrief, actor: User, live_on: date | None = None) -> AmzImageBrief:
    if brief.chosen_asset_id is None:
        raise AmzServiceError("先选定一张图,再标记上线", status_code=409, code="amz_brief_nothing_chosen")
    live_on = live_on or datetime.now(UTC).date()
    brief.live_at = datetime.combine(live_on, datetime.min.time(), tzinfo=UTC)
    brief.status = "live"
    term = str((brief.evidence_json or {}).get("term") or "")
    baseline: dict[str, Any] = {"live_on": live_on.isoformat()}
    if term:
        baseline["term"] = term
        baseline["ads_ctr_14d_before"] = term_ctr(db, store_code=brief.store_code, term=term, start=live_on - timedelta(days=14), end=live_on - timedelta(days=1))
        baseline["sqp_click_share_before"] = sqp_click_share(db, store_code=brief.store_code, asin=brief.asin, term=term, start=live_on - timedelta(days=28), end=live_on - timedelta(days=1))
    brief.baseline_json = baseline
    db.add(brief)
    db.flush()
    work_log.record(db, employee=EMPLOYEE_B, kind="executed", title=f"图已上线(人手动传的):{brief.title}", why=f"基线:{json.dumps(baseline, ensure_ascii=False)[:300]}", store_code=brief.store_code, subject=f"image|{brief.position}|{brief.sku or ''}", asin=brief.asin, sku=brief.sku, detail={"brief_id": str(brief.id)}, source="human", actor_user_id=int(actor.id))
    return brief


def run_lookbacks(db: Session, *, today: date | None = None) -> int:
    """上线满 14 / 28 天的 brief:算上线后 CTR 和 SQP 点击份额,和基线比,写 lookback 与工作日志。幂等(已算过的天不重算)。"""
    today = today or datetime.now(UTC).date()
    done = 0
    for brief in db.scalars(select(AmzImageBrief).where(AmzImageBrief.status == "live", AmzImageBrief.live_at.is_not(None))):
        live_on = brief.live_at.date()
        term = str((brief.evidence_json or {}).get("term") or "")
        lookback = dict(brief.lookback_json or {})
        changed = False
        for days in LOOKBACK_DAYS:
            key = f"d{days}"
            if key in lookback or (today - live_on).days < days or not term:
                continue
            after = term_ctr(db, store_code=brief.store_code, term=term, start=live_on, end=live_on + timedelta(days=days - 1))
            before = (brief.baseline_json or {}).get("ads_ctr_14d_before") or {}
            share_after = sqp_click_share(db, store_code=brief.store_code, asin=brief.asin, term=term, start=live_on, end=live_on + timedelta(days=days))
            share_before = (brief.baseline_json or {}).get("sqp_click_share_before")
            delta = (after["ctr_pct"] - before["ctr_pct"]) if after.get("ctr_pct") is not None and before.get("ctr_pct") is not None else None
            lookback[key] = {"computed_on": today.isoformat(), "ads_ctr_after": after, "ads_ctr_delta_points": round(delta, 2) if delta is not None else None, "sqp_click_share_after": share_after, "sqp_click_share_before": share_before}
            changed = True
            verdict = "涨了" if delta is not None and delta > 0.15 else ("掉了" if delta is not None and delta < -0.15 else "没明显变化")
            work_log.record(db, employee=EMPLOYEE_B, kind="observation", title=f"上线 {days} 天回看:{brief.title} 在「{term}」上的点击率{verdict}({before.get('ctr_pct')}% → {after.get('ctr_pct')}%)", why="经验库材料:同款同词换图前后对照", store_code=brief.store_code, subject=f"image|{brief.position}|{brief.sku or ''}", asin=brief.asin, sku=brief.sku, detail=lookback[key], source="rule")
            done += 1
        if changed:
            brief.lookback_json = lookback
            db.add(brief)
    db.flush()
    return done


# ---------------------------------------------------------------- 视图


def brief_view(brief: AmzImageBrief, *, with_md: bool = False) -> dict[str, Any]:
    out = {
        "id": str(brief.id),
        "store_code": brief.store_code,
        "sku": brief.sku,
        "asin": brief.asin,
        "product_line": brief.product_line,
        "product_line_label": PRODUCT_LINE_LABELS.get(brief.product_line, brief.product_line),
        "position": brief.position,
        "position_label": POSITION_LABELS.get(brief.position, brief.position),
        "title": brief.title,
        "status": brief.status,
        "evidence": brief.evidence_json or {},
        "must_have": brief.must_have_json or [],
        "forbidden": brief.forbidden_json or [],
        "rounds": brief.rounds,
        "max_rounds": brief.max_rounds,
        "source_suggestion_id": str(brief.source_suggestion_id) if brief.source_suggestion_id else None,
        "chosen_asset_id": str(brief.chosen_asset_id) if brief.chosen_asset_id else None,
        "live_at": brief.live_at.isoformat() if brief.live_at else None,
        "baseline": brief.baseline_json or {},
        "lookback": brief.lookback_json or {},
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
        "updated_at": brief.updated_at.isoformat() if brief.updated_at else None,
    }
    if with_md:
        out["brief_md"] = brief.brief_md
    return out


def asset_view(asset: AmzImageAsset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "brief_id": str(asset.brief_id),
        "kind": asset.kind,
        "kind_label": REFERENCE_LABELS.get(asset.kind, "交稿"),
        "round": asset.round,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "bytes": asset.bytes,
        "note": asset.note,
        "submitted_via": asset.submitted_via,
        "status": asset.status,
        "review": asset.review_json or {},
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def list_briefs(db: Session, *, store_codes: list[str] | None, status: str | None = None) -> list[AmzImageBrief]:
    query = select(AmzImageBrief)
    if store_codes is not None:
        if not store_codes:
            return []
        query = query.where(AmzImageBrief.store_code.in_(store_codes))
    if status and status != "all":
        query = query.where(AmzImageBrief.status == status)
    return list(db.scalars(query.order_by(AmzImageBrief.updated_at.desc()).limit(200)))


def codex_prompt(brief: AmzImageBrief) -> str:
    """深链预填的短指令:让 Codex 自己去 MCP 拉完整 brief 和参考图,画完交回。"""
    return (
        f"用 barong_amz_images 这个 MCP:先 amz_get_image_brief(\"{brief.id}\") 拿完整 brief,"
        f"再 amz_get_reference_images(\"{brief.id}\") 拿参考图;按 brief 画一张「{POSITION_LABELS.get(brief.position, brief.position)}」,"
        f"用 amz_submit_image(\"{brief.id}\", image_base64) 交稿,然后 amz_get_submission_status(\"{brief.id}\") 看四道门的结果,"
        f"只改被指出的那一块再交;最多 {brief.max_rounds} 轮。不要自己加任何 brief 里没有的功能或文字。"
    )


__all__ = [
    "BRIEF_STATUSES",
    "KIND_SUBMISSION",
    "POSITIONS",
    "POSITION_LABELS",
    "REFERENCE_KINDS",
    "REFERENCE_LABELS",
    "add_reference",
    "asset_bytes",
    "asset_view",
    "brief_view",
    "codex_prompt",
    "create_brief",
    "create_brief_from_suggestion",
    "decide_asset",
    "derivative_path",
    "dhash",
    "gate_facts",
    "gate_format",
    "gate_same_screen",
    "gate_sibling",
    "hamming",
    "list_briefs",
    "mark_live",
    "media_root",
    "references",
    "review_submission",
    "run_lookbacks",
    "submissions",
    "submit",
    "thumbnail_bytes",
    "validate_image",
]
