from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from ...api.deps import get_audit_context, get_current_user
from ...db.session import get_db
from ...models.user import User
from .conversation_schemas import (
    ConversationDetail,
    ConversationPage,
    ConversationSettingsUpdateRequest,
    ConversationSettingsView,
    DirectConversationCreateRequest,
    GroupCreateRequest,
    GroupDeleteResponse,
    GroupLeaveResponse,
    GroupMembersAddRequest,
    GroupOwnerTransferRequest,
    GroupUpdateRequest,
)
from .conversation_service import (
    C19ConversationControlError,
    add_group_members,
    create_direct_conversation,
    create_group,
    delete_group,
    get_conversation_detail,
    get_settings,
    leave_group,
    list_conversations,
    remove_group_member,
    transfer_group_owner,
    update_group,
    update_settings,
)


router = APIRouter(prefix="/c19", tags=["c19-conversation-control"])
ConversationIdPath = Annotated[str, Path(min_length=1, max_length=64)]
UserIdPath = Annotated[int, Path(gt=0)]


def _raise_control_error(exc: C19ConversationControlError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from None


@router.get("/conversations", response_model=ConversationPage)
def conversation_list(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationPage:
    try:
        return list_conversations(
            db,
            actor=actor,
            limit=limit,
            offset=offset,
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.post("/conversations/direct", response_model=ConversationDetail)
def direct_conversation_create(
    payload: DirectConversationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return create_direct_conversation(
            db,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.get(
    "/conversations/{conversation_id}/settings",
    response_model=ConversationSettingsView,
)
def conversation_settings_get(
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationSettingsView:
    try:
        return get_settings(
            db,
            conversation_id=conversation_id,
            actor=actor,
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.patch(
    "/conversations/{conversation_id}/settings",
    response_model=ConversationSettingsView,
)
def conversation_settings_update(
    payload: ConversationSettingsUpdateRequest,
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationSettingsView:
    try:
        return update_settings(
            db,
            conversation_id=conversation_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation_detail(
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return get_conversation_detail(
            db,
            conversation_id=conversation_id,
            actor=actor,
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.post("/groups", response_model=ConversationDetail)
def group_create(
    payload: GroupCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return create_group(
            db,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.patch("/groups/{conversation_id}", response_model=ConversationDetail)
def group_update(
    payload: GroupUpdateRequest,
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return update_group(
            db,
            conversation_id=conversation_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.post(
    "/groups/{conversation_id}/members",
    response_model=ConversationDetail,
)
def group_members_add(
    payload: GroupMembersAddRequest,
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return add_group_members(
            db,
            conversation_id=conversation_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.delete(
    "/groups/{conversation_id}/members/{user_id}",
    response_model=ConversationDetail,
)
def group_member_remove(
    request: Request,
    conversation_id: ConversationIdPath,
    user_id: UserIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return remove_group_member(
            db,
            conversation_id=conversation_id,
            target_user_id=user_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.post(
    "/groups/{conversation_id}/leave",
    response_model=GroupLeaveResponse,
)
def group_leave(
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> GroupLeaveResponse:
    try:
        return leave_group(
            db,
            conversation_id=conversation_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.post(
    "/groups/{conversation_id}/transfer-owner",
    response_model=ConversationDetail,
)
def group_owner_transfer(
    payload: GroupOwnerTransferRequest,
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return transfer_group_owner(
            db,
            conversation_id=conversation_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


@router.delete("/groups/{conversation_id}", response_model=GroupDeleteResponse)
def group_delete(
    request: Request,
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> GroupDeleteResponse:
    try:
        return delete_group(
            db,
            conversation_id=conversation_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except C19ConversationControlError as exc:
        _raise_control_error(exc)


__all__ = ["router"]
