"""Single-writer validation, scan, promotion, quarantine, and deletion worker."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import WorkerSettings
from .database import DatabaseRuntime
from .models import Asset, TransferTicket
from .repository import _audit, ensure_dataset_identity
from .scanner import ClamdScanner, MalwareDetectedError, Scanner, ScannerUnavailableError
from .validation import (
    ContentValidationError,
    ValidationLimits,
    atomic_promote,
    validate_content,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _new_object_key() -> str:
    value = uuid.uuid4().hex
    return f"{value[:2]}/{value[2:4]}/{value[4:]}"


def _safe_path(root: Path, object_key: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / object_key).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ContentValidationError("unsafe object key") from exc
    return candidate


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
    except FileNotFoundError:
        return


@dataclass(frozen=True, slots=True)
class ClaimedAsset:
    asset_id: str
    version: int
    incoming_object_key: str
    kind: str
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str


class AssetWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        database: DatabaseRuntime | None = None,
        scanner: Scanner | None = None,
    ) -> None:
        self.settings = settings
        self.database = database or DatabaseRuntime.create(settings.database_url)
        self.scanner = scanner or ClamdScanner(
            settings.clamd_host,
            settings.clamd_port,
            signature_max_age_hours=settings.clamd_signature_max_age_hours,
        )
        self.settings.incoming_root.mkdir(parents=True, exist_ok=True)
        self.settings.active_root.mkdir(parents=True, exist_ok=True)
        self.settings.quarantine_root.mkdir(parents=True, exist_ok=True)
        with self.database.session_factory() as session:
            ensure_dataset_identity(session, settings.dataset_id)
        self.limits = ValidationLimits(
            image_max_pixels=settings.image_max_pixels,
            image_max_dimension=settings.image_max_dimension,
            image_max_frames=settings.image_max_frames,
            image_max_total_frame_pixels=settings.image_max_total_frame_pixels,
            thumbnail_max_bytes=settings.thumbnail_max_bytes,
            archive_max_members=settings.archive_max_members,
            archive_max_unpacked_bytes=settings.archive_max_unpacked_bytes,
            archive_max_ratio=settings.archive_max_ratio,
        )
        self._last_orphan_cleanup: datetime | None = None

    def close(self) -> None:
        self.database.dispose()

    def _claim_uploaded(self) -> ClaimedAsset | None:
        with self.database.session_factory() as session:
            statement = (
                select(Asset)
                .where(Asset.status == "uploaded")
                .order_by(Asset.updated_at, Asset.asset_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            asset = session.execute(statement).scalar_one_or_none()
            if asset is None:
                return None
            if (
                not asset.incoming_object_key
                or not asset.filename
                or not asset.media_type
                or not asset.actual_size_bytes
                or not asset.actual_sha256_hex
            ):
                previous = asset.status
                asset.status = "quarantined"
                asset.failure_code = "metadata_invariant"
                asset.updated_at = utcnow()
                _audit(
                    session,
                    asset,
                    "worker_quarantined",
                    actor_type="worker",
                    from_status=previous,
                    to_status="quarantined",
                )
                session.commit()
                return None
            asset.status = "scanning"
            asset.failure_code = None
            asset.updated_at = utcnow()
            _audit(
                session,
                asset,
                "scan_started",
                actor_type="worker",
                from_status="uploaded",
                to_status="scanning",
            )
            claimed = ClaimedAsset(
                asset_id=asset.asset_id,
                version=asset.version,
                incoming_object_key=asset.incoming_object_key,
                kind=asset.kind,
                filename=asset.filename,
                media_type=asset.media_type,
                size_bytes=asset.actual_size_bytes,
                sha256_hex=asset.actual_sha256_hex,
            )
            session.commit()
            return claimed

    def _quarantine_claim(self, claim: ClaimedAsset, failure_code: str) -> None:
        source = _safe_path(self.settings.incoming_root, claim.incoming_object_key)
        quarantine_key: str | None = None
        if source.is_file() and not source.is_symlink():
            quarantine_key = _new_object_key()
            destination = _safe_path(self.settings.quarantine_root, quarantine_key)
            try:
                atomic_promote(source, destination)
                source.unlink()
            except Exception:
                quarantine_key = None
        with self.database.session_factory() as session:
            asset = session.execute(
                select(Asset).where(Asset.asset_id == claim.asset_id).with_for_update()
            ).scalar_one_or_none()
            if asset is None:
                if quarantine_key:
                    _unlink(_safe_path(self.settings.quarantine_root, quarantine_key))
                return
            previous = asset.status
            if previous == "delete_pending":
                if quarantine_key:
                    _unlink(_safe_path(self.settings.quarantine_root, quarantine_key))
                return
            if previous not in {"scanning", "quarantined", "rejected"}:
                if quarantine_key:
                    _unlink(_safe_path(self.settings.quarantine_root, quarantine_key))
                return
            asset.status = "quarantined"
            asset.failure_code = failure_code
            asset.quarantine_object_key = quarantine_key
            if quarantine_key:
                asset.incoming_object_key = None
            asset.updated_at = utcnow()
            _audit(
                session,
                asset,
                "worker_quarantined",
                actor_type="worker",
                from_status=previous,
                to_status="quarantined",
            )
            session.commit()

    def _activate(self, claim: ClaimedAsset) -> None:
        incoming = _safe_path(self.settings.incoming_root, claim.incoming_object_key)
        work_key = uuid.uuid4().hex
        thumbnail_work = self.settings.incoming_root / ".worker" / f"{work_key}.png"
        original_key = _new_object_key()
        thumbnail_key: str | None = _new_object_key() if claim.kind == "image" else None
        original_destination = _safe_path(self.settings.active_root, original_key)
        thumbnail_destination = (
            _safe_path(self.settings.active_root, thumbnail_key)
            if thumbnail_key is not None
            else None
        )
        try:
            if not incoming.is_file() or incoming.is_symlink():
                raise ContentValidationError("incoming object is unavailable")
            observed_size, observed_hash = _sha256(incoming)
            if observed_size != claim.size_bytes or observed_hash != claim.sha256_hex:
                raise ContentValidationError("incoming object digest mismatch")
            self.scanner.scan(incoming)
            result = validate_content(
                incoming,
                kind=claim.kind,
                filename=claim.filename,
                declared_media_type=claim.media_type,
                limits=self.limits,
                thumbnail_path=thumbnail_work if claim.kind == "image" else None,
            )
            if result.size_bytes != claim.size_bytes or result.sha256_hex != claim.sha256_hex:
                raise ContentValidationError("validated object digest mismatch")
            atomic_promote(incoming, original_destination)
            if thumbnail_destination is not None:
                if not thumbnail_work.is_file():
                    raise ContentValidationError("thumbnail generation failed")
                atomic_promote(thumbnail_work, thumbnail_destination)
            with self.database.session_factory() as session:
                asset = session.execute(
                    select(Asset).where(Asset.asset_id == claim.asset_id).with_for_update()
                ).scalar_one_or_none()
                if (
                    asset is None
                    or asset.version != claim.version
                    or asset.status != "scanning"
                ):
                    raise ContentValidationError("asset state changed during validation")
                now = utcnow()
                asset.status = "active"
                asset.active_object_key = original_key
                asset.thumbnail_object_key = thumbnail_key
                asset.thumbnail_size_bytes = result.thumbnail_size_bytes
                asset.thumbnail_sha256_hex = result.thumbnail_sha256_hex
                asset.thumbnail_media_type = result.thumbnail_media_type
                asset.incoming_object_key = None
                asset.failure_code = None
                asset.activated_at = now
                asset.updated_at = now
                _audit(
                    session,
                    asset,
                    "asset_activated",
                    actor_type="worker",
                    from_status="scanning",
                    to_status="active",
                    now=now,
                )
                session.commit()
            _unlink(incoming)
            _unlink(thumbnail_work)
        except MalwareDetectedError:
            _unlink(original_destination)
            _unlink(thumbnail_destination)
            _unlink(thumbnail_work)
            self._quarantine_claim(claim, "malware_detected")
        except ScannerUnavailableError:
            _unlink(original_destination)
            _unlink(thumbnail_destination)
            _unlink(thumbnail_work)
            self._quarantine_claim(claim, "scanner_unavailable")
        except Exception:
            _unlink(original_destination)
            _unlink(thumbnail_destination)
            _unlink(thumbnail_work)
            self._quarantine_claim(claim, "content_validation_failed")

    def _move_terminal_to_quarantine(self) -> bool:
        with self.database.session_factory() as session:
            asset = session.execute(
                select(Asset)
                .where(
                    Asset.status.in_(("quarantined", "rejected")),
                    Asset.quarantine_object_key.is_(None),
                    (
                        Asset.incoming_object_key.is_not(None)
                        | Asset.active_object_key.is_not(None)
                    ),
                )
                .order_by(Asset.updated_at, Asset.asset_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if asset is None:
                return False
            key = asset.incoming_object_key or asset.active_object_key
            source_root = (
                self.settings.incoming_root
                if asset.incoming_object_key
                else self.settings.active_root
            )
            if not key:
                return False
            source = _safe_path(source_root, key)
            quarantine_key = _new_object_key()
            destination = _safe_path(self.settings.quarantine_root, quarantine_key)
            try:
                if source.is_file() and not source.is_symlink():
                    atomic_promote(source, destination)
                    source.unlink()
                    asset.quarantine_object_key = quarantine_key
                asset.incoming_object_key = None
                asset.active_object_key = None
                if asset.thumbnail_object_key:
                    _unlink(
                        _safe_path(
                            self.settings.active_root, asset.thumbnail_object_key
                        )
                    )
                asset.thumbnail_object_key = None
                asset.thumbnail_size_bytes = None
                asset.thumbnail_sha256_hex = None
                asset.thumbnail_media_type = None
                asset.updated_at = utcnow()
                session.commit()
            except Exception:
                session.rollback()
            return True

    def _delete_one(self) -> bool:
        with self.database.session_factory() as session:
            asset = session.execute(
                select(Asset)
                .where(Asset.status == "delete_pending")
                .order_by(Asset.updated_at, Asset.asset_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if asset is None:
                return False
            for root, key in (
                (self.settings.incoming_root, asset.incoming_object_key),
                (self.settings.active_root, asset.active_object_key),
                (self.settings.active_root, asset.thumbnail_object_key),
                (self.settings.quarantine_root, asset.quarantine_object_key),
            ):
                if key:
                    _unlink(_safe_path(root, key))
            now = utcnow()
            asset.status = "deleted"
            asset.intent_sha256 = None
            asset.filename = None
            asset.media_type = None
            asset.declared_size_bytes = None
            asset.declared_sha256_hex = None
            asset.actual_size_bytes = None
            asset.actual_sha256_hex = None
            asset.incoming_object_key = None
            asset.active_object_key = None
            asset.quarantine_object_key = None
            asset.thumbnail_object_key = None
            asset.thumbnail_size_bytes = None
            asset.thumbnail_sha256_hex = None
            asset.thumbnail_media_type = None
            asset.failure_code = None
            asset.deleted_at = now
            asset.updated_at = now
            session.execute(
                update(TransferTicket)
                .where(
                    TransferTicket.asset_id == asset.asset_id,
                    TransferTicket.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            _audit(
                session,
                asset,
                "asset_deleted",
                actor_type="worker",
                from_status="delete_pending",
                to_status="deleted",
                now=now,
            )
            session.commit()
            return True

    def _recover_and_expire(self) -> None:
        now = utcnow()
        with self.database.session_factory() as session:
            session.execute(
                update(Asset)
                .where(
                    Asset.status == "scanning",
                    Asset.updated_at < now - timedelta(minutes=30),
                )
                .values(
                    status="uploaded",
                    failure_code="stale_scan_recovered",
                    updated_at=now,
                )
            )
            expired = list(
                session.execute(
                    select(Asset)
                    .where(
                        Asset.status == "pending_upload",
                        Asset.updated_at < now - timedelta(hours=24),
                    )
                    .with_for_update(skip_locked=True)
                ).scalars()
            )
            for asset in expired:
                if asset.incoming_object_key:
                    _unlink(
                        _safe_path(
                            self.settings.incoming_root, asset.incoming_object_key
                        )
                    )
                asset.incoming_object_key = None
                asset.status = "expired"
                asset.failure_code = "upload_expired"
                asset.updated_at = now
                session.execute(
                    update(TransferTicket)
                    .where(
                        TransferTicket.asset_id == asset.asset_id,
                        TransferTicket.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                _audit(
                    session,
                    asset,
                    "upload_expired",
                    actor_type="worker",
                    from_status="pending_upload",
                    to_status="expired",
                    now=now,
                )
            abandoned = list(
                session.execute(
                    select(Asset)
                    .where(
                        Asset.status == "active",
                        Asset.binding_status == "unbound",
                        Asset.activated_at.is_not(None),
                        Asset.activated_at
                        < now - timedelta(hours=self.settings.unbound_asset_ttl_hours),
                    )
                    .with_for_update(skip_locked=True)
                ).scalars()
            )
            for asset in abandoned:
                asset.status = "delete_pending"
                asset.version += 1
                asset.failure_code = "unbound_asset_expired"
                asset.updated_at = now
                session.execute(
                    update(TransferTicket)
                    .where(
                        TransferTicket.asset_id == asset.asset_id,
                        TransferTicket.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                _audit(
                    session,
                    asset,
                    "unbound_asset_expired",
                    actor_type="worker",
                    from_status="active",
                    to_status="delete_pending",
                    now=now,
                )
            session.execute(
                delete(TransferTicket).where(
                    TransferTicket.expires_at < now - timedelta(days=7)
                )
            )
            session.commit()

    def _cleanup_orphans(self) -> None:
        now = utcnow()
        if (
            self._last_orphan_cleanup is not None
            and now - self._last_orphan_cleanup < timedelta(minutes=10)
        ):
            return
        with self.database.session_factory() as session:
            rows = session.execute(
                select(
                    Asset.incoming_object_key,
                    Asset.active_object_key,
                    Asset.thumbnail_object_key,
                    Asset.quarantine_object_key,
                )
            ).all()
        referenced = {
            value
            for row in rows
            for value in row
            if isinstance(value, str) and value
        }
        cutoff = now - timedelta(hours=self.settings.orphan_grace_hours)
        object_pattern = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{28}$")
        staging_pattern = re.compile(
            r"^\.[0-9a-f]{28}(?:\.[0-9a-f]{32}\.part|\.promoting)$"
        )
        for root in (
            self.settings.incoming_root,
            self.settings.active_root,
            self.settings.quarantine_root,
        ):
            for first in root.glob("[0-9a-f][0-9a-f]"):
                if not first.is_dir() or first.is_symlink():
                    continue
                for second in first.glob("[0-9a-f][0-9a-f]"):
                    if not second.is_dir() or second.is_symlink():
                        continue
                    for candidate in second.iterdir():
                        if not candidate.is_file() or candidate.is_symlink():
                            continue
                        try:
                            modified = datetime.fromtimestamp(
                                candidate.stat().st_mtime, tz=UTC
                            )
                        except OSError:
                            continue
                        if modified >= cutoff:
                            continue
                        relative = candidate.relative_to(root).as_posix()
                        if object_pattern.fullmatch(relative):
                            if relative not in referenced:
                                _unlink(candidate)
                        elif staging_pattern.fullmatch(candidate.name):
                            _unlink(candidate)
        work_root = self.settings.incoming_root / ".worker"
        if work_root.is_dir() and not work_root.is_symlink():
            for candidate in work_root.iterdir():
                if (
                    not candidate.is_file()
                    or candidate.is_symlink()
                    or re.fullmatch(r"[0-9a-f]{32}\.png", candidate.name) is None
                ):
                    continue
                try:
                    modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
                except OSError:
                    continue
                if modified < cutoff:
                    _unlink(candidate)
        self._last_orphan_cleanup = now

    def run_once(self) -> bool:
        self._recover_and_expire()
        self._cleanup_orphans()
        if self._delete_one():
            return True
        if self._move_terminal_to_quarantine():
            return True
        claim = self._claim_uploaded()
        if claim is None:
            return False
        self._activate(claim)
        return True

    def run_forever(self, *, stop_event: threading.Event | None = None) -> None:
        """Finish the current unit of work before honoring a shutdown request."""

        shutdown = stop_event or threading.Event()
        while not shutdown.is_set():
            worked = self.run_once()
            if not worked:
                shutdown.wait(self.settings.poll_seconds)
