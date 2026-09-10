"""先进先出取价——**纯函数,不碰数据库**,照 ``inventory.service.required_for`` 的路子。

为什么是 FIFO 而不是"最近一批入库价":发货一定是先发最早那批,那批当初花了多少钱
是既成事实。用最新价去解释一批老货的成本,数字好看但不是真的。

为什么不建批次消耗表:``mfg_movements`` 已经是一条完整的时间序列,队头能算出来——

    累计消耗量 C = 所有负向流水之和的绝对值
    按时间升序累加入库批次,第一个让累计入库量超过 C 的批次就是队头

这和"当前库存 = 流水求和"是同一个思路:不存一个可以被手改、可以跟流水对不上的
冗余字段。一个物料一年几百条流水,算起来毫无压力。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

ZERO = Decimal("0")
_QTY_EXP = Decimal("0.001")
_MONEY_EXP = Decimal("0.0001")


def q_qty(value: Decimal) -> Decimal:
    return value.quantize(_QTY_EXP, rounding=ROUND_HALF_UP)


def q_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_EXP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Batch:
    """一个入库批次 = 一条正向流水。

    ``unit_price is None`` 的批次是"无价批次"——盘盈进来的料没有采购价。它照样占
    位置、照样被消耗,但队头落到它身上时该行判缺价,绝不拿 0 顶上。
    """

    movement_id: UUID
    qty: Decimal
    unit_price: Decimal | None
    unit_freight: Decimal | None
    created_at: datetime
    is_estimated: bool = False


@dataclass(frozen=True)
class DrawnBatch:
    """本次从某一批取走了多少。"""

    movement_id: UUID
    qty: Decimal
    unit_price: Decimal | None
    unit_freight: Decimal | None
    created_at: datetime
    is_estimated: bool
    # 库存不够时按最新一批的价往外推的部分,不是真实批次
    is_extrapolated: bool = False

    def as_dict(self) -> dict[str, str | bool | None]:
        """写进快照的 ``batch_breakdown``。

        一个加权出来的 12.40,如果不把"哪几批、各多少、各什么价"一起留下,三个月
        后没人解释得清它怎么来的。
        """
        return {
            "movement_id": str(self.movement_id),
            "qty": str(self.qty),
            # 无价批次写 None,不写空串:空串会被当成"有值但解析不了",
            # None 才如实表达"这一批就是没有价格"
            "unit_price": None if self.unit_price is None else str(self.unit_price),
            "unit_freight": (
                None if self.unit_freight is None else str(self.unit_freight)
            ),
            "at": self.created_at.isoformat(),
            "estimated": self.is_estimated,
            "extrapolated": self.is_extrapolated,
        }


@dataclass(frozen=True)
class FifoDraw:
    """按 FIFO 取 ``need`` 之后的结果。"""

    rows: tuple[DrawnBatch, ...]
    need: Decimal
    # 从真实库存批次里取到的量
    drawn_from_stock: Decimal
    # 库存不够、按最新一批价外推的量
    extrapolated: Decimal
    # 取到的批次里有没有无价的(盘盈批次)
    has_missing_price: bool
    # 取到的批次里有没有暂估价的(发票还没来)
    has_estimated_price: bool

    @property
    def crosses_batches(self) -> bool:
        return len(self.rows) > 1

    @property
    def unit_price(self) -> Decimal | None:
        """加权平均单价。任何一批无价 → 返回 None,不用 0 顶。"""
        return self._weighted(lambda row: row.unit_price)

    @property
    def unit_freight(self) -> Decimal | None:
        """加权平均单位运费。运费缺失当 0 处理——没填运费就是没运费,
        这跟"没填单价"不是一回事(后者是不知道,前者是知道且为零)。"""
        if self.has_missing_price:
            return None
        total_qty = sum((row.qty for row in self.rows), ZERO)
        if total_qty <= ZERO:
            return None
        weighted = sum(
            (row.qty * (row.unit_freight or ZERO) for row in self.rows), ZERO
        )
        return q_money(weighted / total_qty)

    def _weighted(self, pick) -> Decimal | None:
        if self.has_missing_price or not self.rows:
            return None
        total_qty = sum((row.qty for row in self.rows), ZERO)
        if total_qty <= ZERO:
            return None
        weighted = sum((row.qty * (pick(row) or ZERO) for row in self.rows), ZERO)
        return q_money(weighted / total_qty)

    def breakdown(self) -> list[dict[str, str | bool | None]]:
        return [row.as_dict() for row in self.rows]


def queue_after_consumption(
    batches: Sequence[Batch], consumed: Decimal
) -> list[Batch]:
    """把 ``consumed`` 从队列前端吃掉,返回还剩下的批次(队头在前)。

    ``batches`` 必须按 ``created_at`` 升序。被吃掉一半的批次会返回剩余数量。
    """
    remaining = consumed if consumed > ZERO else ZERO
    rest: list[Batch] = []
    for batch in batches:
        if remaining <= ZERO:
            rest.append(batch)
            continue
        if batch.qty <= remaining:
            remaining -= batch.qty
            continue
        rest.append(
            Batch(
                movement_id=batch.movement_id,
                qty=q_qty(batch.qty - remaining),
                unit_price=batch.unit_price,
                unit_freight=batch.unit_freight,
                created_at=batch.created_at,
                is_estimated=batch.is_estimated,
            )
        )
        remaining = ZERO
    return rest


def draw(
    batches: Sequence[Batch], *, consumed: Decimal, need: Decimal
) -> FifoDraw:
    """从队头取 ``need`` 的量。

    ``batches`` 按时间升序的全部入库批次,``consumed`` 是历史累计消耗量。

    **库存不够时按最新一批的价外推**,而不是判缺价:这个函数服务的是"如果现在生产
    这个产品要花多少钱"的预估表,缺料是生产模块该拦的事,不是报价该回答的问题。
    外推出来的行会标 ``is_extrapolated``,前端要让人看得出来哪部分是推的。

    一批都没有(``batches`` 为空)才真的取不到价——那时返回空 rows 且
    ``has_missing_price=True``,由调用方决定要不要退回参考价。
    """
    want = need if need > ZERO else ZERO
    queue = queue_after_consumption(batches, consumed)
    rows: list[DrawnBatch] = []
    left = want
    drawn = ZERO

    for batch in queue:
        if left <= ZERO:
            break
        take = batch.qty if batch.qty <= left else left
        rows.append(
            DrawnBatch(
                movement_id=batch.movement_id,
                qty=q_qty(take),
                unit_price=batch.unit_price,
                unit_freight=batch.unit_freight,
                created_at=batch.created_at,
                is_estimated=batch.is_estimated,
            )
        )
        drawn += take
        left -= take

    extrapolated = q_qty(left) if left > ZERO else ZERO
    if extrapolated > ZERO and batches:
        # 外推用**最新**一批的价:它回答的是"再买要花多少",这是这部分唯一诚实的口径
        newest = batches[-1]
        rows.append(
            DrawnBatch(
                movement_id=newest.movement_id,
                qty=extrapolated,
                unit_price=newest.unit_price,
                unit_freight=newest.unit_freight,
                created_at=newest.created_at,
                is_estimated=newest.is_estimated,
                is_extrapolated=True,
            )
        )

    has_missing = (not rows and want > ZERO) or any(
        row.unit_price is None for row in rows
    )
    return FifoDraw(
        rows=tuple(rows),
        need=q_qty(want),
        drawn_from_stock=q_qty(drawn),
        extrapolated=extrapolated,
        has_missing_price=has_missing,
        has_estimated_price=any(row.is_estimated for row in rows),
    )
