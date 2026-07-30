"""开发信业务规则:补邮箱、渲染模板、生成草稿。

三条硬规则(都是用户的业务约束,不是文风):
1. **系统永不自动发送**。草稿箱只生成给人过目 + 复制,发送动作在用户手上。
2. **首封绝不带附件**,图册只在"要价格表"那封回复里发。
3. **模板里绝不出现信用卡/PayPal**,存模板时硬校验拦截。
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..prospects.models import PROSPECT_STATUS_APPROVED, B2BProspect
from . import suppression
from . import templates_catalog as catalog
from .email_finder import find_email_on_site
from .models import (
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_SENT,
    B2BEmailDraft,
    B2BEmailTemplate,
)

logger = logging.getLogger(__name__)

SENDER_NAME = "Barong"
SENDER_DOMAIN = "barongsupply.com"


class OutreachError(RuntimeError):
    """人能看懂的错误,直接冒到界面上。"""


# --------------------------------------------------------------------------
# 模板库
# --------------------------------------------------------------------------


def seed_templates(db: Session) -> int:
    """把内置模板灌进库。幂等:已存在的不动(用户改过的不许被覆盖)。"""
    added = 0
    for spec in catalog.TEMPLATE_CATALOG:
        store_type = spec["store_type"] or ""
        exists = db.scalar(
            select(B2BEmailTemplate)
            .where(B2BEmailTemplate.kind == spec["kind"])
            .where(B2BEmailTemplate.language == spec["language"])
            .where(B2BEmailTemplate.store_type == store_type)
        )
        if exists is not None:
            continue
        db.add(
            B2BEmailTemplate(
                kind=spec["kind"],
                language=spec["language"],
                store_type=store_type,
                subject=spec["subject"],
                body=spec["body"],
                is_builtin=True,
            )
        )
        db.flush()  # session 是 autoflush=False,不 flush 下一轮查重看不见
        added += 1
    db.commit()
    return added


def resolve_template(
    db: Session,
    *,
    kind: str,
    language: str,
    store_type: str | None = None,
) -> B2BEmailTemplate | None:
    """先找店型专属,没有就退回全店型通用的。

    这样新店型不写专属文案也永远发得出信;想为某个店型定制,加一条专属的
    就自动生效,不用改代码。
    """
    stmt = (
        select(B2BEmailTemplate)
        .where(B2BEmailTemplate.kind == kind)
        .where(B2BEmailTemplate.language == language)
        .where(B2BEmailTemplate.active.is_(True))
    )
    if store_type:
        specific = db.scalar(
            stmt.where(B2BEmailTemplate.store_type == store_type)
        )
        if specific is not None:
            return specific
    return db.scalar(stmt.where(B2BEmailTemplate.store_type == ""))


def save_template(
    db: Session,
    *,
    template_id: UUID,
    subject: str | None = None,
    body: str | None = None,
    active: bool | None = None,
) -> B2BEmailTemplate:
    row = db.get(B2BEmailTemplate, template_id)
    if row is None:
        raise OutreachError("模板不存在。")
    if subject is not None or body is not None:
        combined = f"{subject or row.subject}\n{body or row.body}"
        hit = catalog.forbidden_phrase_in(combined)
        if hit:
            raise OutreachError(
                f"模板里出现「{hit}」——B2B 只收电汇，"
                "接受信用卡/PayPal 等于把拒付风险全揽下来。这条不许写。"
            )
    if subject is not None:
        row.subject = subject
    if body is not None:
        row.body = body
    if active is not None:
        row.active = active
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------


def _contact_name(prospect: B2BProspect) -> str:
    """没有联系人姓名时,用 there——"Hi there" 比 "Dear Sir/Madam" 自然得多。"""
    name = (getattr(prospect, "contact_name", None) or "").strip()
    return name or "there"


def render(
    text: str,
    *,
    prospect: B2BProspect,
    product_line: str,
    personal_line: str,
) -> str:
    """把占位符换成真值。缺的一律留空,不报错。"""
    values = {
        "{store_name}": prospect.store_name or "",
        "{contact_name}": _contact_name(prospect),
        "{personal_line}": personal_line,
        "{product_line}": product_line,
        "{city}": prospect.city or "",
        "{sender_name}": SENDER_NAME,
        "{sender_domain}": SENDER_DOMAIN,
    }
    out = text or ""
    for token, value in values.items():
        out = out.replace(token, value)
    return out


def _product_line(products: list[dict]) -> str:
    """把货单写成一句英文短语。**内容全部来自类目树推导,不写死。**"""
    names = [str(p.get("name") or "").strip() for p in products if p.get("name")]
    names = [n for n in names if n][:3]
    if not names:
        return "a small range of consumer goods"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _fallback_personal_line(prospect: B2BProspect) -> str:
    """AI 没给个性化开头时的兜底。宁可平淡,也不能假装认识人家。"""
    place = prospect.city or ""
    category = (prospect.place_category or "shop").lower()
    where = f" in {place}" if place else ""
    return (
        f"I came across your {category}{where} and it looks like you pick "
        "your range yourself rather than just stocking the big brands — "
        "that's why I'm writing to you."
    )


# --------------------------------------------------------------------------
# 补邮箱
# --------------------------------------------------------------------------


def backfill_emails(
    db: Session,
    *,
    limit: int = 25,
    only_fit: bool = True,
) -> dict[str, object]:
    """抓官网联系页补邮箱。**免费,不消耗任何额度。**

    实测命中率约 30%——小零售店大多只放联系表单不公开邮箱,这是行业常态
    不是 bug。捞不到的还有电话可用,别指望这一步能补齐所有人。
    """
    stmt = (
        select(B2BProspect)
        .where(B2BProspect.email.is_(None))
        .where(B2BProspect.website.isnot(None))
        .order_by(B2BProspect.created_at)
        .limit(max(1, min(limit, 100)))
    )
    if only_fit:
        stmt = stmt.where(B2BProspect.screen_verdict == "fit")
    rows = list(db.scalars(stmt))
    if not rows:
        return {"checked": 0, "found": 0, "message": "没有需要补邮箱的客户。"}

    # 出网前抠成纯数据,网络阶段绝不碰 ORM(idle-in-transaction 踩过两次)
    targets = [(row.id, row.website) for row in rows]
    db.commit()

    found = 0
    for prospect_id, website in targets:
        email, path = find_email_on_site(website)
        if not email:
            continue
        row = db.get(B2BProspect, prospect_id)
        if row is None:
            continue
        row.email = email
        row.email_source = f"site{path or ''}"[:64]
        db.commit()
        found += 1

    return {
        "checked": len(targets),
        "found": found,
        "message": (
            f"查了 {len(targets)} 家，捞到 {found} 个邮箱。"
            "捞不到的多半只放联系表单——那些还有电话可以打。"
        ),
    }


# --------------------------------------------------------------------------
# 草稿箱
# --------------------------------------------------------------------------


def generate_drafts(
    db: Session,
    *,
    kind: str = catalog.KIND_FIRST_TOUCH,
    limit: int = 25,
) -> dict[str, object]:
    """给「已通过 + 有邮箱」的客户生成草稿。**只生成,不发送。**"""
    from ..prospects.service import _products_for_store_type

    stmt = (
        select(B2BProspect)
        .where(B2BProspect.status == PROSPECT_STATUS_APPROVED)
        .where(B2BProspect.email.isnot(None))
        .order_by(B2BProspect.created_at)
        .limit(max(1, min(limit, 100)))
    )
    rows = list(db.scalars(stmt))
    if not rows:
        return {
            "created": 0,
            "skipped": 0,
            "message": (
                "没有可生成的客户：需要「已通过审核」并且「有邮箱」。"
                "先去候选客户里点通过，再跑一次补邮箱。"
            ),
        }

    existing = {
        row.prospect_id
        for row in db.scalars(
            select(B2BEmailDraft).where(B2BEmailDraft.kind == kind)
        )
    }
    # 永不再发名单:一次取全量再在内存里比,逐条查库在 100 个候选上就是 100 次
    # 往返。说过"别发了"的人再收到信 = 直接被举报垃圾邮件 = 域名信誉毁掉。
    blocked = suppression.suppressed_set(db)
    products_cache: dict[str, list[dict]] = {}
    created = 0
    skipped = 0
    suppressed = 0

    for prospect in rows:
        if prospect.id in existing:
            skipped += 1
            continue
        if suppression.normalise(prospect.email) in blocked:
            suppressed += 1
            continue
        template = resolve_template(
            db,
            kind=kind,
            language=prospect.language or "en",
            store_type=prospect.store_type,
        )
        if template is None:
            skipped += 1
            continue
        if prospect.store_type not in products_cache:
            products_cache[prospect.store_type] = _products_for_store_type(
                db, prospect.store_type
            )
        products = products_cache[prospect.store_type]
        if not products:
            skipped += 1
            continue

        # AI 在筛选时顺手写好的开发信首句;没有就用兜底(平淡但不假装认识人家)
        personal = (prospect.personal_line or "").strip() or (
            _fallback_personal_line(prospect)
        )
        context = {
            "prospect": prospect,
            "product_line": _product_line(products),
            "personal_line": personal,
        }
        db.add(
            B2BEmailDraft(
                prospect_id=prospect.id,
                kind=kind,
                language=template.language,
                to_email=prospect.email,
                subject=render(template.subject, **context)[:255],
                # 合规落款在**渲染时**追加,不写进模板——法律要求的东西不该
                # 能被"改模板"删掉,而且旧模板不用重灌也自动带上。
                body=catalog.with_compliance_footer(
                    render(template.body, **context),
                    kind=kind,
                    language=template.language,
                ),
            )
        )
        db.flush()
        created += 1

    db.commit()
    if created:
        message = ""
    elif suppressed:
        message = "没有新草稿——符合条件的都在「永不再发」名单里。"
    else:
        message = "没有新草稿要生成。"
    return {
        "created": created,
        "skipped": skipped,
        "suppressed": suppressed,
        "message": message,
    }


def update_draft(
    db: Session,
    *,
    draft_id: UUID,
    subject: str | None = None,
    body: str | None = None,
    status: str | None = None,
) -> B2BEmailDraft:
    row = db.get(B2BEmailDraft, draft_id)
    if row is None:
        raise OutreachError("草稿不存在。")
    if subject is not None or body is not None:
        hit = catalog.forbidden_phrase_in(f"{subject or ''}\n{body or ''}")
        if hit:
            raise OutreachError(
                f"信里出现「{hit}」——B2B 只收电汇，这条不许写。"
            )
    if subject is not None:
        row.subject = subject[:255]
    if body is not None:
        row.body = body
    if status is not None:
        if status not in ("draft", "sent", "skipped"):
            raise OutreachError(f"未知状态：{status}")
        row.status = status
        if status == DRAFT_STATUS_SENT:
            from datetime import datetime, timezone

            row.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def list_drafts(
    db: Session,
    *,
    status: str | None = DRAFT_STATUS_DRAFT,
    limit: int = 100,
) -> list[B2BEmailDraft]:
    stmt = select(B2BEmailDraft).order_by(B2BEmailDraft.created_at)
    if status:
        stmt = stmt.where(B2BEmailDraft.status == status)
    return list(db.scalars(stmt.limit(max(1, min(limit, 300)))))
