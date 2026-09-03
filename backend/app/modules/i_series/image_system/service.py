"""Service layer for the independent I-series image system."""

from __future__ import annotations

import base64
import hashlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
import re
import struct
from threading import RLock
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

try:  # Pillow keeps local fallback image generation fast in tests and dev.
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional local fallback dependency
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.api_key_orchestration import (
    ApiKeyInjectionContext,
    ApiKeyIsolationError,
    ApiKeyOrchestrationError,
    resolve_module_api_key_candidates_for_injection,
)
from ....services.ai_provider_router import AIExecutionRouter
from ....services.api_key_usage_tracker import record_api_key_usage
from ....services.module_execution_gate import (
    ModuleExecutionGateError,
    require_module_execution_ready,
)
from ....services.permission_service import resolve_current_user_permission_info
from ....services.media_store import (
    ensure_image_derivative,
    storage_path,
    write_media_file,
)
from ....core.roles import is_owner_role, is_super_admin_role
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
    DEFAULT_IMAGE_MIME_TYPE,
    IMAGE_EDIT_ENDPOINT,
    IMAGE_GENERATION_ENDPOINT,
    IMAGE_MODEL_NAME,
    MAX_EDIT_REFERENCE_IMAGES,
    MEDIA_BUCKET_EDITED,
    MEDIA_BUCKET_GENERATED,
    MODULE_KEY,
    ORIGIN_I_DIRECT,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
    PERMISSION_READ,
    SOURCE_EDIT,
    SOURCE_GENERATE,
    STATUS_GENERATED,
    STATUS_REMOVED,
    STATUS_STORED,
    TARGET_ORGANIZATION_NAME,
)
from .models import IImageAsset, IImageGenerationEvent
from .prompt_skills import IMAGE_PROMPT_SKILL_VERSION, image_prompt_skill_context
from .schemas import (
    ImageCandidate,
    ImageGenerationRequest,
    ImageSaveItem,
    MediaAssetRead,
    MediaLibrarySaveRequest,
    PromptTransformRequest,
)


@dataclass(frozen=True)
class IScopeContext:
    workspace_key: str
    business_context: str
    scope_mode: str
    organization_name: str


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

IMAGE_PROVIDER_KEY_ALIASES = (
    "4sapi",
    "gpt_image",
    "gpt-image",
    "ai_provider",
    "openai",
    "chatgpt",
    "default",
)
IMAGE_PROVIDER_TIMEOUT_SECONDS = 180.0
PROMPT_CACHE_MAX_ITEMS = 512
IMAGE_GENERATION_CACHE_MAX_ITEMS = 128

_CACHE_LOCK = RLock()
_PROMPT_TRANSFORM_CACHE: OrderedDict[str, tuple[str, str]] = OrderedDict()
_IMAGE_GENERATION_CACHE: OrderedDict[str, tuple[dict[str, Any], ...]] = (
    OrderedDict()
)
_ORGANIZATION_NAME_CACHE: OrderedDict[str, str] = OrderedDict()


def now_utc() -> datetime:
    return datetime.now(UTC)


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prompt_cache_key(payload: PromptTransformRequest) -> str:
    return sha256_text(
        stable_json(
            {
                "prompt": payload.prompt.strip(),
                "prompt_skill_version": IMAGE_PROMPT_SKILL_VERSION,
                "source_type": payload.source_type,
                "style_config": payload.style_config or {},
            }
        )
    )


def image_generation_cache_key(
    *,
    image_prompt_enhanced: str,
    style_config: dict[str, Any] | None,
    aspect_ratio: str,
) -> str:
    return sha256_text(
        stable_json(
            {
                "aspect_ratio": aspect_ratio,
                "image_prompt_enhanced_sha256": sha256_text(
                    image_prompt_enhanced.strip()
                ),
                "model": IMAGE_MODEL_NAME,
                "source_type": SOURCE_GENERATE,
                "style_config": style_config or {},
            }
        )
    )


def _prompt_cache_get(cache_key: str) -> tuple[str, str] | None:
    with _CACHE_LOCK:
        cached = _PROMPT_TRANSFORM_CACHE.get(cache_key)
        if cached is None:
            return None
        _PROMPT_TRANSFORM_CACHE.move_to_end(cache_key)
        return cached


def _prompt_cache_put(cache_key: str, value: tuple[str, str]) -> None:
    with _CACHE_LOCK:
        _PROMPT_TRANSFORM_CACHE[cache_key] = value
        _PROMPT_TRANSFORM_CACHE.move_to_end(cache_key)
        while len(_PROMPT_TRANSFORM_CACHE) > PROMPT_CACHE_MAX_ITEMS:
            _PROMPT_TRANSFORM_CACHE.popitem(last=False)


def _image_cache_get(
    cache_key: str,
    generation_count: int,
) -> list[ImageCandidate] | None:
    with _CACHE_LOCK:
        cached = _IMAGE_GENERATION_CACHE.get(cache_key)
        if cached is None or len(cached) < generation_count:
            return None
        _IMAGE_GENERATION_CACHE.move_to_end(cache_key)
        payloads = cached[:generation_count]

    candidates: list[ImageCandidate] = []
    for payload in payloads:
        cloned = dict(payload)
        cloned["candidate_id"] = f"cand_{uuid4().hex}"
        candidates.append(ImageCandidate(**cloned))
    return candidates


def _image_cache_put(cache_key: str, candidates: list[ImageCandidate]) -> None:
    payloads = tuple(candidate.model_dump(mode="python") for candidate in candidates)
    with _CACHE_LOCK:
        _IMAGE_GENERATION_CACHE[cache_key] = payloads
        _IMAGE_GENERATION_CACHE.move_to_end(cache_key)
        while len(_IMAGE_GENERATION_CACHE) > IMAGE_GENERATION_CACHE_MAX_ITEMS:
            _IMAGE_GENERATION_CACHE.popitem(last=False)


def _organization_name_cache_get(org_id: str) -> str | None:
    with _CACHE_LOCK:
        cached = _ORGANIZATION_NAME_CACHE.get(org_id)
        if cached is None:
            return None
        _ORGANIZATION_NAME_CACHE.move_to_end(org_id)
        return cached


def _organization_name_cache_put(org_id: str, org_name: str) -> None:
    with _CACHE_LOCK:
        _ORGANIZATION_NAME_CACHE[org_id] = org_name
        _ORGANIZATION_NAME_CACHE.move_to_end(org_id)
        while len(_ORGANIZATION_NAME_CACHE) > PROMPT_CACHE_MAX_ITEMS:
            _ORGANIZATION_NAME_CACHE.popitem(last=False)


def user_uuid(user: User | None) -> UUID | None:
    if user is None or user.id is None:
        return None
    return uuid5(NAMESPACE_URL, f"barong-user:{user.id}")


def require_i_permission(
    db: Session,
    user: User,
    request: Request,
    permission_key: str,
) -> None:
    if is_owner_role(user.role) or is_super_admin_role(user.role):
        return
    permissions = resolve_current_user_permission_info(db, user, request=request)
    allowed_keys = {permission_key}
    if permission_key in {PERMISSION_EXECUTE, PERMISSION_MANAGE}:
        allowed_keys.add(PERMISSION_READ)
    if (
        permissions.is_owner_full_access
        or allowed_keys.intersection(permissions.permission_keys)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing permission: {permission_key}",
    )


def scope_context_from_request(
    db: Session,
    request: Request,
    user: User,
) -> IScopeContext:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        org_context = getattr(request.state, "org_context", None)
        org_id = getattr(org_context, "org_id", None)
    if org_id is None:
        org_id = user.organization_id

    workspace_key = str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY
    if workspace_key and workspace_key != DEFAULT_WORKSPACE_KEY:
        organization_name = _organization_name_cache_get(workspace_key)
        if organization_name is None:
            organization = db.get(OrganizationRecord, workspace_key)
            organization_name = organization.org_name if organization is not None else ""
            _organization_name_cache_put(workspace_key, organization_name)
        if organization_name and organization_name != TARGET_ORGANIZATION_NAME:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "I image system is only available for "
                    f"{TARGET_ORGANIZATION_NAME}."
                ),
            )

    return IScopeContext(
        workspace_key=workspace_key,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
        organization_name=TARGET_ORGANIZATION_NAME,
    )


def decode_image_base64(value: str) -> bytes:
    raw = value.strip()
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image payload is not valid base64.",
        ) from exc


def encode_image_base64(contents: bytes) -> str:
    return base64.b64encode(contents).decode("ascii")


def detect_image_mime(contents: bytes) -> str | None:
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(contents) >= 12
        and contents[0:4] == b"RIFF"
        and contents[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def validate_image_bytes(contents: bytes, declared_mime: str | None = None) -> str:
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image file is empty.",
        )
    detected_mime = detect_image_mime(contents)
    if detected_mime is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image format.",
        )
    normalized_declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    if normalized_declared and normalized_declared not in {
        detected_mime,
        "application/octet-stream",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image MIME type does not match the file contents.",
        )
    return detected_mime


def image_dimensions_from_png(contents: bytes) -> tuple[int | None, int | None]:
    if len(contents) >= 24 and contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", contents[16:24])
    return None, None


def local_image_fallback_enabled() -> bool:
    return os.getenv("I_IMAGE_ALLOW_LOCAL_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def provider_url(base_url: str, endpoint: str) -> str:
    base = base_url.strip().rstrip("/")
    suffix = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if base.endswith("/v1") and suffix.startswith("/v1/"):
        suffix = suffix[3:]
    return f"{base}{suffix}"


def provider_size_for_aspect_ratio(value: str) -> tuple[str, int, int]:
    ratio_width, ratio_height = parse_aspect_ratio(value)
    if ratio_width > ratio_height:
        return "1536x1024", 1536, 1024
    if ratio_height > ratio_width:
        return "1024x1536", 1024, 1536
    return "1024x1024", 1024, 1024


def sha256_hex(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def safe_filename(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "image").strip())
    cleaned = cleaned.strip(".-_")
    return cleaned[:180] or "image"


def safe_media_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    reserved = {
        "cache_path",
        "db_content_base64",
        "preview_path",
        "storage_path",
        "storage_provider",
        "storage_relative_path",
        "thumbnail_path",
    }
    return {key: value for key, value in metadata.items() if key not in reserved}


def image_storage_root() -> Path:
    return Path(os.getenv("I_IMAGE_MEDIA_STORAGE_DIR", "/var/lib/barong/i-media"))


def write_media_cache(object_key: str, contents: bytes) -> str:
    root = image_storage_root()
    try:
        path = write_media_file(root, object_key, contents)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=507,
            detail="I media storage is not writable.",
        ) from exc
    return str(path)


def media_object_path(object_key: str) -> Path:
    return storage_path(image_storage_root(), object_key)


def asset_file_path(row: IImageAsset) -> Path | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    root = image_storage_root().resolve(strict=False)
    candidates: list[Path] = []
    storage_path_value = metadata.get("storage_path") or metadata.get("cache_path")
    if storage_path_value:
        candidates.append(Path(str(storage_path_value)))
    if row.object_key:
        candidates.append(root / row.object_key)

    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def ensure_asset_file(row: IImageAsset) -> Path:
    path = asset_file_path(row)
    if path is not None:
        return path
    if row.content_bytes:
        path = write_media_file(image_storage_root(), row.object_key, row.content_bytes)
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        row.storage_provider = "local_filesystem"
        row.metadata_json = {
            **metadata,
            "storage_provider": "local_filesystem",
            "storage_relative_path": row.object_key,
            "storage_path": str(path),
        }
        return path
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="I image file was not found.",
    )


def ensure_asset_derivative(row: IImageAsset, *, kind: str, max_side: int) -> Path:
    ensure_asset_file(row)
    path, object_key, _media_type = ensure_image_derivative(
        root=image_storage_root(),
        object_key=row.object_key,
        kind=kind,
        max_side=max_side,
        contents=row.content_bytes,
    )
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    key_name = f"{kind}_object_key"
    if metadata.get(key_name) != object_key:
        row.metadata_json = {**metadata, key_name: object_key}
    return path


def parse_aspect_ratio(value: str) -> tuple[int, int]:
    cleaned = (value or "1:1").strip().lower().replace("x", ":")
    match = re.fullmatch(r"(\d{1,3})\s*:\s*(\d{1,3})", cleaned)
    if not match:
        return 1, 1
    width = max(1, int(match.group(1)))
    height = max(1, int(match.group(2)))
    return width, height


def dimensions_for_aspect_ratio(value: str) -> tuple[int, int]:
    ratio_width, ratio_height = parse_aspect_ratio(value)
    max_side = 1024
    if ratio_width >= ratio_height:
        width = max_side
        height = max(256, int(round(max_side * ratio_height / ratio_width)))
    else:
        height = max_side
        width = max(256, int(round(max_side * ratio_width / ratio_height)))
    return width, height


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def deterministic_png(width: int, height: int, seed: str) -> bytes:
    if Image is not None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        base_size = 64
        pixels: list[tuple[int, int, int]] = []
        for y in range(base_size):
            y_ratio = y / max(1, base_size - 1)
            for x in range(base_size):
                x_ratio = x / max(1, base_size - 1)
                mix = (x_ratio * 0.62) + (y_ratio * 0.38)
                stripe = 20 if ((x // 8) + (y // 8)) % 2 == 0 else -8
                red = max(
                    0,
                    min(255, int(digest[0] * (1 - mix) + digest[3] * mix) + stripe),
                )
                green = max(
                    0,
                    min(255, int(digest[1] * (1 - mix) + digest[4] * mix) + stripe),
                )
                blue = max(
                    0,
                    min(255, int(digest[2] * (1 - mix) + digest[5] * mix) + stripe),
                )
                pixels.append((red, green, blue))

        image = Image.new("RGB", (base_size, base_size))
        image.putdata(pixels)
        image = image.resize((width, height), Image.Resampling.BICUBIC)
        if ImageDraw is not None:
            draw = ImageDraw.Draw(image)
            inset = max(12, min(width, height) // 18)
            draw.rounded_rectangle(
                (inset, inset, width - inset, height - inset),
                radius=max(8, inset // 2),
                outline=(
                    min(255, digest[6] + 64),
                    min(255, digest[7] + 64),
                    min(255, digest[8] + 64),
                ),
                width=max(3, min(width, height) // 128),
            )
        buffer = BytesIO()
        image.save(buffer, format="PNG", compress_level=1)
        return buffer.getvalue()

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    r1, g1, b1 = digest[0], digest[1], digest[2]
    r2, g2, b2 = digest[3], digest[4], digest[5]
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        y_ratio = y / max(1, height - 1)
        for x in range(width):
            x_ratio = x / max(1, width - 1)
            mix = (x_ratio * 0.55) + (y_ratio * 0.45)
            stripe = 18 if ((x // 64) + (y // 64)) % 2 == 0 else -10
            red = max(0, min(255, int(r1 * (1 - mix) + r2 * mix) + stripe))
            green = max(0, min(255, int(g1 * (1 - mix) + g2 * mix) + stripe))
            blue = max(0, min(255, int(b1 * (1 - mix) + b2 * mix) + stripe))
            rows.extend((red, green, blue))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    text = f"Prompt\0{seed[:512]}".encode("utf-8", errors="ignore")
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"tEXt", text)
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), level=6))
        + png_chunk(b"IEND", b"")
    )


def local_enhanced_prompt(payload: PromptTransformRequest) -> str:
    style = payload.style_config or {}
    style_bits = [
        str(style.get("style") or "").strip(),
        str(style.get("lighting") or "").strip(),
        str(style.get("composition") or "").strip(),
        str(style.get("background") or "").strip(),
    ]
    style_suffix = ", ".join(bit for bit in style_bits if bit)
    mode = "image editing" if payload.source_type == SOURCE_EDIT else "image generation"
    suffix = f", {style_suffix}" if style_suffix else ""
    return (
        f"Professional ecommerce {mode} prompt: {payload.prompt.strip()}. "
        "Create a polished English visual prompt with a clear subject, exact "
        "product and variant details, clean composition, controlled lighting, "
        "realistic materials, sharp focus, high-resolution catalog quality, "
        "and no text artifacts, watermark, distorted geometry, or unwanted "
        f"extra objects{suffix}."
    )


def local_chinese_failure_message(message: str) -> str:
    lowered = message.lower()
    if "no available channel" in lowered:
        return (
            "图片生成失败：当前图片模型 gpt-image-2 的 4sapi/Azure 通道暂不可用，"
            "请稍后重试或检查备用 key 通道。"
        )
    if "safety_violations" in lowered or "safety system" in lowered:
        return (
            "图片生成失败：图片模型安全系统拒绝了这次请求。请调整提示词，"
            "避免敏感、暴力、性暗示或容易被误判的身体接触描述。"
        )
    if "timed out" in lowered or "timeout" in lowered:
        return "图片生成失败：图片模型请求超时，请稍后重试。"
    if "not contain usable image data" in lowered:
        return "图片生成失败：图片模型返回结果中没有可用的图片数据。"
    if message.strip():
        return f"图片生成失败：{message.strip()}"
    return "图片生成失败：后端没有收到可用的失败原因。"


def target_organization(db: Session) -> OrganizationRecord:
    organization = db.scalar(
        select(OrganizationRecord).where(
            OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME,
            OrganizationRecord.status != "deleted",
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="I image system target organization is not configured.",
        )
    return organization


def resolve_i_image_provider_key(
    db: Session,
    *,
    request: Request,
    user: User,
):
    return resolve_i_image_provider_keys(db, request=request, user=user)[0]


def resolve_i_image_provider_keys(
    db: Session,
    *,
    request: Request,
    user: User,
) -> list[ApiKeyInjectionContext]:
    organization = target_organization(db)
    try:
        execution_context = require_module_execution_ready(
            db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            explicit_org_id=organization.org_id,
            key_requirements={},
        )
    except ModuleExecutionGateError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.code,
        ) from exc

    try:
        return resolve_module_api_key_candidates_for_injection(
            db,
            org_id=organization.org_id,
            module_id=execution_context.control_module_id,
            key_aliases=IMAGE_PROVIDER_KEY_ALIASES,
        )
    except (ApiKeyIsolationError, ApiKeyOrchestrationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "I image provider API key is not bound to i.image_system. "
                "Bind the 4sapi image key with alias 4sapi, gpt_image, "
                "ai_provider, openai, chatgpt, or default."
            ),
        ) from exc


def _provider_response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    images = response.get("images")
    if isinstance(images, list):
        return [item for item in images if isinstance(item, dict)]
    output = response.get("output")
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    return []


def _image_base64_from_item(item: dict[str, Any]) -> str | None:
    for key in ("b64_json", "base64", "image_base64", "data"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = item.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def _image_url_from_item(item: dict[str, Any]) -> str | None:
    for key in ("url", "image_url"):
        value = item.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    return None


class IImagePromptEngine:
    def __init__(self, db: Session) -> None:
        self.db = db

    def transform(
        self,
        *,
        payload: PromptTransformRequest,
        request: Request,
        user: User,
    ) -> tuple[str, str]:
        cache_key = prompt_cache_key(payload)
        cached = _prompt_cache_get(cache_key)
        if cached is not None:
            return cached
        if local_image_fallback_enabled():
            fallback = (local_enhanced_prompt(payload), "local_fallback")
            _prompt_cache_put(cache_key, fallback)
            return fallback

        skill = image_prompt_skill_context()
        provider_payload = {
            "module_id": MODULE_KEY,
            "task": "i_image_prompt_transform",
            "prompt": payload.prompt,
            "source_type": payload.source_type,
            "style_config": payload.style_config,
            "required_output": ["image_prompt_enhanced"],
            "prompt_skill": skill,
            "messages": [
                {"role": "system", "content": skill["instruction"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "prompt": payload.prompt,
                            "source_type": payload.source_type,
                            "style_config": payload.style_config,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
        }
        try:
            output = AIExecutionRouter(self.db).execute(
                provider="deepseek",
                task_type="generate",
                payload=provider_payload,
                org=TARGET_ORGANIZATION_NAME,
                module_id=MODULE_KEY,
                user=user,
                request=request,
                fallback_provider=None,
            )
        except Exception as exc:
            if not local_image_fallback_enabled():
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "DeepSeek V4 Pro 提示词优化失败或未正确配置。"
                    ),
                ) from exc
            fallback = (local_enhanced_prompt(payload), "local_fallback")
            _prompt_cache_put(cache_key, fallback)
            return fallback

        enhanced = output.get("image_prompt_enhanced")
        if not isinstance(enhanced, str) or not enhanced.strip():
            enhanced = output.get("enhanced_prompt") or output.get("prompt")
        if not isinstance(enhanced, str) or not enhanced.strip():
            enhanced = output.get("content")
        if not isinstance(enhanced, str) or not enhanced.strip():
            fallback = (local_enhanced_prompt(payload), "local_fallback")
            _prompt_cache_put(cache_key, fallback)
            return fallback
        result = (enhanced.strip(), "deepseek-v4-pro")
        _prompt_cache_put(cache_key, result)
        return result

    def translate_failure_to_chinese(
        self,
        *,
        message: str,
        details: dict[str, Any],
        request: Request,
        user: User,
    ) -> str:
        fallback = local_chinese_failure_message(message)
        if local_image_fallback_enabled():
            return fallback

        provider_payload = {
            "module_id": MODULE_KEY,
            "task": "i_image_failure_reason_translate",
            "failure_message": message,
            "failure_details": details,
            "required_output": ["zh_message"],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate the image generation failure reason into concise "
                        "Chinese for an operations console user. Preserve key model, "
                        "provider, channel, safety, timeout, and fallback-attempt facts. "
                        "Return JSON only with key zh_message."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "failure_message": message,
                            "failure_details": details,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
        }
        try:
            output = AIExecutionRouter(self.db).execute(
                provider="deepseek",
                task_type="generate",
                payload=provider_payload,
                org=TARGET_ORGANIZATION_NAME,
                module_id=MODULE_KEY,
                user=user,
                request=request,
                fallback_provider=None,
            )
        except Exception:
            return fallback

        translated = output.get("zh_message")
        if not isinstance(translated, str) or not translated.strip():
            translated = output.get("message") or output.get("content")
        if isinstance(translated, str) and translated.strip():
            return translated.strip()
        return fallback


class IImageProviderError(RuntimeError):
    pass


class IImageModelEngine:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _release_db_transaction(self) -> None:
        if self.db is None or not self.db.in_transaction():
            return
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _provider_keys(
        self,
        *,
        request: Request,
        user: User,
    ) -> list[ApiKeyInjectionContext]:
        return resolve_i_image_provider_keys(
            self.db,
            request=request,
            user=user,
        )

    def _provider_error_exception(
        self,
        *,
        endpoint: str,
        exc: Exception,
        response: httpx.Response | None = None,
        key: ApiKeyInjectionContext | None = None,
    ) -> HTTPException:
        provider_message = None
        details: dict[str, Any] = {
            "endpoint": endpoint,
            "model": IMAGE_MODEL_NAME,
            "provider": "4sapi",
            "error_class": exc.__class__.__name__,
        }
        if key is not None:
            details["provider_key_alias"] = key.key_alias
            details["provider_key_name"] = key.name
        if response is not None:
            details["provider_status"] = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    message = error_payload.get("message")
                    if isinstance(message, str) and message.strip():
                        provider_message = message.strip()
                        details["provider_error"] = provider_message[:500]
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "I_IMAGE_PROVIDER_REQUEST_FAILED",
                "message": (
                    f"图片模型请求失败：{provider_message}"
                    if provider_message
                    else "图片模型请求失败。"
                ),
                "details": details,
            },
        )

    def _raise_provider_error(
        self,
        *,
        endpoint: str,
        exc: Exception,
        response: httpx.Response | None = None,
        key: ApiKeyInjectionContext | None = None,
    ) -> None:
        raise self._provider_error_exception(
            endpoint=endpoint,
            exc=exc,
            response=response,
            key=key,
        )

    def _candidates_from_provider_response(
        self,
        *,
        response_payload: dict[str, Any],
        source_type: str,
        image_prompt_enhanced: str,
        requested_width: int,
        requested_height: int,
        endpoint: str,
        generation_count: int,
        reference_image_count: int,
    ) -> list[ImageCandidate]:
        items = _provider_response_items(response_payload)
        candidates: list[ImageCandidate] = []
        with httpx.Client(timeout=IMAGE_PROVIDER_TIMEOUT_SECONDS) as client:
            for item in items:
                encoded = _image_base64_from_item(item)
                contents: bytes | None = None
                if encoded:
                    contents = decode_image_base64(encoded)
                else:
                    image_url = _image_url_from_item(item)
                    if image_url:
                        downloaded = client.get(image_url)
                        downloaded.raise_for_status()
                        contents = downloaded.content
                if contents is None:
                    continue

                mime_type = validate_image_bytes(contents)
                width = requested_width
                height = requested_height
                if mime_type == "image/png":
                    detected_width, detected_height = image_dimensions_from_png(contents)
                    width = detected_width or width
                    height = detected_height or height
                digest = sha256_hex(contents)
                candidates.append(
                    ImageCandidate(
                        candidate_id=f"cand_{uuid4().hex}",
                        source_type=source_type,  # type: ignore[arg-type]
                        image_base64=encode_image_base64(contents),
                        mime_type=mime_type,
                        width=width,
                        height=height,
                        file_size=len(contents),
                        content_sha256=digest,
                        image_prompt_enhanced=image_prompt_enhanced,
                        metadata={
                            "model": IMAGE_MODEL_NAME,
                            "model_status": "provider_generated",
                            "provider": "4sapi",
                            "endpoint": endpoint,
                            "reference_image_count": reference_image_count,
                            "revised_prompt": item.get("revised_prompt"),
                        },
                    )
                )

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "I image provider response did not contain usable image data."
                ),
            )
        return candidates[:generation_count]

    def _local_candidates(
        self,
        *,
        event_id: UUID,
        source_type: str,
        image_prompt_enhanced: str,
        aspect_ratio: str,
        generation_count: int,
        reference_image_count: int = 0,
    ) -> list[ImageCandidate]:
        width, height = dimensions_for_aspect_ratio(aspect_ratio)
        candidates: list[ImageCandidate] = []
        for index in range(generation_count):
            seed = json.dumps(
                {
                    "event_id": str(event_id),
                    "index": index,
                    "prompt": image_prompt_enhanced,
                    "source_type": source_type,
                    "reference_image_count": reference_image_count,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            contents = deterministic_png(width, height, seed)
            digest = sha256_hex(contents)
            candidates.append(
                ImageCandidate(
                    candidate_id=f"cand_{uuid4().hex}",
                    source_type=source_type,  # type: ignore[arg-type]
                    image_base64=encode_image_base64(contents),
                    mime_type=DEFAULT_IMAGE_MIME_TYPE,
                    width=width,
                    height=height,
                    file_size=len(contents),
                    content_sha256=digest,
                    image_prompt_enhanced=image_prompt_enhanced,
                    metadata={
                        "model": IMAGE_MODEL_NAME,
                        "model_status": "local_fallback",
                        "reference_image_count": reference_image_count,
                    },
                )
            )
        return candidates

    @staticmethod
    def _attempt_error_summary(
        *,
        attempt: int,
        key: ApiKeyInjectionContext,
        exc: HTTPException,
    ) -> dict[str, Any]:
        detail = exc.detail
        message = str(detail)
        details: dict[str, Any] = {}
        if isinstance(detail, dict):
            raw_message = detail.get("message")
            if isinstance(raw_message, str):
                message = raw_message
            raw_details = detail.get("details")
            if isinstance(raw_details, dict):
                details = raw_details
        return {
            "attempt": attempt,
            "key_alias": key.key_alias,
            "key_name": key.name,
            "message": message[:500],
            "provider_status": details.get("provider_status"),
            "provider_error": details.get("provider_error"),
        }

    @staticmethod
    def _with_attempt_metadata(
        *,
        exc: HTTPException,
        attempts: list[dict[str, Any]],
    ) -> HTTPException:
        detail = exc.detail
        if isinstance(detail, dict):
            next_detail = dict(detail)
            details = (
                dict(next_detail.get("details"))
                if isinstance(next_detail.get("details"), dict)
                else {}
            )
            details["attempts"] = attempts
            details["fallback_attempted"] = len(attempts) > 1
            next_detail["details"] = details
            message = next_detail.get("message")
            if isinstance(message, str) and len(attempts) > 1:
                next_detail["message"] = f"{message}（已尝试备用 key，仍失败。）"
            return HTTPException(status_code=exc.status_code, detail=next_detail)
        return HTTPException(
            status_code=exc.status_code,
            detail={
                "code": "I_IMAGE_PROVIDER_REQUEST_FAILED",
                "message": f"{detail}",
                "details": {
                    "attempts": attempts,
                    "fallback_attempted": len(attempts) > 1,
                },
            },
        )

    def _request_provider_candidates(
        self,
        *,
        key: ApiKeyInjectionContext,
        endpoint: str,
        size: str,
        requested_width: int,
        requested_height: int,
        source_type: str,
        image_prompt_enhanced: str,
        generation_count: int,
        reference_image_count: int,
        reference_images: list[tuple[str, bytes, str | None]] | None,
        mask_image: tuple[str, bytes, str] | None = None,
    ) -> list[ImageCandidate]:
        url = provider_url(key.url, endpoint)
        headers = {
            "Accept": "application/json",
            key.header_name: key.header_value,
        }
        record_api_key_usage(key.key_id)

        try:
            with httpx.Client(timeout=IMAGE_PROVIDER_TIMEOUT_SECONDS) as client:
                if source_type == SOURCE_EDIT:
                    files: list[tuple[str, tuple[str, bytes, str]]] = []
                    for filename, contents, mime_type in reference_images or []:
                        files.append(
                            (
                                os.getenv("I_IMAGE_EDIT_FILE_FIELD", "image[]"),
                                (
                                    safe_filename(filename),
                                    contents,
                                    mime_type or validate_image_bytes(contents),
                                ),
                            )
                        )
                    # 产品保护蒙版:不透明处模型不许改,透明处才重绘。K 用它锁住
                    # 实拍产品像素,只让模型换背景(2026-08-03 换路后的核心)。
                    # 注意它跟参考图用不同的表单字段,重试换字段名时不能连它一起换。
                    mask_file: tuple[str, tuple[str, bytes, str]] | None = None
                    if mask_image is not None:
                        mask_file = (
                            "mask",
                            (
                                safe_filename(mask_image[0]),
                                mask_image[1],
                                mask_image[2] or "image/png",
                            ),
                        )
                    data = {
                        "model": IMAGE_MODEL_NAME,
                        "prompt": image_prompt_enhanced,
                        "n": str(generation_count),
                        "size": size,
                    }
                    post_files = files + ([mask_file] if mask_file else [])
                    response = client.post(
                        url, headers=headers, data=data, files=post_files
                    )
                    if response.status_code in {400, 422} and files:
                        alternate_files = [
                            ("image", file_value) for _, file_value in files
                        ]
                        if mask_file:
                            alternate_files.append(mask_file)
                        response = client.post(
                            url,
                            headers=headers,
                            data=data,
                            files=alternate_files,
                        )
                else:
                    response = client.post(
                        url,
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "model": IMAGE_MODEL_NAME,
                            "prompt": image_prompt_enhanced,
                            "n": generation_count,
                            "size": size,
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise IImageProviderError("provider_response_not_object")
        except httpx.HTTPStatusError as exc:
            self._raise_provider_error(
                endpoint=endpoint,
                exc=exc,
                response=exc.response,
                key=key,
            )
        except (httpx.HTTPError, ValueError) as exc:
            self._raise_provider_error(endpoint=endpoint, exc=exc, key=key)

        try:
            candidates = self._candidates_from_provider_response(
                response_payload=payload,
                source_type=source_type,
                image_prompt_enhanced=image_prompt_enhanced,
                requested_width=requested_width,
                requested_height=requested_height,
                endpoint=endpoint,
                generation_count=generation_count,
                reference_image_count=reference_image_count,
            )
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            self._raise_provider_error(endpoint=endpoint, exc=exc, key=key)
        return candidates

    def generate_candidates(
        self,
        *,
        event_id: UUID,
        source_type: str,
        image_prompt_enhanced: str,
        aspect_ratio: str,
        generation_count: int,
        request: Request,
        user: User,
        style_config: dict[str, Any] | None = None,
        reference_image_count: int = 0,
        reference_images: list[tuple[str, bytes, str | None]] | None = None,
        mask_image: tuple[str, bytes, str] | None = None,
    ) -> list[ImageCandidate]:
        size, requested_width, requested_height = provider_size_for_aspect_ratio(
            aspect_ratio
        )
        cache_key = None
        if source_type == SOURCE_GENERATE and reference_image_count == 0:
            cache_key = image_generation_cache_key(
                image_prompt_enhanced=image_prompt_enhanced,
                style_config=style_config,
                aspect_ratio=aspect_ratio,
            )

        if local_image_fallback_enabled():
            if cache_key is not None:
                cached = _image_cache_get(cache_key, generation_count)
                if cached is not None:
                    return cached
            candidates = self._local_candidates(
                event_id=event_id,
                source_type=source_type,
                image_prompt_enhanced=image_prompt_enhanced,
                aspect_ratio=aspect_ratio,
                generation_count=generation_count,
                reference_image_count=reference_image_count,
            )
            if cache_key is not None:
                _image_cache_put(cache_key, candidates)
            return candidates

        keys = self._provider_keys(request=request, user=user)
        endpoint = (
            IMAGE_EDIT_ENDPOINT if source_type == SOURCE_EDIT else IMAGE_GENERATION_ENDPOINT
        )
        self._release_db_transaction()

        attempts: list[dict[str, Any]] = []
        last_error: HTTPException | None = None
        for index, key in enumerate(keys, start=1):
            try:
                candidates = self._request_provider_candidates(
                    key=key,
                    endpoint=endpoint,
                    size=size,
                    requested_width=requested_width,
                    requested_height=requested_height,
                    source_type=source_type,
                    image_prompt_enhanced=image_prompt_enhanced,
                    generation_count=generation_count,
                    reference_image_count=reference_image_count,
                    reference_images=reference_images,
                    mask_image=mask_image,
                )
                for candidate in candidates:
                    candidate.metadata.update(
                        {
                            "provider_attempt": index,
                            "provider_fallback_used": index > 1,
                            "provider_key_alias": key.key_alias,
                        }
                    )
                return candidates
            except HTTPException as exc:
                last_error = exc
                attempts.append(
                    self._attempt_error_summary(
                        attempt=index,
                        key=key,
                        exc=exc,
                    )
                )
                continue

        raise self._with_attempt_metadata(
            exc=last_error
            or HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "I_IMAGE_PROVIDER_REQUEST_FAILED",
                    "message": "图片模型请求失败。",
                    "details": {
                        "endpoint": endpoint,
                        "model": IMAGE_MODEL_NAME,
                        "provider": "4sapi",
                    },
                },
            ),
            attempts=attempts,
        )


class IImageSystemService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.prompt_engine = IImagePromptEngine(db)
        self.image_engine = IImageModelEngine(db)

    @staticmethod
    def _failure_payload_from_exception(exc: Exception) -> tuple[int, str, dict[str, Any], str]:
        status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
        if not isinstance(status_code, int):
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict):
            raw_message = detail.get("message")
            message = raw_message if isinstance(raw_message, str) else str(detail)
            raw_details = detail.get("details")
            details = dict(raw_details) if isinstance(raw_details, dict) else {}
            code = str(detail.get("code") or "I_IMAGE_TASK_FAILED")
            return status_code, message, details, code
        if isinstance(detail, str):
            return status_code, detail, {}, "I_IMAGE_TASK_FAILED"
        return status_code, str(exc), {}, "I_IMAGE_TASK_FAILED"

    def _translated_failure_exception(
        self,
        *,
        exc: Exception,
        request: Request,
        user: User,
    ) -> HTTPException:
        status_code, message, details, code = self._failure_payload_from_exception(exc)
        translated = self.prompt_engine.translate_failure_to_chinese(
            message=message,
            details=details,
            request=request,
            user=user,
        )
        return HTTPException(
            status_code=status_code,
            detail={
                "code": code,
                "message": translated,
                "details": {
                    **details,
                    "original_message": message,
                    "translated_by": "deepseek-v4-pro_or_local_fallback",
                },
            },
        )

    def transform_prompt(
        self,
        *,
        payload: PromptTransformRequest,
        request: Request,
        user: User,
    ) -> tuple[str, str]:
        return self.prompt_engine.transform(
            payload=payload,
            request=request,
            user=user,
        )

    def generate(
        self,
        *,
        payload: ImageGenerationRequest,
        request: Request,
        user: User,
        scope_context: IScopeContext,
    ) -> tuple[IImageGenerationEvent, list[ImageCandidate], str]:
        enhanced, provider = self.transform_prompt(
            payload=PromptTransformRequest(
                prompt=payload.prompt,
                source_type=SOURCE_GENERATE,
                style_config=payload.style_config,
            ),
            request=request,
            user=user,
        )
        event_id = uuid4()
        event = IImageGenerationEvent(
            id=event_id,
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
            organization_name=scope_context.organization_name,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            source_type=SOURCE_GENERATE,
            status="PROCESSING",
            prompt_original=payload.prompt,
            image_prompt_enhanced=enhanced,
            style_config_json=payload.style_config,
            aspect_ratio=payload.aspect_ratio,
            generation_count=payload.generation_count,
            reference_image_count=0,
            created_by_user_id=user_uuid(user),
            updated_by_user_id=user_uuid(user),
            metadata_json={
                "origin_context": payload.origin_context,
                "prompt_skill_version": IMAGE_PROMPT_SKILL_VERSION,
            },
        )
        self.db.add(event)
        self.db.commit()
        try:
            candidates = self.image_engine.generate_candidates(
                event_id=event_id,
                source_type=SOURCE_GENERATE,
                image_prompt_enhanced=enhanced,
                aspect_ratio=payload.aspect_ratio,
                generation_count=payload.generation_count,
                request=request,
                user=user,
                style_config=payload.style_config,
            )
        except Exception as exc:
            translated_exc = self._translated_failure_exception(
                exc=exc,
                request=request,
                user=user,
            )
            self._record_generation_error(event_id, translated_exc)
            raise translated_exc from exc

        stored_event = self._update_generated_event(event_id, len(candidates))
        return stored_event, candidates, provider

    def edit(
        self,
        *,
        prompt: str,
        style_config: dict[str, Any],
        aspect_ratio: str,
        generation_count: int,
        reference_images: list[tuple[str, bytes, str | None]],
        request: Request,
        user: User,
        scope_context: IScopeContext,
        product_id: UUID | None,
        variant_id: UUID | None,
        origin_context: str,
    ) -> tuple[IImageGenerationEvent, list[ImageCandidate], str, bool]:
        if not reference_images:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Image editing requires at least one reference image.",
            )
        if len(reference_images) > MAX_EDIT_REFERENCE_IMAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Image editing allows at most {MAX_EDIT_REFERENCE_IMAGES} reference images.",
            )
        for _, contents, mime_type in reference_images:
            validate_image_bytes(contents, mime_type)
        enhanced, provider = self.transform_prompt(
            payload=PromptTransformRequest(
                prompt=prompt,
                source_type=SOURCE_EDIT,
                style_config=style_config,
            ),
            request=request,
            user=user,
        )
        event_id = uuid4()
        event = IImageGenerationEvent(
            id=event_id,
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
            organization_name=scope_context.organization_name,
            product_id=product_id,
            variant_id=variant_id,
            source_type=SOURCE_EDIT,
            status="PROCESSING",
            prompt_original=prompt,
            image_prompt_enhanced=enhanced,
            style_config_json=style_config,
            aspect_ratio=aspect_ratio,
            generation_count=generation_count,
            reference_image_count=len(reference_images),
            created_by_user_id=user_uuid(user),
            updated_by_user_id=user_uuid(user),
            metadata_json={
                "origin_context": origin_context,
                "prompt_skill_version": IMAGE_PROMPT_SKILL_VERSION,
            },
        )
        self.db.add(event)
        self.db.commit()
        with TemporaryDirectory(prefix="i-image-refs-") as temp_dir:
            temp_path = Path(temp_dir)
            for index, (filename, contents, mime_type) in enumerate(
                reference_images,
                start=1,
            ):
                (temp_path / f"reference-{index}-{safe_filename(filename)}").write_bytes(
                    contents
                )
            try:
                candidates = self.image_engine.generate_candidates(
                    event_id=event_id,
                    source_type=SOURCE_EDIT,
                    image_prompt_enhanced=enhanced,
                    aspect_ratio=aspect_ratio,
                    generation_count=generation_count,
                    request=request,
                    user=user,
                    style_config=style_config,
                    reference_image_count=len(reference_images),
                    reference_images=reference_images,
                )
            except Exception as exc:
                translated_exc = self._translated_failure_exception(
                    exc=exc,
                    request=request,
                    user=user,
                )
                self._record_generation_error(event_id, translated_exc)
                raise translated_exc from exc
        stored_event = self._update_generated_event(event_id, len(candidates))
        return stored_event, candidates, provider, False

    def _update_generated_event(
        self,
        event_id: UUID,
        candidate_count: int,
    ) -> IImageGenerationEvent:
        event = self.db.get(IImageGenerationEvent, event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="I image generation event was not found after provider execution.",
            )
        event.status = STATUS_GENERATED
        event.candidate_count = candidate_count
        event.error_message = None
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def _record_generation_error(self, event_id: UUID, exc: Exception) -> None:
        self.db.rollback()
        event = self.db.get(IImageGenerationEvent, event_id)
        if event is None:
            return
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict):
            raw_message = detail.get("message")
            message = raw_message if isinstance(raw_message, str) else str(detail)
        else:
            message = detail if isinstance(detail, str) else str(exc)
        event.error_message = message[:2000]
        self.db.add(event)
        self.db.commit()

    def save_to_media_library(
        self,
        *,
        payload: MediaLibrarySaveRequest,
        user: User,
        scope_context: IScopeContext,
    ) -> list[IImageAsset]:
        media_bucket = (
            MEDIA_BUCKET_EDITED
            if payload.source_type == SOURCE_EDIT
            else MEDIA_BUCKET_GENERATED
        )
        rows: list[IImageAsset] = []
        prepared_items: list[dict[str, Any]] = []
        max_workers = max(1, min(8, len(payload.images) * 2))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, item in enumerate(payload.images, start=1):
                contents = decode_image_base64(item.image_base64)
                mime_type = validate_image_bytes(contents, item.mime_type)
                content_sha = sha256_hex(contents)
                if item.content_sha256 and item.content_sha256 != content_sha:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Image content hash does not match content_sha256.",
                    )
                width = item.width
                height = item.height
                if mime_type == "image/png":
                    detected_width, detected_height = image_dimensions_from_png(
                        contents
                    )
                    width = detected_width or width
                    height = detected_height or height
                image_id = f"i-img-{uuid4().hex}"
                filename = (
                    f"{image_id}.png" if mime_type == "image/png" else f"{image_id}.img"
                )
                object_key = (
                    f"I_MEDIA_LIBRARY/{media_bucket}/"
                    f"{scope_context.workspace_key}/{image_id}/{filename}"
                )
                cached_path = write_media_cache(object_key, contents)
                thumbnail_future = executor.submit(
                    ensure_image_derivative,
                    root=image_storage_root(),
                    object_key=object_key,
                    kind="thumbnail",
                    max_side=320,
                    contents=contents,
                )
                preview_future = executor.submit(
                    ensure_image_derivative,
                    root=image_storage_root(),
                    object_key=object_key,
                    kind="preview",
                    max_side=1280,
                    contents=contents,
                )
                prepared_items.append(
                    {
                        "cached_path": cached_path,
                        "content_sha": content_sha,
                        "file_size": len(contents),
                        "filename": filename,
                        "height": height,
                        "image_id": image_id,
                        "index": index,
                        "item": item,
                        "mime_type": mime_type,
                        "object_key": object_key,
                        "preview_future": preview_future,
                        "thumbnail_future": thumbnail_future,
                        "width": width,
                    }
                )

            for prepared in prepared_items:
                thumbnail_path, thumbnail_object_key, _thumbnail_media_type = prepared[
                    "thumbnail_future"
                ].result()
                preview_path, preview_object_key, _preview_media_type = prepared[
                    "preview_future"
                ].result()
                item = prepared["item"]
                cached_path = prepared["cached_path"]
                row = IImageAsset(
                    id=uuid4(),
                    image_id=prepared["image_id"],
                    workspace_key=scope_context.workspace_key,
                    business_context=scope_context.business_context,
                    scope_mode=scope_context.scope_mode,
                    organization_name=scope_context.organization_name,
                    product_id=payload.product_id,
                    variant_id=payload.variant_id,
                    source_type=payload.source_type,
                    origin_context=ORIGIN_I_DIRECT,
                    status=STATUS_STORED,
                    media_bucket=media_bucket,
                    prompt_original=payload.prompt_original,
                    image_prompt_enhanced=payload.image_prompt_enhanced,
                    style_config_json=payload.style_config,
                    aspect_ratio=payload.aspect_ratio,
                    filename=prepared["filename"],
                    object_key=prepared["object_key"],
                    storage_provider="local_filesystem",
                    mime_type=prepared["mime_type"],
                    width=prepared["width"],
                    height=prepared["height"],
                    file_size=prepared["file_size"],
                    content_sha256=prepared["content_sha"],
                    content_bytes=None,
                    metadata_json={
                        **safe_media_metadata(item.metadata),
                        "candidate_id": item.candidate_id,
                        "cache_path": cached_path,
                        "image_index": prepared["index"],
                        "reference_images_stored": False,
                        "storage_path": cached_path,
                        "storage_provider": "local_filesystem",
                        "storage_relative_path": prepared["object_key"],
                        "thumbnail_object_key": thumbnail_object_key,
                        "thumbnail_path": str(thumbnail_path),
                        "temporary_uploads_stored": False,
                        "preview_object_key": preview_object_key,
                        "preview_path": str(preview_path),
                    },
                    created_by_user_id=user_uuid(user),
                    updated_by_user_id=user_uuid(user),
                )
                rows.append(row)
        self.db.add_all(rows)
        self.db.commit()
        return rows

    def list_media_library(
        self,
        *,
        scope_context: IScopeContext,
        limit: int,
        offset: int,
        product_id: UUID | None = None,
        variant_id: UUID | None = None,
        source_type: str | None = None,
    ) -> tuple[list[IImageAsset], int]:
        query = select(IImageAsset).where(
            IImageAsset.workspace_key == scope_context.workspace_key,
            IImageAsset.business_context == scope_context.business_context,
            IImageAsset.organization_name == TARGET_ORGANIZATION_NAME,
            IImageAsset.status != STATUS_REMOVED,
        )
        count_query = select(func.count()).select_from(IImageAsset).where(
            IImageAsset.workspace_key == scope_context.workspace_key,
            IImageAsset.business_context == scope_context.business_context,
            IImageAsset.organization_name == TARGET_ORGANIZATION_NAME,
            IImageAsset.status != STATUS_REMOVED,
        )
        if product_id is not None:
            query = query.where(IImageAsset.product_id == product_id)
            count_query = count_query.where(IImageAsset.product_id == product_id)
        if variant_id is not None:
            query = query.where(IImageAsset.variant_id == variant_id)
            count_query = count_query.where(IImageAsset.variant_id == variant_id)
        if source_type is not None:
            query = query.where(IImageAsset.source_type == source_type)
            count_query = count_query.where(IImageAsset.source_type == source_type)
        rows = list(
            self.db.scalars(
                query.options(defer(IImageAsset.content_bytes))
                .order_by(IImageAsset.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        return rows, int(self.db.scalar(count_query) or 0)

    def require_asset(
        self,
        *,
        asset_id: UUID,
        scope_context: IScopeContext,
        include_content: bool = False,
    ) -> IImageAsset:
        query = select(IImageAsset).where(IImageAsset.id == asset_id)
        if not include_content:
            query = query.options(defer(IImageAsset.content_bytes))
        row = self.db.scalar(query)
        if (
            row is None
            or row.status == STATUS_REMOVED
            or row.workspace_key != scope_context.workspace_key
            or row.business_context != scope_context.business_context
            or row.organization_name != TARGET_ORGANIZATION_NAME
        ):
            raise HTTPException(status_code=404, detail="I image asset was not found.")
        return row

    def delete_asset(
        self,
        *,
        asset_id: UUID,
        scope_context: IScopeContext,
        user: User,
    ) -> IImageAsset:
        row = self.require_asset(
            asset_id=asset_id,
            scope_context=scope_context,
            include_content=False,
        )
        row.status = STATUS_REMOVED
        row.removed_at = now_utc()
        row.removed_by_user_id = user_uuid(user)
        row.updated_by_user_id = user_uuid(user)
        row.metadata_json = {
            **(row.metadata_json or {}),
            "removed_manually": True,
            "removed_at": row.removed_at.isoformat(),
        }
        self.db.add(row)
        self.db.commit()
        return row


def asset_read(row: IImageAsset) -> MediaAssetRead:
    return MediaAssetRead(
        id=row.id,
        image_id=row.image_id,
        product_id=row.product_id,
        variant_id=row.variant_id,
        source_type=row.source_type,
        origin_context=row.origin_context,
        status=row.status,
        media_bucket=row.media_bucket,
        prompt_original=row.prompt_original,
        image_prompt_enhanced=row.image_prompt_enhanced,
        aspect_ratio=row.aspect_ratio,
        filename=row.filename,
        object_key=row.object_key,
        file_url=f"/i/media-library/{row.id}/file",
        thumbnail_url=f"/i/media-library/{row.id}/thumbnail",
        preview_url=f"/i/media-library/{row.id}/preview",
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        file_size=row.file_size,
        content_sha256=row.content_sha256,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def save_item_from_candidate(candidate: ImageCandidate) -> ImageSaveItem:
    return ImageSaveItem(
        image_base64=candidate.image_base64,
        mime_type=candidate.mime_type,
        width=candidate.width,
        height=candidate.height,
        content_sha256=candidate.content_sha256,
        candidate_id=candidate.candidate_id,
        metadata=candidate.metadata,
    )
