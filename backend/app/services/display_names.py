"""用户的「显示名」：中文真名存在 C19 通讯资料里，users.username 只是登录名。

数字员工（白苏婉 baisuwan、霓旌 nijing）登录名是拼音，任何给人看的地方都应该
显示 C19 资料里的 display_name，没有资料才退回登录名。用户管理路由里的
_display_name_map 同源，这里是给业务服务层（M 库存单据、审核审计等）用的轻量版。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.c19 import C19ProfileRecord
from ..models.user import User
from .data_isolation import without_org_data_isolation


def display_name_map(db: Session, user_ids: Iterable[int | None]) -> dict[int, str]:
    """{user_id: 显示名}，只含有资料且名字非空的用户。跨组织可见是设计（用户/职位跨组织可见）。"""
    ids = sorted({int(value) for value in user_ids if value is not None})
    if not ids:
        return {}
    with without_org_data_isolation():
        rows = db.execute(
            select(C19ProfileRecord.user_id, C19ProfileRecord.display_name).where(
                C19ProfileRecord.user_id.in_(ids)
            )
        ).all()
    result: dict[int, str] = {}
    for user_id, name in rows:
        cleaned = (name or "").strip()
        if cleaned:
            result[int(user_id)] = cleaned
    return result


def user_display_name(db: Session, user: User | None) -> str:
    """显示名 → 登录名 → id，永不返回空串。"""
    if user is None:
        return ""
    names = display_name_map(db, [user.id])
    return names.get(user.id) or (user.username or "").strip() or str(user.id)
