"""殷承岳的回复文本。

C19 只认 text/emoji/image/file,所以「类目卡」仍是一条文本:首行 `【类目 #a1b2】Camping Cookware`,
末行机器标记 `⟦category:a1b2⟧`。前端认出标记就渲染成带复制按钮的卡片;旧客户端看到的
仍然是一段可读文本,英文类目名就在首行。语法和 frontend/src/modules/c19/c19CategoryCard.ts 一一对应。
"""

from __future__ import annotations

import hashlib
import re

from .classifier import CategoryVerdict
from .constants import MAX_REASON_CHARS

CARD_HEAD_PREFIX = "【类目 #"
CARD_MARKER_PREFIX = "⟦category:"
PATH_SEPARATOR = " > "
CONFIDENCE_LABEL = {"high": "高", "medium": "中", "low": "低"}

REPLY_CHITCHAT = (
    "在的。我是产品助理殷承岳,只做一件事:告诉你一个产品属于谷歌类目树里的哪个类目。"
    "把产品名、材质、用途或 1688 标题发我(一次一个),我回英文类目名和理由,类目名可以一键复制。"
)
REPLY_NEED_DETAIL = (
    "这句里我没抓到足够的产品信息,定不了类目。再说清楚一点它是什么东西、什么材质、用在哪"
    "(比如「304 不锈钢真空保温杯,户外用」)。一次问一个产品。"
)
REPLY_OFFLINE = "没接通脑子,这句我没处理。稍后再发一遍。"

_GREETINGS = frozenset({
    "你好", "您好", "在吗", "在不在", "在", "嗨", "哈喽", "hello", "hi", "hey", "谢谢", "谢了", "多谢",
    "你是谁", "你是干什么的", "你能干什么", "你会什么", "介绍一下自己", "好的", "ok", "okay", "收到", "嗯", "行",
})


def is_chitchat(text: str) -> bool:
    """问候 / 感谢 / 问身份 → 不用调模型,固定一句话。判据故意窄:拿不准的都交给判定流程。"""
    t = re.sub(r"[\s,.!?~，。！？～、]+", "", (text or "").strip()).casefold()
    if not t:
        return True
    if t in _GREETINGS:
        return True
    return len(t) <= 2


def card_id_for(chosen_id: str, record_id: str) -> str:
    return hashlib.sha1(f"{chosen_id}:{record_id}".encode("utf-8")).hexdigest()[:4]


def _one_line(value: str, limit: int) -> str:
    flat = re.sub(r"\s+", " ", (value or "").strip())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def render_verdict(verdict: CategoryVerdict, *, record_id: str) -> str:
    if verdict.status == "offline":
        return REPLY_OFFLINE
    if verdict.status != "ok" or verdict.chosen is None:
        return REPLY_NEED_DETAIL

    chosen = verdict.chosen
    card_id = card_id_for(chosen.id, record_id)
    path = verdict.path or [part.strip() for part in chosen.full_path.split(">") if part.strip()]
    lines = [
        f"{CARD_HEAD_PREFIX}{card_id}】{chosen.name}",
        f"路径：{PATH_SEPARATOR.join(path)}",
        f"中文：{chosen.name_zh or '—'}",
        f"原因：{_one_line(verdict.reason_zh, MAX_REASON_CHARS) or '描述与该类目的典型产品一致。'}",
    ]
    for cand, why in verdict.alternates[:2]:
        lines.append(f"备选：{cand.name} — {_one_line(why, 120) or '描述另一种归类的可能'}")
    lines.append(f"置信：{CONFIDENCE_LABEL.get(verdict.confidence, '低')}")
    lines.append(f"{CARD_MARKER_PREFIX}{card_id}⟧")
    return "\n".join(lines)
