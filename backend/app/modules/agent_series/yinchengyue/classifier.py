"""判类目的护栏全在这里:候选由代码从表里查,模型只能在候选里选,选了候选外的一律作废。

数据源是 K 系列的 ``k_category_google``(完整谷歌商品分类树,带中文名)。这里只读,不写。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...k_series.product_knowledge.category_resolver import _key, _norm, _sing, google_category_path
from .brain import KeywordHint, RawChoice
from .constants import SHORTLIST_LIMIT

_LOGGER = logging.getLogger("yinchengyue.brain")
_GOOGLE_TREE = "k_category_google"
_CJK_RUN = re.compile(r"[一-鿿]{2,}")
_MAX_ZH_FRAGMENTS = 24
_PER_QUERY_LIMIT = 60
_STOP_TOKENS = frozenset({"and", "the", "for", "with", "set", "sets"})


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    full_path: str
    name_zh: str
    level: int
    is_leaf: bool


@dataclass
class CategoryVerdict:
    status: Literal["ok", "none", "offline"]
    chosen: Candidate | None = None
    path: list[str] = field(default_factory=list)
    confidence: str = "low"
    reason_zh: str = ""
    alternates: list[tuple[Candidate, str]] = field(default_factory=list)
    shortlist_size: int = 0
    hint: KeywordHint | None = None
    error: str = ""


# ---------------------------------------------------------------- 候选


def zh_fragments(raw_text: str) -> list[str]:
    """从原话里切出能拿去查 name_zh 的中文片段。

    分三层:先每段整词(≤6 字),再所有段的 3 字窗口,最后 2 字窗口——长片段更准,
    所以先保证长的都在,再用短的补。去重,最多 _MAX_ZH_FRAGMENTS 个。
    """
    runs = _CJK_RUN.findall(raw_text or "")
    seen: list[str] = []

    def add(fragment: str) -> None:
        if fragment and fragment not in seen:
            seen.append(fragment)

    for run in runs:
        if len(run) <= 6:
            add(run)
    for size in (3, 2):
        for run in runs:
            for start in range(0, len(run) - size + 1):
                add(run[start : start + size])
    return seen[:_MAX_ZH_FRAGMENTS]


def _query(db: Session, *, column_sql: str, like: str) -> list[dict[str, Any]]:
    if db.get_bind().dialect.name == "postgresql":
        where = f"{column_sql} ILIKE :like"
    else:
        where = f"lower(COALESCE({column_sql}, '')) LIKE lower(:like)"
    rows = db.execute(
        text(
            f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
            f"WHERE {where} ORDER BY is_leaf DESC, level DESC, full_path ASC LIMIT :limit"
        ),
        {"like": like, "limit": _PER_QUERY_LIMIT},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    return [dict(row) for row in rows]


def _query_all_tokens(db: Session, *, column_sql: str, tokens: list[str]) -> list[dict[str, Any]]:
    """多词关键词整句对不上时,退一步要求每个词都出现在同一列里("camping lantern" → "Camping Lights & Lanterns")。"""
    if not tokens:
        return []
    is_pg = db.get_bind().dialect.name == "postgresql"
    clauses = []
    params: dict[str, Any] = {"limit": _PER_QUERY_LIMIT}
    for index, token in enumerate(tokens):
        key = f"tok{index}"
        params[key] = f"%{token}%"
        clauses.append(f"{column_sql} ILIKE :{key}" if is_pg else f"lower(COALESCE({column_sql}, '')) LIKE lower(:{key})")
    rows = db.execute(
        text(
            f"SELECT id, name, name_zh, full_path, level, is_leaf FROM {_GOOGLE_TREE} "
            f"WHERE {' AND '.join(clauses)} ORDER BY is_leaf DESC, level DESC, full_path ASC LIMIT :limit"
        ),
        params,
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    return [dict(row) for row in rows]


def _as_candidate(row: dict[str, Any]) -> Candidate:
    return Candidate(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        full_path=str(row.get("full_path") or ""),
        name_zh=str(row.get("name_zh") or ""),
        level=int(row.get("level") or 0),
        is_leaf=bool(row.get("is_leaf")),
    )


def shortlist(db: Session, *, keywords_en: list[str], raw_text: str, limit: int = SHORTLIST_LIMIT) -> list[Candidate]:
    """英文词查 name / full_path,中文片段查 name_zh;合并计分,叶子优先,截到 limit。"""
    scores: dict[str, int] = {}
    rows: dict[str, Candidate] = {}

    def credit(found: list[dict[str, Any]], *, name_points: int, path_points: int, needle: str) -> None:
        needle_l = needle.lower()
        for row in found:
            cand = _as_candidate(row)
            rows.setdefault(cand.id, cand)
            hit_name = needle_l in cand.name.lower() or needle_l in cand.name_zh.lower()
            scores[cand.id] = scores.get(cand.id, 0) + (name_points if hit_name else path_points)

    for keyword in keywords_en:
        # 第一层:整句(含单数化)直接匹配英文名 / 路径。
        for variant in {_norm(keyword), _key(keyword)}:
            if len(variant) < 3:
                continue
            found = _query(db, column_sql="name", like=f"%{variant}%")
            found += _query(db, column_sql="full_path", like=f"%{variant}%")
            credit(found, name_points=3, path_points=1, needle=variant)
        tokens = [_sing(t) for t in _norm(keyword).split() if len(t) >= 3 and t not in _STOP_TOKENS]
        if len(tokens) >= 2:
            # 第二层:每个词都在同一个英文名里("camping lantern" → "Camping Lights & Lanterns")。
            for row in _query_all_tokens(db, column_sql="name", tokens=tokens):
                cand = _as_candidate(row)
                rows.setdefault(cand.id, cand)
                scores[cand.id] = scores.get(cand.id, 0) + 2
            for row in _query_all_tokens(db, column_sql="full_path", tokens=tokens):
                cand = _as_candidate(row)
                rows.setdefault(cand.id, cand)
                scores[cand.id] = scores.get(cand.id, 0) + 1
        # 第三层:中心名词(最后一个词)单独命中英文名,分低,只为把候选面撑开。
        head = tokens[-1] if tokens else ""
        if len(head) >= 4:
            for row in _query(db, column_sql="name", like=f"%{head}%"):
                cand = _as_candidate(row)
                rows.setdefault(cand.id, cand)
                scores[cand.id] = scores.get(cand.id, 0) + 1

    for fragment in zh_fragments(raw_text):
        found = _query(db, column_sql="name_zh", like=f"%{fragment}%")
        # 2 字片段太泛(「不锈」「保温」都能命中一堆),给的分低于 3 字以上的片段。
        credit(found, name_points=3 if len(fragment) >= 3 else 1, path_points=0, needle=fragment)

    ranked = sorted(
        rows.values(),
        key=lambda c: (not c.is_leaf, -scores.get(c.id, 0), -c.level, c.full_path),
    )
    return ranked[:limit]


# ---------------------------------------------------------------- 校验


def _root(cand: Candidate) -> str:
    return cand.full_path.split(">")[0].strip().lower()


def _related(alt: Candidate, chosen: Candidate, keywords_en: list[str]) -> bool:
    """备选得和主选沾边:同一棵大类,或者名字里带着用户产品的关键词。否则就是模型在凑数。"""
    if _root(alt) == _root(chosen):
        return True
    name_l = _norm(alt.name)
    for keyword in keywords_en:
        for token in _norm(keyword).split():
            token = _sing(token)
            if len(token) >= 4 and token not in _STOP_TOKENS and token in name_l:
                return True
    return False


def validate_choice(raw: RawChoice, candidates: list[Candidate], *, keywords_en: list[str] | None = None) -> tuple[Candidate | None, list[tuple[Candidate, str]]]:
    """模型给的 id 必须在候选里;不在就当没选。备选同理,不能和主选重复,还得和主选沾边。"""
    by_id = {c.id: c for c in candidates}
    chosen = by_id.get(raw.chosen_id)
    alternates: list[tuple[Candidate, str]] = []
    for alt in raw.alternates:
        cand = by_id.get(alt.id)
        if cand is None or (chosen is not None and cand.id == chosen.id):
            continue
        if chosen is not None and not _related(cand, chosen, list(keywords_en or [])):
            continue
        if any(existing.id == cand.id for existing, _ in alternates):
            continue
        alternates.append((cand, alt.reason_zh.strip()))
        if len(alternates) >= 2:
            break
    return chosen, alternates


# ---------------------------------------------------------------- 主流程


def classify(
    db: Session,
    text_in: str,
    *,
    extract: Callable[[str], KeywordHint] | None = None,
    choose: Callable[[str, KeywordHint, list[Candidate]], RawChoice] | None = None,
) -> CategoryVerdict:
    from . import brain  # noqa: PLC0415

    extract = extract or brain.extract_keywords
    choose = choose or brain.choose_category

    try:
        hint = extract(text_in)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("第一步(抽英文词)没接通: %r", exc)
        return CategoryVerdict(status="offline", error=f"extract: {exc!r}"[:300])

    if not hint.is_product_question and not hint.keywords_en:
        return CategoryVerdict(status="none", hint=hint)

    candidates = shortlist(db, keywords_en=hint.keywords_en, raw_text=text_in)
    if not candidates:
        return CategoryVerdict(status="none", hint=hint, shortlist_size=0)

    try:
        raw = choose(text_in, hint, candidates)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("第二步(选候选)没接通: %r", exc)
        return CategoryVerdict(status="offline", hint=hint, shortlist_size=len(candidates), error=f"choose: {exc!r}"[:300])

    chosen, alternates = validate_choice(raw, candidates, keywords_en=hint.keywords_en)
    if chosen is None:
        return CategoryVerdict(status="none", hint=hint, shortlist_size=len(candidates), reason_zh=raw.reason_zh.strip())

    chain = google_category_path(db, chosen.id)
    path = [str(seg.get("name") or "") for seg in chain if seg.get("name")]
    if not path:
        path = [part.strip() for part in chosen.full_path.split(">") if part.strip()]

    return CategoryVerdict(
        status="ok",
        chosen=chosen,
        path=path,
        confidence=raw.confidence,
        reason_zh=raw.reason_zh.strip(),
        alternates=alternates,
        shortlist_size=len(candidates),
        hint=hint,
    )
