"""第②步:苏青禾接管 K 流水线(10-26)。

她建进 K 的产品(档案 created),她自己按顺序往下推,和运营在 K 里点按钮一样(k_ops.KHands,身份是批建档卡的老板):

  卖点素材 → 主关键词 → 关键词(K 工作流:富化 → SERP → 两道筛,停在风险词)→ 风险词(她判)
  → 卖点(K 生成 → 她批)→【价格卡,老板批】→ 文案 → 作图指令 → 出图(K 自动品牌审查)
  →【审核卡,老板批】→ 保存图片 → 推上独立站(草稿,P 的上架)→ 回读 Woo

价格卡排在文案前面:K 写文案按变体的包装数量写,颜色变体的主图要变体参考图——变体和售价得先定。

每一步做没做完、下一步干什么,一律从 K 自己的状态推出来(next_step 是纯函数),不另记一套进度。
她自己的判断(主关键词、风险词怎么判、卖点素材)记在档案 draft["pipeline"] / draft["material"] 里,卡上给老板看。

规矩:
- 一次只干一件,在另一个线程里干:K 的关键词一步能跑十几分钟,不能卡住她的 C19 聊天和批卡建档(Runner)。
- 同一步失败两次就停手,发一张「卡住了」的卡:批 = 再试,驳 = 这个品先不做。不会自己无限重试烧钱。
- 老板暂停她,这里也停(正在跑的那一步跑完为止)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import timedelta
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from . import cards, k_ops, material, memory, pricing
from .constants import USAGE_LABEL
from .models import SqhCard, SqhDossier

logger = logging.getLogger(__name__)

# 她推流水线时自己的 AI 判断(主关键词、风险词)记在这个名下;K 自己的调用记在 K 名下。
PIPELINE_USAGE_LABEL = f"{USAGE_LABEL}.k"
BLOCKED_CARD_KIND = "k_blocked"
PRICE_CARD_KIND = "k_price"
REVIEW_CARD_KIND = "k_review"
PIPELINE_CARD_KINDS = (BLOCKED_CARD_KIND, PRICE_CARD_KIND, REVIEW_CARD_KIND)
ACTIVE_JOB = {"pending", "running"}
# 审核卡上的暂存图留多久(K 的暂存图 24 小时没人保存就回收;老板不一定当天看)
REVIEW_HOLD_DAYS = 14
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
    "price_card": "出价格卡",
    "apply_price": "按批的价改变体、选运费模板",
    "copy": "写文案",
    "image_brief": "出作图指令",
    "render": "出图",
    "render_retry": "补出没出成的图",
    "review_card": "出审核卡",
    "rework": "按老板的意见改",
    "save_renders": "保存图片",
    "dispatch": "推上独立站",
    "readback": "回读独立站",
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
    price_applied: bool = False  # 售价填进 K 了(多变体每个都有价 / 单品有价)
    shipping_set: bool = False  # 运费模板选好了
    price_card: str | None = None  # 最近一张价格卡的状态
    copy_ok: bool = False  # 文案在,而且证据快照和现在的卖点/规格对得上(P 门禁同一判据)
    copy_job: str | None = None
    copy_failures: int = 0
    brief_ok: bool = False  # 作图指令在,而且是照现在这版文案出的
    brief_job: str | None = None
    brief_failures: int = 0
    render_requested: bool = False  # 照现在这版作图指令排过图
    render_active: bool = False
    render_failed: int = 0  # 最近一批里失败的张数
    render_retried: bool = False
    staged: int = 0  # 等保存的图
    audit_active: bool = False  # K 的品牌审查在跑(出图批次跑完、保存之后它都会自己跑)
    review_card: str | None = None
    saved: bool = False
    dispatched: bool = False
    upload_status: str | None = None
    live_checked: bool = False


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
        if not (view.price_applied and view.shipping_set):
            if view.price_card == "pending":
                return None  # 等老板批价格卡
            return "apply_price" if view.price_card == "approved" else "price_card"
        return _next_after_price(view)
    if view.sp_job in {"pending", "running"}:
        return None
    if view.sp_candidates:
        return "approve_selling_points"
    # 排队这一下总是「成功」的,失败在 K 那边——按 K 的任务表数,够数就停手发卡,别无限重排
    if view.sp_job == "failed" and view.sp_failures >= MAX_STEP_FAILURES:
        return "block:selling_points"
    return "selling_points"


def _next_after_price(view: View) -> str | None:
    """价定了以后:文案 → 作图指令 → 出图 → 审核卡 →(老板批)→ 保存 → 推上去 → 回读。"""
    if view.copy_job in ACTIVE_JOB:
        return None
    if not view.copy_ok:
        return "block:copy" if view.copy_job == "failed" and view.copy_failures >= MAX_STEP_FAILURES else "copy"
    if view.brief_job in ACTIVE_JOB:
        return None
    if not view.brief_ok:
        return "block:image_brief" if view.brief_job == "failed" and view.brief_failures >= MAX_STEP_FAILURES else "image_brief"
    if not view.render_requested:
        return "render"
    if view.render_active or view.audit_active:
        return None
    if view.review_card in {None, "stale", "expired"}:
        if view.render_failed and not view.render_retried:
            return "render_retry"
        return "review_card" if view.staged else "block:render"
    if view.review_card == "pending":
        return None
    if view.review_card == "rejected":
        return "rework"
    # 审核卡批了
    if not view.saved:
        return "save_renders"
    if not view.dispatched:
        return "dispatch"
    if view.upload_status in {"queued", "dispatched"}:
        return None
    if view.upload_status == "failed":
        return "block:dispatch"
    return None if view.live_checked else "readback"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


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
    material_version = (draft.get("material") or {}).get("version") if isinstance(draft.get("material"), dict) else None
    return View(
        material_done=(material_version or 0) >= material.MATERIAL_VERSION,
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
        price_applied=_price_applied(db, product),
        shipping_set=bool((product.shipping_class or "").strip()),
        price_card=_card_status(db, (pipe.get("price") or {}).get("card_ref")),
        **_later_view(db, product, pipe, jobs),
    )


def _later_view(db: Session, product: Any, pipe: dict[str, Any], jobs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """价定了以后那一段的事实:文案/作图指令/出图/审查从 K 读,审核卡和上架从她的记号 + P 的上传表读。"""
    from sqlalchemy import text

    from ...p_series.upload.assemble import _evidence_gate_blockers  # P 门禁判「文案证据对不对得上」的同一个函数

    reset = pipe.get("reset") or {}
    copy = product.marketing_copy_json
    brief = product.image_instruction_json
    brief_mark = pipe.get("brief") or {}
    render_mark = pipe.get("render") or {}
    publish = pipe.get("publish") or {}
    renders = db.execute(
        text(
            "SELECT batch_id, status, count(*) AS n FROM k_image_render_jobs WHERE product_id = :p "
            "AND batch_id = (SELECT batch_id FROM k_image_render_jobs WHERE product_id = :p ORDER BY created_at DESC LIMIT 1) "
            "GROUP BY batch_id, status"
        ),
        {"p": str(product.id)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    active_any = db.execute(
        text("SELECT count(*) FROM k_image_render_jobs WHERE product_id = :p AND status IN ('pending', 'running')"),
        {"p": str(product.id)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).scalar()
    latest_batch = str(renders[0]["batch_id"]) if renders else None
    upload = None
    if publish.get("job_id"):
        upload = db.execute(
            text("SELECT status FROM p_upload_jobs WHERE job_id = :j"), {"j": publish["job_id"]}, execution_options=SKIP_ORG_DATA_ISOLATION
        ).scalar()
    return {
        "copy_ok": bool(copy) and not _evidence_gate_blockers(product),
        "copy_job": (jobs.get("marketing_copy") or {}).get("status"),
        "copy_failures": k_ops.failed_attempts(db, product.id, "marketing_copy", since=reset.get("copy")),
        "brief_ok": bool(brief) and brief_mark.get("copy_digest") == _digest(copy),
        "brief_job": (jobs.get("image_brief") or {}).get("status"),
        "brief_failures": k_ops.failed_attempts(db, product.id, "image_brief", since=reset.get("image_brief")),
        "render_requested": bool(brief) and render_mark.get("brief_digest") == _digest(brief),
        "render_active": bool(active_any),
        "render_failed": sum(int(r["n"]) for r in renders if r["status"] == "failed"),
        "render_retried": bool(latest_batch) and render_mark.get("retried_batch") == latest_batch,
        "staged": len(staged_renders(db, product.id)),
        "audit_active": (jobs.get("brand_audit") or {}).get("status") in ACTIVE_JOB,
        "review_card": _card_status(db, (pipe.get("review") or {}).get("card_ref")),
        "saved": bool(publish.get("saved_at")),
        "dispatched": bool(publish.get("job_id")),
        "upload_status": upload,
        "live_checked": bool(publish.get("live")),
    }


def staged_renders(db: Session, product_id: Any) -> list[Any]:
    """等保存的出图(K 的 k_auto_render 暂存图),每个位置只留最新的一张(单张重做会在同一位置多出一张)。"""
    from ...k_series.product_knowledge.image_render_jobs import RENDER_PIPELINE_TAG
    from ...k_series.product_knowledge.models import KProductKnowledgeMediaAsset as A

    rows = db.scalars(
        select(A).where(A.product_id == product_id, A.asset_type == "image", A.status == "staged").order_by(A.created_at),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    latest: dict[int, Any] = {}
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("render_pipeline") == RENDER_PIPELINE_TAG:
            latest[int(meta.get("position") or 0)] = row
    return [latest[position] for position in sorted(latest)]


def _price_applied(db: Session, product: Any) -> bool:
    if (product.product_type or "") == "variable_product":
        prices = [v.price_override for v in k_ops.variant_rows(db, product.id)]
        return bool(prices) and all(p is not None for p in prices)
    return product.regular_price is not None


def _card_status(db: Session, ref: Any) -> str | None:
    if not ref:
        return None
    return db.scalar(select(SqhCard.status).where(SqhCard.ref == str(ref)), execution_options=SKIP_ORG_DATA_ISOLATION)


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
        if keep and is_certification_claim(bullet):
            keep = False  # 认证要有证书才能写(GMC 那次封号就是 Misrepresentation);老板在审核卡上看到、有证书再放
        item = {k: bullet.get(k) for k in ("id", "category", "text", "text_zh", "importance_score", "evidence", "evidence_excerpt")}
        item["importance_score"] = item.get("importance_score") or 0
        item["category"] = item.get("category") or "feature"
        item["review_decision"] = "approve" if keep else "reject"
        out.append(item)
    return out


def is_certification_claim(bullet: dict[str, Any]) -> bool:
    """说「通过了某某认证」的卖点。证据只是卖家自己填的属性,没有证书在手就不能对买家说。"""
    category = str(bullet.get("category") or "").lower()
    evidence = str(bullet.get("evidence") or "").lower()
    return "certif" in category or "certification" in evidence


def _judge(db: Session, ask: str, brief: str, extra: str, *, timeout: float = JUDGE_TIMEOUT_SECONDS, role: str | None = None) -> Any:
    from . import brain

    role = role or brain.plan_role(db)  # 她当天 Claude 额度用完就降到便宜档
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
    _drop_old_material(ctx)
    items = material.attribute_items(summary)
    if items:
        k_service.patch_attributes(ctx.db, product_id=ctx.product.id, payload=ProductKnowledgeAttributePatch(items=items), scope_context=ctx.scope)
    draft = dict(ctx.dossier.draft or {})
    draft["material"] = summary
    ctx.dossier.draft = draft
    return f"卖点素材:功能点 {len(summary['features'])} 条、好处 {len(summary['claims'])} 条进了 K,宣传语 {len(summary['hype'])} 条留给老板看"


def _drop_old_material(ctx: Ctx) -> None:
    """重读素材前把她上一版写进 K 的那几行删掉(只删她自己的组和来源);K 没有删属性的接口,
    删完照 K 的规矩作废依赖这些证据的产出(卖点、文案)——和 K 自己改属性时一样。"""
    from sqlalchemy import delete

    from ...k_series.product_knowledge.models import KProductKnowledgeAttribute as A
    from ...k_series.product_knowledge.service import invalidate_evidence_outputs

    result = ctx.db.execute(
        delete(A).where(A.product_id == ctx.product.id, A.attribute_group == material.MATERIAL_GROUP, A.source == material.MATERIAL_SOURCE),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    if result.rowcount:
        invalidate_evidence_outputs(ctx.product)
        ctx.db.add(ctx.product)
    ctx.db.flush()


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
    held = [item["text"] for item in review if item["review_decision"] == "reject" and is_certification_claim(item)]
    _save_pipe(ctx.dossier, selling_points={"kept": kept, "dropped": len(review) - kept, "held_certifications": held, "at": datetime.now(UTC).isoformat()})
    return f"卖点批了 {kept} 条(驳 {len(review) - kept} 条证据核不上的)"


def rejected_indexes(detail: Any) -> dict[int, str]:
    """K 批卖点的 422(SELLING_POINT_EVIDENCE_REQUIRED)里带着 items: [{index, text, error}] → {下标: 原因}。"""
    items = detail.get("items") if isinstance(detail, dict) else None
    out: dict[int, str] = {}
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            out[item["index"]] = str(item.get("error") or "")
    return out


def _contains_battery(dossier: SqhDossier) -> bool:
    """带锂电的走带电线路(运费模板上标「含电池」)。规格里有电芯/容量,或者品名带电池、锂电、充电。"""
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    specs = draft.get("specs") or {}
    if any(isinstance(specs.get(k), dict) and specs[k].get("status") == "ok" for k in ("battery_type", "capacity")):
        return True
    name = str(((draft.get("fields") or {}).get("name_zh") or {}).get("value") or "")
    return any(word in name for word in ("电池", "锂电", "充电"))


def _step_price_card(ctx: Ctx) -> str:
    draft = ctx.dossier.draft if isinstance(ctx.dossier.draft, dict) else {}
    pipe = _pipe(ctx.dossier)
    a = pricing.assumptions()
    lines = pricing.cost_lines([v for v in draft.get("variants") or [] if isinstance(v, dict)], a)
    if not lines:
        raise StepError("档案里没有规格和进价,算不了价")
    query = pipe.get("main_keyword") or ctx.product.primary_keyword or ctx.product.product_name_en or ""
    competitors = pricing.fetch_shopping(ctx.db, query=query, org_id=ctx.hands.org_id)
    previous = (pipe.get("price") or {}).get("card_ref")
    boss_reason = None
    if previous and _card_status(ctx.db, previous) == "rejected":
        boss_reason = ctx.db.scalar(select(SqhCard.decision_reason).where(SqhCard.ref == previous), execution_options=SKIP_ORG_DATA_ISOLATION)
    extra = pricing.price_prompt_extra(lines, competitors, a, boss_reason=boss_reason)
    result = _judge(ctx.db, pricing.PRICE_ASK, _product_brief(ctx.dossier, ctx.product), extra)
    lines, questions, summary = pricing.apply_plan(lines, result, a)
    included = [line for line in lines if line.include and line.price is not None]
    if not included:
        raise StepError("一个能卖的规格都算不出价(缺进价或重量)")
    battery = _contains_battery(ctx.dossier)
    sku = ctx.product.sku
    low, high = min(line.price for line in included), max(line.price for line in included)
    margins = [line.margin for line in included if line.margin is not None]
    price_text = f"${low:.2f}" if low == high else f"${low:.2f}–${high:.2f}"
    card, _ = cards.create_card(
        ctx.db,
        dedupe_key=f"k_price:{ctx.product.id}:{datetime.now(UTC).isoformat()}",
        kind=PRICE_CARD_KIND,
        title=f"{sku} 定价 {price_text}"[:60],
        conclusion=(
            f"{len(included)} 个规格,建议售价 {price_text},单件毛利率 {min(margins):.0%}–{max(margins):.0%}。"
            f"批了我就把它改成{'多变体' if len(included) > 1 else '单品'}、填价,运费模板选 {pricing.DEFAULT_SHIPPING_CLASS}"
            f"{'(含电池)' if battery else ''},然后接着写文案、出图。要改价就驳回,写上你要的价。"
        ),
        why="\n".join(
            part
            for part in (
                pricing.lines_text(lines),
                summary,
                *[f"要你定:{q}" for q in questions],
                pricing.competitors_text(competitors),
                pricing.assumption_text(a),
            )
            if part
        ),
        if_not="不定价,K 写不了文案(文案按规格写),后面的图片和上架都停着。",
        reversible=True,
        confidence="medium",
        evidence={
            "dossier_id": ctx.dossier.id,
            "k_product_id": str(ctx.product.id),
            "sku": sku,
            "main_keyword": query,
            "variants": [line.as_dict() for line in lines],
            "competitors": competitors,
            "questions": questions,
            "summary": summary,
            "assumptions": {k: getattr(a, k) for k in a.__dataclass_fields__},
            "shipping": {"class": pricing.DEFAULT_SHIPPING_CLASS, "contains_battery": battery},
            "boss_reason": boss_reason,
            "recheck": {"type": PRICE_CARD_KIND, "product_id": str(ctx.product.id)},
        },
    )
    _save_pipe(ctx.dossier, price={"card_ref": card.ref, "at": datetime.now(UTC).isoformat()})
    return f"价格卡 #{card.ref} 发了:{len(included)} 个规格 {price_text}"


def _step_apply_price(ctx: Ctx) -> str:
    ref = (_pipe(ctx.dossier).get("price") or {}).get("card_ref")
    card = ctx.db.scalar(select(SqhCard).where(SqhCard.ref == str(ref)), execution_options=SKIP_ORG_DATA_ISOLATION) if ref else None
    if card is None or card.status != "approved":
        raise StepError("找不到批过的价格卡")
    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    lines = [line for line in evidence.get("variants") or [] if isinstance(line, dict) and line.get("include") and line.get("price")]
    if not lines:
        raise StepError("价格卡上没有要卖的规格")
    heaviest = max(lines, key=lambda line: line.get("weight_g") or 0)
    physical: dict[str, Any] = {"price_currency": "USD"}
    if heaviest.get("weight_g"):
        physical["package_weight_json"] = {"value": heaviest["weight_g"], "unit": "g"}
    if isinstance(heaviest.get("dims_cm"), list) and len(heaviest["dims_cm"]) == 3:
        length, width, height = heaviest["dims_cm"]
        physical["package_dimensions_json"] = {"length": length, "width": width, "height": height, "unit": "cm"}
    if len(lines) == 1:
        ctx.hands.update_product(ctx.product.id, regular_price=lines[0]["price"], **physical)
    else:
        default = next((v for v in k_ops.variant_rows(ctx.db, ctx.product.id) if (v.attributes_json or {}).get("default_variant")), None)
        variants = []
        for index, line in enumerate(lines):
            label = line.get("label_en") or line.get("name_en")
            axis = line.get("axis") or "function"
            count = re.search(r"\d+", str(label or "")) if axis == "quantity" else None
            # K 的 quantity 是整数(几件装);标签里抠不出数就按 function 放
            item: dict[str, Any] = {"quantity": int(count.group())} if count else {("function" if axis == "quantity" else axis): label}
            item["price_override"] = line["price"]
            if index == 0 and default is not None:
                item["variant_id"] = default.id  # 原来那条默认变体挂着参考图,原地改,删了会 409
            if line.get("weight_g"):
                item["weight_json"] = {"value": line["weight_g"], "unit": "g"}
            if isinstance(line.get("dims_cm"), list) and len(line["dims_cm"]) == 3:
                item["dimensions_json"] = dict(zip(("length", "width", "height"), line["dims_cm"]), unit="cm")
            if line.get("axis") == "color" and line.get("image_url"):
                item["reference_image_url"] = line["image_url"]
            variants.append(item)
        ctx.hands.sync_variants(ctx.product.id, product_type="variable_product", variants=variants)
        ctx.hands.update_product(ctx.product.id, **physical)
    shipping = evidence.get("shipping") or {}
    ctx.db.expire_all()
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    product = ctx.db.get(P, ctx.product.id, execution_options=SKIP_ORG_DATA_ISOLATION)
    ctx.hands.set_shipping(product, shipping_class_slug=shipping.get("class") or pricing.DEFAULT_SHIPPING_CLASS, contains_battery=bool(shipping.get("contains_battery")))
    ctx.db.expire_all()
    product = ctx.db.get(P, ctx.product.id, execution_options=SKIP_ORG_DATA_ISOLATION)
    if not (_price_applied(ctx.db, product) and (product.shipping_class or "").strip()):
        raise StepError("改完回读:价格或运费模板没落上")
    return f"按批的价改好了:{len(lines)} 个规格,运费模板 {product.shipping_class}"


def _price_fingerprint(db: Session, recheck: dict[str, Any]) -> str:
    """价格卡建好之后,K 里这个品的类型、变体、价格有人动过 → 卡作废重出(批的时候核)。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    try:
        product = db.get(P, UUID(str(recheck.get("product_id"))), execution_options=SKIP_ORG_DATA_ISOLATION)
    except (TypeError, ValueError):
        product = None
    if product is None:
        return cards.fingerprint({"missing": True})
    variants = sorted((str(v.id), str(v.price_override)) for v in k_ops.variant_rows(db, product.id))
    return cards.fingerprint({"type": product.product_type, "price": str(product.regular_price), "variants": variants})


cards.register_fingerprinter(PRICE_CARD_KIND, _price_fingerprint)


# ---------------------------------------------------------------- 文案 → 作图指令 → 出图


def _step_copy(ctx: Ctx) -> str:
    ctx.hands.generate_copy(ctx.product.id)
    return "文案排进 K 的队列了(Claude 写,一两分钟)"


def _step_image_brief(ctx: Ctx) -> str:
    ctx.hands.generate_image_brief(ctx.product.id)
    # 作图指令是照文案出的:记下这版文案,文案换了指令就得重出
    _save_pipe(ctx.dossier, brief={"copy_digest": _digest(ctx.product.marketing_copy_json), "at": datetime.now(UTC).isoformat()})
    return "作图指令排进 K 的队列了"


def _step_render(ctx: Ctx) -> str:
    try:
        out = ctx.hands.render_images(ctx.product.id)
    except k_ops.KOpError as exc:
        if exc.code in {"IMAGE_BRIEF_SELLING_POINTS_STALE", "IMAGE_BRIEF_EVIDENCE_STALE"}:
            _save_pipe(ctx.dossier, brief=None)  # 卖点/规格变过,作图指令重出
            return "作图指令跟不上现在的卖点了,重新出一版"
        raise
    batch = str(getattr(out, "batch_id", "") or "")
    _save_pipe(ctx.dossier, render={"brief_digest": _digest(ctx.product.image_instruction_json), "batch_id": batch, "at": datetime.now(UTC).isoformat()})
    return f"出图排上了:{len(getattr(out, 'jobs', []) or [])} 张(k-worker 一张十几秒到一分钟)"


def _step_render_retry(ctx: Ctx) -> str:
    from sqlalchemy import text

    batch = ctx.db.execute(
        text("SELECT batch_id FROM k_image_render_jobs WHERE product_id = :p ORDER BY created_at DESC LIMIT 1"),
        {"p": str(ctx.product.id)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).scalar()
    ctx.hands.render_retry(ctx.product.id, batch_id=batch)
    mark = {**(_pipe(ctx.dossier).get("render") or {}), "retried_batch": str(batch)}
    _save_pipe(ctx.dossier, render=mark)
    return "没出成的那几张再出一次"


# ---------------------------------------------------------------- 审核卡


COMPLIANCE_ASK = (
    "你在帮一个美国独立站上新品前把关:按美国的规矩看这件商品和它的英文商品页,有没有会惹麻烦的地方。\n"
    "只看真有的,常见的有:驱虫/杀虫/消毒功效(EPA 管,含药剂的驱蚊片尤其要登记)、医疗健康功效(FDA)、儿童用品(CPSC/CPSIA)、"
    "带电子发射的(FCC)、锂电池(运输、标注)、没证书的认证说法、别人的商标、Prop 65。\n"
    "每条一句中文,说清是什么、为什么、建议怎么办;没有就给空数组。\n"
    'Reply JSON only: {"concerns": ["..."]}'
)


def _copy_summary(copy: Any) -> dict[str, Any]:
    copy = copy if isinstance(copy, dict) else {}
    page = copy.get("product_page_copy") if isinstance(copy.get("product_page_copy"), dict) else {}
    fold = page.get("above_the_fold") if isinstance(page.get("above_the_fold"), dict) else {}
    seo = copy.get("seo") if isinstance(copy.get("seo"), dict) else {}
    return {
        "h1": seo.get("h1"),
        "title": seo.get("title"),
        "headline": fold.get("headline"),
        "short_description": fold.get("short_description"),
        "bullets": [str(b) for b in page.get("key_bullets") or []][:8],
        "faq": len(copy.get("page_faq") or []),
        "missing_inputs": [str(m) for m in copy.get("missing_inputs") or []][:6],
    }


def _hold(db: Session, assets: list[Any]) -> None:
    """审核卡上的暂存图标上 hold_until:K 的 24 小时回收不收它们(老板批了才保存)。"""
    until = (datetime.now(UTC) + timedelta(days=REVIEW_HOLD_DAYS)).isoformat()
    for asset in assets:
        asset.metadata_json = {**(asset.metadata_json or {}), "hold_until": until}
        db.add(asset)
    db.flush()


def _step_review_card(ctx: Ctx) -> str:
    from .brain import parse_json

    product, dossier = ctx.product, ctx.dossier
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    pipe = _pipe(dossier)
    staged = staged_renders(ctx.db, product.id)
    images = [
        {
            "asset_id": str(a.id),
            "position": int((a.metadata_json or {}).get("position") or 0),
            "placement": (a.metadata_json or {}).get("placement") or "gallery",
            "role": (a.metadata_json or {}).get("role_label") or a.asset_role,
        }
        for a in staged
    ]
    copy = _copy_summary(product.marketing_copy_json)
    points = [str(b.get("text")) for b in _bullets(product.selling_points_approved_json)]
    audit = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    violations = [
        {"kind": kind, "position": v.get("position"), "finding": str(v.get("finding") or v.get("term") or "")[:300]}
        for kind in ("text", "image")
        for v in audit.get(f"{kind}_violations") or []
        if isinstance(v, dict)
    ]
    price_ref = (pipe.get("price") or {}).get("card_ref")
    price_card = ctx.db.scalar(select(SqhCard).where(SqhCard.ref == str(price_ref)), execution_options=SKIP_ORG_DATA_ISOLATION) if price_ref else None
    prices = [
        {"label": line.get("label_en"), "price": line.get("price")}
        for line in ((price_card.evidence or {}).get("variants") if price_card else []) or []
        if isinstance(line, dict) and line.get("include")
    ]
    flagged = [f"{f.get('path')}({f.get('status')})" for f in draft.get("flagged") or [] if isinstance(f, dict)]
    hype = [r["text"] for r in (draft.get("material") or {}).get("hype") or [] if isinstance(r, dict)]
    held = (pipe.get("selling_points") or {}).get("held_certifications") or []
    result = _judge(
        ctx.db,
        COMPLIANCE_ASK,
        _product_brief(dossier, product),
        "英文商品页:\n" + json.dumps({k: copy[k] for k in ("h1", "headline", "short_description", "bullets")}, ensure_ascii=False),
    )
    data = parse_json(result)
    concerns = [str(c).strip()[:300] for c in (data.get("concerns") or []) if str(c).strip()][:6] if isinstance(data, dict) else []
    _hold(ctx.db, staged)
    lines = [
        f"标题:{copy['h1'] or product.product_name_en}",
        *[f"• {b}" for b in copy["bullets"][:5]],
        f"图片 {len(images)} 张(详情在卡片里);品牌审查:{'干净' if audit.get('clean') and not violations else f'有 {len(violations)} 处要你看'}",
        *[f"审查发现:第 {v['position']} 张 {v['finding'][:120]}" if v["kind"] == "image" else f"审查发现(文字):{v['finding'][:120]}" for v in violations[:4]],
        *[f"合规要你看:{c}" for c in concerns],
        *([f"没写进卖点的认证说法(有证书再放):{';'.join(held)[:200]}"] if held else []),
        *([f"卖家的宣传语我没用:{'、'.join(hype)[:200]}"] if hype else []),
        *([f"档案里还没定的:{'、'.join(flagged)[:200]}"] if flagged else []),
        *(["价格:" + "、".join(f"{item['label']} ${item['price']}" for item in prices)] if prices else []),
    ]
    card, _ = cards.create_card(
        ctx.db,
        dedupe_key=f"k_review:{product.id}:{datetime.now(UTC).isoformat()}",
        kind=REVIEW_CARD_KIND,
        title=f"{product.sku} 上架审核:文案 + {len(images)} 张图"[:60],
        conclusion=(
            "卖点、文案、图片都齐了。批了我就保存图片、推上独立站(落草稿,你在 WP 后台看过再点发布);"
            "不行就驳回,写清楚哪张图、哪句话要改,我照着改。"
        ),
        why="\n".join(line for line in lines if line),
        if_not="这个品停在 K 里,不上架。",
        reversible=True,
        confidence="medium" if (violations or concerns) else "high",
        evidence={
            "dossier_id": dossier.id,
            "k_product_id": str(product.id),
            "sku": product.sku,
            "main_keyword": pipe.get("main_keyword"),
            "copy": copy,
            "selling_points": points,
            "images": images,
            "audit": {"clean": bool(audit.get("clean")), "violations": violations, "errors": [str(e)[:200] for e in audit.get("errors") or []]},
            "concerns": concerns,
            "held_certifications": held,
            "hype": hype,
            "flagged": flagged,
            "prices": prices,
            "risk": [d for d in (pipe.get("risk") or {}).get("decisions") or [] if isinstance(d, dict)],
            "recheck": {"type": REVIEW_CARD_KIND, "product_id": str(product.id)},
        },
    )
    _save_pipe(dossier, review={"card_ref": card.ref, "at": datetime.now(UTC).isoformat(), "history": (pipe.get("review") or {}).get("history") or []})
    return f"审核卡 #{card.ref} 发了:{len(images)} 张图" + (f",合规 {len(concerns)} 条要看" if concerns else "")


def _review_fingerprint(db: Session, recheck: dict[str, Any]) -> str:
    """审核卡建好之后,文案、卖点、待保存的图有人动过 → 卡作废重出(老板批的得是他看到的那一版)。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    try:
        product = db.get(P, UUID(str(recheck.get("product_id"))), execution_options=SKIP_ORG_DATA_ISOLATION)
    except (TypeError, ValueError):
        product = None
    if product is None:
        return cards.fingerprint({"missing": True})
    return cards.fingerprint(
        {
            "copy": _digest(product.marketing_copy_json),
            "points": _digest(product.selling_points_approved_json),
            "staged": [str(a.id) for a in staged_renders(db, product.id)],
        }
    )


cards.register_fingerprinter(REVIEW_CARD_KIND, _review_fingerprint)


REWORK_ASK = (
    "老板驳回了这件商品的上架审核卡,下面是他的原话和卡上的东西(卖点按编号、图片按位置号)。判断他要改什么,只输出 JSON:\n"
    '{"drop_points": ["要去掉的卖点编号,比如 bp3"], "image_fixes": [{"position": 2, "instruction": "这张图怎么改,一句话"}], '
    '"unclear": "他说的里面对不上卖点或图片、或者我改不了的那部分,原话照抄;没有就空字符串"}\n'
    "文案是从卖点写出来的:老板说某句话不对,去掉对应的卖点文案就会跟着改。"
)


def _step_rework(ctx: Ctx) -> str:
    from .brain import parse_json

    pipe = _pipe(ctx.dossier)
    review = pipe.get("review") or {}
    card = ctx.db.scalar(select(SqhCard).where(SqhCard.ref == str(review.get("card_ref"))), execution_options=SKIP_ORG_DATA_ISOLATION)
    reason = (card.decision_reason if card else "") or ""
    approved = _bullets(ctx.product.selling_points_approved_json)
    staged = {int((a.metadata_json or {}).get("position") or 0): a for a in staged_renders(ctx.db, ctx.product.id)}
    listing = "\n".join(f"{b.get('id')}: {b.get('text')}" for b in approved)
    pictures = "\n".join(f"第 {pos} 张:{(a.metadata_json or {}).get('role_label') or a.asset_role}" for pos, a in staged.items())
    result = _judge(ctx.db, REWORK_ASK, _product_brief(ctx.dossier, ctx.product), f"老板原话:{reason}\n\n卖点:\n{listing}\n\n图片:\n{pictures}", role="fast")
    data = parse_json(result) if result is not None else None
    data = data if isinstance(data, dict) else {}
    drop = {str(x) for x in data.get("drop_points") or []} & {str(b.get("id")) for b in approved}
    fixes = [f for f in data.get("image_fixes") or [] if isinstance(f, dict) and int(f.get("position") or 0) in staged and str(f.get("instruction") or "").strip()]
    unclear = str(data.get("unclear") or "").strip()
    done: list[str] = []
    if drop:
        bullets = [
            {**{k: b.get(k) for k in ("id", "category", "text", "text_zh", "importance_score", "evidence", "evidence_excerpt")}, "review_decision": "reject" if str(b.get("id")) in drop else "approve"}
            for b in approved
        ]
        ctx.hands.approve_selling_points(ctx.product.id, bullets=bullets, seo_keywords=[str(x) for x in (ctx.product.selling_points_approved_json or {}).get("seo_keywords") or []])
        done.append(f"去掉卖点 {'、'.join(sorted(drop))}(文案、作图指令、图跟着重出)")
    elif fixes:
        for fix in fixes:
            ctx.hands.render_rework(ctx.product.id, asset_id=staged[int(fix["position"])].id, extra_prompt=f"{fix['instruction']}(老板原话:{reason[:300]})")
        done.append(f"按意见重做第 {'、'.join(str(int(f['position'])) for f in fixes)} 张图")
    if not done:
        raise StepError(f"老板的意见我对不上要改哪里:{unclear or reason[:200]}")
    history = [*(review.get("history") or []), {"card_ref": review.get("card_ref"), "reason": reason, "did": done, "unclear": unclear}]
    _save_pipe(ctx.dossier, review={"card_ref": None, "history": history})
    return ";".join(done) + (f";这部分我改不了,在新审核卡上再问你:{unclear[:120]}" if unclear else "")


# ---------------------------------------------------------------- 老板批了审核卡:保存 → 推上去 → 回读


def _step_save_renders(ctx: Ctx) -> str:
    ctx.hands.save_renders(ctx.product.id)
    publish = {**(_pipe(ctx.dossier).get("publish") or {}), "saved_at": datetime.now(UTC).isoformat()}
    _save_pipe(ctx.dossier, publish=publish)
    return "图片保存了(主图绑好),K 再跑一遍品牌审查"


def _step_dispatch(ctx: Ctx) -> str:
    try:
        out = ctx.hands.dispatch(ctx.product.id)
    except k_ops.KOpError as exc:
        blockers = exc.detail.get("blockers") if isinstance(exc.detail, dict) else None
        raise StepError(f"上架门禁没过:{';'.join(blockers) if blockers else exc.message}") from exc
    publish = {**(_pipe(ctx.dossier).get("publish") or {}), "job_id": out.job_id, "dispatched_at": datetime.now(UTC).isoformat()}
    _save_pipe(ctx.dossier, publish=publish)
    return f"推上独立站的任务排上了(P 上传任务 {out.job_id},一两分钟)"


def _step_readback(ctx: Ctx) -> str:
    """不信「上传成功」四个字:去 Woo 上把这个商品读回来,确认它真在、是草稿。"""
    from sqlalchemy import text

    from ...content_core.wc_sync import fetch_product_states_safely

    publish = _pipe(ctx.dossier).get("publish") or {}
    row = ctx.db.execute(
        text("SELECT status, external_product_id, external_url, error FROM p_upload_jobs WHERE job_id = :j"),
        {"j": publish.get("job_id")},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().first()
    if row is None or row["status"] != "success" or not row["external_product_id"]:
        raise StepError(f"上传任务不是成功状态:{dict(row) if row else '找不到'}")
    woo_id = int(row["external_product_id"])
    ctx.db.commit()  # 出网前放掉事务
    states = fetch_product_states_safely(ctx.db, [woo_id])
    state = (states or {}).get(woo_id)
    if not state:
        raise StepError(f"Woo 上读不到商品 #{woo_id}")
    live = {"woo_id": woo_id, "status": state.get("status"), "url": row["external_url"], "checked_at": datetime.now(UTC).isoformat()}
    _save_pipe(ctx.dossier, publish={**publish, "live": live})
    memory.record(
        ctx.db, kind="observation", subject=f"{ctx.product.sku} 上了独立站",
        body=f"{ctx.product.sku} 推上独立站:Woo #{woo_id},状态 {state.get('status')}(新品落草稿,老板在 WP 后台看过再发布)。",
        refs={"dossier_id": ctx.dossier.id, "woo_id": woo_id, "k_product_id": str(ctx.product.id)},
    )
    return f"Woo 上读回来了:#{woo_id},状态 {state.get('status')}"


# 排进 K 队列的那几步各对应 K 的哪种任务(失败按 K 的任务表数)
JOB_TYPES = {"selling_points": "selling_points", "copy": "marketing_copy", "image_brief": "image_brief"}

STEPS = {
    "material": _step_material,
    "keywords": lambda ctx: _step_keywords(ctx, retry=False),
    "keywords_retry": lambda ctx: _step_keywords(ctx, retry=True),
    "risk_review": _step_risk_review,
    "selling_points": _step_selling_points,
    "approve_selling_points": _step_approve_selling_points,
    "price_card": _step_price_card,
    "apply_price": _step_apply_price,
    "copy": _step_copy,
    "image_brief": _step_image_brief,
    "render": _step_render,
    "render_retry": _step_render_retry,
    "review_card": _step_review_card,
    "rework": _step_rework,
    "save_renders": _step_save_renders,
    "dispatch": _step_dispatch,
    "readback": _step_readback,
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
                return _block(db, dossier=dossier, sku=sku, step=blocked, count=MAX_STEP_FAILURES, message=_block_reason(db, dossier, blocked))
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


def _block_reason(db: Session, dossier: SqhDossier, step: str) -> str:
    from sqlalchemy import text

    if step == "render":
        errors = db.execute(
            text("SELECT position, error FROM k_image_render_jobs WHERE product_id = :p AND status = 'failed' ORDER BY created_at DESC LIMIT 3"),
            {"p": str(dossier.k_product_id)},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).fetchall()
        return "一张图都没出成:" + ";".join(f"第 {pos} 张 {str(err or '')[:120]}" for pos, err in errors) if errors else "一张图都没出成"
    if step == "dispatch":
        job_id = ((_pipe(dossier).get("publish") or {}).get("job_id"))
        error = db.execute(text("SELECT error FROM p_upload_jobs WHERE job_id = :j"), {"j": job_id}, execution_options=SKIP_ORG_DATA_ISOLATION).scalar()
        return f"推上独立站失败:{str(error or '没留原因')[:300]}"
    last = k_ops.latest_jobs(db, dossier.k_product_id).get(JOB_TYPES.get(step, step)) or {}
    return f"K 那边的任务失败:{last.get('error') or '没留原因'}"


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
    if card.kind == PRICE_CARD_KIND:
        # 真正去改交给流水线线程(apply_price / 重出价格卡),这里只回一句
        if decision == "approve":
            return {"ok": True, "note": "好,我这就按这个价改变体、选运费模板,然后接着写文案、出图。"}
        return {"ok": True, "note": "收到,我照你说的重算一版价格卡。"}
    if card.kind == REVIEW_CARD_KIND:
        if decision == "approve":
            return {"ok": True, "note": "好,我这就保存图片、推上独立站(落草稿),推好了在 WP 后台能看到。"}
        return {"ok": True, "note": "收到,我照你说的改,改好再给你看。"}
    step = str(evidence.get("step") or "")
    failures = dict(_pipe(dossier).get("failures") or {})
    failures.pop(step, None)
    if decision == "approve":
        # K 任务表里的失败从这一刻重新数(next_step 按 reset 之后的失败次数判停)
        reset = {**(_pipe(dossier).get("reset") or {}), step: datetime.now(UTC).isoformat()}
        updates: dict[str, Any] = {"failures": failures, "blocked": None, "reset": reset}
        if step == "dispatch":
            # 上传失败那一单作废,重新推
            updates["publish"] = {k: v for k, v in (_pipe(dossier).get("publish") or {}).items() if k not in {"job_id", "dispatched_at"}}
        if step == "render":
            updates["render"] = None  # 重新出一批
        _save_pipe(dossier, **updates)
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
    "PRICE_CARD_KIND",
    "REVIEW_CARD_KIND",
    "staged_renders",
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
