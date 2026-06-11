"""create K series product knowledge tables

Revision ID: k05a_product_knowledge_001
Revises: c05b_permissions_001
Create Date: 2026-06-11

This migration creates only the isolated K Product Knowledge table family.
Raw provider response retention is disabled by default; output_payload_json is
for structured business output or summaries only, not secrets, provider keys,
signed URLs, large prompts, image base64, or credential-like data.

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "k05a_product_knowledge_001"
down_revision: str | Sequence[str] | None = "c05b_permissions_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTS = "k_product_knowledge_products"
ATTRIBUTES = "k_product_knowledge_attributes"
TRANSLATIONS = "k_product_knowledge_translations"
KEYWORDS = "k_product_knowledge_keywords"
RISK_TERMS = "k_product_knowledge_risk_terms"
RESEARCH_RUNS = "k_product_knowledge_research_runs"
AI_EVENTS = "k_product_knowledge_ai_events"
VERSIONS = "k_product_knowledge_versions"
MEDIA_ASSETS = "k_product_knowledge_media_assets"
REVIEW_ITEMS = "k_product_knowledge_review_items"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def user_trace_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Uuid(), nullable=True)


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        PRODUCTS,
        uuid_pk_column(),
        sa.Column(
            "workspace_key",
            sa.String(length=128),
            server_default="default_independent_store",
            nullable=False,
        ),
        sa.Column(
            "business_context",
            sa.String(length=128),
            server_default="independent_store",
            nullable=False,
        ),
        sa.Column(
            "scope_mode",
            sa.String(length=64),
            server_default="adapter_pending",
            nullable=False,
        ),
        sa.Column("product_key", sa.String(length=128), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.String(length=128), nullable=True),
        sa.Column("parent_product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_group_key", sa.String(length=128), nullable=True),
        sa.Column(
            "product_status",
            sa.String(length=50),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "canonical_language",
            sa.String(length=16),
            server_default="en",
            nullable=False,
        ),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        sa.Column("product_name_en", sa.String(length=512), nullable=True),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("product_type", sa.String(length=128), nullable=True),
        sa.Column("short_description_en", sa.Text(), nullable=True),
        sa.Column("long_description_en", sa.Text(), nullable=True),
        sa.Column("primary_use_case_en", sa.Text(), nullable=True),
        sa.Column("target_customer_en", sa.Text(), nullable=True),
        sa.Column("regular_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("sale_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("margin", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("stock_status", sa.String(length=50), nullable=True),
        sa.Column("inventory_quantity", sa.Integer(), nullable=True),
        sa.Column("manage_stock", sa.Boolean(), nullable=True),
        sa.Column("moq", sa.Integer(), nullable=True),
        sa.Column("lead_time", sa.String(length=255), nullable=True),
        sa.Column("shipping_class", sa.String(length=128), nullable=True),
        sa.Column("tax_class", sa.String(length=128), nullable=True),
        sa.Column("materials_json", json_type(), nullable=True),
        sa.Column("dimensions_json", json_type(), nullable=True),
        sa.Column("package_dimensions_json", json_type(), nullable=True),
        sa.Column("weight_json", json_type(), nullable=True),
        sa.Column("package_weight_json", json_type(), nullable=True),
        sa.Column("color_options_json", json_type(), nullable=True),
        sa.Column("size_options_json", json_type(), nullable=True),
        sa.Column("package_includes_json", json_type(), nullable=True),
        sa.Column("certifications_json", json_type(), nullable=True),
        sa.Column("warranty_note_en", sa.Text(), nullable=True),
        sa.Column("safety_note_en", sa.Text(), nullable=True),
        sa.Column("care_instructions_en", sa.Text(), nullable=True),
        sa.Column("country_of_origin", sa.String(length=100), nullable=True),
        sa.Column("primary_keyword", sa.String(length=512), nullable=True),
        sa.Column("secondary_keywords_json", json_type(), nullable=True),
        sa.Column("long_tail_keywords_json", json_type(), nullable=True),
        sa.Column("risk_keywords_json", json_type(), nullable=True),
        sa.Column("seo_title_en", sa.String(length=512), nullable=True),
        sa.Column("seo_description_en", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("gtin", sa.String(length=64), nullable=True),
        sa.Column("upc", sa.String(length=64), nullable=True),
        sa.Column("ean", sa.String(length=64), nullable=True),
        sa.Column("mpn", sa.String(length=128), nullable=True),
        sa.Column("asin_reference", sa.String(length=128), nullable=True),
        sa.Column("google_product_category", sa.String(length=255), nullable=True),
        sa.Column("merchant_product_type", sa.String(length=255), nullable=True),
        sa.Column("category_hint", sa.String(length=255), nullable=True),
        sa.Column("category_path", sa.String(length=1024), nullable=True),
        sa.Column("category_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("main_image_url", sa.String(length=2048), nullable=True),
        sa.Column("gallery_image_urls_json", json_type(), nullable=True),
        sa.Column("video_urls_json", json_type(), nullable=True),
        sa.Column("selected_image_path", sa.String(length=1024), nullable=True),
        sa.Column("visual_profile_path", sa.String(length=1024), nullable=True),
        sa.Column("image_asset_status", sa.String(length=50), nullable=True),
        sa.Column("media_notes_json", json_type(), nullable=True),
        sa.Column("raw_input_text", sa.Text(), nullable=True),
        sa.Column("raw_input_language", sa.String(length=16), nullable=True),
        sa.Column("deepseek_structured_output_json", json_type(), nullable=True),
        sa.Column("ai_confidence_scores_json", json_type(), nullable=True),
        sa.Column("ai_warnings_json", json_type(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=50),
            server_default="draft",
            nullable=False,
        ),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_notes", sa.Text(), nullable=True),
        sa.Column("field_diff_json", json_type(), nullable=True),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "review_status IN ("
            "'draft', 'ai_structured', 'needs_review', 'reviewed', "
            "'approved', 'blocked', 'archived'"
            ")",
            name=op.f("ck_kpk_products_valid_review_status"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_products_parent_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_products")),
        sa.UniqueConstraint(
            "workspace_key",
            "business_context",
            "product_key",
            name=op.f("uq_kpk_products_scope_product_key"),
        ),
    )

    op.create_table(
        ATTRIBUTES,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("attribute_key", sa.String(length=128), nullable=False),
        sa.Column("attribute_value_text", sa.Text(), nullable=True),
        sa.Column("attribute_value_json", json_type(), nullable=True),
        sa.Column("attribute_unit", sa.String(length=50), nullable=True),
        sa.Column("attribute_group", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "requires_review",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "attribute_value_text IS NOT NULL "
            "OR attribute_value_json IS NOT NULL",
            name=op.f("ck_kpk_attributes_has_value"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_attributes_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_attributes")),
    )

    op.create_table(
        TRANSLATIONS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("translation_type", sa.String(length=64), nullable=False),
        sa.Column("source_text_hash", sa.String(length=128), nullable=False),
        sa.Column("translated_payload_json", json_type(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("provider_model", sa.String(length=100), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=50),
            server_default="draft",
            nullable=False,
        ),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_translations_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_translations")),
        sa.UniqueConstraint(
            "product_id",
            "language_code",
            "translation_type",
            "source_text_hash",
            name=op.f("uq_kpk_translations_product_language_source"),
        ),
    )

    op.create_table(
        KEYWORDS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("keyword_text", sa.String(length=512), nullable=False),
        sa.Column("keyword_type", sa.String(length=50), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=50), nullable=True),
        sa.Column("search_intent", sa.String(length=100), nullable=True),
        sa.Column(
            "source",
            sa.String(length=50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="candidate",
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "keyword_type IN ("
            "'primary', 'secondary', 'long_tail', 'b2b', "
            "'negative', 'risk'"
            ")",
            name=op.f("ck_kpk_keywords_valid_keyword_type"),
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected', 'removed')",
            name=op.f("ck_kpk_keywords_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_keywords_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_keywords")),
    )

    op.create_table(
        RISK_TERMS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("term_en", sa.String(length=512), nullable=False),
        sa.Column("term_zh", sa.String(length=512), nullable=True),
        sa.Column("risk_type", sa.String(length=100), nullable=False),
        sa.Column("risk_reason", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="candidate",
            nullable=False,
        ),
        user_trace_column("confirmed_by_user_id"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "status IN ("
            "'candidate', 'confirmed', 'removed', 'false_positive'"
            ")",
            name=op.f("ck_kpk_risk_terms_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_risk_terms_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_risk_terms")),
    )

    op.create_table(
        RESEARCH_RUNS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="queued",
            nullable=False,
        ),
        user_trace_column("requested_by_user_id"),
        sa.Column("target_market", sa.String(length=50), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("seed_keywords_json", json_type(), nullable=True),
        sa.Column("serp_provider", sa.String(length=100), nullable=True),
        sa.Column("serp_result_summary_json", json_type(), nullable=True),
        sa.Column("chatgpt_filter_summary_json", json_type(), nullable=True),
        sa.Column("claude_filter_summary_json", json_type(), nullable=True),
        sa.Column("selected_keyword_ids_json", json_type(), nullable=True),
        sa.Column("error_class", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "status IN ("
            "'queued', 'running', 'succeeded', 'failed', "
            "'needs_review', 'cancelled'"
            ")",
            name=op.f("ck_kpk_research_runs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_research_runs_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_research_runs")),
    )

    op.create_table(
        AI_EVENTS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("input_hash", sa.String(length=128), nullable=True),
        sa.Column("output_summary_json", json_type(), nullable=True),
        sa.Column("output_payload_json", json_type(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_class", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("token_estimate", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(precision=12, scale=6), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_ai_events_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            [f"{RESEARCH_RUNS}.id"],
            name=op.f("fk_kpk_ai_events_research_run_id_research_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_ai_events")),
    )

    op.create_table(
        VERSIONS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=100), nullable=False),
        user_trace_column("changed_by_user_id"),
        sa.Column("change_source", sa.String(length=50), nullable=False),
        sa.Column("before_json", json_type(), nullable=True),
        sa.Column("after_json", json_type(), nullable=True),
        sa.Column("diff_json", json_type(), nullable=True),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_versions_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_versions")),
        sa.UniqueConstraint(
            "product_id",
            "version_number",
            name=op.f("uq_kpk_versions_product_version"),
        ),
    )

    op.create_table(
        MEDIA_ASSETS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("asset_role", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "review_status",
            sa.String(length=50),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("storage_provider", sa.String(length=100), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column("file_url_placeholder", sa.String(length=2048), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", json_type(), nullable=True),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_media_assets_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_media_assets")),
    )

    op.create_table(
        REVIEW_ITEMS,
        uuid_pk_column(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("review_type", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.String(length=50),
            server_default="medium",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("proposed_changes_json", json_type(), nullable=True),
        sa.Column("decision_json", json_type(), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        user_trace_column("assigned_to_user_id"),
        user_trace_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_review_items_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_review_items")),
    )

    op.create_index(
        op.f("ix_kpk_products_scope_status"),
        PRODUCTS,
        ["workspace_key", "business_context", "product_status"],
    )
    op.create_index(
        op.f("ix_kpk_products_scope_review"),
        PRODUCTS,
        ["workspace_key", "business_context", "review_status"],
    )
    op.create_index(
        op.f("ix_kpk_products_scope_sku"),
        PRODUCTS,
        ["workspace_key", "business_context", "sku"],
    )
    op.create_index(op.f("ix_kpk_products_parent"), PRODUCTS, ["parent_product_id"])
    op.create_index(op.f("ix_kpk_products_variant"), PRODUCTS, ["variant_group_key"])
    op.create_index(op.f("ix_kpk_products_created"), PRODUCTS, ["created_at"])
    op.create_index(op.f("ix_kpk_products_updated"), PRODUCTS, ["updated_at"])

    op.create_index(op.f("ix_kpk_attributes_product"), ATTRIBUTES, ["product_id"])
    op.create_index(
        op.f("ix_kpk_attributes_product_key"),
        ATTRIBUTES,
        ["product_id", "attribute_key"],
    )
    op.create_index(op.f("ix_kpk_attributes_group"), ATTRIBUTES, ["attribute_group"])
    op.create_index(
        op.f("ix_kpk_attributes_requires_review"),
        ATTRIBUTES,
        ["requires_review"],
    )
    op.create_index(op.f("ix_kpk_attributes_created"), ATTRIBUTES, ["created_at"])

    op.create_index(op.f("ix_kpk_translations_product"), TRANSLATIONS, ["product_id"])
    op.create_index(
        op.f("ix_kpk_translations_product_language"),
        TRANSLATIONS,
        ["product_id", "language_code"],
    )
    op.create_index(
        op.f("ix_kpk_translations_language_type"),
        TRANSLATIONS,
        ["language_code", "translation_type"],
    )
    op.create_index(
        op.f("ix_kpk_translations_review"),
        TRANSLATIONS,
        ["review_status"],
    )
    op.create_index(op.f("ix_kpk_translations_created"), TRANSLATIONS, ["created_at"])

    op.create_index(
        op.f("ix_kpk_keywords_product_type"),
        KEYWORDS,
        ["product_id", "keyword_type"],
    )
    op.create_index(
        op.f("ix_kpk_keywords_product_status"),
        KEYWORDS,
        ["product_id", "status"],
    )
    op.create_index(
        op.f("ix_kpk_keywords_language_market"),
        KEYWORDS,
        ["language_code", "market"],
    )
    op.create_index(
        op.f("ix_kpk_keywords_lookup"),
        KEYWORDS,
        ["product_id", "keyword_type", "language_code", "market", "keyword_text"],
    )
    op.create_index(op.f("ix_kpk_keywords_created"), KEYWORDS, ["created_at"])

    op.create_index(
        op.f("ix_kpk_risk_terms_product_type"),
        RISK_TERMS,
        ["product_id", "risk_type"],
    )
    op.create_index(
        op.f("ix_kpk_risk_terms_product_status"),
        RISK_TERMS,
        ["product_id", "status"],
    )
    op.create_index(
        op.f("ix_kpk_risk_terms_lookup"),
        RISK_TERMS,
        ["product_id", "risk_type", "term_en"],
    )
    op.create_index(op.f("ix_kpk_risk_terms_created"), RISK_TERMS, ["created_at"])

    op.create_index(
        op.f("ix_kpk_research_runs_product_status"),
        RESEARCH_RUNS,
        ["product_id", "status"],
    )
    op.create_index(op.f("ix_kpk_research_runs_status"), RESEARCH_RUNS, ["status"])
    op.create_index(
        op.f("ix_kpk_research_runs_target"),
        RESEARCH_RUNS,
        ["target_market", "target_language"],
    )
    op.create_index(
        op.f("ix_kpk_research_runs_requested_by"),
        RESEARCH_RUNS,
        ["requested_by_user_id"],
    )
    op.create_index(
        op.f("ix_kpk_research_runs_started"),
        RESEARCH_RUNS,
        ["started_at"],
    )
    op.create_index(
        op.f("ix_kpk_research_runs_created"),
        RESEARCH_RUNS,
        ["created_at"],
    )

    op.create_index(op.f("ix_kpk_ai_events_product"), AI_EVENTS, ["product_id"])
    op.create_index(
        op.f("ix_kpk_ai_events_research_run"),
        AI_EVENTS,
        ["research_run_id"],
    )
    op.create_index(op.f("ix_kpk_ai_events_provider"), AI_EVENTS, ["provider"])
    op.create_index(op.f("ix_kpk_ai_events_type"), AI_EVENTS, ["event_type"])
    op.create_index(op.f("ix_kpk_ai_events_status"), AI_EVENTS, ["status"])
    op.create_index(op.f("ix_kpk_ai_events_created"), AI_EVENTS, ["created_at"])

    op.create_index(op.f("ix_kpk_versions_product"), VERSIONS, ["product_id"])
    op.create_index(op.f("ix_kpk_versions_change_type"), VERSIONS, ["change_type"])
    op.create_index(
        op.f("ix_kpk_versions_changed_by"),
        VERSIONS,
        ["changed_by_user_id"],
    )
    op.create_index(op.f("ix_kpk_versions_created"), VERSIONS, ["created_at"])

    op.create_index(
        op.f("ix_kpk_media_assets_product_role"),
        MEDIA_ASSETS,
        ["product_id", "asset_role"],
    )
    op.create_index(op.f("ix_kpk_media_assets_type"), MEDIA_ASSETS, ["asset_type"])
    op.create_index(op.f("ix_kpk_media_assets_status"), MEDIA_ASSETS, ["status"])
    op.create_index(
        op.f("ix_kpk_media_assets_review"),
        MEDIA_ASSETS,
        ["review_status"],
    )
    op.create_index(
        op.f("ix_kpk_media_assets_object_lookup"),
        MEDIA_ASSETS,
        ["product_id", "asset_role", "object_key"],
    )
    op.create_index(op.f("ix_kpk_media_assets_created"), MEDIA_ASSETS, ["created_at"])

    op.create_index(op.f("ix_kpk_review_items_product"), REVIEW_ITEMS, ["product_id"])
    op.create_index(
        op.f("ix_kpk_review_items_type"),
        REVIEW_ITEMS,
        ["review_type"],
    )
    op.create_index(op.f("ix_kpk_review_items_status"), REVIEW_ITEMS, ["status"])
    op.create_index(op.f("ix_kpk_review_items_severity"), REVIEW_ITEMS, ["severity"])
    op.create_index(
        op.f("ix_kpk_review_items_assigned_to"),
        REVIEW_ITEMS,
        ["assigned_to_user_id"],
    )
    op.create_index(op.f("ix_kpk_review_items_created"), REVIEW_ITEMS, ["created_at"])


def downgrade() -> None:
    op.drop_table(REVIEW_ITEMS)
    op.drop_table(MEDIA_ASSETS)
    op.drop_table(VERSIONS)
    op.drop_table(AI_EVENTS)
    op.drop_table(RESEARCH_RUNS)
    op.drop_table(RISK_TERMS)
    op.drop_table(KEYWORDS)
    op.drop_table(TRANSLATIONS)
    op.drop_table(ATTRIBUTES)
    op.drop_table(PRODUCTS)
