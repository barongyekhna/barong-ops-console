"""会话 ID 生成规则。

这两个函数是 C19 微信化重构**之后**仍在用的活代码:
`modules/c19/conversation_service.py` 从 `schemas/conversation.py` 里 import 它们,
`POST /api/app/c19/conversations/direct` 走的就是这条路。

原来只有 `test_conversation_schema.py` 覆盖它们,而那份测试的其余部分全是
2026-09-01 删掉的旧消息栈(未挂载的 router + 旧 service)。删旧测试时如果不把
这一块单独接出来,就会在「清理」的名义下悄悄丢掉一段活代码的覆盖。
"""

from __future__ import annotations

import re

import pytest

from backend.app.schemas.conversation import (
    generate_direct_conversation_id,
    generate_group_conversation_id,
)

pytestmark = pytest.mark.unit


def test_direct_conversation_id_is_order_independent_and_trimmed() -> None:
    """两个人之间只能有一个单聊会话——谁先谁后、有没有空格都必须算出同一个 id。"""
    assert generate_direct_conversation_id("user-b", "user-a") == (
        generate_direct_conversation_id(" user-a ", " user-b ")
    )


def test_direct_conversation_id_matches_the_route_pattern() -> None:
    """格式必须是 conv_ + 32 位十六进制。

    nginx 配置里按 `^/api/backend/c19/conversations/conv_[0-9a-f]{32}/messages$`
    精确放行,格式一变线上就 404,而且不会有任何测试报错——所以在这里钉死。
    """
    assert re.fullmatch(
        r"conv_[0-9a-f]{32}",
        generate_direct_conversation_id("user-a", "user-b"),
    )


def test_different_pairs_get_different_conversations() -> None:
    assert generate_direct_conversation_id("user-a", "user-b") != (
        generate_direct_conversation_id("user-a", "user-c")
    )


def test_group_conversation_id_matches_the_route_pattern() -> None:
    assert re.fullmatch(
        r"conv_[0-9a-f]{32}",
        generate_group_conversation_id(),
    )


def test_group_conversation_ids_are_unique_per_call() -> None:
    """群聊不像单聊那样由成员推导,每次建群都必须是新会话。"""
    assert generate_group_conversation_id() != generate_group_conversation_id()
