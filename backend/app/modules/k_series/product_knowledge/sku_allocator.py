"""Concurrency-safe, leaf-category SKU allocation for K and P.

Public product SKUs are generated once as ``<leaf prefix>-<sequence>``.  The
database upsert is the serialization point: two workers allocating in the same
leaf receive different numbers, while a unique prefix reservation keeps two
different leaves with the same initials from producing overlapping SKUs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import re
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, NoInspectionAvailable, SQLAlchemyError
from sqlalchemy.orm import Session

from ....services.data_isolation import without_org_data_isolation
from .models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)

logger = logging.getLogger(__name__)

SKU_PREFIX_MAX_LENGTH = 16
SKU_NUMBER_MIN_WIDTH = 3

# Explicit exceptions are the stable contract for ambiguous category initials.
# The sequence table is also a persistent leaf_key -> prefix mapping, and its
# unique prefix constraint resolves previously unseen collisions safely.
CATEGORY_PREFIX_OVERRIDES: dict[str, str] = {
    "cold therapy machine": "CTM",
    "in ground lights": "IGL",
    # Both this category and "Outdoor String Lights" naturally abbreviate OSL.
    "outdoor solar lights": "OSOL",
}

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_PREFIX_RE = re.compile(r"[^A-Z0-9]+")
_MANAGED_SKU_RE = re.compile(r"^[A-Z0-9]{1,16}-[0-9]{3,}$")
_STOP_WORDS = frozenset({"and", "for", "of", "the", "to", "with"})
_PATH_SEPARATOR_RE = re.compile(r"\s*[>›/]\s*")


class SkuAllocationError(RuntimeError):
    """Raised only when no unique prefix can be reserved."""


@dataclass(frozen=True, slots=True)
class LeafCategory:
    key: str
    name: str


def _normalized_name(value: str) -> str:
    return " ".join(_WORD_RE.findall((value or "").lower()))


def _clean_prefix(value: str) -> str:
    return _PREFIX_RE.sub("", (value or "").upper())[:SKU_PREFIX_MAX_LENGTH]


def derive_category_prefix(leaf_name: str) -> str:
    """Derive stable initials such as In-Ground Lights -> IGL."""

    normalized = _normalized_name(leaf_name)
    override = CATEGORY_PREFIX_OVERRIDES.get(normalized)
    if override:
        return _clean_prefix(override)

    raw_words = _WORD_RE.findall(leaf_name or "")
    words = [word for word in raw_words if word.lower() not in _STOP_WORDS]
    if not words:
        return "CAT"
    if len(words) == 1:
        # A three-character stem is more useful than a one-letter namespace.
        prefix = words[0][:3]
    else:
        pieces: list[str] = []
        for word in words:
            # Keep familiar initialisms (LED, USB, etc.) intact.
            pieces.append(word if word.isupper() and len(word) <= 4 else word[0])
        prefix = "".join(pieces)
    return _clean_prefix(prefix) or "CAT"


def is_managed_sku(value: object) -> bool:
    return bool(_MANAGED_SKU_RE.fullmatch(str(value or "").strip().upper()))


def _prefix_candidates(leaf: LeafCategory) -> list[str]:
    base = derive_category_prefix(leaf.name)
    candidates = [base]
    digest = hashlib.sha1(leaf.key.encode("utf-8")).hexdigest().upper()
    for suffix_length in range(2, min(len(digest), 10) + 1):
        stem = base[: SKU_PREFIX_MAX_LENGTH - suffix_length]
        candidate = f"{stem}{digest[:suffix_length]}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _legacy_prefix_max(db: Session, prefix: str) -> int:
    """Avoid reissuing a pre-allocator SKU that already exists in K."""

    try:
        with without_org_data_isolation():
            with db.begin_nested():
                rows = db.execute(
                    text(
                        "SELECT sku FROM k_product_knowledge_products "
                        "WHERE sku LIKE :sku_prefix"
                    ),
                    {"sku_prefix": f"{prefix}-%"},
                ).scalars()
                maximum = 0
                pattern = re.compile(rf"^{re.escape(prefix)}-([0-9]+)$")
                for raw_sku in rows:
                    match = pattern.fullmatch(str(raw_sku or "").strip().upper())
                    if match:
                        maximum = max(maximum, int(match.group(1)))
                return maximum
    except SQLAlchemyError:
        # Unit-level or transitional schemas may not have the K products table.
        # The unique sequence row still protects allocator-to-allocator races.
        logger.debug("Could not inspect legacy SKUs for prefix %s", prefix, exc_info=True)
        return 0


def allocate_sku(db: Session, *, leaf_key: str, leaf_name: str) -> str:
    """Atomically issue the next SKU for a leaf category.

    ``INSERT .. ON CONFLICT .. DO UPDATE .. RETURNING`` works as one statement
    on both the production PostgreSQL database and SQLite-backed regression
    tests.  A savepoint lets a prefix collision retry without aborting the
    caller's transaction.
    """

    leaf = LeafCategory(
        key=str(leaf_key or "").strip()[:128] or "fallback:uncategorized",
        name=str(leaf_name or "").strip()[:512] or "Uncategorized",
    )
    for prefix in _prefix_candidates(leaf):
        first_sequence = _legacy_prefix_max(db, prefix) + 1
        try:
            with without_org_data_isolation():
                with db.begin_nested():
                    row = db.execute(
                        text(
                            "INSERT INTO k_sku_sequences "
                            "(leaf_key, leaf_name, prefix, next_seq) "
                            "VALUES (:leaf_key, :leaf_name, :prefix, :next_seq) "
                            "ON CONFLICT (leaf_key) DO UPDATE SET "
                            "leaf_name = excluded.leaf_name, "
                            "next_seq = k_sku_sequences.next_seq + 1, "
                            "updated_at = CURRENT_TIMESTAMP "
                            "RETURNING prefix, next_seq"
                        ),
                        {
                            "leaf_key": leaf.key,
                            "leaf_name": leaf.name,
                            "prefix": prefix,
                            "next_seq": first_sequence + 1,
                        },
                    ).mappings().one()
            sequence_number = int(row["next_seq"]) - 1
            return f"{row['prefix']}-{sequence_number:0{SKU_NUMBER_MIN_WIDTH}d}"
        except IntegrityError:
            # A different leaf reserved these initials concurrently.  The next
            # stable hash-suffixed candidate becomes this leaf's persisted map.
            continue
    raise SkuAllocationError(f"No unique SKU prefix available for leaf {leaf.key!r}.")


def _category_row(
    db: Session,
    *,
    table_name: str,
    category_id: object,
) -> dict[str, Any] | None:
    normalized_id = str(category_id or "").strip()
    if not normalized_id:
        return None
    try:
        with without_org_data_isolation():
            with db.begin_nested():
                row = db.execute(
                    text(
                        f"SELECT id, name, full_path, is_leaf "  # noqa: S608
                        f"FROM {table_name} WHERE id = :category_id"
                    ),
                    {"category_id": normalized_id},
                ).mappings().first()
        return dict(row) if row is not None else None
    except SQLAlchemyError:
        logger.debug(
            "SKU leaf lookup unavailable table=%s category_id=%s",
            table_name,
            normalized_id,
            exc_info=True,
        )
        return None


def _path_leaf(value: object) -> str | None:
    segments = [
        segment.strip()
        for segment in _PATH_SEPARATOR_RE.split(str(value or ""))
        if segment.strip()
    ]
    return segments[-1] if segments else None


def resolve_product_leaf(db: Session, product: Any) -> LeafCategory:
    """Resolve the channel's real taxonomy leaf, with a non-blocking fallback."""

    channel = str(getattr(product, "channel", None) or "dtc").strip().lower()
    lookups = (
        (
            "k_category_amazon",
            "amazon",
            getattr(product, "amazon_category_id", None),
        ),
        (
            "k_category_google",
            "google",
            getattr(product, "google_product_category", None),
        ),
    )
    if channel != "amazon":
        lookups = (lookups[1], lookups[0])

    non_leaf_ids: set[tuple[str, str]] = set()
    non_leaf_paths: set[str] = set()
    for table_name, taxonomy, category_id in lookups:
        row = _category_row(
            db,
            table_name=table_name,
            category_id=category_id,
        )
        if row is None:
            continue
        if not bool(row.get("is_leaf")):
            normalized_id = str(row.get("id") or category_id or "").strip()
            if normalized_id:
                non_leaf_ids.add((taxonomy, normalized_id))
            for raw_non_leaf_path in (row.get("full_path"), row.get("name")):
                normalized_non_leaf_path = _normalized_name(
                    str(raw_non_leaf_path or "")
                )
                if normalized_non_leaf_path:
                    non_leaf_paths.add(normalized_non_leaf_path)
            logger.warning(
                "SKU taxonomy node is not a leaf; trying path fallback "
                "product_id=%s taxonomy=%s category_id=%s",
                getattr(product, "id", None),
                taxonomy,
                normalized_id,
            )
            continue
        name = str(row.get("name") or "").strip() or _path_leaf(row.get("full_path"))
        if name:
            return LeafCategory(key=f"{taxonomy}:{row['id']}", name=name)

    # R-sourced records retain their full Amazon path, which is still a real
    # leaf name even when a taxonomy cache row is temporarily unavailable.
    for field_name in ("category_path", "merchant_product_type", "category_hint"):
        raw_value = getattr(product, field_name, None)
        name = _path_leaf(raw_value)
        normalized_path = _normalized_name(str(raw_value))[:96]
        if name and normalized_path not in non_leaf_paths:
            return LeafCategory(
                key=f"path:{normalized_path}"[:128],
                name=name,
            )

    for taxonomy, category_id in (
        ("google", getattr(product, "google_product_category", None)),
        ("amazon", getattr(product, "amazon_category_id", None)),
    ):
        normalized_id = str(category_id or "").strip()
        if normalized_id and (taxonomy, normalized_id) not in non_leaf_ids:
            logger.warning(
                "SKU category name unavailable; using category-id fallback "
                "product_id=%s taxonomy=%s category_id=%s",
                getattr(product, "id", None),
                taxonomy,
                normalized_id,
            )
            return LeafCategory(
                key=f"{taxonomy}:{normalized_id}"[:128],
                name=f"Category {normalized_id}",
            )

    logger.warning(
        "SKU leaf category unavailable; using uncategorized sequence product_id=%s",
        getattr(product, "id", None),
    )
    return LeafCategory(key="fallback:uncategorized", name="Uncategorized")


def _synchronize_product_sku_family(
    db: Session,
    product: KProductKnowledgeProduct,
    sku: str,
) -> None:
    """Keep variants and their media references aligned with a fixed SKU.

    Physical media object keys are deliberately left in place: renaming a DB
    path without moving the stored object would break downloads.  The public
    SKU fields and metadata are rekeyed; future images use the new folder.
    """

    variants = db.scalars(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id == product.id)
        .with_for_update()
    ).all()
    new_by_variant_id: dict[Any, str] = {}
    new_by_old_sku: dict[str, str] = {}
    for variant in variants:
        old_variant_sku = str(variant.variant_sku or "").strip()
        new_variant_sku = f"{sku}-{variant.variant_hash}"
        if old_variant_sku:
            new_by_old_sku[old_variant_sku] = new_variant_sku
        new_by_variant_id[variant.id] = new_variant_sku
        variant.parent_sku = sku
        variant.variant_sku = new_variant_sku
        variant.image_folder = f"images/{product.product_key}/{new_variant_sku}"

    assets = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(KProductKnowledgeMediaAsset.product_id == product.id)
        .with_for_update()
    ).all()
    for asset in assets:
        old_asset_sku = str(asset.variant_sku or "").strip()
        new_asset_sku = new_by_variant_id.get(asset.variant_id)
        if new_asset_sku is None and old_asset_sku:
            new_asset_sku = new_by_old_sku.get(old_asset_sku)
        if new_asset_sku is not None:
            asset.variant_sku = new_asset_sku

        if isinstance(asset.metadata_json, dict):
            metadata = dict(asset.metadata_json)
            if "sku" in metadata:
                metadata["sku"] = sku
            metadata_variant_sku = str(metadata.get("variant_sku") or "").strip()
            if metadata_variant_sku in new_by_old_sku:
                metadata["variant_sku"] = new_by_old_sku[metadata_variant_sku]
            elif new_asset_sku is not None and "variant_sku" in metadata:
                metadata["variant_sku"] = new_asset_sku
            asset.metadata_json = metadata


def ensure_product_sku(
    db: Session,
    product: KProductKnowledgeProduct,
    *,
    force_allocate: bool = False,
) -> str:
    """Assign and persist one SKU, or return the already-issued value.

    Persisted products are locked before the check so concurrent first-publish
    requests cannot consume two sequence values for the same product.
    """

    try:
        state = sa_inspect(product)
    except NoInspectionAvailable:
        # Assembly unit tests and offline contract consumers use lightweight
        # product doubles.  They have no row to lock or persist, so preserve an
        # explicitly supplied SKU; production callers always pass the ORM row.
        existing = str(getattr(product, "sku", None) or "").strip().upper()
        if existing:
            return existing
        raise SkuAllocationError("Cannot persist a SKU for a non-ORM product.")
    if state.persistent:
        locked = db.scalar(
            select(KProductKnowledgeProduct)
            .where(KProductKnowledgeProduct.id == product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is not None:
            product = locked

    existing = str(product.sku or "").strip().upper()
    if existing and is_managed_sku(existing) and (
        not force_allocate or state.persistent
    ):
        product.parent_sku = existing
        if state.persistent:
            _synchronize_product_sku_family(db, product, existing)
            db.flush()
        return existing

    leaf = resolve_product_leaf(db, product)
    sku = allocate_sku(db, leaf_key=leaf.key, leaf_name=leaf.name)
    product.sku = sku
    product.parent_sku = sku
    if state.persistent:
        # Also repairs sku=NULL and half-migrated legacy rows.
        _synchronize_product_sku_family(db, product, sku)
    db.add(product)
    db.flush()
    return sku


__all__ = [
    "CATEGORY_PREFIX_OVERRIDES",
    "LeafCategory",
    "SkuAllocationError",
    "allocate_sku",
    "derive_category_prefix",
    "ensure_product_sku",
    "is_managed_sku",
    "resolve_product_leaf",
]
