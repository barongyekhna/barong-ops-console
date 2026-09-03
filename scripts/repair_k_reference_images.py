#!/usr/bin/env python3
"""Repair K reference images corrupted by the shared-cache-key bug (2026-08-03).

``f_series.enrichment.images.get_candidate_image`` used to name its disk cache
``{candidate_id}_{variant}.img`` — without the image URL.  K's multi-image
import (``manual_reference.attach_manual_reference_images``) passes the SAME
candidate_id for every URL of one product, so only the FIRST url was ever
downloaded: every later URL hit that cache file and silently received the first
image's bytes.  The rows look perfect (each carries its own distinct
``source_url``); only the stored content is the same image over and over.

Effect on output: the image model never saw the product's other angles or its
accessories, so it invented them (PSPE-002 shipped an accessory shot with a
shower puff that does not exist in the real package, and the orange suction
hook drawn as a clear white one).

This script re-downloads every reference asset from its own recorded
``source_url``, compares against the stored bytes, and rewrites the ones that
do not match — including their preview/thumbnail derivatives and the
``content_sha256``/``file_size`` bookkeeping.

Run from the backend container (it needs the media volume and DB):

    python scripts/repair_k_reference_images.py                 # dry-run
    python scripts/repair_k_reference_images.py --execute
    python scripts/repair_k_reference_images.py --sku PSPE-002 --execute
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

import backend.app.models  # noqa: E402,F401  (先让模型注册表整体加载，避免循环导入)
from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.modules.f_series.enrichment.images import (  # noqa: E402
    _download,
    _host_allowed,
    sniff_media_type,
)
from backend.app.modules.k_series.product_knowledge.models import (  # noqa: E402
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from backend.app.services.media_store import (  # noqa: E402
    ensure_image_derivative,
    write_media_file,
)


def _media_root() -> Path:
    return Path(
        os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media").strip()
        or "/var/lib/barong/k-media"
    )


def _stored_bytes(root: Path, asset: KProductKnowledgeMediaAsset) -> bytes | None:
    if not asset.object_key:
        return None
    path = root / asset.object_key
    return path.read_bytes() if path.is_file() else None


def _rebuild_derivatives(
    asset: KProductKnowledgeMediaAsset,
    *,
    root: Path,
    execute: bool,
) -> str:
    """只重建派生图。

    2026-08-04：派生图按路径缓存，原图被替换后 preview/thumbnail 仍是旧的。
    所有 vision 调用（姿态标注 / 几何门 / 物理门）读的都是 preview，于是
    六张各不相同的参考图在模型眼里全是同一张。
    """
    if not asset.object_key:
        return "skipped:no_object_key"
    stored = _stored_bytes(root, asset)
    if stored is None:
        return "skipped:file_missing"
    if not execute:
        return "would-fix"
    meta = dict(asset.metadata_json if isinstance(asset.metadata_json, dict) else {})
    for kind, max_side in (("thumbnail", 320), ("preview", 1280)):
        try:
            path, key, _ = ensure_image_derivative(
                root=root,
                object_key=str(asset.object_key),
                kind=kind,
                max_side=max_side,
                contents=stored,
                force=True,
            )
            meta[f"{kind}_path"] = str(path)
            meta[f"{kind}_object_key"] = key
        except Exception:  # noqa: BLE001
            return "failed:derivative"
    asset.metadata_json = meta
    flag_modified(asset, "metadata_json")
    return "fixed"


def _repair_asset(
    asset: KProductKnowledgeMediaAsset,
    *,
    root: Path,
    execute: bool,
) -> str:
    """Return one of: ok | fixed | would-fix | skipped:<why> | failed:<why>."""
    meta = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    source_url = str(meta.get("source_url") or "").strip()
    if not source_url:
        return "skipped:no_source_url"
    if not _host_allowed(source_url):
        return "skipped:host_not_allowed"

    stored = _stored_bytes(root, asset)
    if stored is None:
        return "skipped:file_missing"

    try:
        fresh = _download(source_url)
    except Exception as exc:  # noqa: BLE001 - network/CDN failures are expected
        return f"failed:{type(exc).__name__}"
    if not fresh:
        return "failed:empty_response"

    if hashlib.sha256(fresh).hexdigest() == hashlib.sha256(stored).hexdigest():
        return "ok"
    if not execute:
        return "would-fix"

    object_key = str(asset.object_key)
    write_media_file(root, object_key, fresh)
    derived: dict[str, Any] = {}
    for kind, max_side in (("thumbnail", 320), ("preview", 1280)):
        try:
            path, key, _ = ensure_image_derivative(
                root=root,
                object_key=object_key,
                kind=kind,
                max_side=max_side,
                contents=fresh,
                force=True,
            )
            derived[f"{kind}_path"] = str(path)
            derived[f"{kind}_object_key"] = key
        except Exception:  # noqa: BLE001 - derivative is best-effort, like upload
            pass

    asset.mime_type = sniff_media_type(fresh)
    asset.file_size = len(fresh)
    new_meta = dict(meta)
    new_meta["content_sha256"] = hashlib.sha256(fresh).hexdigest()
    new_meta.update(derived)
    new_meta["repaired_by"] = "repair_k_reference_images"
    asset.metadata_json = new_meta
    flag_modified(asset, "metadata_json")
    return "fixed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually rewrite mismatched images (default: report only)",
    )
    parser.add_argument(
        "--rebuild-derivatives",
        action="store_true",
        help="不回源，只按现有原图重建 preview/thumbnail（原图已修好但派生图是旧的）",
    )
    parser.add_argument(
        "--sku",
        action="append",
        default=None,
        help="limit to these SKUs (repeatable); default = every product",
    )
    args = parser.parse_args()

    root = _media_root()
    db = SessionLocal()
    totals = {"ok": 0, "fixed": 0, "would-fix": 0, "skipped": 0, "failed": 0}
    try:
        query = select(KProductKnowledgeProduct)
        if args.sku:
            query = query.where(KProductKnowledgeProduct.sku.in_(args.sku))
        products = list(db.scalars(query.order_by(KProductKnowledgeProduct.sku)))
        for product in products:
            assets = list(
                db.scalars(
                    select(KProductKnowledgeMediaAsset)
                    .where(
                        KProductKnowledgeMediaAsset.product_id == product.id,
                        KProductKnowledgeMediaAsset.asset_role == "reference",
                        KProductKnowledgeMediaAsset.status == "available",
                    )
                    .order_by(KProductKnowledgeMediaAsset.created_at.asc())
                )
            )
            if not assets:
                continue
            outcomes = [
                (
                    _rebuild_derivatives(asset, root=root, execute=args.execute)
                    if args.rebuild_derivatives
                    else _repair_asset(asset, root=root, execute=args.execute)
                )
                for asset in assets
            ]
            for outcome in outcomes:
                totals[outcome.split(":")[0]] += 1
            changed = sum(1 for o in outcomes if o in ("fixed", "would-fix"))
            detail = "".join(
                f"\n    - {a.object_key.rsplit('/', 1)[-1][:52]}: {o}"
                for a, o in zip(assets, outcomes, strict=True)
                if o != "ok"
            )
            flag = "!!" if changed else "  "
            print(
                f"{flag} {product.sku or product.product_key}: "
                f"{len(assets)} refs, {changed} need repair{detail}"
            )
            if args.execute and changed:
                db.commit()
    finally:
        db.close()

    print(
        "\nTOTAL  ok=%(ok)d fixed=%(fixed)d would-fix=%(would-fix)d "
        "skipped=%(skipped)d failed=%(failed)d" % totals
    )
    if not args.execute and totals["would-fix"]:
        print("Dry run — re-run with --execute to rewrite them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
