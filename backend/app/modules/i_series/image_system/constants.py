"""Constants for the independent I-series image system."""

from __future__ import annotations

from ...k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
    TARGET_ORGANIZATION_NAME,
)

MODULE_KEY = "i.image_system"

PERMISSION_READ = "i.image_system.read"
PERMISSION_EXECUTE = "i.image_system.execute"
PERMISSION_MANAGE = "i.image_system.manage"

SOURCE_GENERATE = "generate"
SOURCE_EDIT = "edit"
SOURCE_TYPES = frozenset({SOURCE_GENERATE, SOURCE_EDIT})

STATUS_TEMP = "TEMP"
STATUS_PROCESSING = "PROCESSING"
STATUS_GENERATED = "GENERATED"
STATUS_STORED = "STORED"
STATUS_REMOVED = "REMOVED"

MEDIA_BUCKET_GENERATED = "generated_images"
MEDIA_BUCKET_EDITED = "edited_images"

ORIGIN_I_DIRECT = "i_direct"
ORIGIN_K_HANDOFF = "k_handoff"

MAX_EDIT_REFERENCE_IMAGES = 10
MAX_GENERATION_COUNT = 8
DEFAULT_IMAGE_MIME_TYPE = "image/png"
IMAGE_MODEL_NAME = "gpt-image-2"
IMAGE_GENERATION_ENDPOINT = "/v1/images/generations"
IMAGE_EDIT_ENDPOINT = "/v1/images/edits"
