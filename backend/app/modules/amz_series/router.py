"""A 系列人用端点。全部挂 ``/api/app/amz``(只挂一次,A0 没有机器端点)。

门:整个 router 先过 ``require_amz_access``(owner 或至少一条店铺授权;super_admin 不直通),
店铺级端点再过 ``require_store(min_role)``。新加端点要同步登记前端代理白名单 ``isAllowedAmzPath``。
"""

from __future__ import annotations

from typing import Any

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from . import experience, fact_sheets, images, service, suggestions
from .constants import MODULE_KEY, STORE_ROLE_GRANT, STORE_ROLE_VIEW, STORE_ROLES
from .deps import StoreAccess, granted_store_codes, require_amz_access, require_store

router = APIRouter(prefix="/amz", tags=["amz-ops"], dependencies=[Depends(require_amz_access)])


def _raise(exc: service.AmzServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


# ---------------------------------------------------------------- 店铺


@router.get("/stores")
def stores_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    stores = service.list_visible_stores(db, store_codes=codes)
    summaries = service.store_summaries(db, stores=stores, user=user, is_owner=is_owner_role(user.role))
    return {
        "module_key": MODULE_KEY,
        "is_owner": is_owner_role(user.role),
        "items": [service.summary_view(item) for item in summaries],
    }


@router.get("/stores/{store_code}")
def store_detail(
    access: StoreAccess = Depends(require_store(STORE_ROLE_VIEW)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    summaries = service.store_summaries(
        db, stores=[access.store], user=access.user, is_owner=is_owner_role(access.user.role)
    )
    payload = service.summary_view(summaries[0])
    payload["seed_imports"] = [
        _seed_view(item) for item in service.list_seed_imports(db, store_codes=[access.store.store_code])
    ]
    return payload


# ---------------------------------------------------------------- 授权


class GrantUpsert(BaseModel):
    user_id: int = Field(ge=1)
    role: str = Field(pattern="^(" + "|".join(STORE_ROLES) + ")$")


def _grant_view(grant: Any) -> dict[str, Any]:
    return {
        "user_id": int(grant.user_id),
        "store_code": grant.store_code,
        "role": grant.role,
        "granted_by_user_id": grant.granted_by_user_id,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


@router.get("/stores/{store_code}/grants")
def grants_list(
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": [_grant_view(item) for item in service.list_grants(db, store_code=access.store.store_code)]}


@router.post("/stores/{store_code}/grants")
def grants_upsert(
    payload: GrantUpsert,
    request: Request,
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        grant = service.upsert_grant(
            db,
            store_code=access.store.store_code,
            user_id=payload.user_id,
            role=payload.role,
            granted_by=access.user,
        )
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(access.user.id),
        action="amz.grant.upsert",
        target_type="amz_store",
        target_id=access.store.store_code,
        result="success",
        request_id=_request_id(request),
        details={"user_id": payload.user_id, "role": payload.role},
    )
    db.commit()
    return _grant_view(grant)


@router.delete("/stores/{store_code}/grants/{user_id}")
def grants_delete(
    user_id: int,
    request: Request,
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    removed = service.delete_grant(db, store_code=access.store.store_code, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="grant not found")
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(access.user.id),
        action="amz.grant.delete",
        target_type="amz_store",
        target_id=access.store.store_code,
        result="success",
        request_id=_request_id(request),
        details={"user_id": user_id},
    )
    db.commit()
    return {"removed": True}


# ---------------------------------------------------------------- 种子 / 员工


def _seed_view(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "file_name": item.file_name,
        "store_code": item.store_code,
        "kind": item.kind,
        "rows": item.rows,
        "checksum": item.checksum,
        "details": item.details_json or {},
        "imported_at": item.imported_at.isoformat() if item.imported_at else None,
    }


@router.get("/seed-imports")
def seed_imports_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    return {"items": [_seed_view(item) for item in service.list_seed_imports(db, store_codes=codes)]}


@router.get("/employees")
def employees_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """员工面板:每人未读数、紧急数、最新一条消息(按调用者能看的店铺)。"""
    codes = granted_store_codes(db, user)
    return suggestions.employee_panel(db, store_codes=codes)


# ---------------------------------------------------------------- 建议(员工消息)


@router.get("/suggestions")
def suggestions_list(
    employee: str | None = Query(default=None, pattern="^[A-Da-d]$"),
    store: str | None = Query(default=None, pattern="^0\\d(?:us|de)$"),
    status: str = Query(default="open", pattern="^(open|approved|rejected|later|expired|executed|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    if store:
        if codes is not None and store not in codes:
            raise HTTPException(status_code=403, detail=f"no access to store {store}")
        codes = [store]
    rows = suggestions.list_suggestions(db, store_codes=codes, employee=employee, status=status)
    return {"items": [suggestions.suggestion_view(row) for row in rows], "shadow": True}


class DecidePayload(BaseModel):
    decision: str = Field(pattern="^(approve|reject|later)$")
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/suggestions/{suggestion_id}/decide")
def suggestions_decide(
    suggestion_id: UUID,
    payload: DecidePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """影子期:只记录你的判断(和驳回原因),不碰亚马逊。"""
    codes = granted_store_codes(db, user)
    try:
        row = suggestions.decide_suggestion(
            db,
            suggestion_id=suggestion_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=user,
            allowed_store_codes=codes,
            request_id=_request_id(request),
        )
    except service.AmzServiceError as exc:
        _raise(exc)
    db.commit()
    return suggestions.suggestion_view(row)


class FactSheetPayload(BaseModel):
    product_line: str = Field(min_length=1, max_length=32)
    store_code: str | None = Field(default=None, max_length=16)
    sku: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    facts: dict[str, Any] = Field(default_factory=dict)


def _can_write_sheets(db: Session, user: User, store_code: str | None) -> None:
    """跨店共用的表:owner 或任一店有「操作」;店级的表:那家店的「操作」。"""
    if is_owner_role(user.role):
        return
    from .models import AmzStoreGrant  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from .constants import STORE_ROLE_RANK, STORE_ROLE_OPERATE  # noqa: PLC0415

    rows = list(db.execute(select(AmzStoreGrant.store_code, AmzStoreGrant.role).where(AmzStoreGrant.user_id == int(user.id))).all())
    ok = any((store_code is None or code == store_code) and STORE_ROLE_RANK.get(role, 0) >= STORE_ROLE_RANK[STORE_ROLE_OPERATE] for code, role in rows)
    if not ok:
        raise HTTPException(status_code=403, detail="需要店铺「操作」角色才能改事实表。")


@router.get("/fact-sheets")
def fact_sheets_list(
    product_line: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    rows = fact_sheets.list_sheets(db, store_codes=codes, product_line=product_line)
    return {"items": [fact_sheets.view(r) for r in rows], "product_lines": list(fact_sheets.PRODUCT_LINES), "uses": fact_sheets.sufficiency.USE_LABELS}


@router.post("/fact-sheets")
def fact_sheets_upsert(
    payload: FactSheetPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """保存即代码判「够不够」(不出网);模型核对另点「判一下」。"""
    _can_write_sheets(db, user, (payload.store_code or "").strip().lower() or None)
    try:
        row = fact_sheets.upsert_sheet(db, product_line=payload.product_line, store_code=payload.store_code, sku=payload.sku, title=payload.title, facts=payload.facts, actor=user)
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.fact_sheet.save", target_type="amz_fact_sheet", target_id=str(row.id), result="success", request_id=_request_id(request), details={"product_line": row.product_line, "store_code": row.store_code, "version": row.version, "ready": row.sufficiency_json.get("ready")})
    db.commit()
    return fact_sheets.view(row)


@router.post("/fact-sheets/{sheet_id}/judge")
def fact_sheets_judge(
    sheet_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """代码清单 + DeepSeek 再读一遍(矛盾 / 追问)。模型挂了判定不变,只附一条错。"""
    try:
        row = fact_sheets.judge_sheet(db, sheet_id=sheet_id, with_model=True)
    except service.AmzServiceError as exc:
        _raise(exc)
    _can_write_sheets(db, user, row.store_code)
    db.commit()
    return fact_sheets.view(row)


# ---------------------------------------------------------------- 经验库(A4)


@router.get("/experience")
def experience_list(
    employee: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    rows = experience.list_entries(db, store_codes=codes, employee=employee)
    return {"items": [experience.view(r) for r in rows], "params": {name: {"default": spec[0], "cap": spec[2], "driven_by": spec[3]} for name, spec in experience.PARAMS.items()}}


# ---------------------------------------------------------------- 图片通道(A5):brief / 参考图 / 交稿 / 选定 / 上线


class BriefCreate(BaseModel):
    suggestion_id: UUID | None = None
    store_code: str | None = Field(default=None, max_length=16)
    position: str = Field(default="main", max_length=16)
    product_line: str | None = Field(default=None, max_length=32)
    sku: str | None = Field(default=None, max_length=128)
    asin: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=500)


class AssetDecide(BaseModel):
    decision: str = Field(pattern="^(choose|reject)$")
    reason: str | None = Field(default=None, max_length=500)


class BriefLive(BaseModel):
    live_on: str | None = Field(default=None, max_length=10)


def _brief_or_404(db: Session, user: User, brief_id: UUID, *, min_role: str = STORE_ROLE_VIEW) -> Any:
    from .constants import STORE_ROLE_RANK  # noqa: PLC0415

    brief = db.get(images.AmzImageBrief, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="brief not found")
    role = service.grant_role_for(db, user=user, store_code=brief.store_code, is_owner=is_owner_role(user.role))
    if STORE_ROLE_RANK.get(role, 0) < STORE_ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="no access to this store")
    return brief


@router.get("/images/briefs")
def image_briefs_list(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    rows = images.list_briefs(db, store_codes=codes, status=status)
    return {"items": [images.brief_view(r) for r in rows], "positions": images.POSITION_LABELS, "reference_kinds": images.REFERENCE_LABELS}


@router.post("/images/briefs")
def image_briefs_create(
    payload: BriefCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """从殷熊的「同屏输了」建议生成 brief,或手动建一份。事实表不够会拒(不够不画)。"""
    from .constants import STORE_ROLE_OPERATE, STORE_ROLE_RANK  # noqa: PLC0415

    try:
        if payload.suggestion_id is not None:
            row = db.get(images.AmzSuggestion, payload.suggestion_id)
            if row is None:
                raise HTTPException(status_code=404, detail="suggestion not found")
            store_code = row.store_code
        else:
            store_code = (payload.store_code or "").strip().lower()
            if not store_code:
                raise HTTPException(status_code=422, detail="store_code required")
        role = service.grant_role_for(db, user=user, store_code=store_code, is_owner=is_owner_role(user.role))
        if STORE_ROLE_RANK.get(role, 0) < STORE_ROLE_RANK[STORE_ROLE_OPERATE]:
            raise HTTPException(status_code=403, detail="需要店铺「操作」角色")
        if payload.suggestion_id is not None:
            brief = images.create_brief_from_suggestion(db, suggestion_id=payload.suggestion_id, actor=user)
        else:
            brief = images.create_brief(db, store_code=store_code, position=payload.position, actor=user, product_line=payload.product_line, sku=payload.sku, asin=payload.asin, title=payload.title, reason=payload.reason)
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.image.brief.create", target_type="amz_image_brief", target_id=str(brief.id), result="success", request_id=_request_id(request), details={"store_code": brief.store_code, "position": brief.position})
    db.commit()
    return images.brief_view(brief, with_md=True)


@router.get("/images/briefs/{brief_id}")
def image_brief_detail(brief_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    brief = _brief_or_404(db, user, brief_id)
    return {
        "brief": images.brief_view(brief, with_md=True),
        "references": [images.asset_view(a) for a in images.references(db, brief)],
        "submissions": [images.asset_view(a) for a in images.submissions(db, brief)],
        "codex_prompt": images.codex_prompt(brief),
    }


@router.post("/images/briefs/{brief_id}/references")
def image_brief_add_reference(
    brief_id: UUID,
    request: Request,
    kind: str = Form(...),
    note: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from .constants import STORE_ROLE_OPERATE  # noqa: PLC0415

    brief = _brief_or_404(db, user, brief_id, min_role=STORE_ROLE_OPERATE)
    try:
        asset = images.add_reference(db, brief=brief, kind=kind, contents=file.file.read(), note=note, actor=user)
    except service.AmzServiceError as exc:
        _raise(exc)
    db.commit()
    return images.asset_view(asset)


@router.post("/images/briefs/{brief_id}/submit")
def image_brief_submit(
    brief_id: UUID,
    request: Request,
    note: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """人手上传一张候选(和 Codex 经 MCP 交稿走同一条路、同四道门)。"""
    from .constants import STORE_ROLE_OPERATE  # noqa: PLC0415

    brief = _brief_or_404(db, user, brief_id, min_role=STORE_ROLE_OPERATE)
    try:
        asset = images.submit(db, brief=brief, contents=file.file.read(), note=note, submitted_via="upload", actor_user_id=int(user.id))
    except service.AmzServiceError as exc:
        _raise(exc)
    db.commit()
    return images.asset_view(asset)


@router.post("/images/assets/{asset_id}/decide")
def image_asset_decide(asset_id: UUID, payload: AssetDecide, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    from .constants import STORE_ROLE_OPERATE  # noqa: PLC0415

    asset = db.get(images.AmzImageAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    _brief_or_404(db, user, asset.brief_id, min_role=STORE_ROLE_OPERATE)
    try:
        asset = images.decide_asset(db, asset=asset, decision=payload.decision, reason=payload.reason, actor=user)
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action=f"amz.image.{payload.decision}", target_type="amz_image_asset", target_id=str(asset.id), result="success", request_id=_request_id(request), details={"reason": payload.reason})
    db.commit()
    return images.asset_view(asset)


@router.post("/images/briefs/{brief_id}/live")
def image_brief_live(brief_id: UUID, payload: BriefLive, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """人在亚马逊后台传完图后来点一下:记上线日和基线,14 / 28 天回看从这天算。"""
    from datetime import date as _date  # noqa: PLC0415

    from .constants import STORE_ROLE_OPERATE  # noqa: PLC0415

    brief = _brief_or_404(db, user, brief_id, min_role=STORE_ROLE_OPERATE)
    try:
        live_on = _date.fromisoformat(payload.live_on) if payload.live_on else None
        brief = images.mark_live(db, brief=brief, actor=user, live_on=live_on)
    except ValueError:
        raise HTTPException(status_code=422, detail="live_on 要是 YYYY-MM-DD") from None
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.image.live", target_type="amz_image_brief", target_id=str(brief.id), result="success", request_id=_request_id(request))
    db.commit()
    return images.brief_view(brief)


@router.get("/images/assets/{asset_id}/file")
def image_asset_file(asset_id: UUID, kind: str = Query(default="preview"), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    asset = db.get(images.AmzImageAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    _brief_or_404(db, user, asset.brief_id)
    if kind == "original":
        path = images.asset_path(asset)
        media_type = asset.mime_type
    else:
        path = images.derivative_path(asset, kind="thumbnail" if kind == "thumbnail" else "preview", max_side=320 if kind == "thumbnail" else 1280)
        media_type = "image/webp" if path.suffix == ".webp" else asset.mime_type
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing")
    response = FileResponse(path=path, content_disposition_type="inline", filename=path.name, media_type=media_type)
    response.headers["Cache-Control"] = "private, max-age=600"
    return response


# ---------------------------------------------------------------- 广告 API 授权(四家公司都走这条)


class AdsOauthStart(BaseModel):
    store_code: str = Field(min_length=4, max_length=16)
    client_id: str = Field(min_length=10, max_length=200)
    client_secret: str = Field(min_length=10, max_length=300)


class AdsOauthCallback(BaseModel):
    code: str = Field(min_length=1, max_length=500)
    state: str = Field(min_length=1, max_length=200)


@router.post("/ads/oauth/start")
def ads_oauth_start(
    payload: AdsOauthStart,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """存钥匙对(加密)、给授权链接。要店铺「授权」角色或 owner。"""
    from .clients import ads_oauth  # noqa: PLC0415
    from .constants import STORE_ROLE_RANK  # noqa: PLC0415

    store = db.get(service.AmzStore, payload.store_code.strip().lower())
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    role = service.grant_role_for(db, user=user, store_code=store.store_code, is_owner=is_owner_role(user.role))
    if STORE_ROLE_RANK.get(role, 0) < STORE_ROLE_RANK[STORE_ROLE_GRANT]:
        raise HTTPException(status_code=403, detail="需要店铺「授权」角色。")
    try:
        url = ads_oauth.start(db, store=store, client_id=payload.client_id, client_secret=payload.client_secret, actor_user_id=int(user.id))
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.ads.oauth.start", target_type="amz_store", target_id=store.store_code, result="success", request_id=_request_id(request))
    db.commit()
    return {"store_code": store.store_code, "authorize_url": url}


@router.post("/ads/oauth/callback")
def ads_oauth_callback(
    payload: AdsOauthCallback,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """授权码换令牌、拉 profile、存密钥。谁点的授权链接谁来收尾(同一个浏览器会话)。"""
    from .clients import ads_oauth  # noqa: PLC0415
    from .constants import STORE_ROLE_RANK  # noqa: PLC0415

    try:
        store_code = ads_oauth.parse_state(payload.state)
        role = service.grant_role_for(db, user=user, store_code=store_code, is_owner=is_owner_role(user.role))
        if STORE_ROLE_RANK.get(role, 0) < STORE_ROLE_RANK[STORE_ROLE_GRANT]:
            raise HTTPException(status_code=403, detail="需要店铺「授权」角色。")
        result = ads_oauth.complete(db, code=payload.code, state=payload.state, actor_user_id=int(user.id))
    except service.AmzServiceError as exc:
        db.rollback()
        create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.ads.oauth.complete", target_type="amz_store", target_id=payload.state.split(".")[0], result="failure", error_code=exc.code, request_id=_request_id(request), details={"error": str(exc)[:300]})
        db.commit()
        _raise(exc)
    create_operation_log(db, actor_type="user", actor_id=str(user.id), action="amz.ads.oauth.complete", target_type="amz_store", target_id=result["store_code"], result="success", request_id=_request_id(request), details={"profiles": result["profiles"], "key_id": result["key_id"]})
    db.commit()
    return result


@router.get("/overview/series")
def overview_series(
    store: str | None = Query(default=None, pattern="^0\\d(?:us|de)$"),
    days: int = Query(default=30, ge=7, le=120),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    if store:
        if codes is not None and store not in codes:
            raise HTTPException(status_code=403, detail=f"no access to store {store}")
        codes = [store]
    return suggestions.daily_series(db, store_codes=codes, days=days)


__all__ = ["router"]
