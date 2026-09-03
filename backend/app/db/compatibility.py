from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from threading import Lock


# 进程级缓存。
#
# 为什么可以缓存：这两个函数回答的是「这张表/这一列存在吗」，而 schema 变更
# 必然伴随发版重启（本项目还有启动门 enforce_migration_safety 在管迁移一致性）。
# 同一个进程里，答案不会中途改变。
#
# 为什么必须缓存：inspect(bind).has_table() 是**实时查询系统目录**，SQLAlchemy
# 不做缓存。而鉴权热路径上有 8 处调用（org_context 2 / permission 2 /
# auth_service 1 / data_isolation 2 / users 仓储 1），每个已鉴权请求全跑一遍。
# 2026-09-01 实测：完整中间件链每请求约 14 次数据库往返、约 90ms，
# 而绕开中间件的只要 0.1 次 —— 这是全站每个登录后请求都要先付的地板。
#
# middleware/data_isolation.py 的 C05B 探针一直是按进程缓存的，这里只是把
# 同样的做法补给其余探测。
_TABLE_CACHE: dict[str, bool] = {}
_COLUMN_CACHE: dict[tuple[str, str], bool] = {}
_PROBE_LOCK = Lock()


def reset_schema_probe_cache_for_tests() -> None:
    """清空缓存。

    测试里改了 schema（建表/加列）之后必须调用，否则读到的是上一次的答案。
    C05B 那个探针的教训：有钩子却零调用方，于是「加一列静默改变全站行为」
    没有任何测试拦得住。
    """
    with _PROBE_LOCK:
        _TABLE_CACHE.clear()
        _COLUMN_CACHE.clear()


def table_exists(db: Session, table_name: str) -> bool:
    cached = _TABLE_CACHE.get(table_name)
    if cached is not None:
        return cached
    exists = inspect(db.get_bind()).has_table(table_name)
    with _PROBE_LOCK:
        _TABLE_CACHE[table_name] = exists
    return exists


def column_exists(db: Session, table_name: str, column_name: str) -> bool:
    key = (table_name, column_name)
    cached = _COLUMN_CACHE.get(key)
    if cached is not None:
        return cached
    inspector = inspect(db.get_bind())
    if not inspector.has_table(table_name):
        exists = False
    else:
        exists = any(
            column.get("name") == column_name
            for column in inspector.get_columns(table_name)
        )
    with _PROBE_LOCK:
        _COLUMN_CACHE[key] = exists
    return exists


def is_missing_table_error(exc: BaseException, table_name: str) -> bool:
    if not isinstance(exc, SQLAlchemyError):
        return False
    message = str(exc).lower()
    return table_name.lower() in message and (
        "undefinedtable" in message or "does not exist" in message
    )
