"""把成本表快照通过 C19 发给人。

**分享是外部副作用**:数字一旦进了对方的聊天窗口就收不回来了。所以这里的规矩比
别处严:

1. 发的一定是**快照**,不是实时表——实时表下一秒就可能变,而对方手里那份不会;
2. ``price_only`` 口径的成本行**在生成卡片时就不存在**,不是前端藏起来,所以对方
   转发、复制、截图都漏不出成本;
3. 发完必须**回读**,在对方的会话里真的看见那条消息,才写台账、才算送达。接口返回
   200 不算数——报告成功不等于真发生。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.display_names import user_display_name
from ..inventory.service import FactoryContext, MfgError, MfgNotFound
from ..inventory import service as inv
from . import card
from . import models as C
from . import schemas as S
from . import service as cost_service


def _client_message_id(sheet_no: str, recipient_user_id: int) -> str:
    # 幂等键:同一份表发给同一个人重复点,记录服务按 client_message_id 去重
    return f"mfgcost-{sheet_no}-{recipient_user_id}-{uuid4().hex[:8]}"


async def share_sheet(
    db: Session,
    ctx: FactoryContext,
    sheet_id: UUID,
    *,
    user: User,
    payload: S.CostShareRequest,
    store: Any,
    conversation_service: Any,
    message_service: Any,
    conversation_schemas: Any,
    message_schemas: Any,
) -> S.CostShareResult:
    """依赖用参数传进来而不是模块级 import:M 系列不该在导入期就绑死 C19 的实现,
    测试里也好换成假的。"""
    sheet = db.scalar(
        select(C.MfgCostSheet).where(
            C.MfgCostSheet.id == sheet_id,
            C.MfgCostSheet.factory_org_id == ctx.factory_org_id,
        )
    )
    if sheet is None:
        raise MfgNotFound("成本表不存在")

    detail = cost_service.get_sheet(db, ctx, sheet.id)
    actor_name = inv._actor_name(db, user)

    delivered: list[S.CostShareRead] = []
    failed: list[dict[str, Any]] = []

    for recipient_user_id in payload.recipient_user_ids:
        token = card.card_token(sheet.sheet_no, str(recipient_user_id))
        try:
            content = card.render(
                sheet,
                detail,
                token=token,
                share_mode=payload.share_mode,
                preface=payload.message,
            )
        except card.CardTooLong as exc:
            raise MfgError(str(exc)) from exc

        try:
            conversation = conversation_service.create_direct_conversation(
                db,
                payload=conversation_schemas.DirectConversationCreateRequest(
                    peer_user_id=recipient_user_id
                ),
                actor=user,
            )
            record = await message_service.send_message(
                db,
                actor=user,
                conversation_id=conversation.conversation_id,
                payload=message_schemas.MessageCreateRequest(
                    client_message_id=_client_message_id(
                        sheet.sheet_no, recipient_user_id
                    ),
                    content_type="text",
                    content=content,
                ),
                store=store,
            )
        except Exception as exc:  # noqa: BLE001 - 一个人失败不该拖垮其余的
            failed.append(
                {
                    "recipient_user_id": recipient_user_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        verified_at = await _verify_delivered(
            db,
            user=user,
            conversation_id=conversation.conversation_id,
            record_id=record.id,
            store=store,
            message_service=message_service,
        )
        if verified_at is None:
            # 发送接口没报错,但回读时那条消息不在对方的会话里。这种情况绝不能
            # 记成"已分享"——台账里的每一行都必须是真的送到了。
            failed.append(
                {
                    "recipient_user_id": recipient_user_id,
                    "error": "已提交但回读未确认,未记入台账",
                }
            )
            continue

        recipient_name = _recipient_name(db, recipient_user_id)
        share = C.MfgCostSheetShare(
            factory_org_id=ctx.factory_org_id,
            sheet_id=sheet.id,
            share_mode=payload.share_mode,
            card_token=token,
            recipient_user_id=str(recipient_user_id),
            recipient_name=recipient_name,
            conversation_id=conversation.conversation_id,
            message_id=str(record.id),
            verified_at=verified_at,
            actor_user_id=str(user.id),
            actor_name=actor_name,
        )
        db.add(share)
        inv._commit(db)
        db.refresh(share)
        delivered.append(S.CostShareRead.model_validate(share))

    return S.CostShareResult(
        sheet_no=sheet.sheet_no,
        share_mode=payload.share_mode,
        delivered=delivered,
        failed=failed,
    )


async def _verify_delivered(
    db: Session,
    *,
    user: User,
    conversation_id: str,
    record_id: str,
    store: Any,
    message_service: Any,
) -> datetime | None:
    """回读:在会话里真的看见这条消息才算数。"""
    try:
        page = await message_service.list_message_history(
            db,
            actor=user,
            conversation_id=conversation_id,
            limit=20,
            cursor=None,
            store=store,
        )
    except Exception:  # noqa: BLE001 - 回读失败就是没验证上
        return None
    for item in page.items:
        if str(item.id) == str(record_id):
            return datetime.now(timezone.utc)
    return None


def _recipient_name(db: Session, recipient_user_id: int) -> str:
    peer = db.get(User, recipient_user_id)
    if peer is None:
        return str(recipient_user_id)
    return user_display_name(db, peer)
