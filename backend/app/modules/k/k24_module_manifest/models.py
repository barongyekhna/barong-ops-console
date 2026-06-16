"""K24-A module manifest schema.

K24-A defines the K-series module manifest structure only. This layer is limited
to field declarations and schema constraints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModuleType = Literal["K"]
ModuleStatus = Literal["active", "deprecated", "experimental"]


class ModuleManifest(BaseModel):
    """Canonical K-series module manifest structure."""

    # A1: Module unique identifier, for example "K19", "K20", "K23", "K24".
    module_key: str = Field(
        min_length=1,
        description="Unique K-series module identifier.",
    )
    # A2: Module display name.
    module_name: str = Field(
        min_length=1,
        description="Human-readable module name.",
    )
    # A3: Module type, limited to the K system.
    module_type: ModuleType = Field(
        description="K-series module type. Allowed value: K.",
    )
    # A4: Module version in x.y.z semver format.
    version: str = Field(
        pattern=r"^\d+\.\d+\.\d+$",
        description="Module version in semver x.y.z format.",
    )
    # A5: Module lifecycle status.
    status: ModuleStatus = Field(
        description="Module status: active, deprecated, or experimental.",
    )
    # A6: Module description.
    description: str = Field(
        description="Plain text module description.",
    )
    # A7: Declared dependency module keys only.
    dependencies: list[str] = Field(
        description="String-only references to dependency module keys.",
    )
    # System metadata: recorded only as schema fields.
    created_at: str = Field(
        min_length=1,
        description="Creation timestamp string recorded as metadata.",
    )
    updated_at: str = Field(
        min_length=1,
        description="Update timestamp string recorded as metadata.",
    )


__all__ = [
    "ModuleManifest",
    "ModuleStatus",
    "ModuleType",
]
