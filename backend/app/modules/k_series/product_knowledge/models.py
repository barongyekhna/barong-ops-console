"""SQLAlchemy models for the isolated K Product Knowledge table family."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_CANONICAL_LANGUAGE,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
    TARGET_ORGANIZATION_NAME,
)


class KUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )


class KTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KProductKnowledgeProduct(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_products"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ("
            "'draft', 'ai_structured', 'needs_review', 'reviewed', "
            "'approved', 'blocked', 'archived'"
            ")",
            name=conv("ck_kpk_products_valid_review_status"),
        ),
        UniqueConstraint(
            "workspace_key",
            "business_context",
            "product_key",
            name="uq_kpk_products_scope_product_key",
        ),
        UniqueConstraint(
            "product_key",
            name="uq_kpk_products_product_key_global",
        ),
        CheckConstraint(
            "product_type IS NULL OR product_type IN ("
            "'simple_product', 'variable_product'"
            ")",
            name=conv("ck_kpk_products_valid_product_type"),
        ),
        Index(
            "ix_kpk_products_scope_status",
            "workspace_key",
            "business_context",
            "product_status",
        ),
        Index(
            "ix_kpk_products_scope_review",
            "workspace_key",
            "business_context",
            "review_status",
        ),
        Index(
            "ix_kpk_products_scope_sku",
            "workspace_key",
            "business_context",
            "sku",
        ),
        Index(
            "ix_kpk_products_scope_parent_sku",
            "workspace_key",
            "business_context",
            "parent_sku",
        ),
        Index("ix_kpk_products_target_market", "target_market"),
        Index("ix_kpk_products_parent", "parent_product_id"),
        Index("ix_kpk_products_variant", "variant_group_key"),
        Index("ix_kpk_products_created", "created_at"),
        Index("ix_kpk_products_updated", "updated_at"),
    )

    workspace_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        server_default=DEFAULT_WORKSPACE_KEY,
    )
    business_context: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        server_default=DEFAULT_BUSINESS_CONTEXT,
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=DEFAULT_SCOPE_MODE,
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=TARGET_ORGANIZATION_NAME,
    )
    product_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_market: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_product_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_products_parent_product_id_products",
        ),
        nullable=True,
    )
    variant_group_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="draft",
    )
    canonical_language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=DEFAULT_CANONICAL_LANGUAGE,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    product_name_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    short_description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    long_description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_use_case_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_customer_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    regular_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inventory_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manage_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipping_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contains_battery: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    us_stock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    shipping_assignment_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    shipping_review_needed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    tax_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    materials_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    dimensions_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    package_dimensions_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    weight_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    package_weight_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    color_options_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    size_options_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    package_includes_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    certifications_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    warranty_note_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_note_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    care_instructions_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    primary_keyword: Mapped[str | None] = mapped_column(String(512), nullable=True)
    secondary_keywords_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    long_tail_keywords_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    risk_keywords_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    seo_title_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    seo_description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ean: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mpn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asin_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Numeric Google taxonomy id only. All writes go through
    # category_resolver.bind_google_category_id; AI path text uses category_hint.
    google_product_category: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    merchant_product_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    category_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    # Amazon-group binding = Keepa leaf node id; DTC binding uses
    # google_product_category above (via the alignment map).
    amazon_category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # DTC auto-alignment was low-confidence / missing -> operator should check.
    category_review_needed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    # Temporary 作图参考图 (R→K carries the product image here; I-system
    # auto-loads it as a reference; cleared when the I output is saved back).
    reference_image_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    main_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    gallery_image_urls_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    video_urls_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    selected_image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    visual_profile_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_asset_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    media_notes_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    raw_input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_input_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deepseek_structured_output_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    ai_confidence_scores_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    ai_warnings_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # --- P-series: channel partition + skill-generated copy / image brief ---
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="dtc",
    )
    marketing_copy_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    marketing_copy_skill_version: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    image_instruction_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    image_instruction_skill_version: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    marketing_copy_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_instruction_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 品牌硬门：第三方品牌词黑名单（内部审查用，永不进上架包）+ 审查快照
    detected_brand_terms: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    brand_audit_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="draft",
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    manual_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_diff_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)


class KProductKnowledgeVariant(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_variants"
    __table_args__ = (
        UniqueConstraint(
            "variant_sku",
            name="uq_kpk_variants_variant_sku_global",
        ),
        UniqueConstraint(
            "product_id",
            "variant_hash",
            name="uq_kpk_variants_product_hash",
        ),
        Index("ix_kpk_variants_product", "product_id"),
        Index("ix_kpk_variants_parent_sku", "parent_sku"),
        Index("ix_kpk_variants_variant_sku", "variant_sku"),
        Index("ix_kpk_variants_status", "status"),
        Index("ix_kpk_variants_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_variants_product_id_products",
        ),
        nullable=False,
    )
    parent_sku: Mapped[str] = mapped_column(String(128), nullable=False)
    variant_sku: Mapped[str] = mapped_column(String(180), nullable=False)
    variant_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    color: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[str | None] = mapped_column(String(128), nullable=True)
    function: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_override: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    attributes_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    image_folder: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="active",
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeAttribute(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_attributes"
    __table_args__ = (
        CheckConstraint(
            "attribute_value_text IS NOT NULL OR attribute_value_json IS NOT NULL",
            name=conv("ck_kpk_attributes_has_value"),
        ),
        Index("ix_kpk_attributes_product", "product_id"),
        Index("ix_kpk_attributes_product_key", "product_id", "attribute_key"),
        Index("ix_kpk_attributes_group", "attribute_group"),
        Index("ix_kpk_attributes_requires_review", "requires_review"),
        Index("ix_kpk_attributes_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_attributes_product_id_products",
        ),
        nullable=False,
    )
    attribute_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribute_value_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    attribute_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attribute_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    requires_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeTranslation(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_translations"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "language_code",
            "translation_type",
            "source_text_hash",
            name="uq_kpk_translations_product_language_source",
        ),
        Index("ix_kpk_translations_product", "product_id"),
        Index("ix_kpk_translations_product_language", "product_id", "language_code"),
        Index(
            "ix_kpk_translations_language_type",
            "language_code",
            "translation_type",
        ),
        Index("ix_kpk_translations_review", "review_status"),
        Index("ix_kpk_translations_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_translations_product_id_products",
        ),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    translation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    translated_payload_json: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="draft",
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeKeyword(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_keywords"
    __table_args__ = (
        CheckConstraint(
            "keyword_type IN ("
            "'primary', 'secondary', 'long_tail', 'b2b', 'negative', 'risk'"
            ")",
            name=conv("ck_kpk_keywords_valid_keyword_type"),
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected', 'removed')",
            name=conv("ck_kpk_keywords_valid_status"),
        ),
        Index("ix_kpk_keywords_product_type", "product_id", "keyword_type"),
        Index("ix_kpk_keywords_product_status", "product_id", "status"),
        Index("ix_kpk_keywords_language_market", "language_code", "market"),
        Index(
            "ix_kpk_keywords_lookup",
            "product_id",
            "keyword_type",
            "language_code",
            "market",
            "keyword_text",
        ),
        Index("ix_kpk_keywords_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_keywords_product_id_products",
        ),
        nullable=False,
    )
    keyword_text: Mapped[str] = mapped_column(String(512), nullable=False)
    keyword_type: Mapped[str] = mapped_column(String(50), nullable=False)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str | None] = mapped_column(String(50), nullable=True)
    search_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="unknown",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="candidate",
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeRiskTerm(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_risk_terms"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'confirmed', 'removed', 'false_positive')",
            name=conv("ck_kpk_risk_terms_valid_status"),
        ),
        Index("ix_kpk_risk_terms_product_type", "product_id", "risk_type"),
        Index("ix_kpk_risk_terms_product_status", "product_id", "status"),
        Index("ix_kpk_risk_terms_lookup", "product_id", "risk_type", "term_en"),
        Index("ix_kpk_risk_terms_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_risk_terms_product_id_products",
        ),
        nullable=False,
    )
    term_en: Mapped[str] = mapped_column(String(512), nullable=False)
    term_zh: Mapped[str | None] = mapped_column(String(512), nullable=True)
    risk_type: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="unknown",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="candidate",
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeResearchRun(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_research_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'queued', 'running', 'succeeded', 'failed', "
            "'needs_review', 'cancelled'"
            ")",
            name=conv("ck_kpk_research_runs_valid_status"),
        ),
        Index("ix_kpk_research_runs_product_status", "product_id", "status"),
        Index("ix_kpk_research_runs_status", "status"),
        Index("ix_kpk_research_runs_target", "target_market", "target_language"),
        Index("ix_kpk_research_runs_requested_by", "requested_by_user_id"),
        Index("ix_kpk_research_runs_started", "started_at"),
        Index("ix_kpk_research_runs_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_research_runs_product_id_products",
        ),
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="queued",
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    target_market: Mapped[str] = mapped_column(String(50), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    seed_keywords_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    serp_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serp_result_summary_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    chatgpt_filter_summary_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    claude_filter_summary_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    selected_keyword_ids_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    error_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeAIEvent(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_ai_events"
    __table_args__ = (
        Index("ix_kpk_ai_events_product", "product_id"),
        Index("ix_kpk_ai_events_research_run", "research_run_id"),
        Index("ix_kpk_ai_events_provider", "provider"),
        Index("ix_kpk_ai_events_type", "event_type"),
        Index("ix_kpk_ai_events_status", "status"),
        Index("ix_kpk_ai_events_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_ai_events_product_id_products",
        ),
        nullable=False,
    )
    research_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_research_runs.id",
            name="fk_kpk_ai_events_research_run_id_research_runs",
        ),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_summary_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    output_payload_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeWorkflowExecution(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'created', 'running', 'blocked', 'failed', "
            "'ready_for_export', 'exported'"
            ")",
            name=conv("ck_kpk_workflow_executions_valid_status"),
        ),
        Index("ix_kpk_workflow_executions_product", "product_id"),
        Index("ix_kpk_workflow_executions_status", "status"),
        Index("ix_kpk_workflow_executions_current_step", "current_step"),
        Index(
            "ix_kpk_workflow_executions_scope",
            "workspace_key",
            "business_context",
            "organization_name",
        ),
        Index("ix_kpk_workflow_executions_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_workflow_executions_product_id_products",
        ),
        nullable=False,
    )
    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_key: Mapped[str] = mapped_column(String(128), nullable=False)
    business_context: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    target_market: Mapped[str] = mapped_column(String(50), nullable=False)
    target_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="created",
    )
    current_step: Mapped[str] = mapped_column(String(100), nullable=False)
    trace_json: Mapped[Any] = mapped_column(json_type(), nullable=False)
    chatgpt_filter_result_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    claude_filter_result_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    risk_approval_log_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    final_keyword_set_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    unit_conversion_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    image_binding_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    export_payloads_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    execution_gate_logs_json: Mapped[Any] = mapped_column(json_type(), nullable=False)
    error_report_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeVersion(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_versions"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "version_number",
            name="uq_kpk_versions_product_version",
        ),
        Index("ix_kpk_versions_product", "product_id"),
        Index("ix_kpk_versions_change_type", "change_type"),
        Index("ix_kpk_versions_changed_by", "changed_by_user_id"),
        Index("ix_kpk_versions_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_versions_product_id_products",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    change_source: Mapped[str] = mapped_column(String(50), nullable=False)
    before_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    after_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    diff_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)


class KProductKnowledgeMediaAsset(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_media_assets"
    __table_args__ = (
        Index("ix_kpk_media_assets_product_role", "product_id", "asset_role"),
        Index("ix_kpk_media_assets_variant_sku", "product_id", "variant_sku"),
        Index("ix_kpk_media_assets_type", "asset_type"),
        Index("ix_kpk_media_assets_status", "status"),
        Index("ix_kpk_media_assets_review", "review_status"),
        Index(
            "ix_kpk_media_assets_object_lookup",
            "product_id",
            "asset_role",
            "object_key",
        ),
        Index("ix_kpk_media_assets_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_media_assets_product_id_products",
        ),
        nullable=False,
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_variants.id",
            name="fk_kpk_media_assets_variant_id_variants",
        ),
        nullable=True,
    )
    variant_sku: Mapped[str | None] = mapped_column(String(180), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="draft",
    )
    review_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="draft",
    )
    storage_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_url_placeholder: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class KProductKnowledgeReviewItem(KUUIDPrimaryKeyMixin, KTimestampMixin, Base):
    __tablename__ = "k_product_knowledge_review_items"
    __table_args__ = (
        Index("ix_kpk_review_items_product", "product_id"),
        Index("ix_kpk_review_items_type", "review_type"),
        Index("ix_kpk_review_items_status", "status"),
        Index("ix_kpk_review_items_severity", "severity"),
        Index("ix_kpk_review_items_assigned_to", "assigned_to_user_id"),
        Index("ix_kpk_review_items_created", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "k_product_knowledge_products.id",
            name="fk_kpk_review_items_product_id_products",
        ),
        nullable=False,
    )
    review_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="open",
    )
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="medium",
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_changes_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    decision_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    assigned_to_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
