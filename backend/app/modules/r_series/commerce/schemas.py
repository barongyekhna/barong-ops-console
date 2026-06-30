"""DTOs for R-series V3 commerce selection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RCommerceRunRequest(BaseModel):
    main_keyword: str = Field(min_length=1, max_length=240)
    category: str = Field(default="home improvement", max_length=160)
    market: Literal["Amazon", "独立站", "Both"] = "Both"
    price_range: str = Field(default="19-39", max_length=80)
    risk_level: Literal["low", "medium", "high"] = "medium"
    target_count: int = Field(default=3, ge=1, le=20)
    task_budget_usd: float = Field(gt=0)

    @field_validator("main_keyword", "category", "price_range")
    @classmethod
    def strip_string(cls, value: str) -> str:
        return value.strip()


class RReason(BaseModel):
    text: str
    source: Literal["deepseek_v4_pro"]


class RSupplier(BaseModel):
    organization_id: str
    supplier_name: str
    product_link: str
    link: str | None = None
    preview_image: str
    price_range: str
    MOQ: int
    dropshipping_support: bool
    moq_1_allowed: bool
    sample_availability: bool
    shipping_origin: str
    rating: float | None = None
    provider: str = "mock_1688_supplier_provider"
    mock: bool = True


class RSizeWeight(BaseModel):
    length_cm: int
    width_cm: int
    height_cm: int
    weight_kg: float
    package_type: str
    shipping_class: str


class RProductCandidate(BaseModel):
    organization_id: str
    candidate_id: str
    main_keyword: str
    market: Literal["Amazon", "独立站", "Both"]
    channel_recommendation: Literal["amazon", "site", "dual"]
    supplier_list: list[RSupplier] = Field(min_length=2, max_length=5)
    supply_chain_incomplete: bool = False
    purchase_price_range: str
    selling_price: str
    size_weight: RSizeWeight
    reason: RReason
    decision_summary: dict[str, Any] = Field(default_factory=dict)
    provider_contract: dict[str, Any] = Field(default_factory=dict)


class RCommerceRunResponse(BaseModel):
    report_name: str
    generated_at: str
    engine: str
    engine_version: str
    organization_id: str
    organization_name: str
    provider_mode: Literal["mock"]
    api_key_dependency: bool
    future_v3_key_ready: bool
    required_skills: list[str]
    selected_products: list[RProductCandidate]
    supplier_data: list[dict[str, Any]]
    budget_usage: dict[str, Any]
    crawl_count: int
    crawl_records: list[dict[str, Any]] = Field(default_factory=list)
    reason_outputs: list[dict[str, Any]]
    decision_outputs: list[dict[str, Any]]
    save_remove_logs: list[dict[str, Any]]
    rejected_candidates: list[dict[str, Any]] = Field(default_factory=list)
    storage: dict[str, Any] = Field(default_factory=dict)
    scope_guard: dict[str, Any] = Field(default_factory=dict)


class RCommerceReviewRequest(BaseModel):
    action: Literal["Save", "Remove", "save", "remove"]
    product: RProductCandidate


class RCommerceReviewResponse(BaseModel):
    status: Literal["saved", "removed"]
    log: dict[str, Any]
    database_path: str
    report_path: str


class RCommerceReportResponse(BaseModel):
    report: dict[str, Any]


class RCommerceSkillResponse(BaseModel):
    engine: str
    engine_version: str
    organization_id: str
    organization_name: str
    provider_mode: Literal["mock"]
    required_skills: list[str]
    skills: dict[str, Any]
