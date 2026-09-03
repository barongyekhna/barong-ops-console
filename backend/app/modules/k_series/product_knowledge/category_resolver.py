"""K 类目落入服务。

三件事（用户要的 5/6/7）：
- **自动创建**（#7）：产品带着一个 `k_category_amazon` 里没有的 Keepa 类目进 K
  时，把它作为 leaf 节点即时插入（真实 id + 名字路径），并做一次在线确定性对齐。
- **自动落入 · 亚马逊分组**（#5）：channel=amazon → 直接绑定 Keepa 类目。
- **自动落入 · 独立站分组**（#6）：channel=dtc → 查 Amazon→Google 对齐表，写入
  google_product_category；对齐缺失/低置信则 category_review_needed=True。

在线只走 SQL + 确定性匹配（快）。AI 对齐是离线批处理（见 scratchpad/align_ai*.py），
不在产品入库路径里跑。
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation

_REVIEW_CONF_FLOOR = Decimal("0.6")
_GOOGLE_PATH_SEPARATOR = re.compile(r"\s*[>›]\s*")
_GOOGLE_CATEGORY_ID = re.compile(r"[0-9]+")


def _norm(s: str) -> str:
    s = (s or "").lower().strip().replace("&", "and")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _sing(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _key(name: str) -> str:
    return " ".join(_sing(w) for w in _norm(name).split())


def _toks(path: str) -> set[str]:
    return {_sing(w) for w in _norm((path or "").replace(">", " ")).split()}


def _leaf_name(cat_path: str | None, cat_id: str) -> str:
    if cat_path:
        tail = cat_path.split(">")[-1].strip()
        if tail:
            return tail
    return cat_id


def _split_google_path(full_path: str | None) -> list[str]:
    """Split either taxonomy separator and normalize insignificant whitespace."""
    if not full_path:
        return []
    return [
        segment
        for raw_segment in _GOOGLE_PATH_SEPARATOR.split(full_path)
        if (segment := re.sub(r"\s+", " ", raw_segment).strip())
    ]


def _segment_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _path_key(segments: list[str]) -> tuple[str, ...]:
    return tuple(_segment_key(segment) for segment in segments)


def _google_category_by_id(
    db: Session, google_id: str
) -> dict[str, object] | None:
    row = db.execute(
        text(
            "SELECT id, name, full_path, parent_id, level "
            "FROM k_category_google WHERE id = :google_id"
        ),
        {"google_id": google_id},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().first()
    return dict(row) if row is not None else None


def _google_categories_named(db: Session, name: str) -> list[dict[str, object]]:
    """Return candidates only; callers must still match their complete path."""
    rows = db.execute(
        text(
            "SELECT id, name, full_path, parent_id, level "
            "FROM k_category_google WHERE lower(name) = lower(:name)"
        ),
        {"name": name},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    return [dict(row) for row in rows]


def _validated_parent_chain(
    db: Session, leaf: dict[str, object]
) -> list[dict[str, object]] | None:
    """Follow parent ids, returning None unless the entire chain is coherent."""
    chain: list[dict[str, object]] = []
    visited: set[str] = set()
    current: dict[str, object] | None = leaf

    while current is not None:
        current_id = str(current.get("id") or "").strip()
        if not current_id or current_id in visited:
            return None
        visited.add(current_id)
        chain.append(current)

        parent_id = str(current.get("parent_id") or "").strip()
        if not parent_id:
            break
        current = _google_category_by_id(db, parent_id)
        if current is None:
            return None

    chain.reverse()
    leaf_segments = _split_google_path(str(leaf.get("full_path") or ""))
    if not leaf_segments or len(chain) != len(leaf_segments):
        return None

    for index, row in enumerate(chain, start=1):
        row_segments = _split_google_path(str(row.get("full_path") or ""))
        expected_segments = leaf_segments[:index]
        if _path_key(row_segments) != _path_key(expected_segments):
            return None
        if _segment_key(row.get("name")) != _segment_key(expected_segments[-1]):
            return None
        try:
            row_level = int(row.get("level") or 0)
        except (TypeError, ValueError):
            return None
        if row_level != index:
            return None

    return chain


def _google_category_path_from_full_path(
    db: Session, leaf: dict[str, object]
) -> list[dict[str, object]]:
    """Resolve every ancestor by its cumulative full path, never by name alone."""
    leaf_id = str(leaf.get("id") or "").strip()
    segments = _split_google_path(str(leaf.get("full_path") or ""))
    if not leaf_id or not segments:
        return []

    chain: list[dict[str, object]] = []
    for index, segment in enumerate(segments, start=1):
        expected_path = _path_key(segments[:index])
        matches = [
            candidate
            for candidate in _google_categories_named(db, segment)
            if _path_key(
                _split_google_path(str(candidate.get("full_path") or ""))
            )
            == expected_path
            and _segment_key(candidate.get("name")) == _segment_key(segment)
        ]
        # The taxonomy has no unique constraint on full_path. Ambiguous data is
        # not safe to project into WooCommerce, so never return a partial chain.
        if len(matches) != 1:
            return []
        chain.append(matches[0])

    if str(chain[-1].get("id") or "").strip() != leaf_id:
        return []
    return chain


def _google_category_by_full_path(
    db: Session, full_path: str
) -> dict[str, object] | None:
    segments = _split_google_path(full_path)
    if not segments:
        return None
    expected_path = _path_key(segments)
    matches = [
        candidate
        for candidate in _google_categories_named(db, segments[-1])
        if _path_key(_split_google_path(str(candidate.get("full_path") or "")))
        == expected_path
    ]
    return matches[0] if len(matches) == 1 else None


def google_category_path(
    db: Session, google_id: str | None
) -> list[dict[str, str]]:
    """Return a Google taxonomy ancestor chain ordered from root to leaf.

    Parent links are preferred, but the imported taxonomy deliberately has no
    parent foreign key. A missing link, cycle, or inconsistent path therefore
    falls back to resolving each cumulative ``full_path`` prefix. If either
    strategy cannot prove the complete path, an empty list is returned.
    """
    normalized_id = str(google_id or "").strip()
    if not normalized_id:
        return []

    leaf = _google_category_by_id(db, normalized_id)
    if leaf is None:
        return []

    chain = _validated_parent_chain(db, leaf)
    if chain is None:
        chain = _google_category_path_from_full_path(db, leaf)
    if not chain:
        return []

    return [
        {"google_id": str(row["id"]), "name": str(row["name"])}
        for row in chain
    ]


def bind_google_category_id(db: Session, product, google_id: object) -> bool:
    """The only write boundary for a K product's Google taxonomy id.

    Google taxonomy primary keys are ASCII decimal ids.  AI category paths and
    merchant taxonomy text must live in hint/path fields, never in the id field.
    Returning ``False`` lets callers mark the product for category review
    without ever persisting an invalid value.
    """
    normalized = str(google_id or "").strip()
    with without_org_data_isolation():
        category_exists = (
            _GOOGLE_CATEGORY_ID.fullmatch(normalized) is not None
            and _google_category_by_id(db, normalized) is not None
        )
    if not category_exists:
        normalized = ""
    product.google_product_category = normalized or None
    return bool(normalized)


def repair_legacy_google_category_path(db: Session, product) -> bool:
    """Replace one legacy path value with its unique Google taxonomy leaf id."""
    raw_value = str(getattr(product, "google_product_category", None) or "").strip()
    if not raw_value or _GOOGLE_CATEGORY_ID.fullmatch(raw_value) is not None:
        return False
    with without_org_data_isolation():
        leaf = _google_category_by_full_path(db, raw_value)
    if leaf is None or not bind_google_category_id(db, product, leaf.get("id")):
        return False
    product.category_hint = raw_value[:255]
    product.category_review_needed = False
    return True


def assign_manual_category(
    db: Session, product, category_id: str | None
) -> None:
    """Bind a category selected from the channel-specific taxonomy tree."""
    if not category_id:
        return
    channel = (getattr(product, "channel", None) or "dtc").strip().lower()
    if channel == "amazon":
        product.amazon_category_id = category_id.strip()
        product.category_review_needed = False
        return
    product.category_review_needed = not bind_google_category_id(
        db, product, category_id
    )


def ensure_amazon_category(
    db: Session,
    cat_id: str | None,
    cat_path: str | None = None,
    name: str | None = None,
) -> bool:
    """Insert the Keepa leaf if unseen (+ attempt online deterministic align).
    Returns True if newly created."""
    if not cat_id:
        return False
    if db.execute(
        text("SELECT 1 FROM k_category_amazon WHERE id = :i"), {"i": cat_id},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).first():
        return False
    leaf = (name or _leaf_name(cat_path, cat_id))[:512]
    level = max(len([s for s in (cat_path or "").split(">") if s.strip()]), 1)
    db.execute(
        text(
            "INSERT INTO k_category_amazon "
            "(id,name,full_path,parent_id,level,is_leaf,marketplace) "
            "VALUES (:i,:n,:p,NULL,:l,true,'US') ON CONFLICT (id) DO NOTHING"
        ),
        {"i": cat_id, "n": leaf, "p": (cat_path or leaf)[:1024], "l": level},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    _deterministic_align(db, cat_id, cat_path or leaf, leaf)
    return True


def _deterministic_align(db: Session, amazon_id: str, apath: str, aname: str) -> None:
    """One cheap online pass: match the leaf name to a Google category, pick the
    best by path-token overlap. No AI here."""
    if db.execute(
        text(
            "SELECT 1 FROM k_category_alignment "
            "WHERE amazon_id = :a AND marketplace = 'US'"
        ),
        {"a": amazon_id},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).first():
        return
    rows = db.execute(
        text("SELECT id, name, full_path FROM k_category_google WHERE lower(name) = :n"),
        {"n": _norm(aname)},  # lower+normalized-ish; exact-name fast path,
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).fetchall()
    # Fall back to key-normalized candidates when exact-lower found nothing.
    if not rows:
        rows = db.execute(
            text(
                "SELECT id, name, full_path FROM k_category_google "
                "WHERE lower(name) LIKE :like"
            ),
            {"like": f"%{_norm(aname)}%"},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).fetchall()
    google_id: str | None = None
    conf: Decimal | None = None
    method = "normalized"
    if rows:
        at = _toks(apath)
        best = max(rows, key=lambda r: len(at & _toks(r[2])))
        overlap = len(at & _toks(best[2]))
        google_id = best[0]
        if _key(best[1]) == _key(aname):
            conf = Decimal("0.95") if overlap >= 2 else Decimal("0.80")
            method = "exact"
        else:
            conf = Decimal("0.70") if overlap >= 2 else Decimal("0.55")
    db.execute(
        text(
            "INSERT INTO k_category_alignment "
            "(amazon_id,marketplace,google_id,method,confidence,reviewed) "
            "VALUES (:a,'US',:g,:m,:c,false) "
            "ON CONFLICT (amazon_id,marketplace) DO NOTHING"
        ),
        {"a": amazon_id, "g": google_id, "m": method, "c": conf},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )


def google_for_amazon(db: Session, amazon_id: str) -> tuple[str | None, Decimal | None]:
    row = db.execute(
        text(
            "SELECT google_id, confidence FROM k_category_alignment "
            "WHERE amazon_id = :a AND marketplace = 'US'"
        ),
        {"a": amazon_id},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).first()
    return (row[0], row[1]) if row else (None, None)


def assign_category(db: Session, product) -> None:
    """Bind the product's category per its channel. Call on R→K transfer and
    after a manual pick. Expects product.channel + (amazon_category_id and/or
    category_path) already set for R-sourced products."""
    channel = (getattr(product, "channel", None) or "dtc").strip().lower()
    amz = getattr(product, "amazon_category_id", None)

    if amz:
        ensure_amazon_category(db, amz, getattr(product, "category_path", None))

    if channel == "amazon":
        # Amazon-group products drop straight into their Keepa node.
        product.category_review_needed = not bool(amz)
        return

    # DTC / 独立站: resolve via the alignment map.
    if not amz:
        product.category_review_needed = True
        return
    google_id, conf = google_for_amazon(db, amz)
    category_bound = bind_google_category_id(db, product, google_id)
    product.category_confidence = conf
    product.category_review_needed = bool(
        not category_bound or (conf is not None and conf < _REVIEW_CONF_FLOOR)
    )


def category_is_bound(product) -> bool:
    """The K→P hard gate: a product must carry a category for its channel."""
    channel = (getattr(product, "channel", None) or "dtc").strip().lower()
    if channel == "amazon":
        return bool(getattr(product, "amazon_category_id", None))
    return bool(getattr(product, "google_product_category", None))
