"""Read-only DB-to-active-volume consistency gate and manifest renderer.

The backup and restore workflows use the exact same implementation.  A
manifest is accepted only when every active object is referenced by metadata,
every metadata reference exists on disk, and size/SHA-256 agree byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .database import DatabaseRuntime
from .models import Asset, DatasetIdentity


OBJECT_KEY_PATTERN = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{28}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AssetConsistencyError(RuntimeError):
    """Raised when metadata and active bytes are not one exact dataset."""


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    sha256_hex: str
    size_bytes: int
    object_key: str

    def render(self) -> str:
        return f"{self.sha256_hex}\t{self.size_bytes}\t{self.object_key}"


def _validated_entry(
    *, object_key: str | None, size_bytes: int | None, sha256_hex: str | None
) -> ManifestEntry | None:
    if object_key is None:
        return None
    if (
        OBJECT_KEY_PATTERN.fullmatch(object_key) is None
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
        or not isinstance(sha256_hex, str)
        or SHA256_PATTERN.fullmatch(sha256_hex) is None
    ):
        raise AssetConsistencyError("active object metadata is incomplete or invalid")
    return ManifestEntry(
        sha256_hex=sha256_hex,
        size_bytes=size_bytes,
        object_key=object_key,
    )


def _assert_read_only_dataset(session: Session, *, dataset_id: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # This must be the first statement in the transaction.
        session.execute(text("SET TRANSACTION READ ONLY"))
    identity = session.get(DatasetIdentity, "primary")
    if identity is None or identity.dataset_id != dataset_id:
        raise AssetConsistencyError("asset dataset identity does not match")


def backup_drain_blocker_count(session: Session, *, dataset_id: str) -> int:
    """Count states that must settle before a portable backup may start."""

    _assert_read_only_dataset(session, dataset_id=dataset_id)
    count = session.scalar(
        select(func.count())
        .select_from(Asset)
        .where(
            or_(
                Asset.status.in_(("uploaded", "scanning", "delete_pending")),
                and_(
                    Asset.status.in_(("rejected", "quarantined")),
                    or_(
                        Asset.incoming_object_key.is_not(None),
                        Asset.active_object_key.is_not(None),
                        Asset.thumbnail_object_key.is_not(None),
                    ),
                ),
            )
        )
    )
    return int(count or 0)


def database_manifest(session: Session, *, dataset_id: str) -> dict[str, ManifestEntry]:
    """Return every DB-owned active original/thumbnail without changing state."""

    _assert_read_only_dataset(session, dataset_id=dataset_id)
    entries: dict[str, ManifestEntry] = {}
    rows = session.execute(
        select(
            Asset.active_object_key,
            Asset.actual_size_bytes,
            Asset.actual_sha256_hex,
            Asset.thumbnail_object_key,
            Asset.thumbnail_size_bytes,
            Asset.thumbnail_sha256_hex,
        )
    ).all()
    for row in rows:
        original = _validated_entry(
            object_key=row.active_object_key,
            size_bytes=row.actual_size_bytes,
            sha256_hex=row.actual_sha256_hex,
        )
        thumbnail = _validated_entry(
            object_key=row.thumbnail_object_key,
            size_bytes=row.thumbnail_size_bytes,
            sha256_hex=row.thumbnail_sha256_hex,
        )
        if row.thumbnail_object_key is None and any(
            value is not None
            for value in (row.thumbnail_size_bytes, row.thumbnail_sha256_hex)
        ):
            raise AssetConsistencyError("thumbnail metadata exists without an object")
        for entry in (original, thumbnail):
            if entry is None:
                continue
            if entry.object_key in entries:
                raise AssetConsistencyError("active object key is referenced more than once")
            entries[entry.object_key] = entry
    return entries


def _hash_regular_file(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssetConsistencyError("active object could not be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AssetConsistencyError("active volume contains a non-regular object")
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
        stable_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        if stable_identity != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or size != after.st_size:
            raise AssetConsistencyError("active object changed during verification")
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def filesystem_manifest(active_root: Path) -> dict[str, ManifestEntry]:
    """Hash every regular object under a non-symlink active volume root."""

    if not active_root.is_absolute():
        raise AssetConsistencyError("active root must be absolute")
    if active_root.is_symlink() or not active_root.is_dir():
        raise AssetConsistencyError("active root must be a non-symlink directory")
    root = active_root.resolve(strict=True)
    entries: dict[str, ManifestEntry] = {}
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directories:
            candidate = directory_path / name
            if candidate.is_symlink():
                raise AssetConsistencyError("active volume contains a symbolic link")
        for name in filenames:
            candidate = directory_path / name
            if candidate.is_symlink():
                raise AssetConsistencyError("active volume contains a symbolic link")
            object_key = candidate.relative_to(root).as_posix()
            if OBJECT_KEY_PATTERN.fullmatch(object_key) is None:
                raise AssetConsistencyError("active volume contains an invalid object path")
            if object_key in entries:
                raise AssetConsistencyError("active volume contains a duplicate object path")
            size_bytes, sha256_hex = _hash_regular_file(candidate)
            entries[object_key] = ManifestEntry(
                sha256_hex=sha256_hex,
                size_bytes=size_bytes,
                object_key=object_key,
            )
    return entries


def assert_consistent_active_dataset(
    session: Session, *, dataset_id: str, active_root: Path
) -> dict[str, ManifestEntry]:
    """Fail closed unless DB metadata and active bytes are exactly equivalent."""

    database_entries = database_manifest(session, dataset_id=dataset_id)
    filesystem_entries = filesystem_manifest(active_root)
    if set(database_entries) != set(filesystem_entries):
        raise AssetConsistencyError(
            "active object path set does not match database metadata"
        )
    for object_key, database_entry in database_entries.items():
        if database_entry != filesystem_entries[object_key]:
            raise AssetConsistencyError(
                "active object size or SHA-256 does not match database metadata"
            )
    return filesystem_entries


def render_manifest(entries: dict[str, ManifestEntry]) -> str:
    lines = [entries[key].render() for key in sorted(entries)]
    return "" if not lines else "\n".join(lines) + "\n"


def _database_url_for_name(database_url: str, database_name: str | None) -> str:
    if database_name is None:
        return database_url
    if DATABASE_NAME_PATTERN.fullmatch(database_name) is None:
        raise AssetConsistencyError("target database name is invalid")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise AssetConsistencyError("database-name override requires PostgreSQL")
    return url.set(database=database_name).render_as_string(hide_password=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="c19-asset-consistency")
    parser.add_argument(
        "--database-name",
        help="validated database name override for isolated restore verification",
    )
    parser.add_argument(
        "--drain-blocker-count",
        action="store_true",
        help="print the read-only pre-backup worker drain blocker count",
    )
    args = parser.parse_args(argv)
    try:
        database_url = os.environ.get("C19_ASSET_DATABASE_URL", "").strip()
        dataset_id = os.environ.get("C19_ASSET_DATASET_ID", "").strip()
        active_root_raw = os.environ.get("C19_ASSET_ACTIVE_ROOT", "").strip()
        if not database_url or not dataset_id:
            raise AssetConsistencyError("required consistency environment is missing")
        runtime = DatabaseRuntime.create(
            _database_url_for_name(database_url, args.database_name)
        )
        try:
            with runtime.session_factory() as session:
                if args.drain_blocker_count:
                    blockers = backup_drain_blocker_count(
                        session, dataset_id=dataset_id
                    )
                    entries = None
                else:
                    if not active_root_raw:
                        raise AssetConsistencyError(
                            "required consistency environment is missing"
                        )
                    entries = assert_consistent_active_dataset(
                        session,
                        dataset_id=dataset_id,
                        active_root=Path(active_root_raw),
                    )
        finally:
            runtime.dispose()
        if args.drain_blocker_count:
            sys.stdout.write(f"{blockers}\n")
        else:
            assert entries is not None
            sys.stdout.write(render_manifest(entries))
        return 0
    except Exception as exc:
        if isinstance(exc, AssetConsistencyError):
            detail = str(exc)
        else:
            detail = "database or filesystem verification failed"
        print(f"C19 asset consistency check failed: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
