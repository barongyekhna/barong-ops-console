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

_REVIEW_CONF_FLOOR = Decimal("0.6")


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
        text("SELECT 1 FROM k_category_amazon WHERE id = :i"), {"i": cat_id}
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
    ).first():
        return
    rows = db.execute(
        text("SELECT id, name, full_path FROM k_category_google WHERE lower(name) = :n"),
        {"n": _norm(aname)},  # lower+normalized-ish; exact-name fast path
    ).fetchall()
    # Fall back to key-normalized candidates when exact-lower found nothing.
    if not rows:
        rows = db.execute(
            text(
                "SELECT id, name, full_path FROM k_category_google "
                "WHERE lower(name) LIKE :like"
            ),
            {"like": f"%{_norm(aname)}%"},
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
    )


def google_for_amazon(db: Session, amazon_id: str) -> tuple[str | None, Decimal | None]:
    row = db.execute(
        text(
            "SELECT google_id, confidence FROM k_category_alignment "
            "WHERE amazon_id = :a AND marketplace = 'US'"
        ),
        {"a": amazon_id},
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
    product.google_product_category = google_id
    product.category_confidence = conf
    product.category_review_needed = bool(
        google_id is None or (conf is not None and conf < _REVIEW_CONF_FLOOR)
    )


def category_is_bound(product) -> bool:
    """The K→P hard gate: a product must carry a category for its channel."""
    channel = (getattr(product, "channel", None) or "dtc").strip().lower()
    if channel == "amazon":
        return bool(getattr(product, "amazon_category_id", None))
    return bool(getattr(product, "google_product_category", None))
