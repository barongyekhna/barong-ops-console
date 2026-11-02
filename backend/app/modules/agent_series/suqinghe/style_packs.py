"""苏青禾管风格包注册表的那一半(M0 冻结版第五部分;交接 09 第 2b 节)。

登记(检查、落盘)在 k-worker 里用命令做(k_series/jiagui/cli.py);登记完是「待生效」。她每一轮看一眼:
- 只改了进度的新版本(老板 10-31:「只改进度不用批」)→ 自动生效,不发卡;通知跟着她每天那一条提醒发,不单独发。
- 其余改动 → 先试算(拿已经选过包的品,按「装了它以后」的注册表重判一遍,列出结果会变的品,花费照常记账),
  再发「风格包待生效」卡:管哪些品类、改了哪些条、检查结果、会变的品。批 = 生效;驳 = 不生效(写原因)。
  机器人只能交稿,人点了才算(和 K 的规矩一样)。
一轮最多处理一个待生效的包。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...k_series.jiagui import registry
from ...k_series.jiagui.models import ACTIVE, PENDING, JiaguiPack
from . import memory, style_route
from .models import SqhRouteRecord

logger = logging.getLogger(__name__)

_X = SKIP_ORG_DATA_ISOLATION
LA = ZoneInfo("America/Los_Angeles")  # 她「每天那一条提醒」按洛杉矶的日子算
PACK_CARD_KIND = "style_pack"
REPLAY_LIMIT = 10  # 试算最多重判这么多个品(每个一次 Opus)
PROVIDES_LABELS = {"routing": "只含选包", "images": "含出图"}


def _changelog_head(row: JiaguiPack, *, limit: int = 1200) -> str:
    """CHANGELOG.md 最上面那一节(这一版改了什么)。"""
    pack = row.pack_json if isinstance(row.pack_json, dict) else {}
    text = registry.read_doc(row.pack_id, row.version, str(pack.get("changelog") or "CHANGELOG.md")) or ""
    sections = text.split("\n## ")
    head = sections[1] if len(sections) > 1 else text
    return ("## " + head.strip())[:limit] if head.strip() else ""


def _pending_queue(db: Session) -> list[JiaguiPack]:
    return list(
        db.scalars(
            select(JiaguiPack).where(JiaguiPack.status == PENDING, JiaguiPack.card_ref.is_(None)).order_by(JiaguiPack.created_at, JiaguiPack.id),
            execution_options=_X,
        )
    )


def has_pending(db: Session) -> bool:
    """还有待生效的包(不管发没发卡)。选包要等注册表定下来再判,免得刚判完就因为一张卡被批又重判一遍。"""
    return db.scalar(select(JiaguiPack.id).where(JiaguiPack.status == PENDING).limit(1), execution_options=_X) is not None


# ---------------------------------------------------------------- 试算


def _latest_pipeline_records(db: Session, *, limit: int) -> list[SqhRouteRecord]:
    latest: dict[int, SqhRouteRecord] = {}
    for row in db.scalars(select(SqhRouteRecord).where(SqhRouteRecord.purpose == style_route.PURPOSE_PIPELINE).order_by(SqhRouteRecord.id), execution_options=_X):
        latest[row.dossier_id] = row
    rows = sorted(latest.values(), key=lambda r: r.id, reverse=True)
    return rows[:limit]


def replay(db: Session, row: JiaguiPack, *, call: style_route.RouteCall | None = None) -> dict[str, Any]:
    """装了这一版以后,已经选过包的品结论会不会变。返回 {ok, products: [{sku, before, after, changed}], errors, calls}。"""
    view = registry.view(db, replace=row)
    now_view = registry.view(db)
    docs = style_route.docs_for(view) if call is None else {}
    out: dict[str, Any] = {"ok": True, "products": [], "errors": [], "calls": 0, "registry_fp": registry.fingerprint(view)}
    for rec in _latest_pipeline_records(db, limit=REPLAY_LIMIT):
        if not rec.facts:
            continue
        price = style_route.price_text(rec.price if isinstance(rec.price, dict) else None)
        result = style_route.judge(db, rec.facts, view, product_id=rec.sku, price=price, call=call, docs=docs)
        out["calls"] += int(result.get("calls") or 0)
        if result["status"] != "pass":
            out["ok"] = False
            out["errors"].append({"sku": rec.sku, "error": result.get("error")})
            continue
        saved = style_route.save(db, dossier_id=rec.dossier_id, sku=rec.sku, result=result, facts=rec.facts, price=rec.price, purpose=style_route.PURPOSE_REPLAY, replay_for=row.id)
        before = style_route.headline(rec.record or {}, now_view)
        after = style_route.headline(saved.record, view)
        changed = (rec.decision_kind, rec.pack_id, rec.variant, rec.missing_key) != (saved.decision_kind, saved.pack_id, saved.variant, saved.missing_key)
        out["products"].append({"sku": rec.sku, "dossier_id": rec.dossier_id, "before": before, "after": after, "changed": changed})
    return out


# ---------------------------------------------------------------- 卡


def _card_text(row: JiaguiPack, previous: JiaguiPack | None, verify: dict[str, Any], rep: dict[str, Any]) -> tuple[str, str, str, str]:
    d = registry.describe(row)
    stage = style_route.STAGE_LABELS.get(row.stage, row.stage)
    provides = "、".join(PROVIDES_LABELS.get(str(p), str(p)) for p in row.provides or [])
    cats = ";".join(d["categories"]) or "(没写)"
    not_for = ";".join(d["not_for"]) or "(没写)"
    if previous is None:
        title = f"风格包待生效:「{row.name}」{row.version}"
        lead = f"桌面送来一个新风格包「{row.name}」({stage},{provides})。管:{cats}。不管:{not_for}。"
    else:
        title = f"风格包待生效:「{row.name}」{previous.version}→{row.version}"
        ch = verify.get("changed_ids") or {}
        parts = [f"{label} {'、'.join(ch.get(k) or [])}" for k, label in (("changed", "改了"), ("added", "加了"), ("removed", "删了")) if ch.get(k)]
        lead = f"「{row.name}」要从 {previous.version} 升到 {row.version}({stage},{provides})。" + ("条目:" + ";".join(parts) + "。" if parts else "条目没变(风格卡或别的文件改了)。")
    changed = [p for p in rep.get("products") or [] if p.get("changed")]
    if rep.get("products"):
        effect = (
            "装了它以后选包结果会变的品:" + ";".join(f"{p['sku']} {p['before']} → {p['after']}" for p in changed)
            if changed
            else f"试算了 {len(rep['products'])} 个已经选过包的品,结论都不变。"
        )
    else:
        effect = "现在还没有品选过包,不影响任何品。"
    if rep.get("errors"):
        effect += f"(另有 {len(rep['errors'])} 个品试算没判成:" + ";".join(f"{e['sku']} {e['error']}" for e in rep["errors"]) + ")"
    conclusion = lead + effect + " 批 = 生效,选包就按它判;驳 = 不生效(写一句为什么)。"
    if row.stage == "usable":
        if_not = "不批,选包时就没有这个包(或者还按旧版判)。"
    else:
        if_not = "不批,选包时就不知道这个包在做,该等它的品会被当成「要新做一个包」。"
    why_parts = [
        "自动检查全过:sha256、文件清单、pack.yaml 和 pack.json 一致、格式检查" + (";和上一版比不只是改进度,所以要你批。" if previous is not None else "。"),
        _changelog_head(row),
    ]
    return title, conclusion, "\n".join(p for p in why_parts if p), if_not


def raise_card(db: Session, row: JiaguiPack, *, previous: JiaguiPack | None, rep: dict[str, Any]) -> Any:
    from . import cards

    checks = registry.checks(db, row)
    verify = next((c.result for c in checks if c.kind == "verify"), {}) or {}
    title, conclusion, why, if_not = _card_text(row, previous, verify, rep)
    card, _ = cards.create_card(
        db,
        dedupe_key=f"style_pack:{row.pack_id}:{row.version}:{row.id}",
        kind=PACK_CARD_KIND,
        title=title[:60],
        conclusion=conclusion,
        why=why,
        if_not=if_not,
        reversible=True,
        confidence="high",
        evidence={
            "pack_row_id": row.id,
            "pack_id": row.pack_id,
            "version": row.version,
            "previous_version": previous.version if previous is not None else None,
            "pack": registry.describe(row),
            "changed_ids": verify.get("changed_ids"),
            "replay": {"products": rep.get("products"), "errors": rep.get("errors"), "calls": rep.get("calls")},
            "checks": [{"kind": c.kind, "ok": c.ok} for c in checks],
        },
    )
    row.card_ref = card.ref
    db.add(row)
    db.flush()
    return card


def after_decision(db: Session, card: Any, *, decision: str, actor: Any) -> dict[str, Any]:
    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    row = db.get(JiaguiPack, int(evidence.get("pack_row_id") or 0), execution_options=_X)
    if row is None:
        return {"ok": False, "note": "找不到这个包的登记了。"}
    if row.status != PENDING:
        return {"ok": False, "note": f"这个包现在是「{row.status}」,不是待生效,没动它。"}
    by = str(getattr(actor, "id", "") or "")
    if decision == "approve":
        old = registry.activate(db, row, by=by)
        memory.log_activity(db, f"风格包「{row.name}」{row.version} 生效了" + (f"(换下 {old.version})" if old is not None else "") + "。", kind="decision")
        return {"ok": True, "note": f"好,「{row.name}」{row.version} 生效了;等别的风格包卡也定了,我就给产品选包。"}
    registry.reject(db, row, by=by, reason=card.decision_reason or "")
    memory.log_activity(db, f"风格包「{row.name}」{row.version} 老板没批:{card.decision_reason or ''}", kind="decision")
    return {"ok": True, "note": "好,这一版不生效。原因我记下了,下一份交接转给桌面。"}


# ---------------------------------------------------------------- 一轮


def tick(db: Session, *, call: style_route.RouteCall | None = None) -> dict[str, Any] | None:
    """处理一个待生效、还没发卡的包。返回做了什么;没活 = None。"""
    queue = _pending_queue(db)
    if not queue:
        return None
    row = queue[0]
    previous = registry.active_row(db, row.pack_id)
    if row.progress_only and previous is not None:
        registry.activate(db, row, by=registry.SYSTEM, reason="只改了进度,按老板 10-31 的规矩自动生效")
        progress = (row.pack_json or {}).get("progress") if isinstance(row.pack_json, dict) else None
        doing = (progress or {}).get("doing") if isinstance(progress, dict) else None
        memory.log_activity(db, f"风格包「{row.name}」更新了进度({previous.version} → {row.version}),自动生效" + (f":{doing}" if doing else "") + "。", kind="work")
        db.commit()
        return {"pack": row.pack_id, "version": row.version, "auto": True}
    rep = replay(db, row, call=call)
    registry.add_check(db, row, kind="replay", ok=bool(rep.get("ok")), result=rep)
    card = raise_card(db, row, previous=previous, rep=rep)
    memory.log_activity(db, f"桌面送来风格包「{row.name}」{row.version},检查过了,卡 #{card.ref} 等老板批。", kind="work")
    db.commit()
    return {"pack": row.pack_id, "version": row.version, "card": card.ref}


def progress_notes(db: Session, *, since: date | None) -> list[str]:
    """只改进度、自动生效的版本(上次开口以后的),跟着每天那一条提醒说一句。"""
    q = select(JiaguiPack).where(JiaguiPack.decided_by == registry.SYSTEM, JiaguiPack.progress_only.is_(True), JiaguiPack.status.in_((ACTIVE, "retired")))
    out: list[str] = []
    for row in db.scalars(q.order_by(JiaguiPack.decided_at), execution_options=_X):
        decided: datetime | None = row.decided_at
        if decided is None or (since is not None and decided.astimezone(LA).date() <= since):
            continue
        out.append(f"风格包「{row.name}」进度更新到 {row.version}")
    return out
