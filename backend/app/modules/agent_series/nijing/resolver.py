"""把用户嘴里的「桌腿」对到账本里的一条物料。纯代码,不猜。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class ItemLike(Protocol):
    id: Any
    kind: str
    code: str
    name: str
    unit: str
    is_archived: bool


@dataclass(frozen=True)
class Resolution:
    status: str  # "one" | "none" | "many"
    matches: list[Any]
    suggestions: list[Any]


def _norm(value: str) -> str:
    return re.sub(r"[\s\-_·/]+", "", (value or "")).casefold()


def resolve_item(text: str | None, items: list[Any], *, kinds: tuple[str, ...] | None = None) -> Resolution:
    """精确 code → 精确 name → 归一后相等 → 唯一包含。多命中列出;0 命中给 3 个最像的。"""
    pool = [i for i in items if not i.is_archived and (kinds is None or i.kind in kinds)]
    query = _norm(text or "")
    if not query:
        return Resolution("none", [], pool[:3])
    for pick in (
        lambda i: i.code.casefold() == (text or "").strip().casefold(),
        lambda i: i.name == (text or "").strip(),
        lambda i: _norm(i.code) == query or _norm(i.name) == query,
    ):
        hits = [i for i in pool if pick(i)]
        if len(hits) == 1:
            return Resolution("one", hits, [])
        if len(hits) > 1:
            return Resolution("many", hits, [])
    contains = [i for i in pool if query in _norm(i.name) or query in _norm(i.code)]
    if len(contains) == 1:
        return Resolution("one", contains, [])
    if len(contains) > 1:
        return Resolution("many", contains, [])
    # 最像的三个:按公共字符数粗排
    scored = sorted(pool, key=lambda i: -len(set(query) & set(_norm(i.name) + _norm(i.code))))
    return Resolution("none", [], scored[:3])


def unit_matches(said: str | None, actual: str) -> bool:
    """用户没说单位就不较真;说了就必须一致(件/个/只 这类近义不做映射,宁可问)。"""
    if not said:
        return True
    return _norm(said) == _norm(actual)
