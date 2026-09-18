"""评论簇:人把评论原文贴进来(亚马逊没有评论正文 API)→ 拆条 → 归簇 → 按簇占比看。

三大家族(决定归谁修):
- defect   产品缺陷   → 事实表 / 工厂
- expectation 预期落差 → 殷笑笑(文案)/ 殷熊(副图):页面没讲清,买家以为能做到
- logistics 物流与包装 → FBA / 包装
- other

每条再给一个短主题(「以为能加热」「电池不耐用」)。DeepSeek flash 归簇;模型不通时用关键词兜底,标 clustered_by=keywords。
对手的 1–3 星评论(whose=competitor)是推新第 1 步的「前三个坑」来源。不 commit。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .catalog import AGENT_HOME_COMPANY, store_spec
from .constants import MODULE_KEY
from .models import AmzReview
from .service import AmzServiceError

_LOGGER = logging.getLogger("amz.reviews")

FAMILIES = ("defect", "expectation", "logistics", "other")
FAMILY_LABELS = {"defect": "产品缺陷", "expectation": "预期落差", "logistics": "物流与包装", "other": "其他"}
FAMILY_OWNER = {"defect": "事实表 / 工厂", "expectation": "殷笑笑(文案)+ 殷熊(副图)", "logistics": "FBA / 包装", "other": "—"}
WHOSE = ("ours", "competitor")
MAX_REVIEWS_PER_PASTE = 200
MAX_REVIEW_CHARS = 2000

_STAR_RE = re.compile(r"^\s*(?:(?P<o>[1-5])(?:[.,]0)?\s*(?:out of 5 stars|von 5 sternen)|(?P<n>[1-5])\s*(?:星|stars?|/\s*5|分)|(?P<s>[★⭐]{1,5}))\s*[:：|,，.、-]?\s*", re.IGNORECASE)

MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), start=1)}
MONTHS.update({m: i for i, m in enumerate(("januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"), start=1)})
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<y>20\d\d)[-/.年](?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})"),
    re.compile(r"\b(?P<mon>[A-Za-zä]+)\s+(?P<d>\d{1,2}),\s*(?P<y>20\d\d)"),  # August 3, 2026
    re.compile(r"\b(?P<d>\d{1,2})\.?\s+(?P<mon>[A-Za-zä]+)\s+(?P<y>20\d\d)"),  # 3 August 2026 / 3. August 2026
)

KEYWORD_FALLBACK: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("expectation", "以为能加热", re.compile(r"heat|hot water|warm|加热|热水|不热|cold water", re.I)),
    ("expectation", "以为能接水管 / 加压", re.compile(r"hose|faucet|pressure|水压|接水管|水龙头", re.I)),
    ("logistics", "到货损坏 / 缺件", re.compile(r"damaged|missing|arrived broken|box|缺件|破损|包装", re.I)),
    ("logistics", "配送慢", re.compile(r"late|shipping|delivery|慢|物流", re.I)),
    ("defect", "漏水", re.compile(r"leak|漏", re.I)),
    ("defect", "电池 / 充电问题", re.compile(r"battery|charg|电池|充电|续航", re.I)),
    ("defect", "用几次就坏", re.compile(r"stopped working|broke|died|quit|dead|坏了|不工作|停止工作", re.I)),
    ("defect", "噪音大", re.compile(r"noisy|loud|噪音|吵", re.I)),
)


def split_paste(raw: str) -> list[tuple[int | None, str]]:
    """一段粘贴 → [(星级, 正文)]。空行分条;每条开头可以写「3星」「2/5」「★★」。"""
    items: list[tuple[int | None, str]] = []
    for block in re.split(r"\n\s*\n", (raw or "").strip()):
        text = " ".join(block.split())
        if not text:
            continue
        stars: int | None = None
        m = _STAR_RE.match(text)
        if m:
            stars = int(m.group("o") or m.group("n")) if (m.group("o") or m.group("n")) else len(m.group("s"))
            text = text[m.end():].strip()
        if len(text) < 4:
            continue
        items.append((stars, text[:MAX_REVIEW_CHARS]))
        if len(items) >= MAX_REVIEWS_PER_PASTE:
            break
    return items


def review_date(text: str) -> date | None:
    """从贴进来的评论里认出评论日期(亚马逊页面上「Reviewed in the United States on August 3, 2026」那种)。认不出返回 None。"""
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            groups = m.groupdict()
            month = int(groups["m"]) if groups.get("m") else MONTHS.get((groups.get("mon") or "").lower())
            if not month:
                continue
            try:
                return date(int(groups["y"]), month, int(groups["d"]))
            except ValueError:
                continue
    return None


def fallback_cluster(text: str) -> tuple[str, str]:
    for family, theme, pattern in KEYWORD_FALLBACK:
        if pattern.search(text):
            return family, theme
    return "other", "其他"


def add_reviews(db: Session, *, product_line: str, whose: str, raw: str, actor_user_id: int, store_code: str | None = None, asin: str | None = None, launch_id: Any = None) -> int:
    if whose not in WHOSE:
        raise AmzServiceError("whose 只能是 ours / competitor", status_code=422, code="amz_reviews_whose_invalid")
    items = split_paste(raw)
    if not items:
        raise AmzServiceError("没认出评论:每条之间空一行,开头可以写「3星」", status_code=422, code="amz_reviews_empty")
    rows = [
        {
            "store_code": (store_code or "").lower() or None,
            "product_line": product_line,
            "asin": (asin or "").strip().upper() or None,
            "whose": whose,
            "stars": stars,
            "text": text,
            "text_sha256": hashlib.sha256(text.lower().encode("utf-8")).hexdigest(),
            "posted_on": review_date(text),
            "launch_id": launch_id,
            "created_by_user_id": actor_user_id,
        }
        for stars, text in items
    ]
    from uuid import uuid4  # noqa: PLC0415

    for row in rows:
        row["id"] = uuid4()
    stmt = pg_insert(AmzReview).values(rows).on_conflict_do_nothing(constraint="uq_amz_reviews_text").returning(AmzReview.id)
    return len(db.execute(stmt).all())


CLUSTER_PROMPT = """你是亚马逊评论分析员。下面是一批评论(编号: 星级: 正文)。给每条归一个家族和一个短主题。
家族只能是:defect(产品本身坏了/质量问题)、expectation(买家以为它能做到某事而它本来就做不到,页面没讲清)、logistics(物流/包装/缺件)、other。
主题用中文 2–10 个字,同类评论用**完全相同**的主题字样(比如都写「以为能加热」),方便合并。
只输出一个 json:{"items": [{"n": 编号, "family": "...", "theme": "..."}]}"""


def _call_model(messages: list[dict[str, Any]], *, org_id: str) -> Any:
    from ...db.session import SessionLocal  # noqa: PLC0415
    from ...services.ai_provider_router import AIExecutionRouter  # noqa: PLC0415
    from r_system_v2.ra.quota_ledger import PROVIDER_AMZ_REVIEWS, refund, try_consume  # noqa: PLC0415

    ledger_db = SessionLocal()
    charged = False
    try:
        try_consume(ledger_db, PROVIDER_AMZ_REVIEWS)
        charged = True
    finally:
        ledger_db.close()
    provider_db = SessionLocal()
    try:
        return AIExecutionRouter(provider_db, timeout_seconds=90.0, total_budget_seconds=120.0).execute(
            provider="deepseek", task_type="agent_chat", payload={"messages": messages, "response_format": {"type": "json_object"}, "temperature": 0}, org=org_id, module_id=MODULE_KEY
        )
    except Exception:
        if charged:
            refund_db = SessionLocal()
            try:
                refund(refund_db, PROVIDER_AMZ_REVIEWS)
            finally:
                refund_db.close()
        raise
    finally:
        provider_db.close()


def cluster_pending(db: Session, *, product_line: str, call=None, batch: int = 60) -> dict[str, int]:
    """把还没归簇的评论归簇。模型不通 → 关键词兜底(不留空)。"""
    pending = list(db.scalars(select(AmzReview).where(AmzReview.product_line == product_line, AmzReview.cluster.is_(None)).order_by(AmzReview.created_at).limit(batch)))
    if not pending:
        return {"model": 0, "keywords": 0}
    org_id = (store_spec(pending[0].store_code).company.org_id if pending[0].store_code and store_spec(pending[0].store_code) else AGENT_HOME_COMPANY.org_id)
    listing = "\n".join(f"{i}: {r.stars or '?'}星: {r.text[:400]}" for i, r in enumerate(pending))
    assigned: dict[int, tuple[str, str]] = {}
    try:
        result = (call or _call_model)([{"role": "system", "content": CLUSTER_PROMPT}, {"role": "user", "content": listing}], org_id=org_id)
        payload = result
        if isinstance(result, dict) and "content" in result and "items" not in result:
            payload = json.loads(result["content"]) if isinstance(result["content"], str) else result["content"]
        for item in (payload or {}).get("items") or []:
            try:
                n = int(item.get("n"))
            except (TypeError, ValueError):
                continue
            family = str(item.get("family") or "other").lower()
            theme = str(item.get("theme") or "").strip()[:60]
            if 0 <= n < len(pending) and family in FAMILIES and theme:
                assigned[n] = (family, theme)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("评论归簇模型没接通,用关键词兜底: %s", exc)
    counts = {"model": 0, "keywords": 0}
    for i, row in enumerate(pending):
        if i in assigned:
            row.family, row.cluster = assigned[i]
            row.clustered_by = "model"
            counts["model"] += 1
        else:
            row.family, row.cluster = fallback_cluster(row.text)
            row.clustered_by = "keywords"
            counts["keywords"] += 1
        db.add(row)
    db.flush()
    return counts


def cluster_table(db: Session, *, product_line: str, whose: str | None = None, max_stars: int | None = None) -> list[dict[str, Any]]:
    """簇占比:[{family, theme, count, share_pct, sample}],按条数倒序。"""
    R = AmzReview
    q = select(R.family, R.cluster, func.count(), func.min(R.text)).where(R.product_line == product_line, R.cluster.is_not(None)).group_by(R.family, R.cluster)
    if whose:
        q = q.where(R.whose == whose)
    if max_stars is not None:
        q = q.where((R.stars.is_(None)) | (R.stars <= max_stars))
    rows = db.execute(q).all()
    total = sum(int(r[2]) for r in rows) or 1
    out = [{"family": r[0], "family_label": FAMILY_LABELS.get(r[0], r[0]), "owner": FAMILY_OWNER.get(r[0], "—"), "theme": r[1], "count": int(r[2]), "share_pct": round(int(r[2]) / total * 100, 1), "sample": (r[3] or "")[:160]} for r in rows]
    out.sort(key=lambda x: -x["count"])
    return out


def monthly_trend(db: Session, *, product_line: str, whose: str | None = None, months: int = 6) -> dict[str, Any]:
    """评论簇按月看占比:这个月差评里「预期落差」占多少,修了文案之后有没有掉下来。

    月份按评论日期(贴的时候认出来的);认不出日期的按贴进来的那天算,并单独数出来。
    """
    R = AmzReview
    month_expr = func.to_char(func.coalesce(R.posted_on, func.date(R.created_at)), "YYYY-MM")
    q = select(month_expr, R.family, R.cluster, func.count(), func.count(R.posted_on)).where(R.product_line == product_line, R.cluster.is_not(None)).group_by(month_expr, R.family, R.cluster)
    if whose:
        q = q.where(R.whose == whose)
    by_month: dict[str, dict[str, Any]] = {}
    for month, family, cluster, count, dated in db.execute(q).all():
        slot = by_month.setdefault(month, {"month": month, "total": 0, "undated": 0, "families": {f: 0 for f in FAMILIES}, "clusters": {}})
        slot["total"] += int(count)
        slot["undated"] += int(count) - int(dated)
        slot["families"][family or "other"] = slot["families"].get(family or "other", 0) + int(count)
        slot["clusters"][cluster] = slot["clusters"].get(cluster, 0) + int(count)
    out = []
    for month in sorted(by_month)[-months:]:
        slot = by_month[month]
        total = slot["total"] or 1
        out.append(
            {
                "month": month,
                "total": slot["total"],
                "undated": slot["undated"],
                "families": [{"family": f, "label": FAMILY_LABELS[f], "count": c, "share_pct": round(c / total * 100, 1)} for f, c in slot["families"].items()],
                "top_clusters": [{"theme": t, "count": c, "share_pct": round(c / total * 100, 1)} for t, c in sorted(slot["clusters"].items(), key=lambda x: -x[1])[:3]],
            }
        )
    return {"product_line": product_line, "whose": whose, "months": out}


def top_pits(db: Session, *, product_line: str, limit: int = 3) -> list[dict[str, Any]]:
    """推新第 1 步:对手 1–3 星评论里前三个坑(不含物流——那不是页面能堵的)。"""
    rows = [r for r in cluster_table(db, product_line=product_line, whose="competitor", max_stars=3) if r["family"] in ("defect", "expectation")]
    return rows[:limit]


__all__ = ["FAMILIES", "FAMILY_LABELS", "FAMILY_OWNER", "WHOSE", "add_reviews", "cluster_pending", "cluster_table", "fallback_cluster", "monthly_trend", "review_date", "split_paste", "top_pits"]
