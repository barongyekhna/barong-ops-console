"""GEO publish-package contract — the packaged, versioned truth for one topic
cluster's publishable guide articles.

Why its own package (same reasoning as the P upload package): the console builds
it, the n8n workflow ``barongGEOpublish001`` consumes it, and any later auditor
(did the live page keep saying what we published?) reads the same object. If every
surface is projected from THIS one shape, they agree by construction.

The shape is frozen and versioned. Consumers pin ``GEO_PUBLISH_PACKAGE_VERSION``;
the n8n Code nodes hard-assert it before writing anything to WordPress.

No DB / framework imports here on purpose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

GEO_PUBLISH_PACKAGE_VERSION = "geo-publish-package-v1"

Channel = Literal["wordpress"]
SchemaType = Literal["Article", "FAQPage"]


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool = False
    blockers: list[str] = Field(default_factory=list)


class Seo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    meta_description: str | None = None
    # K-authored short permalink slug for the post.
    url_slug: str | None = None


class FaqItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    answer: str


class ClusterRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    topic: str | None = None
    # Google taxonomy breadcrumb, mirrored into WP post categories.
    category_path: list[str] = Field(default_factory=list)
    google_category_id: str | None = None


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    item_type: str
    title: str
    # Deterministic HTML. Product links are already real URLs; intra-cluster links
    # are ``{{GEO_LINK_<item_id>}}`` placeholders the publisher backfills once every
    # post exists (mirrors the P image ``{{KP_IMG_n}}`` handshake).
    html: str
    text: str = ""
    seo: Seo = Field(default_factory=Seo)
    schema_type: SchemaType = "Article"
    faq: list[FaqItem] = Field(default_factory=list)
    # Set when this piece was published before — the publisher updates in place
    # instead of creating a duplicate post.
    wp_existing_post_id: int | None = None
    # The token other articles use to link to THIS one.
    link_token: str


class GuidePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = GEO_PUBLISH_PACKAGE_VERSION
    job_id: str | None = None
    cluster_id: UUID
    channel: Channel = "wordpress"
    generated_at: datetime
    gate: Gate = Field(default_factory=Gate)
    cluster: ClusterRef
    # Leaf WP category term id (the Google taxonomy path, mirrored into the post
    # `category` taxonomy). None when category enrichment failed — publishing
    # continues uncategorised rather than blocking.
    wp_category_id: int | None = None
    articles: list[Article] = Field(default_factory=list)


def publish_package_json_schema() -> dict:
    schema = GuidePackage.model_json_schema()
    schema["$schemaVersion"] = GEO_PUBLISH_PACKAGE_VERSION
    return schema


__all__ = [
    "GEO_PUBLISH_PACKAGE_VERSION",
    "Article",
    "ClusterRef",
    "FaqItem",
    "Gate",
    "GuidePackage",
    "Seo",
    "publish_package_json_schema",
]
