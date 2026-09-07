"""DeepSeek quantitative prescreen — the cheap first gate of the R-A funnel.

Runs BEFORE any paid data pull (1688 image search / Rainforest).  Judges only
the structured numbers R-W already collected for free, so the model has no
room to invent facts.  Design rules:

- 宁错放不错杀：hold 一律放行；关键需求字段缺失时代码强制 hold。
- 不判死刑，只排队：cut 不删除产品，只是不花今天的付费额度；分数用于
  auto-cruise 排序，产品数据更新后可重新打分。
- 反幻觉：要求模型回显 evidence 数字，与输入对不上的判定降级为 hold。
- shadow 模式：只打分不拦截，用于上线初期观测误杀率。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.ra.ai_selection import (
    ProviderConfig,
    RAAISelectionError,
    _execute_chat_request,
    _load_provider_configs,
    _try_parse_model_json,
)
from r_system_v2.ra.profit_service import _json_bind


PRESCREEN_VERSION = "ra_prescreen_v1"
DEFAULT_RESCORE_DAYS = 30
DEFAULT_MODE = "enforce"  # enforce | shadow

# 量化阈值摘要：SKILL.md 的"模型版"，只保留数字规则（token 瘦身核心）。
PRESCREEN_SYSTEM_PROMPT = """你是跨境选品的量化过滤器，为一个资金有限的小卖家工作。
你只依据输入 JSON 里给出的结构化数字判断，绝对不引入任何外部知识或臆造数字。
你回答的唯一问题是：这个产品值不值得花付费额度（1688 图搜 + 利润核算）细看？

判断基准（放宽执行，宁错放不错杀）：
- 售价 8-100 美金都可以看，25-70 美金加分；超出区间明显（<5 或 >150）减分。
- 月销量 >=100 加分，>=300 强加分；月销缺失时不得因此淘汰，输出 hold。
- 评论数 0-800 属于可攻区间；页一常见对手评论过万且本品无差异化线索时减分。
- 重量 <=1000g 加分，>2500g 减分（头程与 FBA 费用风险）。
- 类目命中危险线（液体/医疗/刀具/儿童敏感）时输出 cut 并说明。
- 锂电池/含电产品不是红线：卖家有带电产品处理能力，只作为成本提示，不得因此 cut。
- BSR 趋势、评分等字段缺失一律视为"未知"，未知不减分。
- 拿不准就 hold。只有明显平庸（需求弱+竞争死+无差异化空间）才 cut。

渠道预判（channel_guess）：
- amazon：亚马逊已有稳定搜索需求、价格带健康。
- dtc_ad：有视觉冲击/演示型卖点（折叠、磁吸、发光、宠物、户外等）。
- dtc_seo：对应可搜索的问题/场景，长尾词友好。
- both：兼具。

必须只输出一个 JSON 对象，格式：
{"score": 0-100 整数, "verdict": "keep|cut|hold", "reason": "中文一句话，必须引用输入里的具体数字",
 "channel_guess": "amazon|dtc_ad|dtc_seo|both",
 "evidence": {"price": 输入里的售价原值, "monthly_sales": 输入里的月销原值, "reviews": 输入里的评论数原值}}
evidence 里的数字必须与输入完全一致；输入为 null 就写 null。"""


class RAPrescreenError(RuntimeError):
    pass


def prescreen_mode() -> str:
    raw = os.getenv("RA_PRESCREEN_MODE", DEFAULT_MODE).strip().lower()
    return raw if raw in {"enforce", "shadow", "off"} else DEFAULT_MODE


def rescore_days() -> int:
    try:
        return max(1, min(int(os.getenv("RA_PRESCREEN_RESCORE_DAYS", "30")), 365))
    except ValueError:
        return DEFAULT_RESCORE_DAYS


def ensure_prescreen_schema(db: Session) -> None:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ra_prescreen (
              id TEXT PRIMARY KEY,
              org_id TEXT NOT NULL,
              run_id TEXT,
              asin TEXT NOT NULL,
              score INTEGER,
              verdict TEXT NOT NULL,
              channel_guess TEXT,
              reason TEXT,
              evidence {json_type} NOT NULL DEFAULT '{{}}',
              payload {json_type} NOT NULL DEFAULT '{{}}',
              model TEXT,
              mode TEXT NOT NULL DEFAULT 'enforce',
              hallucination_suspect BOOLEAN NOT NULL DEFAULT FALSE,
              audit_status TEXT,
              audit_detail {json_type},
              created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_prescreen_asin
            ON ra_prescreen (org_id, asin, created_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_prescreen_verdict
            ON ra_prescreen (org_id, verdict, created_at DESC)
            """
        )
    )


def get_recent_prescreen(
    db: Session,
    *,
    org_id: str,
    asin: str,
) -> dict[str, Any] | None:
    ensure_prescreen_schema(db)
    row = db.execute(
        text(
            f"""
            SELECT id, asin, score, verdict, channel_guess, reason, evidence,
                   model, mode, hallucination_suspect, created_at
            FROM ra_prescreen
            WHERE org_id = :org_id AND UPPER(asin) = :asin
              AND created_at > CURRENT_TIMESTAMP - INTERVAL '{rescore_days()} days'
              AND COALESCE(payload->>'error', '') = ''
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id, "asin": asin.strip().upper()},
    ).mappings().first()
    if row is None:
        return None
    return {**dict(row), "cached": True}


def run_prescreen_for_product(
    db: Session,
    *,
    org_id: str,
    product: dict[str, Any],
    run_id: str | None = None,
    provider: ProviderConfig | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Score one R-W product. Returns verdict dict; caches by ASIN."""
    asin = str(product.get("asin") or "").strip().upper()
    if not asin:
        raise RAPrescreenError("prescreen 缺少 ASIN。")
    if not force:
        cached = get_recent_prescreen(db, org_id=org_id, asin=asin)
        if cached is not None:
            return cached

    if provider is None:
        provider = _load_provider_configs(db, org_id=org_id)["deepseek"]

    model_input = _prescreen_input(product)
    guard = _missing_data_guard(model_input)
    hallucination_suspect = False
    raw_output: dict[str, Any] = {}
    error_text: str | None = None
    # DeepSeek 调用要几秒：先结束打开的 SQL 事务，避免 idle-in-transaction 超时。
    try:
        db.rollback()
    except Exception:
        pass
    if guard is None:
        try:
            response = _execute_chat_request(
                provider,
                spec={
                    "endpoint": "/v1/chat/completions",
                    "label": "prescreen",
                    "payload": {
                        "model": provider.model,
                        "messages": [
                            {"role": "system", "content": PRESCREEN_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    model_input, ensure_ascii=False, default=str
                                ),
                            },
                        ],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                },
            )
            raw_output = _try_parse_model_json(response.get("content")) or {}
        except RAAISelectionError as exc:
            error_text = str(exc)
    score, verdict, channel_guess, reason = _normalize_output(raw_output)
    if guard is not None:
        verdict = "hold"
        reason = guard
        score = score if raw_output else 50
    elif error_text is not None:
        # 初筛层自身失败绝不拦人：hold 放行，留给后面的硬门与 GPT。
        verdict = "hold"
        reason = f"初筛调用失败，按放行处理：{error_text[:160]}"
        score = 50
    elif verdict == "cut":
        mismatch = _evidence_mismatch(raw_output.get("evidence"), model_input)
        if mismatch:
            hallucination_suspect = True
            verdict = "hold"
            reason = f"证据回显与输入不符（{mismatch}），判定降级为 hold。"

    record = {
        "id": str(uuid4()),
        "org_id": org_id,
        "run_id": run_id,
        "asin": asin,
        "score": score,
        "verdict": verdict,
        "channel_guess": channel_guess,
        "reason": reason,
        "evidence": raw_output.get("evidence") or {},
        "payload": {
            "version": PRESCREEN_VERSION,
            "input": model_input,
            "model_output": raw_output,
            "error": error_text,
            "guard": guard,
        },
        "model": provider.model,
        "mode": prescreen_mode(),
        "hallucination_suspect": hallucination_suspect,
    }
    _insert_prescreen(db, record)
    return {**record, "cached": False}


def load_prescreen_scores(
    db: Session,
    *,
    org_id: str,
    asins: list[str],
) -> dict[str, dict[str, Any]]:
    if not asins:
        return {}
    ensure_prescreen_schema(db)
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (UPPER(asin))
                   UPPER(asin) AS asin, score, verdict, channel_guess, created_at
            FROM ra_prescreen
            WHERE org_id = :org_id AND UPPER(asin) = ANY(:asins)
            ORDER BY UPPER(asin), created_at DESC
            """
        ),
        {"org_id": org_id, "asins": [item.strip().upper() for item in asins]},
    ).mappings()
    return {str(row["asin"]): dict(row) for row in rows}


def sample_cut_products_for_audit(
    db: Session,
    *,
    org_id: str,
    limit: int = 20,
    within_hours: int = 48,
) -> list[dict[str, Any]]:
    """Recent cut verdicts that have not been audited yet (免费词搜抽检)."""
    ensure_prescreen_schema(db)
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT ON (UPPER(p.asin)) p.id, p.asin, p.score, p.reason
            FROM ra_prescreen p
            WHERE p.org_id = :org_id
              AND p.verdict = 'cut'
              AND p.audit_status IS NULL
              AND p.created_at > CURRENT_TIMESTAMP - INTERVAL '{max(1, within_hours)} hours'
            ORDER BY UPPER(p.asin), p.created_at DESC
            LIMIT :limit
            """
        ),
        {"org_id": org_id, "limit": max(1, min(limit, 100))},
    ).mappings()
    return [dict(row) for row in rows]


def record_audit_result(
    db: Session,
    *,
    prescreen_id: str,
    audit_status: str,
    audit_detail: dict[str, Any] | None = None,
) -> None:
    ensure_prescreen_schema(db)
    db.execute(
        text(
            f"""
            UPDATE ra_prescreen
            SET audit_status = :audit_status,
                audit_detail = {_json_bind(db, "audit_detail")}
            WHERE id = :prescreen_id
            """
        ),
        {
            "prescreen_id": prescreen_id,
            "audit_status": audit_status,
            "audit_detail": json.dumps(audit_detail or {}, ensure_ascii=False, default=str),
        },
    )
    db.commit()


def prescreen_daily_stats(db: Session, *, org_id: str) -> dict[str, Any]:
    ensure_prescreen_schema(db)
    row = db.execute(
        text(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE verdict = 'keep') AS keep,
              COUNT(*) FILTER (WHERE verdict = 'cut') AS cut,
              COUNT(*) FILTER (WHERE verdict = 'hold') AS hold,
              COUNT(*) FILTER (WHERE hallucination_suspect) AS hallucination_suspect,
              COUNT(*) FILTER (WHERE audit_status = 'false_kill') AS audited_false_kill,
              COUNT(*) FILTER (WHERE audit_status IS NOT NULL) AS audited
            FROM ra_prescreen
            WHERE org_id = :org_id
              AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
            """
        ),
        {"org_id": org_id},
    ).mappings().first()
    stats = {key: int(row[key] or 0) for key in row.keys()} if row else {}
    stats["mode"] = prescreen_mode()
    stats["generated_at"] = datetime.now(UTC).isoformat()
    return stats


def _prescreen_input(product: dict[str, Any]) -> dict[str, Any]:
    features = product.get("features")
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except json.JSONDecodeError:
            features = {}
    if not isinstance(features, dict):
        features = {}
    return {
        "asin": product.get("asin"),
        "title": product.get("title"),
        "category": product.get("category"),
        "category_path": product.get("category_path"),
        "brand": product.get("brand"),
        "price_usd": _number(product.get("price")),
        "monthly_sales": _number(
            features.get("monthly_sales_value")
            or features.get("monthly_sales_estimate")
            or features.get("monthly_sales")
        ),
        "reviews": _number(features.get("review_count") or product.get("reviews")),
        "rating": _number(features.get("rating")),
        "bsr": _number(features.get("bsr") or product.get("bsr")),
        "package_weight_g": _number(
            features.get("package_weight_g") or features.get("item_weight_g")
        ),
        "fba_fee_usd": _number(features.get("fba_fee_usd")),
        "lithium_battery_warning": bool(features.get("lithium_battery_warning")),
        "subcategory_rank": _number(features.get("subcategory_rank")),
        "rw_skill_score": _number(product.get("skill_score")),
    }


def _missing_data_guard(model_input: dict[str, Any]) -> str | None:
    """Code-side iron rule: missing demand data can never cause a cut."""
    if model_input.get("monthly_sales") is None and model_input.get("reviews") is None:
        return "月销与评论数均缺失，需求无法量化判断，强制 hold 放行。"
    if model_input.get("price_usd") is None:
        return "售价缺失，强制 hold 放行。"
    return None


def _normalize_output(output: dict[str, Any]) -> tuple[int, str, str, str]:
    try:
        score = int(output.get("score"))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))
    verdict = str(output.get("verdict") or "hold").strip().lower()
    if verdict not in {"keep", "cut", "hold"}:
        verdict = "hold"
    channel_guess = str(output.get("channel_guess") or "both").strip().lower()
    if channel_guess not in {"amazon", "dtc_ad", "dtc_seo", "both"}:
        channel_guess = "both"
    reason = str(output.get("reason") or "").strip()[:400] or "模型未给出理由。"
    return score, verdict, channel_guess, reason


def _evidence_mismatch(
    evidence: Any,
    model_input: dict[str, Any],
) -> str | None:
    if not isinstance(evidence, dict):
        return "缺少 evidence 块"
    checks = (
        ("price", "price_usd"),
        ("monthly_sales", "monthly_sales"),
        ("reviews", "reviews"),
    )
    for evidence_key, input_key in checks:
        expected = model_input.get(input_key)
        got = _number(evidence.get(evidence_key))
        if expected is None:
            if got is not None:
                return f"{evidence_key} 输入为空但模型给出 {got}"
            continue
        if got is None:
            return f"{evidence_key} 未回显"
        if abs(float(got) - float(expected)) > max(0.01 * abs(float(expected)), 0.01):
            return f"{evidence_key} 回显 {got} ≠ 输入 {expected}"
    return None


def _insert_prescreen(db: Session, record: dict[str, Any]) -> None:
    ensure_prescreen_schema(db)
    db.execute(
        text(
            f"""
            INSERT INTO ra_prescreen (
              id, org_id, run_id, asin, score, verdict, channel_guess, reason,
              evidence, payload, model, mode, hallucination_suspect
            )
            VALUES (
              :id, :org_id, :run_id, :asin, :score, :verdict, :channel_guess,
              :reason, {_json_bind(db, "evidence")}, {_json_bind(db, "payload")},
              :model, :mode, :hallucination_suspect
            )
            """
        ),
        {
            "id": record["id"],
            "org_id": record["org_id"],
            "run_id": record.get("run_id"),
            "asin": record["asin"],
            "score": record.get("score"),
            "verdict": record["verdict"],
            "channel_guess": record.get("channel_guess"),
            "reason": record.get("reason"),
            "evidence": json.dumps(record.get("evidence") or {}, ensure_ascii=False, default=str),
            "payload": json.dumps(record.get("payload") or {}, ensure_ascii=False, default=str),
            "model": record.get("model"),
            "mode": record.get("mode"),
            "hallucination_suspect": bool(record.get("hallucination_suspect")),
        },
    )
    db.commit()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None
