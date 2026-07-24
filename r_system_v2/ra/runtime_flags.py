"""R-A 运行时开关(数据库标志位,界面实时切换,不用发版)。

2026-07-23 用户拍板:R-A 自动巡航按次烧钱(DeepSeek+4sapi),要一个界面
开关想停就停想开就开;R-W(Keepa 按月订阅)不受影响。

标志位存 ra_runtime_flags,与 quota_ledger 同样的 CREATE TABLE IF NOT
EXISTS 姿势——零迁移。auto_cruise 每轮 tick 先读 auto_cruise_paused。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

FLAG_CRUISE_PAUSED = "auto_cruise_paused"


def ensure_flags_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ra_runtime_flags (
              flag TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by TEXT
            )
            """
        )
    )


def get_flag(db: Session, flag: str, *, default: str = "") -> str:
    ensure_flags_schema(db)
    row = db.execute(
        text("SELECT value FROM ra_runtime_flags WHERE flag = :f"), {"f": flag}
    ).scalar()
    return str(row) if row is not None else default


def set_flag(
    db: Session, flag: str, value: str, *, actor: str | None = None
) -> None:
    ensure_flags_schema(db)
    db.execute(
        text(
            """
            INSERT INTO ra_runtime_flags (flag, value, updated_by)
            VALUES (:f, :v, :a)
            ON CONFLICT (flag) DO UPDATE SET
              value = excluded.value,
              updated_at = CURRENT_TIMESTAMP,
              updated_by = excluded.updated_by
            """
        ),
        {"f": flag, "v": value, "a": actor},
    )


def is_cruise_paused(db: Session) -> bool:
    """自动巡航是否暂停(默认 True:上线即停,主动权交给用户)。"""
    return get_flag(db, FLAG_CRUISE_PAUSED, default="true").strip().lower() == "true"


def set_cruise_paused(db: Session, paused: bool, *, actor: str | None = None) -> None:
    set_flag(db, FLAG_CRUISE_PAUSED, "true" if paused else "false", actor=actor)
