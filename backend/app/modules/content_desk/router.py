"""内容台 API。

权限模型:**进门看自己的键,动手看来源的键。**

内容台的写操作和 GEO/SEO 一样重(批准上线、花钱重写、派单发到 WordPress)。
如果只认 ``content.desk.*``,就等于开了一条**权限洗白通道**——只有内容台权限
的人可以做他在 ``/geo/*`` 上被 403 拦住的事。所以写操作要**两把钥匙**:
内容台的 + 该文章来源引擎的。来源键写在 ``sources.py`` 的声明式表里,
不散落在各个 handler 里,因为两边本来就不对称(见那张表)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
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
from .sources import ContentSource, UnknownSource

router = APIRouter(prefix="/content-desk", tags=["content-desk"])

_IMPLIED_BY = {
    "content.desk.read": (
        "content.desk.read",
        "content.desk.execute",
        "content.desk.manage",
    ),
    "content.desk.execute": ("content.desk.execute", "content.desk.manage"),
    "content.desk.manage": ("content.desk.manage",),
}


def require_desk_permission(permission_key: str):
    """内容台自己的门。owner / super_admin 直通;execute / manage 蕴含 read。

    **这只是进门。** 写操作还要再过一道来源引擎的键——见
    ``sources.py`` 与 ``_require_source_permission``。
    """

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(getattr(user, "role", None))
            or set(_IMPLIED_BY[permission_key]).intersection(
                permissions.permission_keys
            )
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少权限 {permission_key}。",
        )

    return dependency


def _scope(request: Request | None) -> KScopeContext:
    """与 GEO/SEO 同一套 scope 推导,好让三个入口看到同一批行。"""
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    return KScopeContext(
        workspace_key=str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


@router.get("/articles")
def list_articles(
    request: Request,
    queue: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.read")),
) -> dict[str, Any]:
    """归一化的文章列表。``?queue=review`` 拿**有序**待审队列——浮窗
    「批准，下一篇 →」靠顺序稳定,否则人会以为自己漏了一篇。"""
    from . import queries

    scope = _scope(request)
    if queue == "review":
        articles = queries.review_queue(db, scope=scope)
    else:
        articles = queries.list_articles(db, scope=scope)
    return {"articles": articles, "count": len(articles)}


@router.get("/articles/{source_key}/{item_id}")
def article_detail(
    source_key: str,
    item_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.read")),
) -> dict[str, Any]:
    from . import queries

    try:
        article = queries.article_detail(
            db, source_key=source_key, item_id=item_id, scope=_scope(request)
        )
    except UnknownSource as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if article is None:
        raise HTTPException(status_code=404, detail="这篇文章不存在。")
    return article


def _require_source_permission(
    request: Request,
    db: Session,
    user: User,
    source: ContentSource,
    permission_key: str,
) -> None:
    """**第二把钥匙:来源引擎自己的权限。**

    只认 ``content.desk.*`` 等于开一条权限洗白通道——只有内容台权限的人
    可以做他在 ``/geo/*`` 上被 403 拦住的事。owner / super_admin 直通。
    """
    permissions = resolve_current_user_permission_info(db, user, request=request)
    if permissions.is_owner_full_access or is_super_admin_role(
        getattr(user, "role", None)
    ):
        return
    # manage 蕴含 execute 蕴含 read,与两个引擎自己的判定同规。
    implied = {
        permission_key,
        permission_key.rsplit(".", 1)[0] + ".manage",
    }
    if permission_key.endswith(".read"):
        implied.add(permission_key.rsplit(".", 1)[0] + ".execute")
    if not implied.intersection(permissions.permission_keys):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少来源模块权限 {permission_key}。",
        )


def _load(
    db: Session, request: Request, source_key: str, item_id: str
) -> tuple[Any, Any, ContentSource]:
    from . import queries

    try:
        ref = queries.article_ref(
            db, source_key=source_key, item_id=item_id, scope=_scope(request)
        )
    except UnknownSource as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if ref is None:
        raise HTTPException(status_code=404, detail="这篇文章不存在。")
    return ref


def _detail(db: Session, request: Request, source_key: str, item_id: str) -> dict[str, Any]:
    from . import queries

    article = queries.article_detail(
        db, source_key=source_key, item_id=item_id, scope=_scope(request)
    )
    if article is None:
        raise HTTPException(status_code=404, detail="这篇文章不存在。")
    return article


class ReviewIn(BaseModel):
    review_status: str


@router.post("/articles/{source_key}/{item_id}/review")
def review_article(
    source_key: str,
    item_id: str,
    payload: ReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.execute")),
) -> dict[str, Any]:
    """批准 / 驳回。返回**完整 DTO**——GEO 老的 review 端点只返回裸 UUID 的
    product labels,前端做字段级 merge 会把 SKU 变成 UUID。"""
    from . import actions

    item, _parent, source = _load(db, request, source_key, item_id)
    _require_source_permission(request, db, user, source, source.review_permission)
    try:
        actions.set_review(
            db,
            item=item,
            source=source,
            review_status=payload.review_status,
            user=user,
        )
    except actions.DeskActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    return _detail(db, request, source_key, item_id)


@router.post("/articles/{source_key}/{item_id}/revise")
def revise_article(
    source_key: str,
    item_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.execute")),
) -> dict[str, Any]:
    """按批评重写。**同步**,两边都是。"""
    from . import actions

    item, _parent, source = _load(db, request, source_key, item_id)
    _require_source_permission(request, db, user, source, source.execute_permission)
    try:
        actions.revise(
            db, item=item, source=source, scope=_scope(request), user=user
        )
    except actions.DeskActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    # orchestrator 内部出网前 commit 过,但 attach_analysis_to 有「快照全空就
    # 早退不 commit」的分支;而且 commit 会 expire 对象,所以要重新查。
    db.commit()
    return _detail(db, request, source_key, item_id)


@router.post("/articles/{source_key}/{item_id}/analyze")
def analyze_article(
    source_key: str,
    item_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.execute")),
) -> dict[str, Any]:
    """(重新)跑 DeepSeek 解读。**同时补上 SEO 侧根本没有的入口**——
    没有它,解读失败的 SEO 文章就死锁了(重写要求 risks 非空)。"""
    from . import actions

    item, parent, source = _load(db, request, source_key, item_id)
    _require_source_permission(request, db, user, source, source.execute_permission)
    if not actions.analyze(db, item=item, source=source, parent=parent, user=user):
        raise HTTPException(
            status_code=502, detail="内容解读暂时不可用（DeepSeek 没返回可用结果）。"
        )
    return _detail(db, request, source_key, item_id)


class IgnoreIn(BaseModel):
    kind: str
    ignored: bool = True
    surface: str | None = None
    term: str | None = None
    number: str | None = None


@router.post("/articles/{source_key}/{item_id}/audit/ignore")
def ignore_finding(
    source_key: str,
    item_id: str,
    payload: IgnoreIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.manage")),
) -> dict[str, Any]:
    """把一条审查发现标成误报放行(或撤销),按放行后重算 clean。

    **前端传原始 finding 字段,指纹由后端算** —— 指纹不进网络,客户端伪造不了
    一个任意指纹把门禁绕过去(照 K 的做法)。放行要 manage,比批准高一档:
    放行是推翻门禁。
    """
    from sqlalchemy.orm.attributes import flag_modified

    from ..content_core.guards import (
        UnignorableFinding,
        assert_ignorable,
        content_finding_fingerprint,
        recompute_audit_clean,
    )

    item, _parent, source = _load(db, request, source_key, item_id)
    _require_source_permission(request, db, user, source, source.manage_permission)
    try:
        assert_ignorable(payload.kind)
    except UnignorableFinding as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fingerprint = content_finding_fingerprint(
        payload.kind,
        {"surface": payload.surface, "term": payload.term, "number": payload.number},
    )
    # dict(...) 复制 + flag_modified:JSON 列原地改 SQLAlchemy 检测不到(K 踩过)。
    audit = (
        dict(item.brand_audit_json)
        if isinstance(item.brand_audit_json, dict)
        else {}
    )
    if not audit:
        raise HTTPException(status_code=409, detail="这篇还没有审查记录，没有可放行的发现。")
    ignore_set = {str(fp) for fp in audit.get("ignored_findings") or []}
    if payload.ignored:
        ignore_set.add(fingerprint)
    else:
        ignore_set.discard(fingerprint)
    audit["ignored_findings"] = sorted(ignore_set)
    recompute_audit_clean(audit)
    item.brand_audit_json = audit
    flag_modified(item, "brand_audit_json")
    db.add(item)
    db.commit()
    return _detail(db, request, source_key, item_id)


@router.get("/overview")
def overview(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.read")),
) -> dict[str, Any]:
    """一次画完整页:四步导轨 + 待办 + 机器状态。步 5 填导轨与绿条。"""
    from . import queries

    counts = queries.step_counts(db, scope=_scope(request))
    return {"steps": [], "todos": [], "machine": [], "counts": counts, "ready": False}
