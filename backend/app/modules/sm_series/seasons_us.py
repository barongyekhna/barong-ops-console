"""美国季节表（第一版写死；以后接 Pinterest Trends 再换成数据）。

Pinterest 的搜索比现实早 45–60 天，所以每个季节都带 ``lead_days``：
在季节开始前 lead_days 天就开始给对应支柱加权。加权只影响排期器挑支柱的
顺序，不改档案配比的护栏。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .constants import PILLAR_GUIDE, PILLAR_PRODUCT, PILLAR_SCENE


@dataclass(frozen=True)
class Season:
    key: str
    label: str
    start: tuple[int, int]  # (month, day)
    end: tuple[int, int]
    lead_days: int
    boost: dict[str, float]  # 支柱 → 权重倍数


SEASONS: tuple[Season, ...] = (
    Season("camping", "露营季", (4, 1), (9, 30), 60, {PILLAR_GUIDE: 1.3, PILLAR_SCENE: 1.3, PILLAR_PRODUCT: 1.1}),
    Season("memorial_day", "Memorial Day", (5, 20), (5, 31), 45, {PILLAR_PRODUCT: 1.3, PILLAR_SCENE: 1.2}),
    Season("july_4", "Independence Day", (6, 25), (7, 6), 45, {PILLAR_SCENE: 1.3, PILLAR_PRODUCT: 1.2}),
    Season("labor_day", "Labor Day", (8, 25), (9, 8), 45, {PILLAR_PRODUCT: 1.3, PILLAR_GUIDE: 1.1}),
    Season("black_friday", "Black Friday / Cyber Monday", (11, 20), (12, 2), 60, {PILLAR_PRODUCT: 1.5, PILLAR_GUIDE: 1.2}),
    Season("holiday_gifting", "Holiday gifting", (12, 3), (12, 20), 45, {PILLAR_PRODUCT: 1.3, PILLAR_GUIDE: 1.2}),
)


def _in_window(day: date, start: tuple[int, int], end: tuple[int, int], lead_days: int) -> bool:
    for year in (day.year - 1, day.year, day.year + 1):
        start_day = date(year, *start) - timedelta(days=lead_days)
        end_day = date(year, *end)
        if start_day <= day <= end_day:
            return True
    return False


def active_seasons(day: date) -> list[Season]:
    return [season for season in SEASONS if _in_window(day, season.start, season.end, season.lead_days)]


def season_weights(day: date) -> dict[str, float]:
    """支柱 → 权重倍数（默认 1.0）。多个季节叠加取最大值，不相乘。"""
    weights: dict[str, float] = {}
    for season in active_seasons(day):
        for pillar, boost in season.boost.items():
            weights[pillar] = max(weights.get(pillar, 1.0), boost)
    return weights


__all__ = ["SEASONS", "Season", "active_seasons", "season_weights"]
