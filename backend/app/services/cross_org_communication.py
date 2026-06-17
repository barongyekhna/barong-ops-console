from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.session import SessionLocal
from ..models.user import User
from ..schemas.conversation import Conversation as C19DConversation
from ..schemas.cross_org_communication import (
    CROSS_ORG_COMMUNICATION_MODULE_ID,
    CrossOrgCheckRequest,
    CrossOrgConversationRule,
    CrossOrgDataIsolationScope,
    CrossOrgDecision,
    CrossOrgMessageOrgEnvelope,
    CrossOrgMessageSendDecision,
    CrossOrgParticipantIdentity,
    CrossOrgPolicy,
    CrossOrgPolicyMode,
    get_default_cross_org_policy,
)
from ..schemas.message import (
    Conversation as MessageConversation,
    Message,
    MessageBindingError,
    MessageSendRequest,
    enforce_message_conversation_binding,
)
from ..schemas.permission import PermissionAction, PermissionDecision
from . import module_binding_service as c18d_binding
from .auth_service import AuditContext
from .conversation_service import (
    ConversationNotFoundError,
    ConversationParticipantNotFoundError,
    get_conversation_for_actor,
    resolve_conversation_participant,
)
from .event_collector import emit_event, generate_context_id
from .permission_isolation import check_permission
from ..repositories import module_bindings as module_binding_repo


class CrossOrgCommunicationError(ValueError):
    pass


class CrossOrgCommunicationDeniedError(PermissionError):
    def __init__(self, decision: CrossOrgMessageSendDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _trace_id(audit: AuditContext | None) -> str:
    if audit is not None and audit.request_id:
        return audit.request_id
    return generate_context_id()


def _participant_identity(user_id: str, org_id: str) -> CrossOrgParticipantIdentity:
    return CrossOrgParticipantIdentity(user_id=user_id, org_id=org_id)


def _data_scope(
    *,
    sender_org_id: str | None,
    receiver_org_id: str | None,
) -> CrossOrgDataIsolationScope:
    return CrossOrgDataIsolationScope(
        sender_org_id=sender_org_id,
        receiver_org_id=receiver_org_id,
    )


def _ensure_default_global_im_boundary(db: Session) -> bool:
    existing = module_binding_repo.get_module_binding(
        db,
        CROSS_ORG_COMMUNICATION_MODULE_ID,
    )
    if existing is not None:
        return False

    with SessionLocal() as init_db:
        if module_binding_repo.get_module_binding(
            init_db,
            CROSS_ORG_COMMUNICATION_MODULE_ID,
        ) is not None:
            return False
        try:
            module_binding_repo.replace_module_binding(
                init_db,
                module_id=CROSS_ORG_COMMUNICATION_MODULE_ID,
                bound_orgs=[c18d_binding.GLOBAL_MODULE_BOUND_ORG],
            )
            init_db.commit()
        except IntegrityError:
            init_db.rollback()
            return False
    return True


def _emit_cross_org_decision(
    *,
    decision: CrossOrgDecision,
    actor: User,
) -> None:
    emit_event(
        event_type="comm.cross_org.check",
        module="system",
        action="c19e.cross_org.check",
        source="backend",
        status="success" if decision.allowed else "failed",
        context_id=decision.c17_trace_id,
        user_id=_actor_user_id(actor),
        payload={
            "sender_user_id": decision.sender_user_id,
            "receiver_user_id": decision.receiver_user_id,
            "sender_org_id": decision.sender.org_id
            if decision.sender is not None
            else None,
            "receiver_org_id": decision.receiver.org_id
            if decision.receiver is not None
            else None,
            "cross_org": decision.cross_org,
            "allowed": decision.allowed,
            "denial_code": decision.denial_code,
            "c18f_permission_checked": decision.c18f_permission_checked,
            "c18f_denial_code": (
                decision.c18f_permission_decision.denial_code
                if decision.c18f_permission_decision is not None
                else None
            ),
            "policy_mode": decision.policy.mode,
            "c18g_data_scope_required": True,
            "c17_trace_logged": True,
        },
    )


def _decision(
    *,
    request: CrossOrgCheckRequest,
    actor: User,
    policy: CrossOrgPolicy,
    trace_id: str,
    sender: CrossOrgParticipantIdentity | None,
    receiver: CrossOrgParticipantIdentity | None,
    allowed: bool,
    denial_code: str | None,
    reason: str,
    c18f_permission_checked: bool,
    c18f_permission_decision: PermissionDecision | None = None,
    c19a_identity_checked: bool = True,
    c18c_membership_checked: bool = True,
) -> CrossOrgDecision:
    sender_org_id = sender.org_id if sender is not None else None
    receiver_org_id = receiver.org_id if receiver is not None else None
    cross_org = (
        sender_org_id is not None
        and receiver_org_id is not None
        and sender_org_id != receiver_org_id
    )
    decision = CrossOrgDecision(
        sender_user_id=request.sender_user_id,
        receiver_user_id=request.receiver_user_id,
        sender=sender,
        receiver=receiver,
        cross_org=cross_org,
        allowed=allowed,
        denied=not allowed,
        denial_code=denial_code,
        reason=reason,
        policy=policy,
        c18f_permission_checked=c18f_permission_checked,
        c18f_permission_decision=c18f_permission_decision,
        c18g_scope=_data_scope(
            sender_org_id=sender_org_id,
            receiver_org_id=receiver_org_id,
        ),
        c19a_identity_checked=c19a_identity_checked,
        c18c_membership_checked=c18c_membership_checked,
        c17_trace_id=trace_id,
    )
    _emit_cross_org_decision(decision=decision, actor=actor)
    return decision


def can_communicate(
    db: Session,
    *,
    payload: CrossOrgCheckRequest,
    actor: User,
    policy: CrossOrgPolicy | None = None,
    audit: AuditContext | None = None,
) -> CrossOrgDecision:
    active_policy = policy or get_default_cross_org_policy()
    trace_id = _trace_id(audit)

    if not actor.is_active:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=None,
            receiver=None,
            allowed=False,
            denial_code="c19e_actor_inactive",
            reason="Cross-org communication requires an active authenticated actor.",
            c18f_permission_checked=False,
            c19a_identity_checked=False,
            c18c_membership_checked=False,
        )

    if payload.sender_user_id != _actor_user_id(actor):
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=None,
            receiver=None,
            allowed=False,
            denial_code="c19e_sender_must_match_actor",
            reason="Message sender must match the authenticated actor.",
            c18f_permission_checked=False,
            c19a_identity_checked=False,
            c18c_membership_checked=False,
        )

    try:
        sender_resolution = resolve_conversation_participant(
            db,
            user_id=payload.sender_user_id,
        )
        receiver_resolution = resolve_conversation_participant(
            db,
            user_id=payload.receiver_user_id,
        )
    except ConversationParticipantNotFoundError:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=None,
            receiver=None,
            allowed=False,
            denial_code="c19e_identity_not_verified",
            reason=(
                "C19A identity and active C18C membership are required for both "
                "participants."
            ),
            c18f_permission_checked=False,
            c19a_identity_checked=True,
            c18c_membership_checked=True,
        )

    sender = _participant_identity(
        sender_resolution.user_id,
        sender_resolution.org_id,
    )
    receiver = _participant_identity(
        receiver_resolution.user_id,
        receiver_resolution.org_id,
    )

    if sender.org_id == receiver.org_id:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=True,
            denial_code=None,
            reason="Same-org communication is allowed after C19A/C18C validation.",
            c18f_permission_checked=False,
        )

    if active_policy.mode == CrossOrgPolicyMode.CLOSED:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=False,
            denial_code="c19e_policy_closed",
            reason="Cross-org communication policy is closed.",
            c18f_permission_checked=False,
        )

    if not active_policy.rules.allow_cross_org_chat:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=False,
            denial_code="c19e_cross_org_chat_disabled",
            reason="Cross-org chat is disabled by system policy.",
            c18f_permission_checked=False,
        )

    if not active_policy.rules.require_permission:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=False,
            denial_code="c19e_c18f_required",
            reason="C19E forbids cross-org communication without C18F permission.",
            c18f_permission_checked=False,
        )

    if active_policy.rules.require_mutual_approval:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=False,
            denial_code="c19e_mutual_approval_reserved",
            reason="Mutual approval is required by policy but is not implemented.",
            c18f_permission_checked=False,
        )

    _ensure_default_global_im_boundary(db)
    permission_decision = check_permission(
        db,
        payload.sender_user_id,
        sender.org_id,
        CROSS_ORG_COMMUNICATION_MODULE_ID,
        PermissionAction.READ,
    )
    if permission_decision.denied:
        return _decision(
            request=payload,
            actor=actor,
            policy=active_policy,
            trace_id=trace_id,
            sender=sender,
            receiver=receiver,
            allowed=False,
            denial_code="c19e_c18f_permission_denied",
            reason="C18F denied cross-org communication.",
            c18f_permission_checked=True,
            c18f_permission_decision=permission_decision,
        )

    return _decision(
        request=payload,
        actor=actor,
        policy=active_policy,
        trace_id=trace_id,
        sender=sender,
        receiver=receiver,
        allowed=True,
        denial_code=None,
        reason="Cross-org communication is allowed by C19E policy and C18F.",
        c18f_permission_checked=True,
        c18f_permission_decision=permission_decision,
    )


def _conversation_rule(
    *,
    conversation: C19DConversation,
    communication_decision: CrossOrgDecision,
) -> CrossOrgConversationRule:
    if communication_decision.sender is None or communication_decision.receiver is None:
        raise CrossOrgCommunicationError("Conversation rule requires resolved orgs.")
    return CrossOrgConversationRule(
        conversation_id=conversation.conversation_id,
        participants=tuple(conversation.participants),  # type: ignore[arg-type]
        sender_org_id=communication_decision.sender.org_id,
        receiver_org_id=communication_decision.receiver.org_id,
        cross_org=communication_decision.cross_org,
        conversation_cross_org_value=communication_decision.cross_org,
    )


def _message_envelope(
    *,
    message: Message,
    communication_decision: CrossOrgDecision,
) -> CrossOrgMessageOrgEnvelope:
    if communication_decision.sender is None or communication_decision.receiver is None:
        raise CrossOrgCommunicationError("Message envelope requires resolved orgs.")
    return CrossOrgMessageOrgEnvelope(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        from_user_id=message.from_user_id,
        to_user_id=message.to_user_id,
        sender_org_id=communication_decision.sender.org_id,
        receiver_org_id=communication_decision.receiver.org_id,
        content_type=message.content_type,
        status=message.status,
        cross_org=communication_decision.cross_org,
    )


def _emit_message_send_decision(
    *,
    decision: CrossOrgMessageSendDecision,
    actor: User,
) -> None:
    emit_event(
        event_type="comm.message.send",
        module="system",
        action="c19e.message.send",
        source="backend",
        status="success" if decision.allowed else "failed",
        context_id=decision.communication_decision.c17_trace_id,
        user_id=_actor_user_id(actor),
        payload={
            "allowed": decision.allowed,
            "denial_code": decision.denial_code,
            "message_id": decision.message.message_id
            if decision.message is not None
            else None,
            "conversation_id": decision.conversation.conversation_id
            if decision.conversation is not None
            else None,
            "sender_org_id": decision.message.sender_org_id
            if decision.message is not None
            else decision.communication_decision.c18g_scope.sender_org_id,
            "receiver_org_id": decision.message.receiver_org_id
            if decision.message is not None
            else decision.communication_decision.c18g_scope.receiver_org_id,
            "cross_org": decision.communication_decision.cross_org,
            "persistence_implemented": False,
            "websocket_implemented": False,
        },
    )


def _send_decision(
    *,
    communication_decision: CrossOrgDecision,
    actor: User,
    allowed: bool,
    denial_code: str | None,
    reason: str,
    conversation: CrossOrgConversationRule | None = None,
    message: CrossOrgMessageOrgEnvelope | None = None,
) -> CrossOrgMessageSendDecision:
    decision = CrossOrgMessageSendDecision(
        allowed=allowed,
        denied=not allowed,
        denial_code=denial_code,
        reason=reason,
        communication_decision=communication_decision,
        conversation=conversation,
        message=message,
    )
    _emit_message_send_decision(decision=decision, actor=actor)
    return decision


def send_message_after_cross_org_check(
    db: Session,
    *,
    payload: MessageSendRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> CrossOrgMessageSendDecision:
    communication_decision = can_communicate(
        db,
        payload=CrossOrgCheckRequest(
            sender_user_id=payload.from_user_id,
            receiver_user_id=payload.to_user_id,
        ),
        actor=actor,
        audit=audit,
    )
    if communication_decision.denied:
        return _send_decision(
            communication_decision=communication_decision,
            actor=actor,
            allowed=False,
            denial_code=communication_decision.denial_code,
            reason=communication_decision.reason,
        )

    conversation = get_conversation_for_actor(
        db,
        conversation_id=payload.conversation_id,
        actor=actor,
    )
    message = Message(
        from_user_id=payload.from_user_id,
        to_user_id=payload.to_user_id,
        conversation_id=payload.conversation_id,
        content_type=payload.content_type,
        content=payload.content,
        attachments=payload.attachments,
        media_type=payload.media_type,
    )

    binding_conversation = MessageConversation(
        conversation_id=conversation.conversation_id,
        participants=tuple(conversation.participants),
    )
    try:
        enforce_message_conversation_binding(
            message=message,
            conversation=binding_conversation,
        )
    except MessageBindingError:
        return _send_decision(
            communication_decision=communication_decision,
            actor=actor,
            allowed=False,
            denial_code="c19e_message_conversation_binding_denied",
            reason="Message sender and receiver must match C19D conversation.",
        )

    conversation_rule = _conversation_rule(
        conversation=conversation,
        communication_decision=communication_decision,
    )
    message_envelope = _message_envelope(
        message=message,
        communication_decision=communication_decision,
    )
    return _send_decision(
        communication_decision=communication_decision,
        actor=actor,
        allowed=True,
        denial_code=None,
        reason="Message accepted by C19E send boundary.",
        conversation=conversation_rule,
        message=message_envelope,
    )


__all__ = [
    "ConversationNotFoundError",
    "CrossOrgCommunicationDeniedError",
    "can_communicate",
    "send_message_after_cross_org_check",
]
