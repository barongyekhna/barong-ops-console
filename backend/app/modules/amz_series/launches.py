"""A4 推新流程六步(用户 2026-09-15 定):推新只有一次,上架前把所有事做完,上架后只做三件事。

0 损益表门  pnl         售价 − 佣金 − FBA − 出厂头程 − 推新广告 − 促销退款 = 每件毛利;低于线亮红不许往下走
1 看战场    battlefield 对手名单、词清单、对手差评前三个坑(评论簇)、上架窗口
2 建 listing listing     事实表在「写五点」「出图」上够;主图 brief 过四道门并选定
3 上架前门  prelaunch   清单全绿才放行;人可以强制放行但要写原因(人的命令高于程序)
4 蜜月期    honeymoon   45 天只做三件事:收词升精准 / 看四个数 / 守纪律(不砍价不改 listing)
5 第 45 天判 verdict     达标 → 成长期;不达标 → 说清哪一环断了
6 复盘      retro       写进经验库,下一个新品从复盘开始

家规:推新期全部 L1(影子期只建议);绝不刷单、不激励评论;请求评论只走亚马逊官方按钮 / Solicitations。不 commit。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models.user import User
from . import fact_sheets, reviews, work_log
from .constants import EMPLOYEE_A, EMPLOYEE_C, EMPLOYEE_D, EMPLOYEE_E
from .models import AmzExperience, AmzImageBrief, AmzLaunch, AmzProduct, AmzSalesDaily, AmzSqp, AmzStore, AmzSuggestion
from .rules import PRODUCT_LINE_LABELS, SuggestionDraft
from .service import AmzServiceError

STAGES: tuple[str, ...] = ("pnl", "battlefield", "listing", "prelaunch", "honeymoon", "verdict", "retro", "growth", "killed")
STAGE_LABELS = {"pnl": "0 损益表门", "battlefield": "1 看战场", "listing": "2 建 listing", "prelaunch": "3 上架前门", "honeymoon": "4 蜜月期", "verdict": "5 第 45 天判", "retro": "6 复盘", "growth": "已进成长期", "killed": "已砍"}
HONEYMOON_DAYS = 45

USD_PER_CNY = Decimal("1") / Decimal("7.2")
DEFAULTS = {"referral_pct": 15.0, "launch_tacos_pct": 25.0, "promo_refund_pct": 10.0, "margin_floor_usd": 4.0}

# 第 45 天达标线
VERDICT_MIN_REVIEWS = 15
VERDICT_MIN_CVR_PCT = 10.0
VERDICT_MAX_MAIN_RANK = 30
STOCK_MIN_DAYS = 45


# ---------------------------------------------------------------- 0 损益表门(纯函数)


def _d(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (ArithmeticError, ValueError):
        return None


def compute_pnl(inputs: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """每件毛利。缺项不猜:列出来,门判不过。"""
    cost = facts.get("cost") or {}
    price = _d(inputs.get("price_usd")) or _d(cost.get("price_usd"))
    fba = _d(inputs.get("fba_fee_usd"))
    factory = _d(cost.get("factory_cny"))
    freight = _d(cost.get("freight_cny"))
    referral_pct = _d(inputs.get("referral_pct")) or Decimal(str(DEFAULTS["referral_pct"]))
    tacos_pct = _d(inputs.get("launch_tacos_pct")) or Decimal(str(DEFAULTS["launch_tacos_pct"]))
    promo_pct = _d(inputs.get("promo_refund_pct")) or Decimal(str(DEFAULTS["promo_refund_pct"]))
    floor = _d(inputs.get("margin_floor_usd")) or Decimal(str(DEFAULTS["margin_floor_usd"]))
    missing = [label for label, value in (("售价(美元)", price), ("FBA 配送费(美元)", fba), ("出厂价(元,事实表)", factory), ("头程(元,事实表)", freight)) if value is None]
    if missing:
        return {"ok": False, "missing": missing, "floor_usd": float(floor)}
    landed = (factory + freight) * USD_PER_CNY
    lines = {
        "售价": price,
        "佣金": -(price * referral_pct / 100),
        "FBA 配送费": -fba,
        "出厂 + 头程": -landed,
        "推新广告(TACOS)": -(price * tacos_pct / 100),
        "促销与退款": -(price * promo_pct / 100),
    }
    margin = sum(lines.values(), Decimal(0))
    return {
        "ok": margin >= floor,
        "missing": [],
        "lines": {k: round(float(v), 2) for k, v in lines.items()},
        "margin_usd": round(float(margin), 2),
        "margin_pct": round(float(margin / price * 100), 1) if price else None,
        "floor_usd": float(floor),
        "breakeven_price_usd": round(float((fba + landed + floor) / (1 - (referral_pct + tacos_pct + promo_pct) / 100)), 2) if (referral_pct + tacos_pct + promo_pct) < 100 else None,
        "assumptions": {"referral_pct": float(referral_pct), "launch_tacos_pct": float(tacos_pct), "promo_refund_pct": float(promo_pct), "cny_per_usd": 7.2},
    }


# ---------------------------------------------------------------- 3 上架前门(纯函数 + 取数)

MANUAL_ITEMS: tuple[tuple[str, str], ...] = (
    ("bullets_cover_pits", "五点第 1 条和副图 2 堵住了前三个坑"),
    ("backend_terms", "后台搜索词填好(250 字节,不重复页面上的词)"),
    ("anchor_price", "锚定价:标价高一档,coupon 降到目标价"),
    ("vine", "Vine 已报名"),
    ("request_review", "Request a Review 自动请求已开(或每天人工点)"),
    ("insert_card", "盒内插卡合规(不诱导好评、不给好处)"),
    ("ads_ready_paused", "广告活动建好、先暂停"),
)


def stock_days(inputs: dict[str, Any]) -> float | None:
    units = _d(inputs.get("fba_units"))
    velocity = _d(inputs.get("expected_daily_units"))
    if units is None or velocity is None or velocity <= 0:
        return None
    return round(float(units / velocity), 1)


def gate_items(db: Session, launch: AmzLaunch) -> list[dict[str, Any]]:
    inputs = launch.inputs_json or {}
    ticks = (launch.checklist_json or {}).get("ticks") or {}
    items: list[dict[str, Any]] = []
    pnl = launch.pnl_json or {}
    items.append({"key": "pnl", "label": f"每件毛利 ≥ ${pnl.get('floor_usd', DEFAULTS['margin_floor_usd'])}", "auto": True, "ok": bool(pnl.get("ok")), "detail": f"${pnl.get('margin_usd')}" if pnl.get("margin_usd") is not None else "损益表没算完"})
    copy_ok = fact_sheets.ready_for(db, product_line=launch.product_line, use="copy", store_code=launch.store_code, sku=launch.sku) is not None
    image_ok = fact_sheets.ready_for(db, product_line=launch.product_line, use="image", store_code=launch.store_code, sku=launch.sku) is not None
    items.append({"key": "facts", "label": "事实表在「写五点」和「出图」上都够", "auto": True, "ok": copy_ok and image_ok, "detail": f"写五点{'够' if copy_ok else '不够'} · 出图{'够' if image_ok else '不够'}"})
    main = db.scalar(select(AmzImageBrief).where(AmzImageBrief.store_code == launch.store_code, AmzImageBrief.product_line == launch.product_line, AmzImageBrief.position == "main", AmzImageBrief.status.in_(("approved", "live"))).order_by(AmzImageBrief.updated_at.desc()))
    items.append({"key": "main_image", "label": "主图过了四道门并被选定", "auto": True, "ok": main is not None, "detail": main.title if main else "图片页还没有选定的主图"})
    pits = (launch.battlefield_json or {}).get("pits") or []
    items.append({"key": "pits_known", "label": "对手差评前三个坑已找出", "auto": True, "ok": len(pits) >= 1, "detail": "、".join(p.get("theme", "") for p in pits) or "评论簇里还没有对手 1–3 星评论"})
    days = stock_days(inputs)
    items.append({"key": "stock", "label": f"FBA 库存够 {STOCK_MIN_DAYS} 天", "auto": True, "ok": days is not None and days >= STOCK_MIN_DAYS, "detail": f"{days} 天" if days is not None else "填入库件数和预计日销"})
    guard_ok = _d(inputs.get("launch_daily_budget_usd")) is not None and _d(inputs.get("launch_max_cpc_usd")) is not None
    items.append({"key": "guardrails", "label": "推新护栏:日预算上限、最高 CPC 已定", "auto": True, "ok": guard_ok, "detail": f"日预算 ${inputs.get('launch_daily_budget_usd')} · 最高 CPC ${inputs.get('launch_max_cpc_usd')}" if guard_ok else "没填"})
    for key, label in MANUAL_ITEMS:
        tick = ticks.get(key) or {}
        items.append({"key": key, "label": label, "auto": False, "ok": bool(tick.get("ok")), "detail": f"用户{tick.get('by')} {str(tick.get('at', ''))[:10]}" if tick.get("ok") else "待勾"})
    return items


# ---------------------------------------------------------------- 4/5 蜜月期与第 45 天(取数 + 纯函数)


def honeymoon_metrics(db: Session, launch: AmzLaunch, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    if launch.live_on is None:
        return {}
    day = (today - launch.live_on).days + 1
    inputs = launch.inputs_json or {}
    out: dict[str, Any] = {"day": day, "of": HONEYMOON_DAYS, "cvr_pct": None, "units": None, "sessions": None, "main_term": inputs.get("main_term"), "main_term_click_share_pct": None}
    if launch.asin:
        S = AmzSalesDaily
        row = db.execute(select(func.sum(S.units_ordered), func.sum(S.sessions)).where(S.store_code == launch.store_code, S.child_asin == launch.asin, S.report_date >= launch.live_on, S.report_date <= today)).one()
        units, sessions = int(row[0] or 0), int(row[1] or 0)
        out.update({"units": units, "sessions": sessions, "cvr_pct": round(units / sessions * 100, 2) if sessions else None})
        if inputs.get("main_term"):
            share = db.scalar(select(AmzSqp.clicks_share_pct).where(AmzSqp.store_code == launch.store_code, AmzSqp.asin == launch.asin, func.lower(AmzSqp.search_query) == str(inputs["main_term"]).lower()).order_by(AmzSqp.period_start.desc()))
            out["main_term_click_share_pct"] = float(share) if share is not None else None
    out["reviews"] = _d(inputs.get("reviews_count"))
    out["main_rank"] = _d(inputs.get("main_term_rank"))
    out["reviews"] = int(out["reviews"]) if out["reviews"] is not None else None
    out["main_rank"] = int(out["main_rank"]) if out["main_rank"] is not None else None
    return out


def judge_day45(metrics: dict[str, Any], *, pits_expectation_share_pct: float | None = None) -> dict[str, Any]:
    """达标:评论 ≥15、CVR >10%、主词前 30。不达标说清哪一环断了;缺数就说缺数,不硬判。"""
    reviews_n, cvr, rank, share = metrics.get("reviews"), metrics.get("cvr_pct"), metrics.get("main_rank"), metrics.get("main_term_click_share_pct")
    missing = [label for label, value in (("评论数", reviews_n), ("转化率(要 SP-API 销售与流量)", cvr), ("主词排名", rank)) if value is None]
    if missing:
        return {"result": "incomplete", "missing": missing, "breaks": []}
    breaks: list[dict[str, str]] = []
    if rank > VERDICT_MAX_MAIN_RANK:
        if share is not None and share < 1.0:
            breaks.append({"link": "词", "why": f"主词排第 {rank},点击份额只有 {share}%——词没接住", "fix": "殷笑笑把主词放进标题前 80 字符;殷素素主词精准组加价到护栏上限"})
        else:
            breaks.append({"link": "主图", "why": f"主词排第 {rank},有曝光没点击", "fix": "殷熊按同屏门重做主图"})
    if cvr <= VERDICT_MIN_CVR_PCT:
        if pits_expectation_share_pct is not None and pits_expectation_share_pct >= 30:
            breaks.append({"link": "预期", "why": f"转化率 {cvr}%,自家评论里预期落差占 {pits_expectation_share_pct}%", "fix": "副图 2 和五点 1 把「它不是什么」说死"})
        else:
            breaks.append({"link": "五点 / 价格", "why": f"转化率 {cvr}% ≤ {VERDICT_MIN_CVR_PCT}%", "fix": "对照兄弟店和对手的五点与价格;先改五点,价格留到最后"})
    if reviews_n < VERDICT_MIN_REVIEWS:
        breaks.append({"link": "评论", "why": f"45 天只有 {reviews_n} 条评论", "fix": "查 Vine 是否发出、请求评论是否每单都点;绝不做任何激励评论"})
    return {"result": "pass" if not breaks else "fail", "missing": [], "breaks": breaks}


# ---------------------------------------------------------------- 状态机


def get(db: Session, launch_id: UUID) -> AmzLaunch:
    row = db.get(AmzLaunch, launch_id)
    if row is None:
        raise AmzServiceError("launch not found", status_code=404, code="amz_launch_not_found")
    return row


def create(db: Session, *, store_code: str, product_line: str, title: str, actor: User, sku: str | None = None, asin: str | None = None) -> AmzLaunch:
    store = db.get(AmzStore, (store_code or "").lower())
    if store is None:
        raise AmzServiceError(f"unknown store {store_code}", status_code=404, code="amz_store_not_found")
    if product_line not in fact_sheets.PRODUCT_LINES:
        raise AmzServiceError(f"unknown product line {product_line}", status_code=422, code="amz_product_line_invalid")
    launch = AmzLaunch(store_code=store.store_code, product_line=product_line, sku=(sku or "").strip() or None, asin=(asin or "").strip().upper() or None, title=title.strip()[:255] or f"{store.store_code} {PRODUCT_LINE_LABELS.get(product_line, product_line)} 推新", stage="pnl", inputs_json=dict(DEFAULTS), created_by_user_id=int(actor.id))
    db.add(launch)
    db.flush()
    work_log.record(db, employee=EMPLOYEE_D, kind="observation", title=f"开始推新:{launch.title}", store_code=store.store_code, subject=f"launch|{launch.id}", sku=launch.sku, asin=launch.asin, detail={"launch_id": str(launch.id)}, source="human", actor_user_id=int(actor.id))
    return launch


def update_inputs(db: Session, *, launch: AmzLaunch, patch: dict[str, Any]) -> AmzLaunch:
    allowed = {"price_usd", "fba_fee_usd", "referral_pct", "launch_tacos_pct", "promo_refund_pct", "margin_floor_usd", "fba_units", "expected_daily_units", "launch_daily_budget_usd", "launch_max_cpc_usd", "main_term", "reviews_count", "main_term_rank", "competitor_asins", "keywords", "window_note", "sku", "asin"}
    inputs = dict(launch.inputs_json or {})
    for key, value in (patch or {}).items():
        if key not in allowed:
            continue
        if key in ("sku", "asin"):
            setattr(launch, key, (str(value or "").strip().upper() if key == "asin" else str(value or "").strip()) or None)
        else:
            inputs[key] = value
    launch.inputs_json = inputs
    refresh(db, launch=launch)
    return launch


def _derived_competitors(db: Session, launch: AmzLaunch) -> list[str]:
    """人没填就用系统从品牌分析选出来的对手(同站点、同产品线、在盯的)。"""
    from .models import AmzCompetitor, AmzStore  # noqa: PLC0415

    store = db.get(AmzStore, launch.store_code)
    if store is None:
        return []
    return list(db.scalars(select(AmzCompetitor.asin).where(AmzCompetitor.marketplace == store.country, AmzCompetitor.product_line == launch.product_line, AmzCompetitor.whose == "competitor", AmzCompetitor.active.is_(True)).order_by(AmzCompetitor.created_at)))


def refresh(db: Session, *, launch: AmzLaunch) -> AmzLaunch:
    """重算所有能算的:损益、战场(对手差评坑)、清单、蜜月指标。"""
    sheet = fact_sheets.ready_for(db, product_line=launch.product_line, use="pnl", store_code=launch.store_code, sku=launch.sku)
    facts = (sheet.facts_json if sheet is not None else {}) or {}
    pnl = compute_pnl(launch.inputs_json or {}, facts)
    if sheet is None:
        pnl = {**pnl, "ok": False, "missing": sorted(set(pnl.get("missing") or []) | {"事实表在「算损益」上不够"})}
    launch.pnl_json = pnl
    inputs = launch.inputs_json or {}
    launch.battlefield_json = {
        "competitor_asins": inputs.get("competitor_asins") or (facts.get("competitor_asins") or []) or _derived_competitors(db, launch),
        "keywords": inputs.get("keywords") or [],
        "window_note": inputs.get("window_note") or "",
        "pits": reviews.top_pits(db, product_line=launch.product_line),
        "own_clusters": reviews.cluster_table(db, product_line=launch.product_line, whose="ours")[:5],
    }
    items = gate_items(db, launch)
    launch.checklist_json = {**(launch.checklist_json or {}), "items": items, "all_green": all(i["ok"] for i in items)}
    if launch.live_on is not None:
        launch.honeymoon_json = honeymoon_metrics(db, launch)
    db.add(launch)
    db.flush()
    return launch


def tick(db: Session, *, launch: AmzLaunch, key: str, ok: bool, actor: User) -> AmzLaunch:
    if key not in {k for k, _ in MANUAL_ITEMS}:
        raise AmzServiceError("这一项是自动判的,不能手勾", status_code=422, code="amz_launch_tick_auto")
    checklist = dict(launch.checklist_json or {})
    ticks = dict(checklist.get("ticks") or {})
    ticks[key] = {"ok": bool(ok), "by": int(actor.id), "at": datetime.now(UTC).isoformat()}
    checklist["ticks"] = ticks
    launch.checklist_json = checklist
    return refresh(db, launch=launch)


NEXT_STAGE = {"pnl": "battlefield", "battlefield": "listing", "listing": "prelaunch"}


def advance(db: Session, *, launch: AmzLaunch, actor: User, override_reason: str | None = None) -> AmzLaunch:
    """往下走一步。每一步有自己的门;人可以强制放行,但必须写原因(进台账)。"""
    refresh(db, launch=launch)
    stage = launch.stage
    blocked: str | None = None
    if stage == "pnl" and not (launch.pnl_json or {}).get("ok"):
        blocked = "损益表门没过:" + ("缺 " + "、".join(launch.pnl_json.get("missing")) if launch.pnl_json.get("missing") else f"每件毛利 ${launch.pnl_json.get('margin_usd')} < ${launch.pnl_json.get('floor_usd')}")
    elif stage == "listing":
        items = {i["key"]: i for i in (launch.checklist_json or {}).get("items") or []}
        if not (items.get("facts", {}).get("ok") and items.get("main_image", {}).get("ok")):
            blocked = "listing 没建完:事实表要够、主图要选定"
    elif stage == "prelaunch" and not (launch.checklist_json or {}).get("all_green"):
        red = [i["label"] for i in (launch.checklist_json or {}).get("items") or [] if not i["ok"]]
        blocked = "上架前门没全绿:" + ";".join(red)
    elif stage not in ("pnl", "battlefield", "listing", "prelaunch"):
        raise AmzServiceError(f"{STAGE_LABELS.get(stage, stage)} 阶段不用手动往下走", status_code=409, code="amz_launch_stage_locked")
    if blocked and not (override_reason or "").strip():
        raise AmzServiceError(blocked, status_code=409, code="amz_launch_gate_blocked")
    if stage == "prelaunch":
        launch.stage = "honeymoon"
        launch.live_on = datetime.now(UTC).date()
    else:
        launch.stage = NEXT_STAGE[stage]
    note = f"推新 {STAGE_LABELS[stage]} → {STAGE_LABELS[launch.stage]}" + (f"(强制放行:{override_reason.strip()})" if blocked else "")
    work_log.record(db, employee=EMPLOYEE_D, kind="approved", title=note, why=blocked or "", store_code=launch.store_code, subject=f"launch|{launch.id}", sku=launch.sku, asin=launch.asin, detail={"launch_id": str(launch.id), "override": bool(blocked)}, source="human", actor_user_id=int(actor.id))
    return refresh(db, launch=launch)


def run_daily(db: Session, *, store_code: str, today: date | None = None) -> dict[str, int]:
    """蜜月期:每天重算指标;满 45 天判一次,并给殷素素落一条要人拍板的建议(会触发主动开口)。"""
    today = today or datetime.now(UTC).date()
    judged = updated = 0
    for launch in db.scalars(select(AmzLaunch).where(AmzLaunch.store_code == store_code, AmzLaunch.stage == "honeymoon")):
        refresh(db, launch=launch)
        updated += 1
        if launch.live_on is None or (today - launch.live_on).days + 1 < HONEYMOON_DAYS:
            continue
        own = reviews.cluster_table(db, product_line=launch.product_line, whose="ours")
        expectation_share = sum(c["share_pct"] for c in own if c["family"] == "expectation") if own else None
        verdict = judge_day45(launch.honeymoon_json or {}, pits_expectation_share_pct=expectation_share)
        launch.verdict_json = {**verdict, "judged_on": today.isoformat(), "metrics": launch.honeymoon_json}
        launch.stage = "verdict"
        db.add(launch)
        headline = {"pass": "达标,可以进成长期", "fail": "没达标:" + "、".join(b["link"] for b in verdict["breaks"]), "incomplete": "缺数没法判:" + "、".join(verdict["missing"])}[verdict["result"]]
        draft = SuggestionDraft(employee=EMPLOYEE_D, store_code=store_code, action_type="launch_day45", severity="bad", title=f"「{launch.title}」上架满 45 天:{headline}", why="; ".join(f"{b['link']}:{b['why']}" for b in verdict["breaks"]) or "评论、转化率、主词排名三项都过线。", prediction="; ".join(b["fix"] for b in verdict["breaks"]) or "进成长期,按正常梯子走;在推新页点「进成长期」并写复盘。", subject=f"launch|{launch.id}|day45", evidence={"launch_id": str(launch.id), **verdict})
        if db.scalar(select(AmzSuggestion.id).where(AmzSuggestion.dedupe_key == draft.dedupe_key)) is None:
            db.add(AmzSuggestion(employee=draft.employee, store_code=store_code, action_type=draft.action_type, severity=draft.severity, title=draft.title[:512], why=draft.why, prediction=draft.prediction, evidence_json=draft.evidence, level="L0", status="open", dedupe_key=draft.dedupe_key, as_of=today))
        judged += 1
    db.flush()
    return {"updated": updated, "judged": judged}


def close(db: Session, *, launch: AmzLaunch, outcome: str, retro: dict[str, Any], actor: User) -> AmzLaunch:
    """第 45 天判完后收尾:进成长期或砍。复盘写进经验库——下一个新品从这里开始。"""
    if launch.stage != "verdict":
        raise AmzServiceError("要先到「第 45 天判」才能收尾", status_code=409, code="amz_launch_not_judged")
    if outcome not in ("growth", "killed"):
        raise AmzServiceError("outcome 只能是 growth / killed", status_code=422, code="amz_launch_outcome_invalid")
    lessons = [str(x).strip() for x in (retro.get("lessons") or []) if str(x).strip()]
    if not lessons:
        raise AmzServiceError("复盘至少写一条教训", status_code=422, code="amz_launch_retro_required")
    launch.stage = outcome
    launch.retro_json = {"outcome": outcome, "lessons": lessons, "by": int(actor.id), "at": datetime.now(UTC).isoformat(), "verdict": launch.verdict_json}
    db.add(launch)
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    stmt = pg_insert(AmzExperience).values(entry_key=f"store|{launch.store_code}|launch|{launch.id}", scope="store", store_code=launch.store_code, action_type="launch", kind="launch", employee=EMPLOYEE_D, statement=f"推新「{launch.title}」{'进了成长期' if outcome == 'growth' else '砍了'}。教训:{';'.join(lessons)}", evidence_json={"launch_id": str(launch.id), "verdict": launch.verdict_json, "pnl": launch.pnl_json}, samples=1, hits=1 if outcome == "growth" else 0, value=None, status="active")
    db.execute(stmt.on_conflict_do_nothing(constraint="uq_amz_experience_key"))
    for employee in (EMPLOYEE_A, EMPLOYEE_C, EMPLOYEE_D, EMPLOYEE_E):
        work_log.record(db, employee=employee, kind="note", title=f"推新复盘:{launch.title} → {'成长期' if outcome == 'growth' else '砍'}", why=";".join(lessons), store_code=launch.store_code, subject=f"launch|{launch.id}", sku=launch.sku, asin=launch.asin, detail={"launch_id": str(launch.id)}, source="human", actor_user_id=int(actor.id))
    db.flush()
    return launch


def view(launch: AmzLaunch) -> dict[str, Any]:
    return {
        "id": str(launch.id),
        "store_code": launch.store_code,
        "product_line": launch.product_line,
        "product_line_label": PRODUCT_LINE_LABELS.get(launch.product_line, launch.product_line),
        "sku": launch.sku,
        "asin": launch.asin,
        "title": launch.title,
        "stage": launch.stage,
        "stage_label": STAGE_LABELS.get(launch.stage, launch.stage),
        "inputs": launch.inputs_json or {},
        "pnl": launch.pnl_json or {},
        "battlefield": launch.battlefield_json or {},
        "checklist": launch.checklist_json or {},
        "honeymoon": launch.honeymoon_json or {},
        "verdict": launch.verdict_json or {},
        "retro": launch.retro_json or {},
        "live_on": launch.live_on.isoformat() if launch.live_on else None,
        "updated_at": launch.updated_at.isoformat() if launch.updated_at else None,
    }


def list_launches(db: Session, *, store_codes: list[str] | None) -> list[AmzLaunch]:
    q = select(AmzLaunch).order_by(AmzLaunch.updated_at.desc())
    if store_codes is not None:
        if not store_codes:
            return []
        q = q.where(AmzLaunch.store_code.in_(store_codes))
    return list(db.scalars(q.limit(100)))


__all__ = ["DEFAULTS", "HONEYMOON_DAYS", "MANUAL_ITEMS", "STAGES", "STAGE_LABELS", "advance", "close", "compute_pnl", "create", "gate_items", "get", "honeymoon_metrics", "judge_day45", "list_launches", "refresh", "run_daily", "stock_days", "tick", "update_inputs", "view"]
