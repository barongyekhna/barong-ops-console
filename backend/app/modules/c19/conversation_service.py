from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models.c19 import (
    C19AffiliationRecord,
    C19ConversationMemberRecord,
    C19ConversationRecord,
    C19ConversationUserSettingRecord,
)
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from ...schemas.conversation import (
    generate_direct_conversation_id,
    generate_group_conversation_id,
)
from ...services.auth_service import AuditContext
from ...services.data_isolation import without_org_data_isolation
from .conversation_repository import (
    ConversationListRow,
    active_block_exists_across,
    active_block_exists_between,
    add_conversation,
    add_conversation_member,
    add_conversation_settings,
    get_conversation,
    get_conversation_member,
    get_conversation_settings,
    get_direct_conversation_by_pair,
    get_active_user,
    list_active_user_ids,
    list_actor_conversations,
    list_authorized_affiliations,
    list_conversation_members,
)
from .conversation_schemas import (
    ConversationDetail,
    ConversationMemberInput,
    ConversationMemberView,
    ConversationPage,
    ConversationSettingsUpdateRequest,
    ConversationSettingsView,
    ConversationSummary,
    DirectConversationCreateRequest,
    GroupCreateRequest,
    GroupDeleteResponse,
    GroupLeaveResponse,
    GroupMembersAddRequest,
    GroupOwnerTransferRequest,
    GroupUpdateRequest,
)
from .identity_sync_service import sync_profile_for_user


MAX_GROUP_PARTICIPANTS = 200


@dataclass(frozen=True, slots=True)
class ResolvedParticipant:
    user_id: int
    affiliation: C19AffiliationRecord | None


class C19ConversationControlError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error(code: str, message: str, status_code: int) -> C19ConversationControlError:
    return C19ConversationControlError(
        code=code,
        message=message,
        status_code=status_code,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user_id(actor: User) -> int:
    if not actor.is_active:
        raise _error(
            "c19_access_denied",
            "C19 access denied.",
            403,
        )
    try:
        actor_user_id = int(actor.id)
    except (TypeError, ValueError):
        raise _error(
            "c19_access_denied",
            "C19 access denied.",
            403,
        ) from None
    if actor_user_id <= 0:
        raise _error(
            "c19_access_denied",
            "C19 access denied.",
            403,
        )
    return actor_user_id


def _canonical_pair_key(first_user_id: int, second_user_id: int) -> str:
    low, high = sorted((first_user_id, second_user_id))
    if low == high:
        raise _error(
            "c19_invalid_participants",
            "Conversation participants must be distinct.",
            409,
        )
    return f"{low}:{high}"


def _resolve_participant(
    db: Session,
    *,
    user_id: int,
    requested_affiliation_id: str | None,
    for_update: bool = False,
) -> ResolvedParticipant:
    user = get_active_user(db, user_id=user_id, for_update=for_update)
    if user is None:
        raise _error(
            "c19_access_denied",
            "C19 access denied.",
            403,
        )
    sync_profile_for_user(db, user=user)
    # Affiliation is optional descriptive context.  Never infer one merely
    # because the user currently has exactly one organization membership.
    if requested_affiliation_id is None:
        return ResolvedParticipant(user_id=user_id, affiliation=None)
    affiliations = list_authorized_affiliations(
        db,
        user_id=user_id,
        for_update=for_update,
    )
    if requested_affiliation_id is not None:
        for affiliation in affiliations:
            if affiliation.affiliation_id == requested_affiliation_id:
                return ResolvedParticipant(
                    user_id=user_id,
                    affiliation=affiliation,
                )
        raise _error(
            "c19_access_denied",
            "C19 access denied.",
            403,
        )
    raise AssertionError("requested affiliation branch must return or raise")


def _deny_blocked_relationship() -> None:
    raise _error(
        "c19_relationship_access_denied",
        "Relationship access denied.",
        403,
    )


def _ensure_pair_not_blocked(
    db: Session,
    *,
    first_user_id: int,
    second_user_id: int,
) -> None:
    if active_block_exists_between(
        db,
        first_user_id=first_user_id,
        second_user_id=second_user_id,
    ):
        _deny_blocked_relationship()


def _ensure_group_candidates_not_blocked(
    db: Session,
    *,
    candidate_user_ids: set[int],
    all_participant_user_ids: set[int],
) -> None:
    if active_block_exists_across(
        db,
        candidate_user_ids=candidate_user_ids,
        participant_user_ids=all_participant_user_ids,
    ):
        _deny_blocked_relationship()


def _write_audit(
    db: Session,
    *,
    actor_user_id: int,
    action: str,
    target_type: str,
    target_id: str,
    audit: AuditContext | None,
    details: dict[str, object] | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor_user_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        result="success",
        request_id=audit.request_id if audit is not None else None,
        ip_address=audit.ip_address if audit is not None else None,
        user_agent=audit.user_agent if audit is not None else None,
        details=details,
    )


def _settings_view(
    *,
    conversation_id: str,
    user_id: int,
    member: C19ConversationMemberRecord,
    settings: C19ConversationUserSettingRecord | None,
) -> ConversationSettingsView:
    if settings is not None:
        return ConversationSettingsView.model_validate(settings)
    return ConversationSettingsView(
        conversation_id=conversation_id,
        user_id=user_id,
        is_pinned=False,
        is_muted=False,
        is_archived=False,
        notification_level="all",
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _member_view(member: C19ConversationMemberRecord) -> ConversationMemberView:
    return ConversationMemberView(
        user_id=member.user_id,
        affiliation_id=member.affiliation_id,
        org_id=member.org_id_at_join,
        role=member.role,
        status=member.status,
        joined_at=member.joined_at,
        left_at=member.left_at,
    )


def _detail_for_actor(
    db: Session,
    *,
    conversation: C19ConversationRecord,
    actor_member: C19ConversationMemberRecord,
) -> ConversationDetail:
    members = list_conversation_members(
        db,
        conversation_id=conversation.conversation_id,
    )
    settings = get_conversation_settings(
        db,
        conversation_id=conversation.conversation_id,
        user_id=actor_member.user_id,
    )
    return ConversationDetail(
        conversation_id=conversation.conversation_id,
        type=conversation.conversation_type,
        title=conversation.title,
        status=conversation.status,
        created_by_user_id=conversation.created_by_user_id,
        members=[_member_view(member) for member in members],
        settings=_settings_view(
            conversation_id=conversation.conversation_id,
            user_id=actor_member.user_id,
            member=actor_member,
            settings=settings,
        ),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _summary_from_row(row: ConversationListRow) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=row.conversation.conversation_id,
        type=row.conversation.conversation_type,
        title=row.conversation.title,
        status=row.conversation.status,
        actor_role=row.actor_member.role,
        actor_org_id=row.actor_member.org_id_at_join,
        active_member_count=row.active_member_count,
        settings=_settings_view(
            conversation_id=row.conversation.conversation_id,
            user_id=row.actor_member.user_id,
            member=row.actor_member,
            settings=row.settings,
        ),
        created_at=row.conversation.created_at,
        updated_at=row.conversation.updated_at,
    )


def _new_member(
    *,
    conversation_id: str,
    participant: ResolvedParticipant,
    role: str,
) -> C19ConversationMemberRecord:
    affiliation = participant.affiliation
    return C19ConversationMemberRecord(
        conversation_id=conversation_id,
        affiliation_id=(affiliation.affiliation_id if affiliation else None),
        user_id=participant.user_id,
        org_id_at_join=(affiliation.org_id if affiliation else None),
        role=role,
        status="active",
        joined_at=_now(),
        left_at=None,
    )


def _new_settings(
    *,
    conversation_id: str,
    user_id: int,
) -> C19ConversationUserSettingRecord:
    return C19ConversationUserSettingRecord(
        conversation_id=conversation_id,
        user_id=user_id,
        is_pinned=False,
        is_muted=False,
        is_archived=False,
        notification_level="all",
    )


def _require_active_member(
    db: Session,
    *,
    conversation: C19ConversationRecord,
    user_id: int,
    for_update: bool = False,
) -> C19ConversationMemberRecord:
    if conversation.status == "closed":
        raise _error("c19_conversation_not_found", "Conversation not found.", 404)
    member = get_conversation_member(
        db,
        conversation_id=conversation.conversation_id,
        user_id=user_id,
        for_update=for_update,
    )
    if member is None or member.status != "active":
        raise _error("c19_conversation_not_found", "Conversation not found.", 404)
    return member


def _require_group(
    conversation: C19ConversationRecord | None,
) -> C19ConversationRecord:
    if (
        conversation is None
        or conversation.conversation_type != "group"
        or conversation.status == "closed"
    ):
        raise _error("c19_group_not_found", "Group not found.", 404)
    return conversation


def _validate_one_active_owner(
    db: Session,
    *,
    conversation_id: str,
) -> list[C19ConversationMemberRecord]:
    members = list_conversation_members(
        db,
        conversation_id=conversation_id,
        for_update=True,
    )
    active_owners = [
        member
        for member in members
        if member.status == "active" and member.role == "owner"
    ]
    if len(active_owners) != 1:
        raise _error(
            "c19_group_owner_invariant",
            "Group ownership invariant failed.",
            409,
        )
    return members


def list_conversations(
    db: Session,
    *,
    actor: User,
    limit: int,
    offset: int,
) -> ConversationPage:
    actor_user_id = _actor_user_id(actor)
    with without_org_data_isolation():
        rows, total = list_actor_conversations(
            db,
            user_id=actor_user_id,
            limit=limit,
            offset=offset,
        )
        return ConversationPage(
            items=[_summary_from_row(row) for row in rows],
            count=total,
            limit=limit,
            offset=offset,
        )


def get_conversation_detail(
    db: Session,
    *,
    conversation_id: str,
    actor: User,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    with without_org_data_isolation():
        conversation = get_conversation(db, conversation_id=conversation_id)
        if conversation is None:
            raise _error(
                "c19_conversation_not_found",
                "Conversation not found.",
                404,
            )
        actor_member = _require_active_member(
            db,
            conversation=conversation,
            user_id=actor_user_id,
        )
        return _detail_for_actor(
            db,
            conversation=conversation,
            actor_member=actor_member,
        )


def create_direct_conversation(
    db: Session,
    *,
    payload: DirectConversationCreateRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    peer_user_id = payload.peer_user_id
    direct_pair_key = _canonical_pair_key(actor_user_id, peer_user_id)

    try:
        with without_org_data_isolation():
            requested_affiliations = {
                actor_user_id: payload.actor_affiliation_id,
                peer_user_id: payload.peer_affiliation_id,
            }
            resolved_participants = {
                user_id: _resolve_participant(
                    db,
                    user_id=user_id,
                    requested_affiliation_id=requested_affiliations[user_id],
                    for_update=True,
                )
                for user_id in sorted(requested_affiliations)
            }
            actor_participant = resolved_participants[actor_user_id]
            peer_participant = resolved_participants[peer_user_id]
            _ensure_pair_not_blocked(
                db,
                first_user_id=actor_user_id,
                second_user_id=peer_user_id,
            )

            existing = get_direct_conversation_by_pair(
                db,
                direct_pair_key=direct_pair_key,
                for_update=True,
            )
            if existing is not None:
                actor_member = _require_active_member(
                    db,
                    conversation=existing,
                    user_id=actor_user_id,
                    for_update=True,
                )
                peer_member = _require_active_member(
                    db,
                    conversation=existing,
                    user_id=peer_user_id,
                    for_update=True,
                )
                return _detail_for_actor(
                    db,
                    conversation=existing,
                    actor_member=actor_member,
                )

            conversation_id = generate_direct_conversation_id(
                str(actor_user_id),
                str(peer_user_id),
            )
            conversation = C19ConversationRecord(
                conversation_id=conversation_id,
                conversation_type="direct",
                direct_pair_key=direct_pair_key,
                title=None,
                created_by_user_id=actor_user_id,
                status="active",
            )
            actor_member = _new_member(
                conversation_id=conversation_id,
                participant=actor_participant,
                role="member",
            )
            peer_member = _new_member(
                conversation_id=conversation_id,
                participant=peer_participant,
                role="member",
            )

            try:
                with db.begin_nested():
                    add_conversation(db, conversation)
                    db.flush()
                    for member in (actor_member, peer_member):
                        add_conversation_member(db, member)
                    db.flush()
                    for member in (actor_member, peer_member):
                        add_conversation_settings(
                            db,
                            _new_settings(
                                conversation_id=conversation_id,
                                user_id=member.user_id,
                            ),
                        )
                    db.flush()
            except IntegrityError:
                existing = get_direct_conversation_by_pair(
                    db,
                    direct_pair_key=direct_pair_key,
                    for_update=True,
                )
                if existing is None:
                    raise _error(
                        "c19_conversation_conflict",
                        "Conversation creation conflicted.",
                        409,
                    ) from None
                actor_member = _require_active_member(
                    db,
                    conversation=existing,
                    user_id=actor_user_id,
                    for_update=True,
                )
                peer_member = _require_active_member(
                    db,
                    conversation=existing,
                    user_id=peer_user_id,
                    for_update=True,
                )
                return _detail_for_actor(
                    db,
                    conversation=existing,
                    actor_member=actor_member,
                )

            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.conversation.direct.create",
                target_type="c19_conversation",
                target_id=conversation_id,
                audit=audit,
                details={
                    "participant_count": 2,
                    "explicit_org_snapshot_count": len(
                        {
                            affiliation.org_id
                            for affiliation in (
                                actor_participant.affiliation,
                                peer_participant.affiliation,
                            )
                            if affiliation is not None
                        }
                    ),
                },
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def _resolve_group_participants(
    db: Session,
    *,
    actor_user_id: int,
    actor_affiliation_id: str | None,
    members: list[ConversationMemberInput],
) -> tuple[ResolvedParticipant, list[ResolvedParticipant]]:
    member_user_ids = [member.user_id for member in members]
    if actor_user_id in member_user_ids or len(member_user_ids) != len(
        set(member_user_ids)
    ):
        raise _error(
            "c19_invalid_participants",
            "Group participants must be distinct and exclude the actor.",
            409,
        )
    requested_affiliations = {
        actor_user_id: actor_affiliation_id,
        **{member.user_id: member.affiliation_id for member in members},
    }
    resolved_by_user_id = {
        user_id: _resolve_participant(
            db,
            user_id=user_id,
            requested_affiliation_id=requested_affiliations[user_id],
            for_update=True,
        )
        for user_id in sorted(requested_affiliations)
    }
    actor_participant = resolved_by_user_id[actor_user_id]
    resolved_members = [
        resolved_by_user_id[member.user_id]
        for member in members
    ]
    all_user_ids = {actor_user_id, *member_user_ids}
    _ensure_group_candidates_not_blocked(
        db,
        candidate_user_ids=all_user_ids,
        all_participant_user_ids=all_user_ids,
    )
    return actor_participant, resolved_members


def create_group(
    db: Session,
    *,
    payload: GroupCreateRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            actor_participant, member_participants = _resolve_group_participants(
                db,
                actor_user_id=actor_user_id,
                actor_affiliation_id=payload.actor_affiliation_id,
                members=payload.members,
            )
            participant_count = 1 + len(member_participants)
            if participant_count < 3 or participant_count > MAX_GROUP_PARTICIPANTS:
                raise _error(
                    "c19_group_size_invalid",
                    "Group participant count must be between 3 and 200.",
                    409,
                )

            conversation_id = generate_group_conversation_id()
            conversation = C19ConversationRecord(
                conversation_id=conversation_id,
                conversation_type="group",
                direct_pair_key=None,
                title=payload.title,
                created_by_user_id=actor_user_id,
                status="active",
            )
            actor_member = _new_member(
                conversation_id=conversation_id,
                participant=actor_participant,
                role="owner",
            )
            members = [
                actor_member,
                *[
                    _new_member(
                        conversation_id=conversation_id,
                        participant=participant,
                        role="member",
                    )
                    for participant in member_participants
                ],
            ]
            add_conversation(db, conversation)
            db.flush()
            for member in members:
                add_conversation_member(db, member)
            db.flush()
            for member in members:
                add_conversation_settings(
                    db,
                    _new_settings(
                        conversation_id=conversation_id,
                        user_id=member.user_id,
                    ),
                )
            db.flush()
            _validate_one_active_owner(db, conversation_id=conversation_id)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.create",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
                details={
                    "participant_count": participant_count,
                    "explicit_organization_count": len(
                        {
                            participant.affiliation.org_id
                            for participant in (
                                actor_participant,
                                *member_participants,
                            )
                            if participant.affiliation is not None
                        }
                    ),
                },
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def update_group(
    db: Session,
    *,
    conversation_id: str,
    payload: GroupUpdateRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            if actor_member.role not in {"owner", "admin"}:
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            _validate_one_active_owner(db, conversation_id=conversation_id)
            conversation.title = payload.title
            conversation.updated_at = _now()
            db.add(conversation)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.update",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
                details={"updated_fields": ["title"]},
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def add_group_members(
    db: Session,
    *,
    conversation_id: str,
    payload: GroupMembersAddRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            if actor_member.role not in {"owner", "admin"}:
                raise _error("c19_group_access_denied", "Group access denied.", 403)

            all_members = _validate_one_active_owner(
                db,
                conversation_id=conversation_id,
            )
            active_members = [member for member in all_members if member.status == "active"]
            new_user_ids = {member.user_id for member in payload.members}
            active_user_ids = {member.user_id for member in active_members}
            if new_user_ids & active_user_ids:
                raise _error(
                    "c19_group_member_conflict",
                    "One or more group members already exist.",
                    409,
                )
            if len(active_user_ids) + len(new_user_ids) > MAX_GROUP_PARTICIPANTS:
                raise _error(
                    "c19_group_size_invalid",
                    "Group participant count cannot exceed 200.",
                    409,
                )

            resolved = [
                _resolve_participant(
                    db,
                    user_id=member.user_id,
                    requested_affiliation_id=member.affiliation_id,
                    for_update=True,
                )
                for member in sorted(
                    payload.members,
                    key=lambda item: item.user_id,
                )
            ]
            _ensure_group_candidates_not_blocked(
                db,
                candidate_user_ids=new_user_ids,
                all_participant_user_ids=active_user_ids | new_user_ids,
            )
            historical_by_user_id = {member.user_id: member for member in all_members}
            new_settings: list[C19ConversationUserSettingRecord] = []
            for participant in resolved:
                affiliation = participant.affiliation
                existing = historical_by_user_id.get(participant.user_id)
                if existing is not None:
                    if existing.status == "banned":
                        raise _error(
                            "c19_group_access_denied",
                            "Group access denied.",
                            403,
                        )
                    existing.affiliation_id = (
                        affiliation.affiliation_id if affiliation else None
                    )
                    existing.org_id_at_join = (
                        affiliation.org_id if affiliation else None
                    )
                    existing.role = "member"
                    existing.status = "active"
                    existing.joined_at = _now()
                    existing.left_at = None
                    db.add(existing)
                else:
                    new_member = _new_member(
                        conversation_id=conversation_id,
                        participant=participant,
                        role="member",
                    )
                    add_conversation_member(db, new_member)
                    new_settings.append(
                        _new_settings(
                            conversation_id=conversation_id,
                            user_id=participant.user_id,
                        ),
                    )
            conversation.updated_at = _now()
            db.add(conversation)
            db.flush()
            for settings in new_settings:
                add_conversation_settings(db, settings)
            db.flush()
            _validate_one_active_owner(db, conversation_id=conversation_id)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.members.add",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
                details={"member_count_added": len(resolved)},
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def remove_group_member(
    db: Session,
    *,
    conversation_id: str,
    target_user_id: int,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            members = _validate_one_active_owner(db, conversation_id=conversation_id)
            target = next(
                (
                    member
                    for member in members
                    if member.user_id == target_user_id and member.status == "active"
                ),
                None,
            )
            if target is None:
                raise _error("c19_group_member_not_found", "Group member not found.", 404)
            if actor_user_id == target_user_id or target.role == "owner":
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            if actor_member.role == "admin" and target.role != "member":
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            if actor_member.role not in {"owner", "admin"}:
                raise _error("c19_group_access_denied", "Group access denied.", 403)

            target.status = "removed"
            target.left_at = _now()
            db.add(target)
            conversation.updated_at = _now()
            db.add(conversation)
            _validate_one_active_owner(db, conversation_id=conversation_id)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.member.remove",
                target_type="c19_group_member",
                target_id=f"{conversation_id}:{target_user_id}",
                audit=audit,
                details={"conversation_id": conversation_id},
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def leave_group(
    db: Session,
    *,
    conversation_id: str,
    actor: User,
    audit: AuditContext | None = None,
) -> GroupLeaveResponse:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            _validate_one_active_owner(db, conversation_id=conversation_id)
            if actor_member.role == "owner":
                raise _error(
                    "c19_group_owner_transfer_required",
                    "Transfer group ownership before leaving.",
                    409,
                )
            actor_member.status = "left"
            actor_member.left_at = _now()
            db.add(actor_member)
            conversation.updated_at = _now()
            db.add(conversation)
            _validate_one_active_owner(db, conversation_id=conversation_id)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.leave",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
            )
            db.commit()
            return GroupLeaveResponse(
                conversation_id=conversation_id,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def transfer_group_owner(
    db: Session,
    *,
    conversation_id: str,
    payload: GroupOwnerTransferRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationDetail:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            members = _validate_one_active_owner(db, conversation_id=conversation_id)
            if actor_member.role != "owner":
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            target = next(
                (
                    member
                    for member in members
                    if member.user_id == payload.new_owner_user_id
                    and member.status == "active"
                ),
                None,
            )
            if target is None or target.user_id == actor_user_id:
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            if target.user_id not in list_active_user_ids(
                db,
                user_ids={target.user_id},
            ):
                raise _error(
                    "c19_group_access_denied",
                    "Group access denied.",
                    403,
                )

            actor_member.role = "admin"
            target.role = "owner"
            db.add(actor_member)
            db.add(target)
            conversation.updated_at = _now()
            db.add(conversation)
            db.flush()
            _validate_one_active_owner(db, conversation_id=conversation_id)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.owner.transfer",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
                details={"new_owner_user_id": target.user_id},
            )
            db.commit()
            return _detail_for_actor(
                db,
                conversation=conversation,
                actor_member=actor_member,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def delete_group(
    db: Session,
    *,
    conversation_id: str,
    actor: User,
    audit: AuditContext | None = None,
) -> GroupDeleteResponse:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = _require_group(
                get_conversation(
                    db,
                    conversation_id=conversation_id,
                    for_update=True,
                )
            )
            actor_member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            members = _validate_one_active_owner(db, conversation_id=conversation_id)
            if actor_member.role != "owner":
                raise _error("c19_group_access_denied", "Group access denied.", 403)
            now = _now()
            for member in members:
                if member.status in {"active", "invited"}:
                    member.status = "removed"
                    member.left_at = now
                    db.add(member)
            conversation.status = "closed"
            conversation.updated_at = now
            db.add(conversation)
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.group.delete",
                target_type="c19_group",
                target_id=conversation_id,
                audit=audit,
                details={"member_count_closed": len(members)},
            )
            db.commit()
            return GroupDeleteResponse(conversation_id=conversation_id)
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def get_settings(
    db: Session,
    *,
    conversation_id: str,
    actor: User,
) -> ConversationSettingsView:
    actor_user_id = _actor_user_id(actor)
    with without_org_data_isolation():
        conversation = get_conversation(db, conversation_id=conversation_id)
        if conversation is None:
            raise _error(
                "c19_conversation_not_found",
                "Conversation not found.",
                404,
            )
        member = _require_active_member(
            db,
            conversation=conversation,
            user_id=actor_user_id,
        )
        settings = get_conversation_settings(
            db,
            conversation_id=conversation_id,
            user_id=actor_user_id,
        )
        return _settings_view(
            conversation_id=conversation_id,
            user_id=actor_user_id,
            member=member,
            settings=settings,
        )


def update_settings(
    db: Session,
    *,
    conversation_id: str,
    payload: ConversationSettingsUpdateRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> ConversationSettingsView:
    actor_user_id = _actor_user_id(actor)
    try:
        with without_org_data_isolation():
            conversation = get_conversation(
                db,
                conversation_id=conversation_id,
                for_update=True,
            )
            if conversation is None:
                raise _error(
                    "c19_conversation_not_found",
                    "Conversation not found.",
                    404,
                )
            member = _require_active_member(
                db,
                conversation=conversation,
                user_id=actor_user_id,
                for_update=True,
            )
            settings = get_conversation_settings(
                db,
                conversation_id=conversation_id,
                user_id=actor_user_id,
                for_update=True,
            )
            if settings is None:
                settings = _new_settings(
                    conversation_id=conversation_id,
                    user_id=actor_user_id,
                )
                add_conversation_settings(db, settings)
            updated_fields: list[str] = []
            for field_name in (
                "is_pinned",
                "is_muted",
                "is_archived",
                "notification_level",
            ):
                if field_name in payload.model_fields_set:
                    setattr(settings, field_name, getattr(payload, field_name))
                    updated_fields.append(field_name)
            settings.updated_at = _now()
            db.add(settings)
            db.flush()
            _write_audit(
                db,
                actor_user_id=actor_user_id,
                action="c19.conversation.settings.update",
                target_type="c19_conversation_settings",
                target_id=f"{conversation_id}:{actor_user_id}",
                audit=audit,
                details={"updated_fields": updated_fields},
            )
            db.commit()
            return _settings_view(
                conversation_id=conversation_id,
                user_id=actor_user_id,
                member=member,
                settings=settings,
            )
    except C19ConversationControlError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


__all__ = [
    "C19ConversationControlError",
    "MAX_GROUP_PARTICIPANTS",
    "add_group_members",
    "create_direct_conversation",
    "create_group",
    "delete_group",
    "get_conversation_detail",
    "get_settings",
    "leave_group",
    "list_conversations",
    "remove_group_member",
    "transfer_group_owner",
    "update_group",
    "update_settings",
]
