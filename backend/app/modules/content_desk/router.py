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
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info

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


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    user: User = Depends(require_desk_permission("content.desk.read")),
) -> dict[str, Any]:
    """一次画完整页:四步导轨 + 待办 + 机器状态。步 5 填真实载荷。"""
    return {"steps": [], "todos": [], "machine": [], "ready": False}
