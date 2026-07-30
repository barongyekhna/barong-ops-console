"""收款银行信息。**买家就是照着这几行去银行汇款的,所以它是 PI 的核心。**

存在数据库(复用 `b2b_site_settings` 那张 KV 表),**不进代码仓库**:
账号这种东西不该躺在 git 历史里,而且它本来就该是"设置一次"的运营数据。

⚠️ 这不是密钥——它印在发给买家的单子上,**本来就是要给对方看的**。所以走
普通设置而不是密钥管理:进密钥管理反而取不出来渲染。
"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.orm import Session

from ..website.models import B2BSiteSetting

PREFIX = "bank_"

FIELDS: tuple[tuple[str, str, bool], ...] = (
    # (key, 中文标签, 是否必填)
    ("beneficiary", "收款人名称（Beneficiary）", True),
    ("bank_name", "银行名称", True),
    ("swift", "SWIFT / BIC", True),
    ("account", "账号 / IBAN", True),
    ("bank_address", "银行地址", False),
    ("intermediary", "中转行（如果银行给了）", False),
)


class BankingProfile(TypedDict, total=False):
    beneficiary: str
    bank_name: str
    swift: str
    account: str
    bank_address: str
    intermediary: str


def read(db: Session) -> BankingProfile:
    rows = {
        row.key: row.value or ""
        for row in db.query(B2BSiteSetting).all()
        if str(row.key).startswith(PREFIX)
    }
    return {
        key: rows.get(f"{PREFIX}{key}", "") for key, _label, _required in FIELDS
    }  # type: ignore[return-value]


def write(db: Session, profile: dict[str, str]) -> BankingProfile:
    for key, _label, _required in FIELDS:
        if key not in profile:
            continue
        value = str(profile.get(key) or "").strip()[:200]
        full = f"{PREFIX}{key}"
        row = db.get(B2BSiteSetting, full)
        if row is None:
            db.add(B2BSiteSetting(key=full, value=value))
        else:
            row.value = value
    db.flush()
    return read(db)


def missing_required(profile: BankingProfile) -> list[str]:
    """还差哪些必填项。**没填全不许开单**——一张没有收款信息的 PI 是废纸,
    买家拿到只会回来问,反而显得不专业。"""
    return [
        label
        for key, label, required in FIELDS
        if required and not str(profile.get(key) or "").strip()
    ]
