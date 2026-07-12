"""Role-scoped, fail-closed configuration for the C19 asset runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


HARD_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_FILE_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024
HARD_THUMBNAIL_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_OWNER_RESERVED_FILES = 2_000
DEFAULT_OWNER_RESERVED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_GLOBAL_RESERVED_FILES = 100_000
DEFAULT_GLOBAL_RESERVED_BYTES = 50 * 1024 * 1024 * 1024


class AssetConfigurationError(RuntimeError):
    """Raised before startup when role-owned configuration is unsafe."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AssetConfigurationError(f"{name} must be configured")
    if "CHANGE-ME" in value.upper():
        raise AssetConfigurationError(f"{name} contains a deployment placeholder")
    return value


def _secret(name: str) -> str:
    value = _required(name)
    if len(value) < 32:
        raise AssetConfigurationError(f"{name} must contain at least 32 characters")
    return value


def _positive_int(name: str, default: int, *, ceiling: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise AssetConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise AssetConfigurationError(f"{name} must be positive")
    if ceiling is not None and value > ceiling:
        raise AssetConfigurationError(f"{name} exceeds the compiled safety limit")
    return value


def _path(name: str) -> Path:
    raw = _required(name)
    value = Path(raw)
    if not value.is_absolute():
        raise AssetConfigurationError(f"{name} must be an absolute path")
    return value


def escape_alembic_url(database_url: str) -> str:
    return database_url.replace("%", "%%")


@dataclass(frozen=True, slots=True)
class AssetApiSettings:
    database_url: str
    service_token: str
    gateway_token: str
    dataset_id: str
    upload_ticket_ttl_seconds: int = 900
    download_ticket_ttl_seconds: int = 60
    download_ticket_max_uses: int = 12
    max_pending_uploads_per_owner: int = 20
    max_upload_tickets_per_asset: int = 8
    database_workers: int = 4
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES
    file_max_bytes: int = DEFAULT_FILE_MAX_BYTES
    thumbnail_max_bytes: int = DEFAULT_THUMBNAIL_MAX_BYTES
    owner_reserved_file_limit: int = DEFAULT_OWNER_RESERVED_FILES
    owner_reserved_byte_limit: int = DEFAULT_OWNER_RESERVED_BYTES
    global_reserved_file_limit: int = DEFAULT_GLOBAL_RESERVED_FILES
    global_reserved_byte_limit: int = DEFAULT_GLOBAL_RESERVED_BYTES

    def __post_init__(self) -> None:
        if not self.database_url.strip() or "CHANGE-ME" in self.database_url.upper():
            raise AssetConfigurationError("C19_ASSET_DATABASE_URL must be configured")
        for name, value in (
            ("C19_ASSET_SERVICE_TOKEN", self.service_token),
            ("C19_ASSET_GATEWAY_TOKEN", self.gateway_token),
        ):
            if len(value) < 32 or "CHANGE-ME" in value.upper():
                raise AssetConfigurationError(f"{name} must be a non-placeholder secret")
        if not self.dataset_id.strip() or len(self.dataset_id) > 128:
            raise AssetConfigurationError("C19_ASSET_DATASET_ID is invalid")
        if self.service_token == self.gateway_token:
            raise AssetConfigurationError("service and gateway tokens must be distinct")
        for value in (self.image_max_bytes, self.file_max_bytes):
            if value <= 0 or value > HARD_MAX_BYTES:
                raise AssetConfigurationError("asset byte limit is invalid")
        if not 0 < self.thumbnail_max_bytes <= HARD_THUMBNAIL_MAX_BYTES:
            raise AssetConfigurationError("thumbnail byte limit is invalid")
        for value in (
            self.upload_ticket_ttl_seconds,
            self.download_ticket_ttl_seconds,
            self.download_ticket_max_uses,
            self.max_pending_uploads_per_owner,
            self.max_upload_tickets_per_asset,
            self.database_workers,
            self.owner_reserved_file_limit,
            self.owner_reserved_byte_limit,
            self.global_reserved_file_limit,
            self.global_reserved_byte_limit,
        ):
            if value <= 0:
                raise AssetConfigurationError("asset runtime limit must be positive")
        if self.global_reserved_file_limit < self.owner_reserved_file_limit:
            raise AssetConfigurationError(
                "global reserved file limit must cover one owner limit"
            )
        if self.global_reserved_byte_limit < self.owner_reserved_byte_limit:
            raise AssetConfigurationError(
                "global reserved byte limit must cover one owner limit"
            )

    @classmethod
    def from_environment(cls) -> "AssetApiSettings":
        return cls(
            database_url=_required("C19_ASSET_DATABASE_URL"),
            service_token=_secret("C19_ASSET_SERVICE_TOKEN"),
            gateway_token=_secret("C19_ASSET_GATEWAY_TOKEN"),
            dataset_id=_required("C19_ASSET_DATASET_ID"),
            upload_ticket_ttl_seconds=_positive_int(
                "C19_ASSET_UPLOAD_TICKET_TTL_SECONDS", 900
            ),
            download_ticket_ttl_seconds=_positive_int(
                "C19_ASSET_DOWNLOAD_TICKET_TTL_SECONDS", 60
            ),
            download_ticket_max_uses=_positive_int(
                "C19_ASSET_DOWNLOAD_TICKET_MAX_USES", 12
            ),
            max_pending_uploads_per_owner=_positive_int(
                "C19_ASSET_MAX_PENDING_PER_OWNER", 20
            ),
            max_upload_tickets_per_asset=_positive_int(
                "C19_ASSET_MAX_UPLOAD_TICKETS_PER_ASSET", 8
            ),
            database_workers=_positive_int("C19_ASSET_DATABASE_WORKERS", 4),
            image_max_bytes=_positive_int(
                "C19_ASSET_IMAGE_MAX_BYTES", DEFAULT_IMAGE_MAX_BYTES,
                ceiling=HARD_MAX_BYTES,
            ),
            file_max_bytes=_positive_int(
                "C19_ASSET_FILE_MAX_BYTES", DEFAULT_FILE_MAX_BYTES,
                ceiling=HARD_MAX_BYTES,
            ),
            thumbnail_max_bytes=_positive_int(
                "C19_ASSET_THUMBNAIL_MAX_BYTES",
                DEFAULT_THUMBNAIL_MAX_BYTES,
                ceiling=HARD_THUMBNAIL_MAX_BYTES,
            ),
            owner_reserved_file_limit=_positive_int(
                "C19_ASSET_OWNER_RESERVED_FILE_LIMIT",
                DEFAULT_OWNER_RESERVED_FILES,
            ),
            owner_reserved_byte_limit=_positive_int(
                "C19_ASSET_OWNER_RESERVED_BYTE_LIMIT",
                DEFAULT_OWNER_RESERVED_BYTES,
            ),
            global_reserved_file_limit=_positive_int(
                "C19_ASSET_GLOBAL_RESERVED_FILE_LIMIT",
                DEFAULT_GLOBAL_RESERVED_FILES,
            ),
            global_reserved_byte_limit=_positive_int(
                "C19_ASSET_GLOBAL_RESERVED_BYTE_LIMIT",
                DEFAULT_GLOBAL_RESERVED_BYTES,
            ),
        )


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    api_url: str
    gateway_token: str
    incoming_root: Path
    active_root: Path
    hard_max_bytes: int = HARD_MAX_BYTES
    request_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        parsed = urlsplit(self.api_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AssetConfigurationError("C19_ASSET_API_URL must be HTTP(S)")
        if len(self.gateway_token) < 32 or "CHANGE-ME" in self.gateway_token.upper():
            raise AssetConfigurationError("C19_ASSET_GATEWAY_TOKEN is invalid")
        if self.hard_max_bytes <= 0 or self.hard_max_bytes > HARD_MAX_BYTES:
            raise AssetConfigurationError("gateway byte limit is invalid")
        if not self.incoming_root.is_absolute() or not self.active_root.is_absolute():
            raise AssetConfigurationError("gateway roots must be absolute")
        if self.incoming_root == self.active_root:
            raise AssetConfigurationError("gateway roots must be distinct")

    @classmethod
    def from_environment(cls) -> "GatewaySettings":
        return cls(
            api_url=_required("C19_ASSET_API_URL").rstrip("/"),
            gateway_token=_secret("C19_ASSET_GATEWAY_TOKEN"),
            incoming_root=_path("C19_ASSET_INCOMING_ROOT"),
            active_root=_path("C19_ASSET_ACTIVE_ROOT"),
            hard_max_bytes=_positive_int(
                "C19_ASSET_HARD_MAX_BYTES", HARD_MAX_BYTES, ceiling=HARD_MAX_BYTES
            ),
            request_timeout_seconds=_positive_int(
                "C19_ASSET_GATEWAY_REQUEST_TIMEOUT_SECONDS", 30
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    database_url: str
    dataset_id: str
    incoming_root: Path
    active_root: Path
    quarantine_root: Path
    clamd_host: str
    clamd_port: int = 3310
    poll_seconds: int = 2
    image_max_pixels: int = 40_000_000
    image_max_dimension: int = 20_000
    image_max_frames: int = 500
    image_max_total_frame_pixels: int = 100_000_000
    thumbnail_max_bytes: int = DEFAULT_THUMBNAIL_MAX_BYTES
    archive_max_members: int = 2_000
    archive_max_unpacked_bytes: int = HARD_MAX_BYTES * 4
    archive_max_ratio: int = 200
    clamd_signature_max_age_hours: int = 48
    unbound_asset_ttl_hours: int = 24
    orphan_grace_hours: int = 24

    def __post_init__(self) -> None:
        if not self.database_url.strip() or "CHANGE-ME" in self.database_url.upper():
            raise AssetConfigurationError("C19_ASSET_DATABASE_URL is invalid")
        if not self.dataset_id.strip() or len(self.dataset_id) > 128:
            raise AssetConfigurationError("C19_ASSET_DATASET_ID is invalid")
        roots = (self.incoming_root, self.active_root, self.quarantine_root)
        if any(not root.is_absolute() for root in roots) or len(set(roots)) != 3:
            raise AssetConfigurationError("worker roots must be absolute and distinct")
        if not self.clamd_host.strip() or self.clamd_port <= 0:
            raise AssetConfigurationError("ClamAV endpoint is invalid")
        limits = (
            self.poll_seconds,
            self.image_max_pixels,
            self.image_max_dimension,
            self.image_max_frames,
            self.image_max_total_frame_pixels,
            self.thumbnail_max_bytes,
            self.archive_max_members,
            self.archive_max_unpacked_bytes,
            self.archive_max_ratio,
            self.clamd_signature_max_age_hours,
            self.unbound_asset_ttl_hours,
            self.orphan_grace_hours,
        )
        if any(value <= 0 for value in limits):
            raise AssetConfigurationError("worker safety limits must be positive")

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        return cls(
            database_url=_required("C19_ASSET_DATABASE_URL"),
            dataset_id=_required("C19_ASSET_DATASET_ID"),
            incoming_root=_path("C19_ASSET_INCOMING_ROOT"),
            active_root=_path("C19_ASSET_ACTIVE_ROOT"),
            quarantine_root=_path("C19_ASSET_QUARANTINE_ROOT"),
            clamd_host=_required("C19_ASSET_CLAMD_HOST"),
            clamd_port=_positive_int("C19_ASSET_CLAMD_PORT", 3310),
            poll_seconds=_positive_int("C19_ASSET_WORKER_POLL_SECONDS", 2),
            image_max_pixels=_positive_int(
                "C19_ASSET_IMAGE_MAX_PIXELS", 40_000_000
            ),
            image_max_dimension=_positive_int(
                "C19_ASSET_IMAGE_MAX_DIMENSION", 20_000
            ),
            image_max_frames=_positive_int("C19_ASSET_IMAGE_MAX_FRAMES", 500),
            image_max_total_frame_pixels=_positive_int(
                "C19_ASSET_IMAGE_MAX_TOTAL_FRAME_PIXELS", 100_000_000
            ),
            thumbnail_max_bytes=_positive_int(
                "C19_ASSET_THUMBNAIL_MAX_BYTES",
                DEFAULT_THUMBNAIL_MAX_BYTES,
                ceiling=HARD_THUMBNAIL_MAX_BYTES,
            ),
            archive_max_members=_positive_int(
                "C19_ASSET_ARCHIVE_MAX_MEMBERS", 2_000
            ),
            archive_max_unpacked_bytes=_positive_int(
                "C19_ASSET_ARCHIVE_MAX_UNPACKED_BYTES", HARD_MAX_BYTES * 4
            ),
            archive_max_ratio=_positive_int("C19_ASSET_ARCHIVE_MAX_RATIO", 200),
            clamd_signature_max_age_hours=_positive_int(
                "C19_ASSET_CLAMD_SIGNATURE_MAX_AGE_HOURS", 48
            ),
            unbound_asset_ttl_hours=_positive_int(
                "C19_ASSET_UNBOUND_TTL_HOURS", 24
            ),
            orphan_grace_hours=_positive_int(
                "C19_ASSET_ORPHAN_GRACE_HOURS", 24
            ),
        )
