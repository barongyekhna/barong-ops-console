"""放行词表(11-03 老板定):老板确认「用在我们商品上不是别人的牌子」的普通词,全站所有商品、所有品牌检查都认。

起因:熊猫造型的淋浴器叫 Panda Outdoor Shower,「panda」一再被 K 的风险词、品牌审查、苏青禾的代码当成别人的商标挡掉。
老板原话:「不能因为有一家公司叫panda，就不让我用这个词形容我的产品了。我的产品是真实的panda造型的。就好像说不能因为
苹果手机叫苹果，就不让买苹果的果农叫苹果了吧……他的panda商标只限餐饮类和我一点关系都没有」。

规矩:
- 只有老板(owner)能加/删(router 用 require_owner);AI 永远不往里加词。
- 一个被判成「别人的牌子」的词/短语,只要整词含放行词,就不算违规;但同一个短语里还带着真正的竞品牌子
  (``HARD_BRANDS``,如 DeWalt、Coleman、Stanley)就照样拦——「panda shower for dewalt」不能因为有 panda 就过。
- 进程内缓存 ``CACHE_SECONDS``:老板在后台加了词,worker 一分钟内认到;读表失败退回上一次读到的(第一次失败 = 空集)。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

_LOGGER = logging.getLogger("k-brand-allow")

CACHE_SECONDS = 60.0
MAX_TERM_LENGTH = 120

# 同品类真竞品(定价提示词点名的工具/户外大牌 + 苏青禾选品不要的),在放行词旁边出现也照样拦。
# FAQ 研究里那张第三方牌子黑名单(faq_research._THIRD_PARTY_BRAND_BLACKLIST)也算,运行时合进来。
_EXTRA_HARD_BRANDS = (
    "milwaukee",
    "dewalt",
    "bosch",
    "makita",
    "ryobi",
    "thermacell",
    "hyper tough",
    "ozark trail",
    "black+decker",
    "black and decker",
    "worx",
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+'&-]*")
# 风险原因 / 审查理由里说「是别人的牌子」;「非品牌词」「not a brand」这类否定说法不算(原来按字一刀切,连这种都挡)
_BRAND_REASON = re.compile(r"商标|品牌|侵权|竞品|trademark|brand", re.IGNORECASE)
_NOT_BRAND_REASON = re.compile(
    r"(?:非|不是|无|没有|不涉及|不属于|不含)\s*(?:第三方|别人的?|他人的?)?\s*(?:品牌|商标)"
    r"|not\s+(?:a\s+)?(?:third[- ]party\s+)?(?:brand|trademark)|no\s+(?:brand|trademark)|generic\s+(?:term|word)",
    re.IGNORECASE,
)
_cache_lock = threading.Lock()
_cache: tuple[float, frozenset[str]] | None = None


def normalize(term: Any) -> str:
    """小写、空白压成一个、去掉首尾标点;空 = 空字符串。"""
    text = " ".join(str(term or "").lower().split())
    return text.strip(" \t\"'`.,;:!?()[]{}<>“”‘’「」|/\\")


def hard_brands() -> tuple[str, ...]:
    from .faq_research import _THIRD_PARTY_BRAND_BLACKLIST  # noqa: PLC0415 —— 防循环导入

    return tuple(dict.fromkeys([*_THIRD_PARTY_BRAND_BLACKLIST, *_EXTRA_HARD_BRANDS]))


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def reason_says_brand(reason: Any) -> bool:
    """K / 审查器给的理由是不是在说「这是别人的牌子」(带否定的不算)。"""
    text = str(reason or "")
    return bool(_BRAND_REASON.search(text)) and not _NOT_BRAND_REASON.search(text)


def contains_hard_brand(term: Any) -> bool:
    text = normalize(term)
    return bool(text) and any(_has_phrase(text, brand) for brand in hard_brands())


def is_covered(term: Any, allowed: Iterable[str] | None = None) -> bool:
    """这个被判成「牌子」的词/短语,是不是老板放行过的普通词(整词出现),且旁边没有真竞品牌子。"""
    text = normalize(term)
    if not text:
        return False
    words = allowed_words() if allowed is None else frozenset(normalize(w) for w in allowed)
    if not any(word and _has_phrase(text, word) for word in words):
        return False
    return not contains_hard_brand(text)


def strip_covered(terms: Iterable[Any], allowed: Iterable[str] | None = None) -> list[str]:
    """从「禁用牌子」名单里去掉老板放行过的词(给文案/出图/SEO 的 forbidden 名单用)。"""
    words = allowed_words() if allowed is None else frozenset(normalize(w) for w in allowed)
    out: list[str] = []
    for term in terms:
        text = str(term or "").strip()
        if text and not is_covered(text, words):
            out.append(text)
    return out


def _load(db: Session | None) -> frozenset[str]:
    from .models import KBrandAllowTerm  # noqa: PLC0415

    if db is not None:
        # 用调用方的会话读,包一层 savepoint:表不在 / 读失败只回滚这一小段,不把调用方的事务弄坏
        with db.begin_nested():
            terms = db.scalars(select(KBrandAllowTerm.term)).all()
        return frozenset(normalize(t) for t in terms if normalize(t))
    from ....db.session import SessionLocal  # noqa: PLC0415

    with SessionLocal() as session:
        words = frozenset(normalize(t) for t in session.scalars(select(KBrandAllowTerm.term)) if normalize(t))
        session.rollback()
        return words


def allowed_words(db: Session | None = None, *, fresh: bool = False) -> frozenset[str]:
    """放行词(归一化)。默认走一分钟缓存;``fresh`` 或传了 db 且缓存过期时重读。读不到 = 上一次的。"""
    global _cache  # noqa: PLW0603
    now = time.monotonic()
    with _cache_lock:
        if not fresh and _cache is not None and now - _cache[0] < CACHE_SECONDS:
            return _cache[1]
    try:
        words = _load(db)
    except Exception:  # noqa: BLE001 —— 读表失败不拖垮审查,退回上一次;也记进缓存,一分钟内不再反复连库
        _LOGGER.warning("brand allow-list read failed", exc_info=True)
        with _cache_lock:
            words = _cache[1] if _cache is not None else frozenset()
            _cache = (now, words)
            return words
    with _cache_lock:
        _cache = (now, words)
    return words


def reset_cache() -> None:
    global _cache  # noqa: PLW0603
    with _cache_lock:
        _cache = None


class BrandAllowError(ValueError):
    pass


def validate_term(term: Any) -> str:
    text = normalize(term)
    if not text:
        raise BrandAllowError("放行词不能是空的")
    if len(text) > MAX_TERM_LENGTH:
        raise BrandAllowError(f"放行词最长 {MAX_TERM_LENGTH} 个字符")
    if not _TOKEN.search(text):
        raise BrandAllowError("放行词要是英文词(商品页、关键词都是英文)")
    if contains_hard_brand(text):
        raise BrandAllowError("这是同品类真竞品的牌子,不能放行")
    return text


def list_terms(db: Session) -> list[dict[str, Any]]:
    from .models import KBrandAllowTerm  # noqa: PLC0415

    rows = db.scalars(select(KBrandAllowTerm).order_by(KBrandAllowTerm.term)).all()
    return [
        {"id": str(row.id), "term": row.term, "note": row.note, "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]


def add_term(db: Session, *, term: Any, note: str | None, user_id: UUID | None) -> dict[str, Any]:
    """加一个放行词(已有就更新备注)。调用方 commit。"""
    from .models import KBrandAllowTerm  # noqa: PLC0415

    text = validate_term(term)
    row = db.scalar(select(KBrandAllowTerm).where(KBrandAllowTerm.term == text))
    if row is None:
        row = KBrandAllowTerm(term=text, note=(note or "").strip()[:2000] or None, created_by_user_id=user_id)
        db.add(row)
    elif note and note.strip():
        row.note = note.strip()[:2000]
    db.flush()
    reset_cache()
    return {"id": str(row.id), "term": row.term, "note": row.note}


def remove_term(db: Session, *, term: Any) -> bool:
    from .models import KBrandAllowTerm  # noqa: PLC0415

    row = db.scalar(select(KBrandAllowTerm).where(KBrandAllowTerm.term == normalize(term)))
    if row is None:
        return False
    db.delete(row)
    db.flush()
    reset_cache()
    return True


__all__ = [
    "BrandAllowError",
    "CACHE_SECONDS",
    "add_term",
    "allowed_words",
    "contains_hard_brand",
    "hard_brands",
    "is_covered",
    "list_terms",
    "normalize",
    "reason_says_brand",
    "remove_term",
    "reset_cache",
    "strip_covered",
    "validate_term",
]
