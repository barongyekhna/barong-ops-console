"""霓旌的手:进程内直接调 M 系列 service,以说话人的身份。

这里没有任何「她自己的」权限——每个函数都拿说话人的 User 过
``service.user_may_access``,跟 HTTP 路由用的是同一个门。写入分两步:
``build_*_card`` 只算不写(出确认卡),``execute_card`` 在用户确认后才落单。
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ....models.user import User
from ...m_series.inventory import schemas as S
from ...m_series.inventory import service
from ...m_series.inventory.service import FactoryContext, InsufficientStock, MfgError
from .constants import AGENT_DISPLAY_NAME
from .intents import Intent
from .resolver import resolve_item, unit_matches

KIND_LABEL = {"part": "物料", "product": "成品"}
DOC_LABEL = {"receipt": "入库", "production": "生产", "shipment": "发货", "adjustment": "盘点调整"}


class NotAuthorized(Exception):
    pass


class NeedsClarification(Exception):
    """问回去。message 就是要回给用户的话。"""


@dataclass
class Card:
    card_id: str
    kind: str  # receipt | production | shipment | adjustment | undo
    speaker_id: str
    conversation_id: str
    text: str
    created_at: float
    # 执行所需
    item_id: str | None = None
    qty: str | None = None
    note: str | None = None
    reason: str | None = None
    reversals: list[dict[str, str]] = field(default_factory=list)  # undo 用:[{item_id, qty_delta}]
    undo_doc_no: str | None = None
    request_text: str | None = None  # 开卡那句原话;落单时记进备注的是它,不是「确认」两个字

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Card":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})  # type: ignore[arg-type]


def fmt(value: Decimal | str | int) -> str:
    n = Decimal(str(value))
    if n == n.to_integral_value():
        return f"{int(n):,}"
    return f"{n.normalize():,f}"


def authorize(db: Session, speaker: User) -> FactoryContext:
    ctx = service.resolve_factory_context(db)
    if not getattr(speaker, "is_active", True) or not service.user_may_access(speaker, ctx):
        raise NotAuthorized()
    return ctx


# ---------------------------------------------------------------- 查


def stock_reply(db: Session, ctx: FactoryContext, intent: Intent) -> str:
    rows = service.stock_rows(db, ctx)
    if intent.item:
        res = resolve_item(intent.item, rows)
        if res.status == "one":
            r = res.matches[0]
            return f"{r.name}({r.code})现有 {fmt(r.stock)} {r.unit}。"
        if res.status == "many":
            return "你说的是哪个?\n" + "\n".join(f"  {r.code} {r.name}:{fmt(r.stock)} {r.unit}" for r in res.matches)
        return _not_found(intent.item, res.suggestions)
    if not rows:
        return "账上还没有任何物料或成品。"
    parts = [r for r in rows if r.kind == "part"]
    prods = [r for r in rows if r.kind == "product"]
    out = []
    if prods:
        out.append("成品:\n" + "\n".join(f"  {r.code} {r.name}:{fmt(r.stock)} {r.unit}" for r in prods))
    if parts:
        out.append("物料:\n" + "\n".join(f"  {r.code} {r.name}:{fmt(r.stock)} {r.unit}" for r in parts))
    return "\n".join(out)


def documents_reply(db: Session, ctx: FactoryContext, intent: Intent) -> str:
    item_id = None
    if intent.item:
        res = resolve_item(intent.item, service.list_items(db, ctx, include_archived=True))
        if res.status == "one":
            item_id = res.matches[0].id
    docs, total = service.list_documents(db, ctx, doc_type=None, item_id=item_id, limit=8, offset=0)
    if not docs:
        return "还没有单据。"
    lines = [f"最近 {len(docs)} 张(共 {total}):"]
    for d in docs:
        lines.append(f"  {d.doc_no} {DOC_LABEL.get(d.doc_type, d.doc_type)} · {_summarize(d)} · {d.actor_name} · {d.created_at:%m-%d %H:%M}")
    return "\n".join(lines)


def _summarize(doc: Any) -> str:
    p = doc.payload_json or {}
    if doc.doc_type == "receipt":
        return ",".join(f"{l['code']} +{fmt(l['qty'])}" for l in p.get("lines", []))
    if doc.doc_type in ("production", "shipment"):
        prod = p.get("product") or {}
        sign = "+" if doc.doc_type == "production" else "−"
        return f"{prod.get('code')} {sign}{fmt(prod.get('qty', 0))}"
    item = p.get("item") or {}
    delta = Decimal(str(p.get("qty_delta", 0)))
    return f"{item.get('code')} {'+' if delta > 0 else ''}{fmt(delta)}"


def _not_found(said: str, suggestions: list[Any]) -> str:
    hint = ""
    if suggestions:
        hint = "\n账上比较像的有:\n" + "\n".join(f"  {s.code} {s.name}({s.unit})" for s in suggestions)
    return f"库里没有叫「{said}」的物料或成品。{hint}\n要新建的话请去控制台「库存」里建,我不碰主档。"


# ---------------------------------------------------------------- 出卡(只算不写)


def _pick_item(db: Session, ctx: FactoryContext, intent: Intent, kinds: tuple[str, ...]) -> Any:
    if not intent.item:
        raise NeedsClarification("没听清是哪个物料/成品,请把名称或编码说一下。")
    rows = service.stock_rows(db, ctx)
    res = resolve_item(intent.item, rows, kinds=kinds)
    if res.status == "none":
        raise NeedsClarification(_not_found(intent.item, res.suggestions))
    if res.status == "many":
        raise NeedsClarification(
            "你说的是哪个?请用编码再说一遍:\n"
            + "\n".join(f"  {r.code} {r.name}(现有 {fmt(r.stock)} {r.unit})" for r in res.matches)
        )
    item = res.matches[0]
    if not unit_matches(intent.unit, item.unit):
        raise NeedsClarification(
            f"{item.name}({item.code})的单位是「{item.unit}」,你说的是「{intent.unit}」。是要按 {item.unit} 算吗?请重新说一遍。"
        )
    return item


CARD_MARKER_PREFIX = "⟦card:"


def _card_footer(card_id: str) -> str:
    """最后一行是机器标记:通讯前端认出它就渲染成带「确认/取消」按钮的卡片,
    按钮替用户发「确认 #id」/「取消 #id」。别的客户端看到的仍是可读文本。"""
    return f"回「确认」执行,回「取消」作废(30 分钟后自动作废)。\n{CARD_MARKER_PREFIX}{card_id}⟧"


def build_card(
    db: Session,
    ctx: FactoryContext,
    *,
    intent: Intent,
    speaker: User,
    conversation_id: str,
    now: float,
) -> Card:
    card_id = uuid.uuid4().hex[:4]
    if intent.qty is None:
        raise NeedsClarification("没听清数量,请用阿拉伯数字再说一遍。")
    qty = intent.qty

    if intent.intent == "receipt":
        if qty <= 0:
            raise NeedsClarification("入库数量得是正数。")
        item = _pick_item(db, ctx, intent, ("part", "product"))
        text = (
            f"【待确认 #{card_id}】入库\n"
            f"  {item.code} {item.name}  +{fmt(qty)} {item.unit}\n"
            f"  现有 {fmt(item.stock)} → {fmt(Decimal(str(item.stock)) + qty)}\n"
            + (f"  备注:{intent.note}\n" if intent.note else "")
            + _card_footer(card_id)
        )
        return Card(card_id, "receipt", str(speaker.id), conversation_id, text, now, item_id=str(item.id), qty=str(qty), note=intent.note)

    if intent.intent == "production":
        if qty <= 0:
            raise NeedsClarification("生产数量得是正数。")
        item = _pick_item(db, ctx, intent, ("product",))
        try:
            preview = service.preview_production(db, ctx, item.id, qty)
        except MfgError as exc:
            raise NeedsClarification(str(exc)) from exc
        if not preview.feasible:
            short = [r for r in preview.requirements if r.short > 0]
            raise NeedsClarification(
                f"物料不够,生产 {fmt(qty)} {item.unit} {item.name} 做不了,没有登记:\n"
                + "\n".join(f"  {r.name}({r.code}) 需要 {fmt(r.required)} 现有 {fmt(r.available)} 缺 {fmt(r.short)} {r.unit}" for r in short)
                + "\n先入库再说。"
            )
        lines = "\n".join(
            f"  − {r.name}({r.code}) {fmt(r.required)} {r.unit}" + ("(按箱,向上取整)" if r.mode == "per_carton" else "") + f"  剩 {fmt(r.available - r.required)}"
            for r in preview.requirements
        )
        text = (
            f"【待确认 #{card_id}】生产\n"
            f"  {item.code} {item.name}  +{fmt(qty)} {item.unit}(现有 {fmt(item.stock)} → {fmt(Decimal(str(item.stock)) + qty)})\n"
            f"  将扣物料:\n{lines}\n"
            + (f"  备注:{intent.note}\n" if intent.note else "")
            + _card_footer(card_id)
        )
        return Card(card_id, "production", str(speaker.id), conversation_id, text, now, item_id=str(item.id), qty=str(qty), note=intent.note)

    if intent.intent == "shipment":
        if qty <= 0:
            raise NeedsClarification("发货数量得是正数。")
        item = _pick_item(db, ctx, intent, ("product",))
        stock = Decimal(str(item.stock))
        if stock < qty:
            raise NeedsClarification(f"{item.name}({item.code})现有 {fmt(stock)} {item.unit},不够发 {fmt(qty)}。没有登记。")
        text = (
            f"【待确认 #{card_id}】发货\n"
            f"  {item.code} {item.name}  −{fmt(qty)} {item.unit}\n"
            f"  现有 {fmt(stock)} → {fmt(stock - qty)}\n"
            + (f"  备注:{intent.note}\n" if intent.note else "")
            + _card_footer(card_id)
        )
        return Card(card_id, "shipment", str(speaker.id), conversation_id, text, now, item_id=str(item.id), qty=str(qty), note=intent.note)

    if intent.intent == "adjustment":
        if qty == 0:
            raise NeedsClarification("调整量不能是 0。")
        reason = (intent.reason or intent.note or "").strip()
        if not reason:
            raise NeedsClarification("盘点调整必须说原因(比如「盘点少了」「入库时多记了」),请连原因一起再说一遍。")
        item = _pick_item(db, ctx, intent, ("part", "product"))
        stock = Decimal(str(item.stock))
        after = stock + qty
        if after < 0:
            raise NeedsClarification(f"{item.name} 现有 {fmt(stock)} {item.unit},调 {fmt(qty)} 会变成负数,没有登记。")
        text = (
            f"【待确认 #{card_id}】盘点调整\n"
            f"  {item.code} {item.name}  {'+' if qty > 0 else ''}{fmt(qty)} {item.unit}\n"
            f"  现有 {fmt(stock)} → {fmt(after)}\n"
            f"  原因:{reason}\n"
            + _card_footer(card_id)
        )
        return Card(card_id, "adjustment", str(speaker.id), conversation_id, text, now, item_id=str(item.id), qty=str(qty), reason=reason)

    raise NeedsClarification("这个我不会。")


def build_undo_card(
    db: Session,
    ctx: FactoryContext,
    *,
    intent: Intent,
    speaker: User,
    conversation_id: str,
    now: float,
) -> Card:
    """撤销 = 反向盘点调整。只撤说话人自己最近的一张(或他点名的单号)。"""
    docs, _ = service.list_documents(db, ctx, doc_type=None, item_id=None, limit=50, offset=0)
    target = None
    if intent.doc_ref:
        ref = intent.doc_ref.strip().upper()
        target = next((d for d in docs if d.doc_no.upper() == ref), None)
        if target is None:
            raise NeedsClarification(f"最近 50 张单里没有 {ref}。")
    else:
        target = next((d for d in docs if d.actor_user_id == str(speaker.id) and not (d.payload_json or {}).get("reversal_of")), None)
        if target is None:
            raise NeedsClarification("没找到你最近开的单。")
    if (target.payload_json or {}).get("reversal_of"):
        raise NeedsClarification(f"{target.doc_no} 本身就是一张冲销单,不能再冲。")
    _, movements = service.get_document(db, ctx, target.id)
    stocks = service.stock_of(db, ctx, [m.item_id for m in movements])
    reversals = []
    lines = []
    for m in movements:
        delta = -Decimal(str(m.qty_delta))
        after = stocks[m.item_id] + delta
        if after < 0:
            raise NeedsClarification(
                f"冲销 {target.doc_no} 会让 {m.item_name} 变成 {fmt(after)} {m.item_unit}(负数),做不了。"
            )
        reversals.append({"item_id": str(m.item_id), "qty_delta": str(delta)})
        lines.append(f"  {m.item_code} {m.item_name}  {'+' if delta > 0 else ''}{fmt(delta)} {m.item_unit}(→ {fmt(after)})")
    card_id = uuid.uuid4().hex[:4]
    text = (
        f"【待确认 #{card_id}】冲销 {target.doc_no}({DOC_LABEL.get(target.doc_type, target.doc_type)})\n"
        "  将开反向盘点调整:\n" + "\n".join(lines) + "\n" + _card_footer(card_id)
    )
    return Card(card_id, "undo", str(speaker.id), conversation_id, text, now, reversals=reversals, undo_doc_no=target.doc_no, reason=f"冲销 {target.doc_no}")


# ---------------------------------------------------------------- 执行(用户确认后)


def _note(card: Card, speaker: User, original_text: str, record_id: str) -> str:
    base = (card.note or "").strip()
    said = (card.request_text or original_text)[:120]
    tag = f"[{AGENT_DISPLAY_NAME} · {getattr(speaker, 'username', speaker.id)} 原话:{said} 确认:c19:{record_id}]"
    return f"{base} {tag}".strip()


def execute_card(
    db: Session,
    ctx: FactoryContext,
    *,
    card: Card,
    speaker: User,
    original_text: str,
    record_id: str,
) -> tuple[str, list[str]]:
    """落单。返回 (回复文本, 单号列表)。InsufficientStock/MfgError 往上抛,调用方转述。"""
    note = _note(card, speaker, original_text, record_id)
    if card.kind == "receipt":
        doc = service.receipt(db, ctx, user=speaker, payload=S.ReceiptCreate(lines=[S.ReceiptLine(item_id=card.item_id, qty=Decimal(card.qty))], note=note))
        return _after(db, ctx, f"已入库 {doc.doc_no}", [card.item_id]), [doc.doc_no]
    if card.kind == "production":
        doc = service.production(db, ctx, user=speaker, payload=S.ProductionCreate(product_id=card.item_id, qty=Decimal(card.qty), note=note))
        consumed = doc.payload_json.get("bom_snapshot", [])
        item_ids = [card.item_id] + [r["item_id"] for r in consumed]
        return _after(db, ctx, f"已登记生产 {doc.doc_no}", item_ids), [doc.doc_no]
    if card.kind == "shipment":
        doc = service.shipment(db, ctx, user=speaker, payload=S.ShipmentCreate(product_id=card.item_id, qty=Decimal(card.qty), note=note))
        return _after(db, ctx, f"已发货 {doc.doc_no}", [card.item_id]), [doc.doc_no]
    if card.kind == "adjustment":
        doc = service.adjustment(db, ctx, user=speaker, payload=S.AdjustmentCreate(item_id=card.item_id, qty_delta=Decimal(card.qty), reason=f"{card.reason} {_note(card, speaker, original_text, record_id)}".strip()))
        return _after(db, ctx, f"已调整 {doc.doc_no}", [card.item_id]), [doc.doc_no]
    if card.kind == "undo":
        doc_nos = []
        for rev in card.reversals:
            doc = service.adjustment(
                db, ctx, user=speaker,
                payload=S.AdjustmentCreate(item_id=rev["item_id"], qty_delta=Decimal(rev["qty_delta"]), reason=f"{card.reason} {_note(card, speaker, original_text, record_id)}".strip()),
            )
            doc.payload_json = {**doc.payload_json, "reversal_of": card.undo_doc_no}
            db.add(doc)
            db.commit()
            doc_nos.append(doc.doc_no)
        return _after(db, ctx, f"已冲销 {card.undo_doc_no}(调整单 {', '.join(doc_nos)})", [r["item_id"] for r in card.reversals]), doc_nos
    raise MfgError("未知的卡类型")


def _after(db: Session, ctx: FactoryContext, headline: str, item_ids: list[str]) -> str:
    from uuid import UUID

    ids = [UUID(str(i)) for i in item_ids]
    rows = {str(r.id): r for r in service.stock_rows(db, ctx, include_archived=True)}
    stocks = service.stock_of(db, ctx, ids)
    lines = []
    for i in ids:
        r = rows.get(str(i))
        if r:
            lines.append(f"  {r.name}({r.code})现有 {fmt(stocks[i])} {r.unit}")
    return headline + "。\n" + "\n".join(lines)
