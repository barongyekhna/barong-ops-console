"""Local persistent media file helpers."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath

try:  # Pillow is installed in the backend image; tests can run without it.
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]


INLINE_IMAGE_CACHE_CONTROL = "public, max-age=86400"
DERIVED_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def storage_path(root: Path, object_key: str) -> Path:
    cleaned = str(object_key).strip().lstrip("/")
    if not cleaned:
        raise ValueError("object_key is required.")
    root_resolved = root.resolve(strict=False)
    path = (root_resolved / cleaned).resolve(strict=False)
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("object_key escapes media storage root.") from exc
    return path


def write_media_file(root: Path, object_key: str, contents: bytes) -> Path:
    path = storage_path(root, object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def media_file_etag(path: Path) -> str:
    stat = path.stat()
    seed = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:32]


def derived_object_key(object_key: str, kind: str, extension: str = "webp") -> str:
    source = PurePosixPath(str(object_key).strip().lstrip("/"))
    stem = source.name or "image"
    parent = source.parent if str(source.parent) != "." else PurePosixPath("")
    derived = parent / "_derived" / f"{stem}.{kind}.{extension}"
    return str(derived)


def ensure_image_derivative(
    *,
    root: Path,
    object_key: str,
    kind: str,
    max_side: int,
    contents: bytes | None = None,
    force: bool = False,
) -> tuple[Path, str, str]:
    """Create a cached WebP derivative if Pillow is available.

    When Pillow is unavailable, fall back to the original path without writing a
    mislabeled derivative. This keeps local tests dependency-light while the
    deployed backend still serves real thumbnails.

    ``force=True`` rebuilds even when a derivative already exists — required
    whenever the ORIGINAL bytes were replaced under the same object_key. The
    cache keys off the path only, so without this an updated original keeps
    serving its stale derivative (2026-08-04: the reference-image repair fixed
    six originals but every preview stayed identical, and every vision call —
    pose tagging, geometry gate, physics gate — kept seeing one same old photo).
    """

    original_path = storage_path(root, object_key)
    if Image is None or ImageOps is None:
        return original_path, object_key, "application/octet-stream"

    target_key = derived_object_key(object_key, kind)
    target_path = storage_path(root, target_key)
    if target_path.is_file() and not force:
        return target_path, target_key, "image/webp"

    if contents is None:
        contents = original_path.read_bytes()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(contents)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        image.save(target_path, format="WEBP", quality=82, method=4)
    return target_path, target_key, "image/webp"

