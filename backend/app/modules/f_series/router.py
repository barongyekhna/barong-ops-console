"""F 类目富化控制面 API。

树浏览/搜索（带 F 标记层统计）→ 选段发起富化运行（Serper 关键词收割）→
关键词与候选池审核 → 人工放行的候选一键进 K。全部人用端点，
鉴权照 P 系列口径：owner / super_admin 放行，否则需持有对应 f.enrichment.* 权限。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from r_system_v2.ra.quota_ledger import (
    PROVIDER_F_1688_APP_CALLS,
    PROVIDER_F_1688_IMAGE_SEARCH,
    PROVIDER_SERPER,
    usage_today,
)

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.permission_service import resolve_current_user_permission_info
from .enrichment import constants as C
from .enrichment import images
from .enrichment import profiles as profile_engine
from .enrichment import runs as run_engine
from .enrichment import service
from .enrichment.models import (
    FCategoryCandidate,
    FCategoryKeyword,
    FEnrichmentRun,
    FProductMarketRef,
)

router = APIRouter(prefix="/f", tags=["f-enrichment"])


def _require_f_permission(permission_key: str):
    """owner / super_admin 放行；execute / review 隐含 read。"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key == C.PERMISSION_READ:
            allowed_keys.update({C.PERMISSION_EXECUTE, C.PERMISSION_REVIEW})
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


# --------------------------------------------------------------- schemas


class TreeNode(BaseModel):
    id: str
    name: str
    name_zh: str | None = None
    full_path: str
    level: int
    is_leaf: bool
    children_count: int = 0
    keywords_count: int = 0
    candidates_count: int = 0


class ProfileProduct(BaseModel):
    en: str
    zh: str
    note_zh: str


class ProfileResponse(BaseModel):
    category_id: str
    exists: bool
    products: list[ProfileProduct] = []


class TreeResponse(BaseModel):
    parent_id: str | None
    items: list[TreeNode]


class RunCreateRequest(BaseModel):
    category_ids: list[str] = Field(min_length=1, max_length=50)
    # full = 爬词+1688找货（默认一键全链）；keywords_only；sourcing_only（只补货源）
    mode: str = Field(default="full", pattern="^(full|keywords_only|sourcing_only)$")


class RunItem(BaseModel):
    run_id: str
    status: str
    mode: str
    categories_total: int
    categories_done: int
    keywords_found: int
    serper_calls: int
    candidates_found: int
    alibaba_calls: int
    selection: list[dict[str, Any]]
    error: str | None
    requested_by: str | None
    created_at: str | None
    finished_at: str | None


class RunsResponse(BaseModel):
    runs: list[RunItem]


class KeywordItem(BaseModel):
    id: str
    category_id: str
    category_path: str
    keyword_text: str
    keyword_type: str
    rank: int | None
    status: str


class KeywordsResponse(BaseModel):
    items: list[KeywordItem]
    total: int


class KeywordReviewRequest(BaseModel):
    status: str = Field(pattern="^(candidate|approved|rejected)$")


class CandidateCreateRequest(BaseModel):
    category_id: str
    title: str = Field(min_length=1, max_length=512)
    source_url: str | None = Field(default=None, max_length=2048)
    image_url: str | None = Field(default=None, max_length=2048)
    price_cny: Decimal | None = None
    moq: int | None = Field(default=None, ge=0)
    supplier_name: str | None = Field(default=None, max_length=255)
    weight_note: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CandidateItem(BaseModel):
    id: str
    category_id: str
    category_path: str
    title: str
    source: str
    source_url: str | None
    image_url: str | None
    price_cny: str | None
    moq: int | None
    supplier_name: str | None
    weight_note: str | None
    red_flags: list[dict[str, str]]
    automation_blocked: bool
    status: str
    notes: str | None
    profile_product_zh: str | None
    profile_product_en: str | None
    score: int | None
    score_json: dict[str, Any] | None
    recommended_rank: int | None
    k_product_id: str | None
    created_at: str | None


class CandidatesResponse(BaseModel):
    items: list[CandidateItem]
    total: int


class CandidateReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject|reopen)$")
    notes: str | None = None


class ImportToKResponse(BaseModel):
    product_id: str
    deduped: bool


# --------------------------------------------------------------- helpers


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _run_item(run: FEnrichmentRun) -> RunItem:
    return RunItem(
        run_id=str(run.id),
        status=run.status,
        mode=run.mode,
        categories_total=run.categories_total,
        categories_done=run.categories_done,
        keywords_found=run.keywords_found,
        serper_calls=run.serper_calls,
        candidates_found=run.candidates_found,
        alibaba_calls=run.alibaba_calls,
        selection=list(run.selection_json or [])[:20],
        error=run.error,
        requested_by=run.requested_by_username,
        created_at=_iso(run.created_at),
        finished_at=_iso(run.finished_at),
    )


def _candidate_item(candidate: FCategoryCandidate) -> CandidateItem:
    return CandidateItem(
        id=str(candidate.id),
        category_id=candidate.category_id,
        category_path=candidate.category_path,
        title=candidate.title,
        source=candidate.source,
        source_url=candidate.source_url,
        image_url=candidate.image_url,
        price_cny=str(candidate.price_cny) if candidate.price_cny is not None else None,
        moq=candidate.moq,
        supplier_name=candidate.supplier_name,
        weight_note=candidate.weight_note,
        red_flags=list(candidate.red_flags_json or []),
        automation_blocked=candidate.automation_blocked,
        status=candidate.status,
        notes=candidate.notes,
        profile_product_zh=candidate.profile_product_zh,
        profile_product_en=candidate.profile_product_en,
        score=candidate.score,
        score_json=dict(candidate.score_json) if candidate.score_json else None,
        recommended_rank=candidate.recommended_rank,
        k_product_id=str(candidate.k_product_id) if candidate.k_product_id else None,
        created_at=_iso(candidate.created_at),
    )


# --------------------------------------------------------------- endpoints


@router.get("/categories/tree", response_model=TreeResponse)
def f_categories_tree(
    parent_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> TreeResponse:
    """谷歌树逐层下钻（共享 K 的树），每个节点带 F 富化统计 = F 标记层。"""
    del user
    items = service.browse_tree(db, parent_id)
    return TreeResponse(
        parent_id=parent_id,
        items=[TreeNode(**item) for item in items],
    )


@router.get("/categories/search", response_model=TreeResponse)
def f_categories_search(
    q: str = "",
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> TreeResponse:
    del user
    items = service.search_tree(db, q, limit=limit)
    for item in items:
        item.setdefault("children_count", 0)
    return TreeResponse(parent_id=None, items=[TreeNode(**item) for item in items])


@router.get("/categories/{category_id}/profile", response_model=ProfileResponse)
def f_category_profile_get(
    category_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> ProfileResponse:
    """读类目产品画像缓存；没有缓存时 exists=false（前端显示生成按钮）。"""
    del user
    cached = profile_engine.get_profile(db, category_id)
    if cached is None:
        return ProfileResponse(category_id=category_id, exists=False)
    return ProfileResponse(
        category_id=category_id,
        exists=True,
        products=[ProfileProduct(**item) for item in (cached.products_json or [])],
    )


@router.post("/categories/{category_id}/profile", response_model=ProfileResponse)
def f_category_profile_generate(
    category_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_EXECUTE)),
) -> ProfileResponse:
    """生成类目产品画像（DeepSeek 一次、缓存永久；已有缓存直接返回）。"""
    del user
    node = service.category_node(db, category_id)
    if node is None:
        raise HTTPException(status_code=404, detail="类目不存在。")
    org_id = run_engine._target_org_id(db)
    if not org_id:
        raise HTTPException(status_code=409, detail="目标组织不存在。")
    try:
        profile = profile_engine.ensure_profile(
            db,
            category_id=str(node["id"]),
            category_path=str(node["full_path"]),
            name_zh=(str(node["name_zh"]) if node.get("name_zh") else None),
            org_id=org_id,
        )
    except profile_engine.FProfileUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ProfileResponse(
        category_id=category_id,
        exists=True,
        products=[ProfileProduct(**item) for item in (profile.products_json or [])],
    )


@router.post("/runs", response_model=RunItem, status_code=status.HTTP_201_CREATED)
def f_run_create(
    payload: RunCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_EXECUTE)),
) -> RunItem:
    """选段发起富化运行：展开子树 → 逐类目 Serper 收割 (+1688 找货)。"""
    try:
        run, _nodes = run_engine.create_run(
            db, category_ids=payload.category_ids, user=user, mode=payload.mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    run_engine.start_run(run.id)
    db.refresh(run)
    return _run_item(run)


@router.get("/runs", response_model=RunsResponse)
def f_runs_list(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> RunsResponse:
    del user
    run_engine.reap_stale_runs(db)
    db.commit()
    runs = db.scalars(
        select(FEnrichmentRun).order_by(FEnrichmentRun.created_at.desc()).limit(limit)
    ).all()
    return RunsResponse(runs=[_run_item(run) for run in runs])


@router.get("/runs/{run_id}", response_model=RunItem)
def f_run_get(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> RunItem:
    del user
    run = db.get(FEnrichmentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在。")
    return _run_item(run)


@router.get("/keywords", response_model=KeywordsResponse)
def f_keywords_list(
    category_id: str | None = Query(default=None),
    run_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> KeywordsResponse:
    del user
    query = select(FCategoryKeyword)
    if category_id:
        query = query.where(FCategoryKeyword.category_id == category_id)
    if run_id:
        query = query.where(FCategoryKeyword.run_id == run_id)
    if status_filter:
        query = query.where(FCategoryKeyword.status == status_filter)
    rows = db.scalars(
        query.order_by(
            FCategoryKeyword.category_path.asc(),
            FCategoryKeyword.keyword_type.asc(),
            FCategoryKeyword.rank.asc().nulls_last(),
        ).limit(limit)
    ).all()
    return KeywordsResponse(
        items=[
            KeywordItem(
                id=str(row.id),
                category_id=row.category_id,
                category_path=row.category_path,
                keyword_text=row.keyword_text,
                keyword_type=row.keyword_type,
                rank=row.rank,
                status=row.status,
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.patch("/keywords/{keyword_id}", response_model=KeywordItem)
def f_keyword_review(
    keyword_id: UUID,
    payload: KeywordReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_REVIEW)),
) -> KeywordItem:
    row = db.get(FCategoryKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=404, detail="关键词不存在。")
    row.status = payload.status
    row.reviewed_by_user_id = user.id
    db.commit()
    return KeywordItem(
        id=str(row.id),
        category_id=row.category_id,
        category_path=row.category_path,
        keyword_text=row.keyword_text,
        keyword_type=row.keyword_type,
        rank=row.rank,
        status=row.status,
    )


@router.get("/candidates", response_model=CandidatesResponse)
def f_candidates_list(
    category_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> CandidatesResponse:
    del user
    query = select(FCategoryCandidate)
    if category_id:
        query = query.where(FCategoryCandidate.category_id == category_id)
    if status_filter:
        query = query.where(FCategoryCandidate.status == status_filter)
    rows = db.scalars(
        query.order_by(FCategoryCandidate.created_at.desc()).limit(limit)
    ).all()
    return CandidatesResponse(
        items=[_candidate_item(row) for row in rows],
        total=len(rows),
    )


@router.get("/categories/{category_id}/market-refs")
def f_market_refs(
    category_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    """市场参考页（按画像产品分组）：竞品怎么定价/怎么配变体，组头展示。

    用户硬规则：独立站排平台前面（独立站可多至 6 条，平台只是补位）。
    """
    del user
    rows = db.scalars(
        select(FProductMarketRef)
        .where(FProductMarketRef.category_id == category_id)
        .order_by(FProductMarketRef.created_at.desc())
        .limit(400)
    ).all()
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = groups.setdefault(row.profile_product_zh, [])
        if len(bucket) >= 6:
            continue
        bucket.append(
            {
                "title": row.title,
                "page_url": row.page_url,
                "source_domain": row.source_domain,
                "site_type": row.site_type,
            }
        )
    order = {"independent": 0, "platform": 1, "content": 2}
    for bucket in groups.values():
        bucket.sort(key=lambda ref: order.get(str(ref.get("site_type")), 1))
    return {"category_id": category_id, "groups": groups}


@router.get("/candidates/{candidate_id}/image")
def f_candidate_image(
    candidate_id: UUID,
    variant: str = Query(default="thumb", pattern="^(thumb|full)$"),
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> Response:
    """候选图片代理：服务端回源阿里 CDN（绕防盗链）+ 磁盘缓存提速。

    thumb=310px 缩略图（列表）；full=原图（悬浮放大预览 / K 参考图）。
    """
    del user
    candidate = db.get(FCategoryCandidate, candidate_id)
    if candidate is None or not candidate.image_url:
        raise HTTPException(status_code=404, detail="候选或其图源不存在。")
    try:
        data, media_type = images.get_candidate_image(
            str(candidate.id), candidate.image_url, variant
        )
    except images.FImageUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=604800, immutable"},
    )


@router.post(
    "/candidates",
    response_model=CandidateItem,
    status_code=status.HTTP_201_CREATED,
)
def f_candidate_create(
    payload: CandidateCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_REVIEW)),
) -> CandidateItem:
    """过渡期人工贴 1688 链接建候选；1688 API 过审后自动填充走同一张表。"""
    try:
        candidate = service.create_candidate(
            db,
            category_id=payload.category_id,
            title=payload.title,
            user=user,
            source_url=payload.source_url,
            image_url=payload.image_url,
            price_cny=payload.price_cny,
            moq=payload.moq,
            supplier_name=payload.supplier_name,
            weight_note=payload.weight_note,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _candidate_item(candidate)


@router.patch("/candidates/{candidate_id}", response_model=CandidateItem)
def f_candidate_review(
    candidate_id: UUID,
    payload: CandidateReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_REVIEW)),
) -> CandidateItem:
    """人工审核：approve = 放行（红线候选的唯一出口）/ reject / reopen。"""
    candidate = db.get(FCategoryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选不存在。")
    if candidate.status == "imported_to_k":
        raise HTTPException(status_code=409, detail="候选已进 K，不能再改状态。")
    candidate.status = {
        "approve": "approved",
        "reject": "rejected",
        "reopen": "pending_review",
    }[payload.action]
    if payload.notes is not None:
        candidate.notes = payload.notes or None
    candidate.reviewed_by_user_id = user.id
    db.commit()
    return _candidate_item(candidate)


@router.post("/candidates/{candidate_id}/import-to-k", response_model=ImportToKResponse)
def f_candidate_import_to_k(
    candidate_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_REVIEW)),
) -> ImportToKResponse:
    """人工放行的候选搬进 K（channel=dtc、直绑谷歌类目）→ 走 K→I→P 现成链。"""
    candidate = db.get(FCategoryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选不存在。")
    try:
        result = service.import_candidate_to_k(db, candidate=candidate, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ImportToKResponse(**result)


@router.get("/quota")
def f_quota(
    db: Session = Depends(get_db),
    user: User = Depends(_require_f_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    """F 关心的三条额度（serper 共账、1688 词搜与 CPS 图搜为 F 独立闸）。"""
    del user
    # 额度台账是全局计数器（无 org 列），豁免 C18G 裸 SQL 隔离检查。
    with without_org_data_isolation():
        payload = usage_today(db)
    return {
        "serper": payload.get(PROVIDER_SERPER),
        "alibaba1688_app_calls": payload.get(PROVIDER_F_1688_APP_CALLS),
        "cps_image_search": payload.get(PROVIDER_F_1688_IMAGE_SEARCH),
    }
