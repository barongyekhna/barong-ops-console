"""第②步:苏青禾接管 K 流水线(10-26)。

她建进 K 的产品(档案 created),她自己按顺序往下推,和运营在 K 里点按钮一样(k_ops.KHands,身份是批建档卡的老板):

  卖点素材 → 主关键词 → 关键词(K 工作流:富化 → SERP → 两道筛,停在风险词)→ 风险词(她判)
  → 卖点(K 生成 → 她批)→【价格卡,老板批】→ 文案 → 作图指令 → 出图 →【审核卡,老板批】→ 保存图片 → 推上独立站(草稿)

价格卡排在文案前面:K 写文案按变体的包装数量写,颜色变体的主图要变体参考图——变体和售价得先定。

每一步做没做完、下一步干什么,一律从 K 自己的状态推出来(next_step 是纯函数),不另记一套进度。
她自己的判断(主关键词、风险词怎么判、卖点素材)记在档案 draft["pipeline"] / draft["material"] 里,卡上给老板看。

规矩:
- 一次只干一件,在另一个线程里干:K 的关键词一步能跑十几分钟,不能卡住她的 C19 聊天和批卡建档(Runner)。
- 同一步失败两次就停手,发一张「卡住了」的卡:批 = 再试,驳 = 这个品先不做。不会自己无限重试烧钱。
- 老板暂停她,这里也停(正在跑的那一步跑完为止)。
"""

from __future__ import annotations

import logging
import re
import secrets
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from . import cards, k_ops, material, memory
from .constants import USAGE_LABEL
from .models import SqhCard, SqhDossier

logger = logging.getLogger(__name__)

# 她推流水线时自己的 AI 判断(主关键词、风险词)记在这个名下;K 自己的调用记在 K 名下。
PIPELINE_USAGE_LABEL = f"{USAGE_LABEL}.k"
BLOCKED_CARD_KIND = "k_blocked"
PIPELINE_CARD_KINDS = (BLOCKED_CARD_KIND,)
MAX_STEP_FAILURES = 2
# K 工作流的「running」超过这么久没动静,当成上一次跑到一半断了(worker 重启之类),从断的那步重跑
RUNNING_STALE_MINUTES = 40
RISK_STEPS = {"risk_term_manual_review", "risk_term_review_manual"}
JUDGE_TIMEOUT_SECONDS = 120.0

STEP_LABELS = {
    "material": "收卖点素材",
    "keywords": "跑关键词",
    "keywords_retry": "重跑关键词",
    "risk_review": "判风险词",
    "selling_points": "生成卖点",
    "approve_selling_points": "批卖点",
}


# ---------------------------------------------------------------- 下一步干什么(纯函数)


@dataclass(frozen=True)
class View:
    """一个产品在 K 里走到哪了。全是从 K 和档案里读出来的事实,不是她另记的进度。"""

    material_done: bool
    stopped: bool  # 老板驳了「卡住」卡:这个品先不做
    blocked_step: str | None  # 「卡住」卡还在等老板
    execution_status: str | None
    execution_step: str | None
    execution_minutes: float | None  # K 工作流记录多久没更新了
    risk_approved: bool
    sp_job: str | None  # 最近一次卖点任务的状态
    sp_failures: int  # K 生成卖点失败了几次(老板批「再试」后重新数)
    sp_candidates: bool
    sp_approved: bool


def next_step(view: View) -> str | None:
    """None = 现在没她的事(在等 K 跑完、等老板,或者这个品停了)。"""
    if view.stopped or view.blocked_step:
        return None
    if not view.material_done:
        return "material"
    if view.execution_status is None:
        return "keywords"
    if view.execution_status in {"running", "created"}:
        return "keywords_retry" if (view.execution_minutes or 0) > RUNNING_STALE_MINUTES else None
    if not view.risk_approved:
        # 停在风险词 = 正常;停在别处(SERP、两道筛失败,blocked/failed 带错误码)= 重跑那一步
        return "risk_review" if view.execution_step in RISK_STEPS else "keywords_retry"
    if view.sp_approved:
        return None  # 下一步是价格卡
    if view.sp_job in {"pending", "running"}:
        return None
    if view.sp_candidates:
        return "approve_selling_points"
    # 排队这一下总是「成功」的,失败在 K 那边——按 K 的任务表数,够数就停手发卡,别无限重排
    if view.sp_job == "failed" and view.sp_failures >= MAX_STEP_FAILURES:
        return "block:selling_points"
    return "selling_points"


def _pipe(dossier: SqhDossier) -> dict[str, Any]:
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    pipe = draft.get("pipeline")
    return dict(pipe) if isinstance(pipe, dict) else {}


def _save_pipe(dossier: SqhDossier, **updates: Any) -> dict[str, Any]:
    draft = dict(dossier.draft or {})
    pipe = {**_pipe(dossier), **updates}
    draft["pipeline"] = pipe
    dossier.draft = draft  # 换新对象,JSON 列才认得出改了
    return pipe


def _bullets(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [b for b in payload.get("bullets") or [] if isinstance(b, dict) and str(b.get("text") or "").strip()]


def build_view(db: Session, dossier: SqhDossier, product: Any) -> View:
    pipe = _pipe(dossier)
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    execution = k_ops.latest_execution(db, product.id)
    jobs = k_ops.latest_jobs(db, product.id)
    minutes = None
    if execution is not None and execution.updated_at is not None:
        minutes = (datetime.now(UTC) - execution.updated_at).total_seconds() / 60
    approved = product.selling_points_approved_json if isinstance(product.selling_points_approved_json, dict) else {}
    candidates = product.selling_points_candidates_json if isinstance(product.selling_points_candidates_json, dict) else {}
    return View(
        material_done="material" in draft,
        stopped=bool(pipe.get("stopped")),
        blocked_step=(pipe.get("blocked") or {}).get("step") if isinstance(pipe.get("blocked"), dict) else None,
        execution_status=getattr(execution, "status", None),
        execution_step=getattr(execution, "current_step", None),
        execution_minutes=minutes,
        risk_approved=bool(execution is not None and (execution.risk_approval_log_json or {}).get("approved") is True),
        sp_job=(jobs.get("selling_points") or {}).get("status"),
        sp_failures=k_ops.failed_attempts(db, product.id, "selling_points", since=(pipe.get("reset") or {}).get("selling_points")),
        sp_candidates=candidates.get("review_status") == "candidate" and bool(_bullets(candidates)),
        sp_approved=approved.get("review_status") == "approved" and bool(_bullets(approved)),
    )


# ---------------------------------------------------------------- 她管哪些产品


def managed(db: Session) -> list[tuple[SqhDossier, Any]]:
    """她建进 K 的产品(档案 created),按建档先后。K 里归档了的不管。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    rows = list(
        db.scalars(
            select(SqhDossier).where(SqhDossier.status == "created", SqhDossier.k_product_id.is_not(None)).order_by(SqhDossier.id),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
    )
    out: list[tuple[SqhDossier, Any]] = []
    for dossier in rows:
        try:
            product = db.get(P, UUID(str(dossier.k_product_id)), execution_options=SKIP_ORG_DATA_ISOLATION)
        except (TypeError, ValueError):
            product = None
        if product is not None and product.review_status != "archived" and product.product_status != "archived":
            out.append((dossier, product))
    return out


def pick(db: Session) -> tuple[int, str] | None:
    """下一件要干的活:(档案号, 步骤)。按建档先后,一个品一个品往前推。"""
    with without_org_data_isolation():
        for dossier, product in managed(db):
            step = next_step(build_view(db, dossier, product))
            if step:
                return dossier.id, step
    return None


# ---------------------------------------------------------------- 她自己的判断:主关键词、风险词


def _product_brief(dossier: SqhDossier, product: Any) -> str:
    """给判断用的商品资料:中文标题、英文名、类目、规格名、档案里核过的参数。不含进价、不含 1688 链接。"""
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    fields = draft.get("fields") or {}
    name_zh = (fields.get("name_zh") or {}).get("value") if isinstance(fields.get("name_zh"), dict) else None
    category = (fields.get("category") or {}).get("value") if isinstance(fields.get("category"), dict) else None
    specs = [
        f"{key}: {item.get('value')}{(' ' + item['unit']) if item.get('unit') else ''}"
        for key, item in (draft.get("specs") or {}).items()
        if isinstance(item, dict) and item.get("status") == "ok"
    ]
    variants = [str(v.get("name_en") or v.get("name_zh") or "") for v in draft.get("variants") or [] if isinstance(v, dict)]
    features = [row["text"] for row in (draft.get("material") or {}).get("features") or [] if isinstance(row, dict)]
    category_text = ""
    if isinstance(category, dict):
        category_text = str(category.get("path") or category.get("name") or category.get("google_category_id") or "")
    return "\n".join(
        line
        for line in (
            f"中文标题:{name_zh or ''}",
            f"英文名:{product.product_name_en or ''}",
            f"谷歌类目:{category_text}",
            f"规格(变体):{' / '.join(v for v in variants if v) or '只有一个'}",
            f"核过的参数:{';'.join(specs) or '(没有)'}",
            f"功能点(卖家详情图上印的):{';'.join(features) or '(没有)'}",
        )
    )


_KEYWORD_ASK = (
    "你在给独立站(面向美国买家)的一件新品定「主关键词」:美国买家在 Google 上搜这类东西最常打的那几个英文词。\n"
    "要求:\n"
    "- main_keyword:2–4 个英文单词,小写,是品类词(比如 cordless drill、12v drill battery、mosquito repellent lantern),不是商品标题。\n"
    "- 不带任何品牌或型号(包括别人的,如 DeWalt、Makita),不带没法证实的说法(best、strongest、top rated、年份)。\n"
    "- 说的是这件商品本身:套装看主体,配件看它配什么。\n"
    "- seed_keywords:3–5 个这件商品别的常见英文搜法,同样不带品牌和夸张词。\n"
    'Reply JSON only: {"main_keyword": "...", "seed_keywords": ["..."], "reason": "一句中文:为什么选这个"}'
)
_KEYWORD_OK = re.compile(r"^[a-z0-9][a-z0-9 \-]{1,58}[a-z0-9]$")
_HYPE_WORDS = {"best", "top", "strongest", "cheapest", "rated", "no.1", "#1", "2025", "2026", "2027"}


def _clean_keyword(value: Any) -> str | None:
    text = " ".join(str(value or "").lower().split())
    if not _KEYWORD_OK.match(text) or not 2 <= len(text.split()) <= 5:
        return None
    if _HYPE_WORDS.intersection(text.split()):
        return None
    return text


def parse_keyword_choice(result: Any) -> dict[str, Any] | None:
    from .brain import parse_json

    data = parse_json(result)
    if not isinstance(data, dict):
        return None
    main = _clean_keyword(data.get("main_keyword"))
    if main is None:
        return None
    seeds: list[str] = []
    for raw in data.get("seed_keywords") or []:
        seed = _clean_keyword(raw)
        if seed and seed != main and seed not in seeds:
            seeds.append(seed)
    return {"main_keyword": main, "seed_keywords": seeds[:5], "reason": str(data.get("reason") or "").strip()[:200]}


_RISK_ASK = (
    "下面是 K 的 AI 从搜索结果里筛出来的「风险关键词」,每个都要定:approve(留着用)或 reject(不用)。\n"
    "规矩(和老板以前人工审的一致——以前几乎全驳,只留商品自己的叫法和资料里有依据的参数):\n"
    "- 默认 reject。三条同时满足才 approve:①说的就是这件商品,商品资料里有依据(参数、功能对得上);"
    "②不带任何品牌、商标、店名、别人的型号;③不带医疗、杀虫/驱虫功效、安全认证、"
    "「最好/第一/专家推荐/测试认可/年份榜单」这类没法证实的说法,也不暗示带了没有的配件或功能。\n"
    "- 拿不准就 reject。\n"
    'Reply JSON only: {"decisions": [{"term": "原样抄", "decision": "approve|reject", "reason": "一句中文"}]}'
)


# K 给的风险原因里带这些字 = 别人的牌子。不管模型怎么说一律不用(用了就是蹭商标,GMC 那次就是 Misrepresentation)
_TRADEMARK_MARKERS = ("商标", "品牌", "侵权", "竞品", "trademark", "brand")


def fill_risk_decisions(result: Any, terms: list[str], reasons: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """模型的判断 → K 要的 decisions。每个风险词都得有;没判到、判得不对的一律 reject(默认不用)。

    ``reasons`` = K 自己给每个风险词的原因;原因里说是商标/品牌的,模型说留也不留。
    """
    from .brain import parse_json

    reasons = reasons or {}
    data = parse_json(result)
    given: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        for item in data.get("decisions") or []:
            if isinstance(item, dict) and str(item.get("term") or "").strip():
                given[" ".join(str(item["term"]).lower().split())] = item
    out: list[dict[str, Any]] = []
    for term in terms:
        item = given.get(" ".join(term.lower().split())) or {}
        approve = item.get("decision") == "approve"
        reason = str(item.get("reason") or "").strip() or ("资料有依据,留着" if approve else "她没判到,按默认不用")
        k_reason = str(reasons.get(term) or "").lower()
        if approve and any(marker in k_reason for marker in _TRADEMARK_MARKERS):
            approve, reason = False, "K 说这是别人的商标/品牌,一律不用"
        out.append({"term": term, "decision": "approve" if approve else "reject", "reason": f"苏青禾:{reason}"[:1000]})
    return out


def selling_point_review(candidates: dict[str, Any], errors: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """K 生成的候选卖点 → 批准请求里的 bullets:证据核得上的批,核不上的驳。

    ``errors`` = 上一次提交 K 逐条退回的(下标 → 原因),这些直接驳。卖点的说法 K 的生成器已经只从证据里写,
    她这里不改字,只做取舍;老板在审核卡上看全部。
    """
    errors = errors or {}
    out: list[dict[str, Any]] = []
    for index, bullet in enumerate(_bullets(candidates)):
        keep = bullet.get("verification_status") == "verified" and index not in errors and str(bullet.get("evidence") or "").strip()
        item = {k: bullet.get(k) for k in ("id", "category", "text", "text_zh", "importance_score", "evidence", "evidence_excerpt")}
        item["importance_score"] = item.get("importance_score") or 0
        item["category"] = item.get("category") or "feature"
        item["review_decision"] = "approve" if keep else "reject"
        out.append(item)
    return out


def _judge(db: Session, ask: str, brief: str, extra: str, *, timeout: float = JUDGE_TIMEOUT_SECONDS) -> Any:
    from . import brain

    role = brain.plan_role(db)  # 她当天 Claude 额度用完就降到便宜档
    db.commit()  # 出网前放掉事务
    return brain._execute(
        role,
        [{"role": "user", "content": f"{ask}\n\n商品资料:\n{brief}\n\n{extra}".strip()}],
        timeout=timeout,
        usage_label=PIPELINE_USAGE_LABEL,
    )


# ---------------------------------------------------------------- 一步一步干


class StepError(RuntimeError):
    """这一步没做成;原因要能直接给老板看。"""


@dataclass
class Ctx:
    db: Session
    dossier: SqhDossier
    product: Any
    hands: k_ops.KHands
    scope: Any


def _actor(db: Session, dossier: SqhDossier) -> User:
    """替谁干:批建档卡的那个老板。"""
    card = db.scalar(select(SqhCard).where(SqhCard.ref == dossier.card_ref), execution_options=SKIP_ORG_DATA_ISOLATION) if dossier.card_ref else None
    user_id = getattr(card, "decided_by_user_id", None)
    user = db.get(User, int(user_id)) if user_id and str(user_id).isdigit() else None
    if user is None or not user.is_active:
        raise StepError("找不到批这件事的老板账号(或者已停用),没法替他在 K 里操作。")
    return user


def _step_material(ctx: Ctx) -> str:
    from ...k_series.product_knowledge import service as k_service
    from ...k_series.product_knowledge.schemas import ProductKnowledgeAttributePatch

    capture = ctx.dossier.capture if isinstance(ctx.dossier.capture, dict) else {}
    summary = material.collect(ctx.db, capture, usage_label=PIPELINE_USAGE_LABEL)
    items = material.attribute_items(summary)
    if items:
        k_service.patch_attributes(ctx.db, product_id=ctx.product.id, payload=ProductKnowledgeAttributePatch(items=items), scope_context=ctx.scope)
    draft = dict(ctx.dossier.draft or {})
    draft["material"] = summary
    ctx.dossier.draft = draft
    return f"卖点素材:功能点 {len(summary['features'])} 条、好处 {len(summary['claims'])} 条进了 K,宣传语 {len(summary['hype'])} 条留给老板看"


def _keyword_choice(ctx: Ctx) -> dict[str, Any]:
    pipe = _pipe(ctx.dossier)
    if pipe.get("main_keyword"):
        return {"main_keyword": pipe["main_keyword"], "seed_keywords": pipe.get("seed_keywords") or []}
    result = _judge(ctx.db, _KEYWORD_ASK, _product_brief(ctx.dossier, ctx.product), "")
    choice = parse_keyword_choice(result)
    if choice is None:
        raise StepError("没定出主关键词(模型的回答不合规矩)")
    _save_pipe(ctx.dossier, main_keyword=choice["main_keyword"], seed_keywords=choice["seed_keywords"], keyword_reason=choice["reason"])
    ctx.db.commit()
    return choice


def _execution_outcome(execution: Any) -> str:
    report = getattr(execution, "error_report_json", None) or {}
    code = report.get("code") if isinstance(report, dict) else None
    if getattr(execution, "current_step", None) in RISK_STEPS:
        terms = (getattr(execution, "claude_filter_result_json", None) or {}).get("risk_keywords") or []
        return f"关键词跑完了,停在风险词({len(terms)} 个等我判)"
    message = (report.get("message") if isinstance(report, dict) else "") or ""
    raise StepError(f"关键词没跑通:{code or getattr(execution, 'status', '?')} {message}"[:500])


def _step_keywords(ctx: Ctx, *, retry: bool) -> str:
    choice = _keyword_choice(ctx)
    if retry:
        execution = k_ops.latest_execution(ctx.db, ctx.product.id)
        report = (getattr(execution, "error_report_json", None) or {}) if execution is not None else {}
        step = (report.get("failed_step") if isinstance(report, dict) else None) or getattr(execution, "current_step", None) or "deepseek_enrichment"
        ctx.hands.retry_keywords(ctx.product.id, step=step, main_keyword=choice["main_keyword"], seed_keywords=choice["seed_keywords"])
    else:
        ctx.hands.start_keywords(ctx.product.id, main_keyword=choice["main_keyword"], seed_keywords=choice["seed_keywords"])
    ctx.db.expire_all()
    return _execution_outcome(k_ops.latest_execution(ctx.db, ctx.product.id))


def _step_risk_review(ctx: Ctx) -> str:
    execution = k_ops.latest_execution(ctx.db, ctx.product.id)
    raw_terms = (execution.claude_filter_result_json or {}).get("risk_keywords") or []
    terms = [str(t.get("term") if isinstance(t, dict) else t).strip() for t in raw_terms]
    terms = [t for t in terms if t]
    reasons = {str(t.get("term")).strip(): str(t.get("reason") or "") for t in raw_terms if isinstance(t, dict)}
    decisions: list[dict[str, Any]] = []
    if terms:
        listing = "\n".join(f"- {term}(K 的风险原因:{reasons.get(term, '')})" for term in terms)
        result = _judge(ctx.db, _RISK_ASK, _product_brief(ctx.dossier, ctx.product), f"风险词:\n{listing}")
        decisions = fill_risk_decisions(result, terms, reasons)
    ctx.hands.review_risk(ctx.product.id, execution_id=execution.id, decisions=decisions)
    kept = [d["term"] for d in decisions if d["decision"] == "approve"]
    _save_pipe(ctx.dossier, risk={"decisions": decisions, "at": datetime.now(UTC).isoformat()})
    return f"风险词判完:{len(terms)} 个里留了 {len(kept)} 个" + (f"({'、'.join(kept)[:120]})" if kept else "")


def _step_selling_points(ctx: Ctx) -> str:
    ctx.hands.generate_selling_points(ctx.product.id)
    return "卖点排进 K 的队列了,一两分钟出结果"


def _step_approve_selling_points(ctx: Ctx) -> str:
    candidates = ctx.product.selling_points_candidates_json or {}
    seo = [str(x) for x in candidates.get("seo_keywords") or []]
    review = selling_point_review(candidates)
    if not any(item["review_decision"] == "approve" for item in review):
        raise StepError("K 给的候选卖点一条证据都核不上,没法批")
    try:
        ctx.hands.approve_selling_points(ctx.product.id, bullets=review, seo_keywords=seo)
    except k_ops.KOpError as exc:
        # K 逐条核证据,退回的那几条驳掉再交一次;还不行就算这一步失败
        errors = rejected_indexes(exc.detail)
        if not errors:
            raise
        review = selling_point_review(candidates, errors)
        if not any(item["review_decision"] == "approve" for item in review):
            raise StepError("候选卖点被 K 逐条退回,剩下的一条都不够格") from exc
        ctx.hands.approve_selling_points(ctx.product.id, bullets=review, seo_keywords=seo)
    kept = sum(1 for item in review if item["review_decision"] == "approve")
    _save_pipe(ctx.dossier, selling_points={"kept": kept, "dropped": len(review) - kept, "at": datetime.now(UTC).isoformat()})
    return f"卖点批了 {kept} 条(驳 {len(review) - kept} 条证据核不上的)"


def rejected_indexes(detail: Any) -> dict[int, str]:
    """K 批卖点的 422(SELLING_POINT_EVIDENCE_REQUIRED)里带着 items: [{index, text, error}] → {下标: 原因}。"""
    items = detail.get("items") if isinstance(detail, dict) else None
    out: dict[int, str] = {}
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            out[item["index"]] = str(item.get("error") or "")
    return out


# 排进 K 队列的那几步各对应 K 的哪种任务(失败按 K 的任务表数)
JOB_TYPES = {"selling_points": "selling_points"}

STEPS = {
    "material": _step_material,
    "keywords": lambda ctx: _step_keywords(ctx, retry=False),
    "keywords_retry": lambda ctx: _step_keywords(ctx, retry=True),
    "risk_review": _step_risk_review,
    "selling_points": _step_selling_points,
    "approve_selling_points": _step_approve_selling_points,
}


def run_step(dossier_id: int, step: str) -> dict[str, Any]:
    """在流水线线程里跑一步(自己开会话)。成功清掉这一步的失败计数;失败记一笔,够两次就发「卡住」卡。"""
    from ....db.session import SessionLocal
    from .executor import _scope

    db = SessionLocal()
    try:
        with without_org_data_isolation():
            dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
            if dossier is None:
                return {"ok": False, "note": f"档案 #{dossier_id} 不在了"}
            from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

            product = db.get(P, UUID(str(dossier.k_product_id)), execution_options=SKIP_ORG_DATA_ISOLATION)
            sku = getattr(product, "sku", None) or dossier.k_product_id
            if step.startswith("block:"):
                blocked = step.split(":", 1)[1]
                last = k_ops.latest_jobs(db, dossier.k_product_id).get(JOB_TYPES.get(blocked, blocked)) or {}
                return _block(db, dossier=dossier, sku=sku, step=blocked, count=MAX_STEP_FAILURES, message=f"K 那边的任务失败:{last.get('error') or '没留原因'}")
            label = STEP_LABELS.get(step, step)
            try:
                if product is None:
                    raise StepError("K 里找不到这个产品了")
                hands = k_ops.KHands(db, actor=_actor(db, dossier), org_id=_scope(db).workspace_key)
                memory.log_activity(db, f"{sku}:开始{label}。", kind="pipeline")
                db.commit()
                note = STEPS[step](Ctx(db=db, dossier=dossier, product=product, hands=hands, scope=_scope(db)))
            except (StepError, k_ops.KOpError) as exc:
                db.rollback()
                return _record_failure(db, dossier_id=dossier_id, sku=sku, step=step, message=str(exc))
            except Exception as exc:  # noqa: BLE001 —— 一步出错不能拖垮她,记账后下一轮再看
                logger.exception("pipeline step failed dossier=%s step=%s", dossier_id, step)
                db.rollback()
                return _record_failure(db, dossier_id=dossier_id, sku=sku, step=step, message=f"{exc.__class__.__name__}: {exc}"[:500])
            dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
            failures = dict(_pipe(dossier).get("failures") or {})
            failures.pop(step, None)
            _save_pipe(dossier, failures=failures, last={"step": step, "note": note, "at": datetime.now(UTC).isoformat()})
            memory.log_activity(db, f"{sku}:{note}。"[:500], kind="pipeline")
            db.commit()
            return {"ok": True, "step": step, "note": note}
    finally:
        db.close()


def _record_failure(db: Session, *, dossier_id: int, sku: str, step: str, message: str) -> dict[str, Any]:
    dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION)
    failures = dict(_pipe(dossier).get("failures") or {})
    entry = dict(failures.get(step) or {})
    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last"] = message[:500]
    entry["at"] = datetime.now(UTC).isoformat()
    failures[step] = entry
    _save_pipe(dossier, failures=failures)
    memory.log_activity(db, f"{sku}:{STEP_LABELS.get(step, step)}没成(第 {entry['count']} 次):{message[:200]}", kind="error")
    if entry["count"] >= MAX_STEP_FAILURES:
        return _block(db, dossier=dossier, sku=sku, step=step, count=entry["count"], message=message)
    db.commit()
    return {"ok": False, "step": step, "note": message, "failures": entry["count"], "blocked": False}


def _block(db: Session, *, dossier: SqhDossier, sku: str, step: str, count: int, message: str) -> dict[str, Any]:
    """停手,发一张「卡住了」的卡等老板定:批 = 再试,驳 = 这个品先不做。"""
    label = STEP_LABELS.get(step, step)
    at = datetime.now(UTC).isoformat()
    card, _ = cards.create_card(
        db,
        # 每次卡住都是新的一张(pipe["blocked"] 挡着,没定之前不会再卡第二次);只按秒区分会撞上前一张已批的卡
        dedupe_key=f"k_blocked:{dossier.k_product_id}:{step}:{at}:{secrets.token_hex(3)}",
        kind=BLOCKED_CARD_KIND,
        title=f"{sku} 卡在「{label}」",
        conclusion=f"{label}试了 {count} 次都没成,我先停在这儿。批 = 让我再试一次;驳 = 这个品先不做。",
        why=f"最后一次的原因:{message[:400]}",
        if_not="这个品停在 K 里,后面的卖点、文案、图片、上架都不会动。",
        reversible=True,
        confidence="high",
        evidence={"dossier_id": dossier.id, "k_product_id": dossier.k_product_id, "sku": sku, "step": step, "count": count, "last_error": message[:500]},
    )
    _save_pipe(dossier, blocked={"step": step, "card_ref": card.ref, "at": at})
    memory.log_activity(db, f"{sku}:{label}连着没成,停手了,发卡 #{card.ref} 等老板定。", kind="error")
    memory.record(
        db, kind="observation", subject=f"{sku} 卡住了", body=f"{sku} 在「{label}」连着失败 {count} 次,发卡 #{card.ref} 等老板定。原因:{message[:300]}",
        refs={"dossier_id": dossier.id, "card_ref": card.ref, "step": step},
    )
    db.commit()
    return {"ok": False, "step": step, "note": message, "failures": count, "blocked": True, "card_ref": card.ref}


def after_decision(db: Session, card: SqhCard, *, decision: str) -> dict[str, Any]:
    """「卡住」卡的决定:批 = 清掉这一步的失败、再试;驳 = 这个品先停。只改档案里的记号,真正去干等流水线线程。"""
    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    dossier = db.get(SqhDossier, int(evidence.get("dossier_id") or 0), execution_options=SKIP_ORG_DATA_ISOLATION)
    if dossier is None:
        return {"ok": False, "note": "卡上的档案不在了。"}
    step = str(evidence.get("step") or "")
    failures = dict(_pipe(dossier).get("failures") or {})
    failures.pop(step, None)
    if decision == "approve":
        # K 任务表里的失败从这一刻重新数(next_step 按 reset 之后的失败次数判停)
        reset = {**(_pipe(dossier).get("reset") or {}), step: datetime.now(UTC).isoformat()}
        _save_pipe(dossier, failures=failures, blocked=None, reset=reset)
        db.flush()
        return {"ok": True, "note": f"好,我再试一次「{STEP_LABELS.get(step, step)}」,一会儿看结果。"}
    _save_pipe(dossier, failures=failures, blocked=None, stopped={"step": step, "card_ref": card.ref, "reason": card.decision_reason, "at": datetime.now(UTC).isoformat()})
    db.flush()
    return {"ok": True, "note": "收到,这个品先不做了。要接着做,跟我说一声。"}


# ---------------------------------------------------------------- 在另一个线程里干


class Runner:
    """K 流水线的活在另一个线程里干,一次只干一件。主循环每轮问一次「闲着吗」,闲着就派下一件。"""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqh-pipeline")
        self._future: Future[dict[str, Any]] | None = None
        self.current: tuple[int, str] | None = None
        self.last: dict[str, Any] | None = None

    def busy(self) -> bool:
        if self._future is None:
            return False
        if not self._future.done():
            return True
        try:
            self.last = self._future.result()
        except Exception:  # noqa: BLE001 —— run_step 自己兜了;这里只防万一
            logger.exception("pipeline step crashed %s", self.current)
        self._future = None
        self.current = None
        return False

    def maybe_start(self, db: Session) -> tuple[int, str] | None:
        if self.busy():
            return None
        job = pick(db)
        db.commit()
        if job is None:
            return None
        self.current = job
        self._future = self._executor.submit(run_step, *job)
        return job

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "BLOCKED_CARD_KIND",
    "PIPELINE_CARD_KINDS",
    "Runner",
    "STEP_LABELS",
    "View",
    "after_decision",
    "build_view",
    "fill_risk_decisions",
    "managed",
    "next_step",
    "parse_keyword_choice",
    "pick",
    "rejected_indexes",
    "run_step",
    "selling_point_review",
]
