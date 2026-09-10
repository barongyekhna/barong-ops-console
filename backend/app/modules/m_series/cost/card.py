"""出货成本明细的 C19 卡片文本。

C19 的记录服务只认 text/emoji/image/file(消息存在独立部署的 c19_record_service
里,加一种 content_type 要跨两个服务、两套迁移),所以卡片仍是**一条文本**:首行
``【出货明细 #a1b2】…``,末行机器标记 ``⟦cost:a1b2⟧``,中间是字段行。前端认出标记
就渲染成表格;别的客户端、通知摘要、以后翻聊天记录的人,看到的都还是一段能读懂的
文本。倪静的待确认卡和殷承岳的类目卡走的是同一条路子。

语法与 frontend/src/modules/c19/c19CostCard.ts 一一对应,改一边必须改另一边。

**price_only 口径在这里就不生成成本行**——不是前端藏起来。对方转发出去、复制文本、
截图,都漏不出成本,因为那些数字压根没进过这条消息。
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from . import models as C
from . import schemas as S

CARD_HEAD_PREFIX = "【出货明细 #"
CARD_MARKER_PREFIX = "⟦cost:"
SEP = "|"
MISSING = "—"

# C19 请求侧限 4000 字符(比 nginx 的 16KB 更紧)。留一点余量给结尾标记和换行。
MAX_CONTENT_CHARS = 3900


class CardTooLong(ValueError):
    """物料太多,一条消息装不下。"""


def card_token(sheet_no: str, recipient_user_id: str) -> str:
    return hashlib.sha1(
        f"{sheet_no}:{recipient_user_id}".encode("utf-8")
    ).hexdigest()[:4]


def _flat(value: str, limit: int = 60) -> str:
    """压成一行。卡片是行结构,正文里混进换行会把整张卡拆散。"""
    text = re.sub(r"\s+", " ", (value or "").strip())
    # 竖线是分隔符,名字里带竖线会把列数撑爆
    text = text.replace(SEP, "/")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _money(value: Decimal | None) -> str:
    return MISSING if value is None else f"{value:.2f}"


def _qty(value: Decimal | None) -> str:
    if value is None:
        return MISSING
    normalized = value.normalize()
    text = format(normalized, "f")
    return text


def render(
    sheet: C.MfgCostSheet,
    detail: S.CostSheetDetail,
    *,
    token: str,
    share_mode: str,
    preface: str | None = None,
) -> str:
    """把一份快照渲染成卡片文本。

    ``share_mode='price_only'`` 时只出产品、批量、出厂价、有效期四样——成本明细
    根本不进这条消息。
    """
    head = (
        f"{CARD_HEAD_PREFIX}{token}】{_flat(sheet.product_name)} "
        f"{_flat(sheet.product_code, 32)} × {_qty(sheet.batch_qty)} {sheet.product_unit}"
    )
    lines: list[str] = []
    if preface:
        lines.append(_flat(preface, 200))
    lines.append(head)
    lines.append(f"单号：{sheet.sheet_no}")
    lines.append(
        f"批量：{_qty(sheet.batch_qty)} {sheet.product_unit}"
        + ("（预估，未生产）" if sheet.basis == C.BASIS_ESTIMATE else "")
    )

    if share_mode == C.SHARE_MODE_FULL:
        for line in detail.materials:
            lines.append(
                SEP.join(
                    [
                        "料",
                        _flat(line.code or "", 32),
                        _flat(line.name, 40),
                        f"{_qty(line.qty)} {line.unit}",
                        _money(line.unit_price),
                        _money(line.unit_freight),
                        _money(line.line_material),
                    ]
                )
            )
        for line in detail.labor:
            lines.append(
                SEP.join(
                    [
                        "工",
                        _flat(line.name, 40),
                        "每批" if line.mode == C.LABOR_MODE_PER_BATCH else "每件",
                        _money(line.unit_price),
                        _money(line.line_total),
                    ]
                )
            )
        lines.append(
            "计："
            + " / ".join(
                [
                    f"物料 {_money(sheet.material_total)}",
                    f"运费 {_money(sheet.freight_total)}",
                    f"人工 {_money(sheet.labor_total)}",
                    f"单位成本 {_money(sheet.unit_cost)}",
                ]
            )
        )
        if sheet.missing_price_count:
            # 缺价必须说出来。少了这一句,对方看到的是一张"合计是横杠"的表,
            # 会以为是显示故障,而不是"这里真的没有价格"。
            lines.append(f"缺价：{sheet.missing_price_count} 项，合计不出数")

    price_bits = [f"出厂价 {_money(sheet.sale_price)}"]
    if (
        share_mode == C.SHARE_MODE_FULL
        and sheet.sale_price is not None
        and sheet.unit_cost is not None
    ):
        margin = sheet.sale_price - sheet.unit_cost
        price_bits.append(f"单位毛利 {_money(margin)}")
        if sheet.sale_price > 0:
            rate = margin / sheet.sale_price * Decimal("100")
            price_bits.append(f"毛利率 {rate:.1f}%")
    lines.append("价：" + " / ".join(price_bits))

    lines.append(
        f"效：{sheet.expires_on.isoformat()}"
        + ("（含铜价类波动料）" if sheet.has_volatile else "")
    )
    lines.append(f"{CARD_MARKER_PREFIX}{token}⟧")

    content = "\n".join(lines)
    if len(content) > MAX_CONTENT_CHARS:
        raise CardTooLong(
            f"物料条目太多,一条消息装不下({len(content)} 字符,上限 "
            f"{MAX_CONTENT_CHARS})。请拆分产品或改用「仅出厂价」分享。"
        )
    return content
