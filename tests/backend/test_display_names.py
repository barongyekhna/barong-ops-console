"""显示名：有 C19 资料的用户显示汉字真名，没有的退回登录名。

数字员工（baisuwan / nijing）登录名是拼音，给人看的地方必须显示资料里的汉字。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.c19 import C19ProfileRecord
from backend.app.models.user import User
from backend.app.services.display_names import display_name_map, user_display_name


@pytest.mark.integration
def test_display_name_prefers_c19_profile_and_falls_back_to_username(
    clean_auth_tables: None,
) -> None:
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        bot = User(
            username=f"nijing_{suffix}",
            password_hash=hash_password("example-only-display-name-password"),
            role="viewer",
            is_active=True,
            is_bot=True,
        )
        plain = User(
            username=f"plain_{suffix}",
            password_hash=hash_password("example-only-display-name-password"),
            role="operator",
            is_active=True,
        )
        db.add_all([bot, plain])
        db.flush()
        # 库有 check 约束不允许空白 display_name，所以「资料存在但名字空白」不需要测
        db.add(C19ProfileRecord(user_id=bot.id, display_name="霓旌"))
        db.commit()
        bot_id, plain_id = bot.id, plain.id

    with SessionLocal() as db:
        names = display_name_map(db, [bot_id, plain_id, None])
        assert names == {bot_id: "霓旌"}

        assert user_display_name(db, db.get(User, bot_id)) == "霓旌"
        # 没有 C19 资料：退回登录名
        assert user_display_name(db, db.get(User, plain_id)) == f"plain_{suffix}"
        assert user_display_name(db, None) == ""
        assert display_name_map(db, []) == {}
