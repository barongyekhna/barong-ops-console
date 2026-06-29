"""FastAPI router for the independent I-series image system."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....db.session import get_db
from ....models.user import User
from .constants import (
    MAX_EDIT_REFERENCE_IMAGES,
    MAX_GENERATION_COUNT,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
    PERMISSION_READ,
    SOURCE_EDIT,
    SOURCE_TYPES,
)
from .schemas import (
    DeleteMediaResponse,
    ImageEditResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    MediaLibraryListResponse,
    MediaLibrarySaveRequest,
    MediaLibrarySaveResponse,
    PromptTransformRequest,
    PromptTransformResponse,
)
from .service import (
    IImageSystemService,
    asset_read,
    ensure_asset_derivative,
    ensure_asset_file,
    require_i_permission,
    scope_context_from_request,
)
from ....services.media_store import (
    DERIVED_IMAGE_CACHE_CONTROL,
    INLINE_IMAGE_CACHE_CONTROL,
    media_file_etag,
)

router = APIRouter(prefix="/i", tags=["i-image-system"])


def _scope_and_permission(
    db: Session,
    request: Request,
    user: User,
    permission_key: str,
):
    require_i_permission(db, user, request, permission_key)
    return scope_context_from_request(db, request, user)


def _json_form(value: str | None) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="style_config must be valid JSON.",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="style_config must be a JSON object.",
        )
    return parsed


@router.post("/prompts/transform", response_model=PromptTransformResponse)
def transform_prompt(
    payload: PromptTransformRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PromptTransformResponse:
    _scope_and_permission(db, request, user, PERMISSION_EXECUTE)
    enhanced, provider = IImageSystemService(db).transform_prompt(
        payload=payload,
        request=request,
        user=user,
    )
    return PromptTransformResponse(
        image_prompt_enhanced=enhanced,
        provider=provider,
        skill_version="i-image-prompt-skill-2026-06-27",
    )


@router.post("/images/generate", response_model=ImageGenerationResponse)
def generate_images(
    payload: ImageGenerationRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImageGenerationResponse:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_EXECUTE)
    event, candidates, provider = IImageSystemService(db).generate(
        payload=payload,
        request=request,
        user=user,
        scope_context=scope_context,
    )
    return ImageGenerationResponse(
        event_id=event.id,
        image_prompt_enhanced=event.image_prompt_enhanced or "",
        lifecycle=["TEMP", "PROCESSING", "GENERATED"],
        candidates=candidates,
        prompt_provider=provider,
    )


@router.post("/images/edit", response_model=ImageEditResponse)
async def edit_images(
    request: Request,
    prompt: str = Form(..., min_length=1, max_length=8000),
    style_config: str | None = Form(default=None),
    aspect_ratio: str = Form(default="1:1"),
    generation_count: int = Form(default=1, ge=1, le=MAX_GENERATION_COUNT),
    product_id: UUID | None = Form(default=None),
    variant_id: UUID | None = Form(default=None),
    origin_context: str = Form(default="i_direct"),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImageEditResponse:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_EXECUTE)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image editing requires at least one uploaded reference image.",
        )
    if len(files) > MAX_EDIT_REFERENCE_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image editing allows at most {MAX_EDIT_REFERENCE_IMAGES} images.",
        )
    references: list[tuple[str, bytes, str | None]] = []
    for file in files:
        references.append(
            (
                file.filename or "reference-image",
                await file.read(),
                file.content_type,
            )
        )
    event, candidates, provider, persisted = IImageSystemService(db).edit(
        prompt=prompt,
        style_config=_json_form(style_config),
        aspect_ratio=aspect_ratio,
        generation_count=generation_count,
        reference_images=references,
        request=request,
        user=user,
        scope_context=scope_context,
        product_id=product_id,
        variant_id=variant_id,
        origin_context=origin_context,
    )
    return ImageEditResponse(
        event_id=event.id,
        image_prompt_enhanced=event.image_prompt_enhanced or "",
        lifecycle=["TEMP", "PROCESSING", "GENERATED"],
        reference_image_count=len(references),
        candidates=candidates,
        prompt_provider=provider,
        temp_reference_images_persisted=persisted,
    )


@router.post(
    "/media-library",
    response_model=MediaLibrarySaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_media_library(
    payload: MediaLibrarySaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MediaLibrarySaveResponse:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_MANAGE)
    rows = IImageSystemService(db).save_to_media_library(
        payload=payload,
        user=user,
        scope_context=scope_context,
    )
    items = [asset_read(row) for row in rows]
    return MediaLibrarySaveResponse(items=items, count=len(items))


@router.get("/media-library", response_model=MediaLibraryListResponse)
def list_media_library(
    request: Request,
    product_id: UUID | None = Query(default=None),
    variant_id: UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MediaLibraryListResponse:
    if source_type is not None and source_type not in SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_type must be generate or edit.",
        )
    scope_context = _scope_and_permission(db, request, user, PERMISSION_READ)
    rows, count = IImageSystemService(db).list_media_library(
        scope_context=scope_context,
        product_id=product_id,
        variant_id=variant_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return MediaLibraryListResponse(
        items=[asset_read(row) for row in rows],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get("/media-library/{asset_id}/file")
def download_media_library_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_READ)
    row = IImageSystemService(db).require_asset(
        asset_id=asset_id,
        scope_context=scope_context,
        include_content=True,
    )
    path = ensure_asset_file(row)
    db.add(row)
    db.commit()
    response = FileResponse(
        path=path,
        content_disposition_type="inline",
        filename=row.filename,
        media_type=row.mime_type,
    )
    response.headers["Cache-Control"] = INLINE_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(path)
    response.headers["X-I-Image-Id"] = row.image_id
    return response


@router.get("/media-library/{asset_id}/thumbnail")
def thumbnail_media_library_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_READ)
    row = IImageSystemService(db).require_asset(
        asset_id=asset_id,
        scope_context=scope_context,
        include_content=True,
    )
    path = ensure_asset_derivative(row, kind="thumbnail", max_side=320)
    db.add(row)
    db.commit()
    response = FileResponse(
        path=path,
        content_disposition_type="inline",
        filename=row.filename,
        media_type="image/webp" if path.suffix == ".webp" else row.mime_type,
    )
    response.headers["Cache-Control"] = DERIVED_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(path)
    return response


@router.get("/media-library/{asset_id}/preview")
def preview_media_library_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_READ)
    row = IImageSystemService(db).require_asset(
        asset_id=asset_id,
        scope_context=scope_context,
        include_content=True,
    )
    path = ensure_asset_derivative(row, kind="preview", max_side=1280)
    db.add(row)
    db.commit()
    response = FileResponse(
        path=path,
        content_disposition_type="inline",
        filename=row.filename,
        media_type="image/webp" if path.suffix == ".webp" else row.mime_type,
    )
    response.headers["Cache-Control"] = DERIVED_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(path)
    return response


@router.delete("/media-library/{asset_id}", response_model=DeleteMediaResponse)
def delete_media_library_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeleteMediaResponse:
    scope_context = _scope_and_permission(db, request, user, PERMISSION_MANAGE)
    row = IImageSystemService(db).delete_asset(
        asset_id=asset_id,
        scope_context=scope_context,
        user=user,
    )
    return DeleteMediaResponse(asset_id=row.id, image_id=row.image_id)
