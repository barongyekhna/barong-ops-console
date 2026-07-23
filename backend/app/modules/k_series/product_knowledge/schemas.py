"""Pydantic DTOs for the K Product Knowledge API skeleton."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ....schemas.common import reject_sensitive_data
from .buyer_display import normalize_package_includes
from .constants import DEFAULT_CANONICAL_LANGUAGE
from .structured_specs import normalize_operator_structured_specs

ReviewStatus = Literal[
    "draft",
    "ai_structured",
    "needs_review",
    "reviewed",
    "approved",
    "blocked",
    "archived",
]
KeywordType = Literal["primary", "secondary", "long_tail", "b2b", "negative", "risk"]
KeywordStatus = Literal["candidate", "approved", "rejected", "removed"]
RiskTermStatus = Literal["candidate", "confirmed", "removed", "false_positive"]
ProductType = Literal["simple_product", "variable_product"]
ImageSourceType = Literal["manual_upload_image", "i_system_asset"]
WorkflowStatus = Literal[
    "created",
    "running",
    "blocked",
    "failed",
    "ready_for_export",
    "exported",
]
RiskReviewDecision = Literal["approve", "reject"]


class ProductKnowledgeAttributeItem(BaseModel):
    attribute_key: str = Field(min_length=1, max_length=128)
    attribute_value_text: str | None = None
    attribute_value_json: dict[str, Any] | list[Any] | None = None
    attribute_unit: str | None = Field(default=None, max_length=50)
    attribute_group: str | None = Field(default=None, max_length=128)
    source: str | None = Field(default=None, max_length=100)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    requires_review: bool = False

    @field_validator("attribute_value_json")
    @classmethod
    def validate_attribute_json(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @model_validator(mode="after")
    def require_value(self) -> "ProductKnowledgeAttributeItem":
        if self.attribute_value_text is None and self.attribute_value_json is None:
            raise ValueError(
                "At least one of attribute_value_text or attribute_value_json "
                "is required."
            )
        self.attribute_key = self.attribute_key.strip()
        return self


class ProductKnowledgeKeywordItem(BaseModel):
    keyword_text: str = Field(min_length=1, max_length=512)
    keyword_type: KeywordType
    language_code: str = Field(min_length=1, max_length=16)
    market: str | None = Field(default=None, max_length=50)
    search_intent: str | None = Field(default=None, max_length=100)
    source: str = Field(default="unknown", min_length=1, max_length=50)
    status: KeywordStatus = "candidate"
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    reason: str | None = None

    @model_validator(mode="after")
    def normalize_strings(self) -> "ProductKnowledgeKeywordItem":
        self.keyword_text = self.keyword_text.strip()
        self.language_code = self.language_code.strip().lower()
        if self.market is not None:
            self.market = self.market.strip() or None
        return self


class ProductKnowledgeRiskTermItem(BaseModel):
    term_en: str = Field(min_length=1, max_length=512)
    term_zh: str | None = Field(default=None, max_length=512)
    risk_type: str = Field(min_length=1, max_length=100)
    risk_reason: str | None = None
    suggested_action: str | None = None
    source: str = Field(default="unknown", min_length=1, max_length=50)
    status: RiskTermStatus = "candidate"

    @model_validator(mode="after")
    def normalize_strings(self) -> "ProductKnowledgeRiskTermItem":
        self.term_en = self.term_en.strip()
        self.risk_type = self.risk_type.strip()
        return self


class ProductKnowledgeVariantItem(BaseModel):
    variant_sku: str | None = Field(default=None, max_length=180)
    color: str | None = Field(default=None, max_length=128)
    size: str | None = Field(default=None, max_length=128)
    function: str | None = Field(default=None, max_length=128)
    quantity: int | None = Field(default=None, ge=0)
    price_override: Decimal | None = Field(default=None, ge=0)
    # 每个变体独立的物理规格(1 个装和 2 个装的尺寸重量不一样),
    # 结构与父体 dimensions_json / weight_json 同构,落库进 attributes_json.physical。
    dimensions_json: dict[str, Any] | list[Any] | None = None
    weight_json: dict[str, Any] | list[Any] | None = None
    # 可选:该变体(颜色)的专属参考图链接——同色多卡填一张即可。
    # 渲染管线按颜色自动出"该色主图",上架时挂到对应 Woo variation(选色即换图)。
    reference_image_url: str | None = Field(default=None, max_length=2000)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reference_image_url")
    @classmethod
    def _validate_variant_reference_url(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("变体参考图链接必须以 http:// 或 https:// 开头")
        return cleaned

    @field_validator("attributes")
    @classmethod
    def validate_variant_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return reject_sensitive_data(value)

    @field_validator("dimensions_json", "weight_json")
    @classmethod
    def validate_variant_physical_json(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @model_validator(mode="after")
    def normalize_variant_strings(self) -> "ProductKnowledgeVariantItem":
        if self.variant_sku is not None:
            self.variant_sku = self.variant_sku.strip() or None
        if self.variant_sku is not None:
            raise ValueError("variant_sku is auto-generated and cannot be provided.")
        if self.color is not None:
            self.color = self.color.strip() or None
        if self.size is not None:
            self.size = self.size.strip() or None
        if self.function is not None:
            self.function = self.function.strip() or None
        return self


class ProductKnowledgeCreate(BaseModel):
    product_key: str | None = Field(default=None, max_length=128)
    raw_input_text: str = Field(min_length=1)
    main_keyword: str | None = Field(default=None, max_length=512)
    target_market: str = Field(default="US", min_length=1, max_length=50)
    target_locale: str | None = Field(default=None, max_length=16)
    parent_sku: str | None = Field(default=None, max_length=128)
    raw_input_language: str | None = Field(default=None, max_length=16)
    source_system: str | None = Field(default="manual", max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=128)
    product_status: str = Field(default="draft", min_length=1, max_length=50)
    review_status: ReviewStatus = "draft"
    canonical_language: str | None = Field(default=None, max_length=16)
    product_name_en: str | None = Field(default=None, max_length=512)
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    product_type: ProductType = "simple_product"
    channel: str = "dtc"
    category_id: str | None = Field(default=None, max_length=32)
    regular_price: Decimal | None = Field(default=None, ge=0)
    price_currency: str | None = Field(default=None, max_length=3)
    dimensions_json: dict[str, Any] | list[Any] | None = None
    weight_json: dict[str, Any] | list[Any] | None = None
    structured_specs_json: dict[str, Any] | None = None
    package_includes_json: list[str] | None = None
    short_description_en: str | None = None
    long_description_en: str | None = None
    primary_use_case_en: str | None = None
    target_customer_en: str | None = None
    manual_notes: str | None = None
    # 可选:1688 货源链接 —— 建品时顺手贴上,SKU 签发后自动灌入 W-S 货源库,
    # 出单即有「1688 下单」直达按钮;留空则以后去 W-S 货源库补。
    source_url: str | None = Field(default=None, max_length=1000)
    # 可选:参考图链接(1688 商品主图右键复制地址即可)——直接进 K 参考图
    # 管线喂渲染。域名白名单 alicdn/amazon,防 SSRF。
    reference_image_url: str | None = Field(default=None, max_length=2000)
    # 可选:多条参考图链接(多角度/多颜色)。第一张成功入库的作为主参考图,
    # 其余全部落 K 媒体库备渲染;单条失败跳过不阻塞建品。
    reference_image_urls: list[str] | None = Field(default=None, max_length=8)
    variants: list[ProductKnowledgeVariantItem] = Field(default_factory=list)
    attributes: list[ProductKnowledgeAttributeItem] = Field(default_factory=list)
    keywords: list[ProductKnowledgeKeywordItem] = Field(default_factory=list)
    risk_terms: list[ProductKnowledgeRiskTermItem] = Field(default_factory=list)

    @field_validator("source_url", "reference_image_url")
    @classmethod
    def _validate_source_url(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("货源链接必须以 http:// 或 https:// 开头")
        return cleaned

    @field_validator("reference_image_urls")
    @classmethod
    def _validate_reference_image_urls(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if not value:
            return None
        cleaned: list[str] = []
        for item in value:
            entry = (item or "").strip()
            if not entry:
                continue
            if not entry.lower().startswith(("http://", "https://")):
                raise ValueError("参考图链接必须以 http:// 或 https:// 开头")
            if len(entry) > 2000:
                raise ValueError("单条参考图链接不能超过 2000 字符")
            if entry not in cleaned:
                cleaned.append(entry)
        return cleaned or None

    @model_validator(mode="after")
    def _variable_product_price_rules(self) -> "ProductKnowledgeCreate":
        # 多变体产品价格只存在于变体上(2026-07-22 用户拍板):
        # 父体价一律置空(Woo 父体展示价由变体推导),且每个变体必须有价。
        if self.product_type == "variable_product":
            self.regular_price = None
            if self.variants and any(
                item.price_override is None for item in self.variants
            ):
                raise ValueError("多变体产品的每个变体都必须填写价格")
        return self

    @field_validator("dimensions_json", "weight_json")
    @classmethod
    def validate_physical_json(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @field_validator("structured_specs_json")
    @classmethod
    def validate_manual_structured_specs(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        reject_sensitive_data(value)
        return normalize_operator_structured_specs(value)

    @field_validator("package_includes_json")
    @classmethod
    def validate_package_includes(cls, value: list[str] | None) -> list[str] | None:
        reject_sensitive_data(value)
        normalized = normalize_package_includes(value)
        return normalized or None

    @field_validator("channel")
    @classmethod
    def _normalize_channel(cls, value: str) -> str:
        v = (value or "dtc").strip().lower()
        return v if v in ("amazon", "dtc") else "dtc"

    @field_validator("category_id")
    @classmethod
    def _normalize_category_id(cls, value: str | None) -> str | None:
        v = (value or "").strip()
        return v or None

    @model_validator(mode="after")
    def normalize_required_strings(self) -> "ProductKnowledgeCreate":
        if self.product_key is not None and self.product_key.strip():
            raise ValueError("product_key is auto-generated and cannot be provided.")
        if self.main_keyword is not None:
            self.main_keyword = self.main_keyword.strip() or None
        self.target_market = self.target_market.strip().upper()
        if self.target_locale is not None:
            self.target_locale = self.target_locale.strip().lower() or None
        if self.raw_input_language is not None:
            self.raw_input_language = self.raw_input_language.strip().lower() or None
        if self.canonical_language is not None:
            self.canonical_language = self.canonical_language.strip().lower() or None
        if self.parent_sku is not None:
            self.parent_sku = self.parent_sku.strip() or None
        if self.sku is not None:
            self.sku = self.sku.strip() or None
        if self.price_currency is not None:
            self.price_currency = self.price_currency.strip().upper() or None
        if self.product_type == "variable_product" and not self.variants:
            raise ValueError("variable_product requires at least one variant.")
        if self.product_type == "simple_product" and self.variants:
            raise ValueError("simple_product does not accept variant rows.")
        return self


class ProductKnowledgeUpdate(BaseModel):
    source_system: str | None = Field(default=None, max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=128)
    parent_sku: str | None = Field(default=None, max_length=128)
    target_market: str | None = Field(default=None, max_length=50)
    product_status: str | None = Field(default=None, min_length=1, max_length=50)
    review_status: ReviewStatus | None = None
    canonical_language: str | None = Field(default=None, min_length=1, max_length=16)
    raw_input_text: str | None = None
    raw_input_language: str | None = Field(default=None, max_length=16)
    main_keyword: str | None = Field(default=None, max_length=512)
    product_name_en: str | None = Field(default=None, max_length=512)
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    product_type: ProductType | None = None
    regular_price: Decimal | None = Field(default=None, ge=0)
    price_currency: str | None = Field(default=None, max_length=3)
    dimensions_json: dict[str, Any] | list[Any] | None = None
    weight_json: dict[str, Any] | list[Any] | None = None
    structured_specs_json: dict[str, Any] | None = None
    package_includes_json: list[str] | None = None
    short_description_en: str | None = None
    long_description_en: str | None = None
    primary_use_case_en: str | None = None
    target_customer_en: str | None = None
    manual_notes: str | None = None

    @field_validator("dimensions_json", "weight_json")
    @classmethod
    def validate_physical_json(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @field_validator("structured_specs_json")
    @classmethod
    def validate_manual_structured_specs(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        reject_sensitive_data(value)
        return normalize_operator_structured_specs(value)

    @field_validator("package_includes_json")
    @classmethod
    def validate_package_includes(cls, value: list[str] | None) -> list[str] | None:
        reject_sensitive_data(value)
        normalized = normalize_package_includes(value)
        return normalized or None

    @model_validator(mode="after")
    def normalize_languages(self) -> "ProductKnowledgeUpdate":
        if self.raw_input_language is not None:
            self.raw_input_language = self.raw_input_language.strip().lower()
        if self.main_keyword is not None:
            self.main_keyword = self.main_keyword.strip() or None
        if self.canonical_language is not None:
            self.canonical_language = self.canonical_language.strip().lower()
        if self.parent_sku is not None:
            self.parent_sku = self.parent_sku.strip() or None
        if self.target_market is not None:
            self.target_market = self.target_market.strip().upper() or None
        if self.price_currency is not None:
            self.price_currency = self.price_currency.strip().upper() or None
        return self


class ProductKnowledgeVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    parent_sku: str
    variant_sku: str
    variant_hash: str
    color: str | None
    size: str | None
    function: str | None
    quantity: int | None
    price_override: Decimal | None
    attributes_json: dict[str, Any] | list[Any] | None
    image_folder: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_key: str
    product_status: str
    review_status: str
    channel: str = "dtc"
    marketing_copy_json: Any | None = None
    image_instruction_json: Any | None = None
    marketing_copy_zh: str | None = None
    image_instruction_zh: str | None = None
    reference_image_url: str | None = None
    detected_brand_terms: Any | None = None
    brand_audit_json: Any | None = None
    canonical_language: str
    raw_input_text: str | None
    raw_input_language: str | None
    main_keyword: str | None = None
    primary_keyword: str | None = None
    product_name_en: str | None
    brand_name: str | None
    manufacturer: str | None
    product_type: str | None
    short_description_en: str | None
    long_description_en: str | None
    primary_use_case_en: str | None
    target_customer_en: str | None
    sku: str | None
    parent_sku: str | None = None
    target_market: str | None = None
    shipping_class: str | None = None
    shipping_review_needed: bool = False
    shipping_assignment: dict[str, Any] | None = None
    contains_battery: bool = False
    category_id: str | None = None
    category_tree: Literal["google", "amazon"] | None = None
    google_product_category: str | None = None
    amazon_category_id: str | None = None
    structured_specs_json: dict[str, Any] | None = None
    specs_incomplete: bool = False
    missing_required_specs: list[str] = Field(default_factory=list)
    package_includes_json: list[str] | None = None
    selling_points_candidates_json: dict[str, Any] | None = None
    selling_points_approved_json: dict[str, Any] | None = None
    faq_research_json: dict[str, Any] | None = None
    workspace_key: str
    business_context: str
    scope_mode: str
    organization_name: str
    created_at: datetime
    updated_at: datetime
    attributes_count: int | None = None
    keywords_count: int | None = None
    risk_terms_count: int | None = None
    variant_count: int | None = None
    variants: list[ProductKnowledgeVariantRead] = Field(default_factory=list)


class ProductKnowledgeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_key: str
    sku: str | None
    product_name_en: str | None
    brand_name: str | None
    product_type: str | None
    product_status: str
    review_status: str
    canonical_language: str
    parent_sku: str | None = None
    target_market: str | None = None
    main_keyword: str | None = None
    primary_keyword: str | None = None
    variant_count: int | None = None
    variants: list[ProductKnowledgeVariantRead] = Field(default_factory=list)
    workspace_key: str
    business_context: str
    scope_mode: str
    organization_name: str
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeListResponse(BaseModel):
    items: list[ProductKnowledgeListItem]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ProductKnowledgeAttributePatch(BaseModel):
    items: list[ProductKnowledgeAttributeItem] = Field(default_factory=list)


class ProductKnowledgeKeywordPatch(BaseModel):
    items: list[ProductKnowledgeKeywordItem] = Field(default_factory=list)


class ProductKnowledgeRiskTermPatch(BaseModel):
    items: list[ProductKnowledgeRiskTermItem] = Field(default_factory=list)


class ProductKnowledgeAttributeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    attribute_key: str
    attribute_value_text: str | None
    attribute_value_json: dict[str, Any] | list[Any] | None
    attribute_unit: str | None
    attribute_group: str | None
    source: str | None
    confidence: Decimal | None
    requires_review: bool
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeAttributeListResponse(BaseModel):
    items: list[ProductKnowledgeAttributeRead]
    count: int = Field(ge=0)


class ProductKnowledgeKeywordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    keyword_text: str
    keyword_type: str
    language_code: str
    market: str | None
    search_intent: str | None
    source: str
    status: str
    confidence: Decimal | None
    reason: str | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeKeywordListResponse(BaseModel):
    items: list[ProductKnowledgeKeywordRead]
    count: int = Field(ge=0)


class ProductKnowledgeRiskTermRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    term_en: str
    term_zh: str | None
    risk_type: str
    risk_reason: str | None
    suggested_action: str | None
    source: str
    status: str
    confirmed_by_user_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeRiskTermListResponse(BaseModel):
    items: list[ProductKnowledgeRiskTermRead]
    count: int = Field(ge=0)


class ProductKnowledgeWorkflowStartRequest(BaseModel):
    target_market: str = Field(default="US", min_length=1, max_length=50)
    target_region: str | None = Field(default=None, max_length=100)
    main_keyword: str | None = Field(default=None, max_length=512)
    serp_query: str | None = Field(default=None, max_length=512)
    seed_keywords: list[str] = Field(default_factory=list, max_length=50)
    competitors: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def normalize_workflow_input(self) -> "ProductKnowledgeWorkflowStartRequest":
        self.target_market = self.target_market.strip().upper()
        if self.target_region is not None:
            self.target_region = self.target_region.strip() or None
        if self.main_keyword is not None:
            self.main_keyword = self.main_keyword.strip() or None
        if self.serp_query is not None:
            self.serp_query = self.serp_query.strip() or None
        self.seed_keywords = [_clean_text(item) for item in self.seed_keywords]
        self.seed_keywords = [item for item in self.seed_keywords if item]
        self.competitors = [_clean_text(item) for item in self.competitors]
        self.competitors = [item for item in self.competitors if item]
        return self


class ProductKnowledgeRiskReviewDecision(BaseModel):
    risk_term_id: UUID | None = None
    term: str = Field(min_length=1, max_length=512)
    decision: RiskReviewDecision
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def normalize_decision(self) -> "ProductKnowledgeRiskReviewDecision":
        self.term = self.term.strip()
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


class ProductKnowledgeRiskReviewRequest(BaseModel):
    execution_id: UUID | None = None
    decisions: list[ProductKnowledgeRiskReviewDecision] = Field(default_factory=list)
    confirm_no_risk_terms: bool = False


class ProductKnowledgeWorkflowExportRequest(BaseModel):
    execution_id: UUID | None = None


class ProductKnowledgeWorkflowControlRequest(BaseModel):
    execution_id: UUID | None = None
    step: str | None = Field(default=None, max_length=100)
    workflow_payload: ProductKnowledgeWorkflowStartRequest | None = None

    @model_validator(mode="after")
    def normalize_step(self) -> "ProductKnowledgeWorkflowControlRequest":
        if self.step is not None:
            self.step = self.step.strip() or None
        return self


class ProductKnowledgeImageBindRequest(BaseModel):
    source_type: ImageSourceType = "manual_upload_image"
    variant_sku: str | None = Field(default=None, max_length=180)
    asset_id: UUID | None = None
    manual_asset_id: UUID | None = None
    i_system_image_asset_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_source_identifier(self) -> "ProductKnowledgeImageBindRequest":
        if self.variant_sku is not None:
            self.variant_sku = self.variant_sku.strip() or None
        if self.i_system_image_asset_id is not None:
            self.i_system_image_asset_id = self.i_system_image_asset_id.strip() or None
        if self.source_type == "manual_upload_image" and not (
            self.asset_id or self.manual_asset_id
        ):
            raise ValueError("manual_upload_image requires asset_id or manual_asset_id.")
        if self.source_type == "i_system_asset" and not (
            self.i_system_image_asset_id or self.asset_id
        ):
            raise ValueError("i_system_asset requires i_system_image_asset_id.")
        return self


class ProductKnowledgeWorkflowExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    organization_name: str
    workspace_key: str
    business_context: str
    scope_mode: str
    target_market: str
    target_region: str | None
    status: str
    current_step: str
    trace_json: list[dict[str, Any]]
    chatgpt_filter_result_json: dict[str, Any] | None
    claude_filter_result_json: dict[str, Any] | None
    risk_approval_log_json: dict[str, Any] | None
    final_keyword_set_json: dict[str, Any] | None
    unit_conversion_json: dict[str, Any] | None
    image_binding_json: dict[str, Any] | None
    export_payloads_json: dict[str, Any] | None
    execution_gate_logs_json: list[dict[str, Any]]
    error_report_json: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeWorkflowReport(BaseModel):
    workflow_id: UUID
    product_id: UUID
    organization: str
    status: str
    current_step: str
    full_pipeline_trace: list[dict[str, Any]]
    chatgpt_filter_result: dict[str, Any] | None
    claude_filter_result: dict[str, Any] | None
    risk_approval_log: dict[str, Any] | None
    final_keyword_set: dict[str, Any] | None
    export_payloads: dict[str, Any] | None
    execution_gate_logs: list[dict[str, Any]]
    error_report: dict[str, Any] | None


class ProductKnowledgeWorkflowExportResponse(BaseModel):
    execution: ProductKnowledgeWorkflowExecutionRead
    report: ProductKnowledgeWorkflowReport


class ProductKnowledgeMediaDownloadResponse(BaseModel):
    asset_id: UUID
    product_id: UUID
    object_key: str | None
    download_url: str | None
    original_url: str | None = None
    filename: str | None
    review_status: str
    status: str


class ArchiveProductKnowledgeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ErrorResponse(BaseModel):
    code: str
    message: str


def _clean_text(value: Any) -> str:
    return str(value).strip()
