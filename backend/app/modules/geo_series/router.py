"""GEO content engine control-plane API.

List / create topic clusters (from a K product or a category), trigger content
generation (queued to the geo-worker), and review the generated AI-citable items.
All human endpoints; auth mirrors P/F: owner / super_admin pass, otherwise the
caller needs the matching ``geo.content.*`` permission. Milestone 1 = review only;
publishing (a dedicated n8n flow) is milestone 2.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_WORKSPACE_KEY,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext
from .content import constants as C
from .content import service
from .content.analysis import analyze_item
from .content.assemble import cluster_products, load_cluster_items
from .content.publish_gate import (
    cluster_publish_state,
    publish_blockers,
    publishable_items,
)
from .monitor.probe import normalize_question, probe_candidates, terrain_by_question
from .monitor.seed import seed_from_cluster
from .monitor.service import MonitorError, run_sweep
from .monitor.state import monitor_state
from .content.backlink_jobs import create_backlink_job
from .content.backlink_jobs import jobs_recent as backlink_jobs_recent
from .content.backlink_targets import collect_backlink_targets
from .content.publish_jobs import create_publish_job, jobs_for_cluster
from ...modules.content_core.critique import (
    collect_critiques,
    collect_data_gaps,
    summarize_patterns,
)
from .content.generation_jobs import enqueue_geo_jobs, jobs_status
from .content.orchestrator import GeoContentError, GeoContentOrchestrator
from .content.topic_sourcing import list_topic_candidates

router = APIRouter(prefix="/geo", tags=["geo-content"])


def _require_geo_permission(permission_key: str):
    """owner / super_admin pass; execute / manage imply read."""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key == C.PERMISSION_READ:
            allowed_keys.update({C.PERMISSION_EXECUTE, C.PERMISSION_MANAGE})
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


def _public_base() -> str:
    import os

    return os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")


def _scope_context(request: Request | None) -> KScopeContext:
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    workspace_key = str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY
    return KScopeContext(
        workspace_key=workspace_key,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


# --------------------------------------------------------------- schemas


class CreateClusterRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    topic: str | None = None
    google_category_id: str | None = None
    category_path: str | None = None
    seed_product_id: UUID | None = None


class CreateClusterFromProductRequest(BaseModel):
    product_id: UUID


class ReviewItemRequest(BaseModel):
    review_status: str = Field(pattern="^(pending|approved|rejected)$")


class PickedQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=512)
    intent: str | None = None


class PickedQuestionsRequest(BaseModel):
    questions: list[PickedQuestion] = Field(default_factory=list)


# --------------------------------------------------------------- endpoints


@router.get("/clusters")
def geo_list_clusters(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    clusters = service.list_clusters(db, scope_context=scope)
    counts = service.cluster_item_counts(
        db, cluster_ids=[c.id for c in clusters]
    )
    return {
        "clusters": [
            {
                **service.serialize_cluster(c),
                "item_count": counts.get(str(c.id), 0),
            }
            for c in clusters
        ]
    }


@router.post("/clusters", status_code=status.HTTP_201_CREATED)
def geo_create_cluster(
    payload: CreateClusterRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    scope = _scope_context(request)
    cluster = service.create_cluster(
        db,
        scope_context=scope,
        title=payload.title,
        topic=payload.topic,
        google_category_id=payload.google_category_id,
        category_path=payload.category_path,
        seed_product_id=payload.seed_product_id,
        user=user,
    )
    db.commit()
    return service.serialize_cluster(cluster)


@router.post("/clusters/from-product", status_code=status.HTTP_201_CREATED)
def geo_create_cluster_from_product(
    payload: CreateClusterFromProductRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    scope = _scope_context(request)
    try:
        cluster = service.create_cluster_from_product(
            db, product_id=payload.product_id, scope_context=scope, user=user
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return service.serialize_cluster(cluster)


@router.get("/clusters/{cluster_id}")
def geo_get_cluster(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    items = service.list_items(db, cluster_id=cluster_id, scope_context=scope)
    labels = service.product_label_map(db, cluster=cluster)
    return {
        "cluster": service.serialize_cluster(cluster),
        "items": [
            service.serialize_item(i, product_labels=labels) for i in items
        ],
        "products": service.cluster_products(db, cluster=cluster),
    }


@router.get("/clusters/{cluster_id}/topic-candidates")
def geo_topic_candidates(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    candidates = list_topic_candidates(db, cluster=cluster, scope_context=scope)
    # 阵地数据挂到候选上:选题时就能看见"这条打不打得动",
    # 而不是写完发布了才发现前排全是守门人榜单(2026-07-29 首轮监测的教训)。
    terrain = terrain_by_question(db, cluster_id=cluster_id)
    for candidate in candidates:
        reading = terrain.get(normalize_question(str(candidate.get("question") or "")))
        candidate["terrain"] = reading or None
    return {"candidates": candidates, "picked": cluster.picked_questions_json or []}


@router.post("/clusters/{cluster_id}/topic-terrain")
def geo_probe_topic_terrain(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Check the search terrain of this cluster's topic candidates.

    Metered and cached: a candidate read within the last week is not re-checked,
    and one press probes at most MAX_PROBE_PER_CALL new questions.
    """
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    candidates = list_topic_candidates(db, cluster=cluster, scope_context=scope)
    questions = [str(c.get("question") or "") for c in candidates]
    try:
        outcome = probe_candidates(
            db,
            cluster_id=cluster_id,
            questions=questions,
            scope_context=scope,
            user=user,
        )
    except MonitorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return outcome


@router.post("/clusters/{cluster_id}/picked-questions")
def geo_save_picked_questions(
    cluster_id: UUID,
    payload: PickedQuestionsRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    scope = _scope_context(request)
    cluster = service.save_picked_questions(
        db,
        cluster_id=cluster_id,
        scope_context=scope,
        questions=[q.model_dump() for q in payload.questions],
        user=user,
    )
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    db.commit()
    return service.serialize_cluster(cluster)


@router.post("/clusters/{cluster_id}/generate")
def geo_generate_cluster(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    batch_id, jobs = enqueue_geo_jobs(
        db, cluster_ids=[cluster_id], user=user, scope_context=scope
    )
    db.commit()
    return {"batch_id": str(batch_id), "jobs": jobs}


@router.get("/clusters/{cluster_id}/jobs")
def geo_cluster_jobs(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    del user, request
    return {"jobs": jobs_status(db, cluster_id=cluster_id)}


@router.post("/clusters/{cluster_id}/products/{product_id}/spotlight")
def geo_generate_product_spotlight(
    cluster_id: UUID,
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Opt-in: give a differentiated product its own article inside this cluster."""
    scope = _scope_context(request)
    try:
        item = GeoContentOrchestrator(db).generate_product_spotlight(
            cluster_id=cluster_id,
            product_id=product_id,
            scope_context=scope,
            user=user,
        )
    except GeoContentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    return service.serialize_item(item)


@router.post("/clusters/{cluster_id}/publish")
def geo_publish_cluster(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Send this cluster's APPROVED guides to the site (drafts, for your final say)."""
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    items = load_cluster_items(db, cluster_id=cluster_id, scope_context=scope)
    products = cluster_products(db, cluster=cluster, scope_context=scope)
    blockers = publish_blockers(db, cluster=cluster, items=items, products=products)
    if blockers:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )
    job = create_publish_job(
        db,
        cluster_id=cluster_id,
        scope_context=scope,
        user=user,
        public_base=_public_base(),
    )
    db.commit()
    return {
        "job_id": job.job_id,
        "status": job.status,
        "dispatched": job.status == "dispatched",
        "article_count": len(publishable_items(items)),
    }


@router.get("/clusters/{cluster_id}/publishes")
def geo_publish_ledger(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    items = load_cluster_items(db, cluster_id=cluster_id, scope_context=scope)
    products = cluster_products(db, cluster=cluster, scope_context=scope)
    return {
        "jobs": jobs_for_cluster(db, cluster_id=cluster_id),
        **cluster_publish_state(
            db, cluster=cluster, items=items, products=products
        ),
    }


@router.get("/clusters/{cluster_id}/critique-summary")
def geo_critique_summary(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    """Where the module — not one article — needs fixing.

    ``patterns`` = critiques recurring across pieces, i.e. defects in the writing
    rules themselves. ``data_gaps`` = critiques no rewrite can honour because the
    fact is missing from K; fill those at the source.
    """
    scope = _scope_context(request)
    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")
    items = service.list_items(db, cluster_id=cluster_id, scope_context=scope)
    critiques = collect_critiques(items)
    data_gaps = collect_data_gaps(items)
    # Release the read transaction before the summary call (idle-in-txn rule).
    topic = cluster.topic or cluster.title
    db.commit()
    patterns = summarize_patterns(critiques, topic=topic, user=user)
    return {
        "critique_count": len(critiques),
        "patterns": patterns,
        "data_gaps": data_gaps,
        "critiques": critiques,
    }


@router.post("/items/{item_id}/revise")
def geo_revise_item(
    item_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Rewrite this piece against its critique — never by inventing facts.

    Critiques that would require data we do not have come back as `unaddressed`
    with the missing fact named, so they surface as K data gaps instead.
    """
    scope = _scope_context(request)
    try:
        item = GeoContentOrchestrator(db).revise_item(
            item_id=item_id, scope_context=scope, user=user
        )
    except GeoContentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    cluster = service.get_cluster(
        db, cluster_id=item.cluster_id, scope_context=scope
    )
    labels = (
        service.product_label_map(db, cluster=cluster) if cluster is not None else {}
    )
    return service.serialize_item(item, product_labels=labels)


@router.post("/items/{item_id}/analyze")
def geo_analyze_item(
    item_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """(Re)run the DeepSeek-flash reading aid for one piece.

    New content is analysed automatically; this covers pieces generated before
    the feature existed, or a retry when the provider was down.
    """
    scope = _scope_context(request)
    item = service.get_item(db, item_id=item_id, scope_context=scope)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    cluster = service.get_cluster(
        db, cluster_id=item.cluster_id, scope_context=scope
    )
    topic = (cluster.topic or cluster.title) if cluster else ""
    result = analyze_item(item, topic=topic, user=user)
    if result is None:
        raise HTTPException(
            status_code=502, detail="内容解读暂时不可用（DeepSeek 未返回可用结果）。"
        )
    item.analysis_json = result
    db.commit()
    labels = (
        service.product_label_map(db, cluster=cluster) if cluster is not None else {}
    )
    return service.serialize_item(item, product_labels=labels)


@router.post("/items/{item_id}/review")
def geo_review_item(
    item_id: UUID,
    payload: ReviewItemRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    scope = _scope_context(request)
    try:
        item = service.set_item_review(
            db,
            item_id=item_id,
            scope_context=scope,
            review_status=payload.review_status,
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.commit()
    return service.serialize_item(item)


# Surface GeoContentError (raised in the worker, but also usable synchronously)
# as a clean HTTP error if any endpoint ever calls the orchestrator directly.
__all__ = ["router", "GeoContentError"]


@router.get("/backlinks")
def geo_backlink_state(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    """What a backlink run would do right now, plus the recent ledger."""
    targets, skipped = collect_backlink_targets(db)
    return {
        "ready": bool(targets),
        "target_count": len(targets),
        "targets": [
            {
                "sku": t.get("sku"),
                "woo_product_id": t.get("woo_product_id"),
                "guide_count": t.get("guide_count"),
            }
            for t in targets
        ],
        "skipped": skipped,
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status,
                "error": j.error,
                "updated_count": len(j.updated_items_json or []),
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in backlink_jobs_recent(db)
        ],
    }


@router.post("/backlinks")
def geo_backlink_dispatch(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Refresh the 'Learn more' block on every live product page that has guides.

    Owner's ruling (2026-07-29): this is a button, not an automatic side effect of
    publishing — product pages are paid-traffic landing pages, so a human decides
    when they change.
    """
    scope = _scope_context(request)
    targets, skipped = collect_backlink_targets(db)
    if not targets:
        raise HTTPException(
            status_code=409,
            detail={
                "ready": False,
                "blockers": skipped
                or ["没有需要更新的产品页——先发布指南，或先把产品上架。"],
            },
        )
    job = create_backlink_job(
        db,
        scope_context=scope,
        targets=targets,
        user=user,
        public_base=_public_base(),
    )
    db.commit()
    return {
        "job_id": job.job_id,
        "status": job.status,
        "dispatched": job.status == "dispatched",
        "target_count": len(targets),
        "skipped": skipped,
    }


# ------------------------------------------------------------------ 里程碑4
# 阵地监测:买家问句的自然搜索结果——我们排第几、谁在占位、软不软。


@router.get("/monitor")
def geo_monitor_state(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_READ)),
) -> dict[str, Any]:
    """Watch list + the latest observation for each question."""
    scope = _scope_context(request)
    return monitor_state(db, scope_context=scope)


@router.post("/monitor/seed-from-cluster/{cluster_id}")
def geo_monitor_seed(
    cluster_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Import this cluster's chosen buyer questions into the watch list."""
    scope = _scope_context(request)
    added, skipped = seed_from_cluster(db, cluster_id=cluster_id, scope_context=scope)
    db.commit()
    return {"added": added, "skipped": skipped}


@router.post("/monitor/run")
def geo_monitor_run(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_geo_permission(C.PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    """Check every watched question once. Metered against the GEO monitor budget."""
    scope = _scope_context(request)
    try:
        run = run_sweep(db, scope_context=scope, user=user)
    except MonitorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": str(run.id),
        "status": run.status,
        "question_count": run.question_count,
        "checked_count": run.checked_count,
        "error": run.error,
    }
