"""选包判定 route.decide() —— M0 接口 v1 冻结版(交接 12)第三部分第 4 节,纯标准库。

模型只交判断(jiagui-judgement/1),这里按算法下结论,输出 jiagui-route/1 的 computed/decision/missing_pack/flags。
第 0 步:判断不完整 / 坏 id / 分数越界 → status=error,不放行。
和 Mac 的参考实现(交接 12_route_ref/decide.py)对同一份 vectors_v1.json 18/18 一致(测试 test_jiagui_route.py 带着这份向量)。
基座 M1 交付的 jiagui.route.decide() 到了以后,两边再对一遍;在那之前控制台用这一份。
"""
from __future__ import annotations

from typing import Any

SCHEMA_OUT = "jiagui-route/1"
CORE = "console-m2a"  # 控制台自己的判定实现;M1 之后换成基座版本号
USABLE = "usable"
IN_PROGRESS_STAGES = ("collecting", "planning")
IDEA = "idea"
RETIRED = "retired"


class JudgementError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _ids(items: Any, key: str = "id") -> list[str]:
    return [str(i[key]) for i in (items or []) if isinstance(i, dict) and key in i]


def _exactly_once(seen: list[Any], expected: list[str], where: str) -> None:
    seen_s = [str(s) for s in seen]
    unknown = sorted(set(seen_s) - set(expected))
    if unknown:
        raise JudgementError("E.JUDGEMENT.BAD_ID", f"{where}: unknown {unknown}")
    if sorted(seen_s) != sorted(expected):
        raise JudgementError("E.JUDGEMENT.INCOMPLETE", f"{where}: judged {sorted(seen_s)}, expected {sorted(expected)}")


def _is_score(v: Any) -> bool:
    return type(v) is int and v in (0, 1, 2)


def validate_judgement(judgement: dict[str, Any], usable: list[dict], in_progress: list[dict], ideas: list[dict]) -> None:
    """第 0 步:usable 的每个包都判全(红线/题/先例各一次、分数 0/1/2、category_match 必填、变体在包内);
    collecting/planning 的包在 in_progress 各列一次,idea 的包在 idea_packs 各列一次;match 为真要有合法品类 id。"""
    packs = judgement.get("packs") or {}
    if not isinstance(packs, dict):
        raise JudgementError("E.JUDGEMENT.INCOMPLETE", "packs missing")
    _exactly_once(list(packs), _ids(usable), "packs")
    for pack in usable:
        r, j = pack.get("routing") or {}, packs[pack["id"]]
        pid = pack["id"]
        if not isinstance(j, dict):
            raise JudgementError("E.JUDGEMENT.INCOMPLETE", f"{pid}: not an object")
        _exactly_once(_ids(j.get("red_lines")), _ids(r.get("red_lines")), f"{pid}.red_lines")
        _exactly_once(_ids(j.get("scores"), "q"), _ids(r.get("fit_questions")), f"{pid}.scores")
        _exactly_once(_ids(j.get("precedents")), _ids(r.get("precedents")), f"{pid}.precedents")
        for x in j.get("red_lines") or []:
            if not isinstance(x.get("hit"), bool):
                raise JudgementError("E.JUDGEMENT.BAD_ID", f"{pid}.red_lines.{x.get('id')}: hit must be true/false")
        for s in j.get("scores") or []:
            if not _is_score(s.get("score")):
                raise JudgementError("E.JUDGEMENT.BAD_SCORE", f"{pid}.{s.get('q')} = {s.get('score')!r}")
        for x in j.get("precedents") or []:
            if not isinstance(x.get("same_kind"), bool):
                raise JudgementError("E.JUDGEMENT.BAD_ID", f"{pid}.precedents.{x.get('id')}: same_kind must be true/false")
        if "category_match" not in j:
            raise JudgementError("E.JUDGEMENT.INCOMPLETE", f"{pid}.category_match missing")
        cat = (j.get("category_match") or {}).get("id")
        if cat is not None and str(cat) not in _ids(r.get("categories")):
            raise JudgementError("E.JUDGEMENT.BAD_ID", f"{pid}.category_match {cat}")
        pick = (j.get("variant_pick") or {}).get("id")
        if pick is not None and str(pick) not in _ids(r.get("variants")):
            raise JudgementError("E.JUDGEMENT.BAD_ID", f"{pid}.variant_pick {pick}")
    for key, group in (("in_progress", in_progress), ("idea_packs", ideas)):
        rows = judgement.get(key) or []
        _exactly_once([x.get("pack") for x in rows if isinstance(x, dict)], _ids(group), key)
        by_id = {p["id"]: p for p in group}
        for row in rows:
            if not isinstance(row.get("match"), bool):
                raise JudgementError("E.JUDGEMENT.BAD_ID", f"{key}.{row.get('pack')}: match must be true/false")
            if row["match"] and str(row.get("category")) not in _ids((by_id[str(row["pack"])].get("routing") or {}).get("categories")):
                raise JudgementError("E.JUDGEMENT.BAD_ID", f"{key}.{row['pack']}.category {row.get('category')}")


def _tier(total: int, maximum: int, th: dict[str, Any]) -> str:
    if total * 100 >= int(th.get("use_pct", 70)) * maximum:
        return "use"
    if total * 100 >= int(th.get("variant_pct", 50)) * maximum:
        return "variant"
    return "none"


def _ratio_cmp(a: dict[str, Any], b: dict[str, Any]) -> int:
    return a["total"] * b["max"] - b["total"] * a["max"]


def _best(computed: dict[str, dict[str, Any]], tier: str) -> tuple[str | None, list[str]]:
    rows = [(pid, row) for pid, row in computed.items() if row["tier"] == tier]
    if not rows:
        return None, []
    top = rows[0]
    for item in rows[1:]:
        if _ratio_cmp(item[1], top[1]) > 0:
            top = item
    return top[0], [pid for pid, row in rows if _ratio_cmp(row, top[1]) == 0]


def _override_hit(overrides: Any, pid: str, cat: str) -> bool:
    for o in overrides or []:
        if isinstance(o, dict):
            if str(o.get("pack")) == pid and str(o.get("category")) == cat:
                return True
        elif isinstance(o, (list, tuple)) and len(o) == 2 and str(o[0]) == pid and str(o[1]) == cat:
            return True
    return False


def _score_pack(pack: dict[str, Any], j: dict[str, Any], overrides: Any, flags: list[dict[str, Any]]) -> dict[str, Any]:
    r = pack.get("routing") or {}
    pid = pack["id"]
    row: dict[str, Any] = {"out": None, "total": None, "max": None, "pct": None, "tier": "none", "scores": None, "precedent": None}
    verdicts = {str(p["id"]): p.get("verdict") for p in r.get("precedents") or []}
    same = [str(x["id"]) for x in j.get("precedents") or [] if x.get("same_kind") is True]
    fails = [p for p in same if verdicts.get(p) == "fail"]
    if fails:
        if any(verdicts.get(p) != "fail" for p in same):
            flags.append({"code": "ROUTE.PRECEDENT_CONFLICT", "level": "amber", "pack": pid, "same_kind": same})
        row["out"] = {"by": "precedent", "id": fails[0]}
        return row
    if same:
        row["precedent"] = same[0]
    cat = (j.get("category_match") or {}).get("id")
    if cat is not None and _override_hit(overrides, pid, str(cat)):
        row["out"] = {"by": "owner_override", "id": str(cat)}
        return row
    hits = [str(x["id"]) for x in j.get("red_lines") or [] if x.get("hit") is True]
    if hits:
        row["out"] = {"by": "red_line", "id": hits[0]}
        row["red_lines_hit"] = hits
        return row
    scores = {str(s["q"]): int(s["score"]) for s in j.get("scores") or []}
    total, maximum = sum(scores.values()), 2 * len(r.get("fit_questions") or [])
    row.update(total=total, max=maximum, pct=(total * 100 // maximum) if maximum else 0, tier=_tier(total, maximum, r.get("thresholds") or {}), scores=scores)
    return row


def decide(
    judgement: dict[str, Any],
    registry_view: list[dict[str, Any]],
    brand: dict[str, Any] | None = None,
    overrides: Any = None,
) -> dict[str, Any]:
    brand = brand or {}
    allowed = [str(s) for s in brand.get("allowed_styles") or []]
    live = [p for p in registry_view if p.get("stage") != RETIRED]
    usable = [p for p in live if p.get("stage") == USABLE]
    in_progress = [p for p in live if p.get("stage") in IN_PROGRESS_STAGES]
    ideas = [p for p in live if p.get("stage") == IDEA]
    record: dict[str, Any] = {
        "schema": SCHEMA_OUT,
        "core": CORE,
        "product": judgement.get("product") or {},
        "registry": [{"id": p["id"], "version": p.get("version"), "stage": p.get("stage")} for p in registry_view],
        "brand": {"allowed_styles": allowed},
        "judgement": judgement,
        "computed": {"packs": {}, "rule_4_5": {"checked": False, "waiting_for": None}},
        "decision": {"kind": None, "compliance_hold": None, "listing": "hold"},
        "missing_pack": None,
        "flags": [],
        "status": "pass",
        "codes": [],
        "error": None,
    }
    try:
        validate_judgement(judgement, usable, in_progress, ideas)
    except JudgementError as e:
        record.update(status="error", codes=[e.code], error={"code": e.code, "detail": e.detail})
        return record

    candidates = [p for p in usable if not allowed or p["id"] in allowed]
    flags: list[dict[str, Any]] = record["flags"]
    computed = {p["id"]: _score_pack(p, judgement["packs"][p["id"]], overrides, flags) for p in candidates}
    record["computed"]["packs"] = computed
    progress_match = next((x for x in judgement.get("in_progress") or [] if x.get("match") is True), None)
    idea_match = next((x for x in judgement.get("idea_packs") or [] if x.get("match") is True), None)
    rule_4_5 = record["computed"]["rule_4_5"]
    decision: dict[str, Any] | None = None

    top, tied = _best(computed, "use")
    if top:
        decision = {"kind": "ask_owner", "packs": tied} if len(tied) > 1 else {"kind": "use", "pack": top}
    else:
        top, tied = _best(computed, "variant")
        if top:
            rule_4_5["checked"] = True
            if progress_match:
                rule_4_5["waiting_for"] = progress_match["pack"]
            elif len(tied) > 1:
                decision = {"kind": "ask_owner", "packs": tied}
            else:
                pack = next(p for p in candidates if p["id"] == top)
                j = judgement["packs"][top]
                pick = (j.get("variant_pick") or {}).get("id")
                variant = next((v for v in (pack.get("routing") or {}).get("variants") or [] if str(v["id"]) == str(pick)), None)
                scores = computed[top]["scores"]
                triggered = variant is not None and (
                    not variant.get("triggers") or any(scores.get(str(t["q"]), 99) <= int(t.get("max_score", 2)) for t in variant["triggers"])
                )
                if not triggered:
                    flags.append({"code": "ROUTE.VARIANT_TRIGGER_MISMATCH", "level": "amber", "pack": top, "variant": pick})
                decision = {"kind": "variant", "pack": top, "variant": pick}

    missing = None
    if decision is None:
        if progress_match:
            pack = next(p for p in in_progress if p["id"] == progress_match["pack"])
            missing = {"kind": "in_progress", "pack": pack["id"], "stage": pack.get("stage"), "category": progress_match.get("category"), "progress": pack.get("progress")}
        elif idea_match:
            pack = next(p for p in ideas if p["id"] == idea_match["pack"])
            missing = {"kind": "idea", "pack": pack["id"], "stage": IDEA, "category": idea_match.get("category"), "progress": pack.get("progress")}
        else:
            missing = {"kind": "new", "pack": None, "stage": None, "category": None, "progress": None, "suggestion": judgement.get("new_pack")}
        missing.update(waiting_products=None, listing="hold")
        decision = {"kind": "missing"}

    decision["compliance_hold"] = any(isinstance(c, dict) and c.get("blocks") is True for c in judgement.get("compliance") or [])
    decision["listing"] = "allowed" if decision["kind"] in ("use", "variant") and not decision["compliance_hold"] else "hold"
    record["decision"], record["missing_pack"] = decision, missing
    return record


def validate(record: dict[str, Any]) -> list[str]:
    """route.validate():只查格式和硬规则。"""
    problems: list[str] = []
    d = record.get("decision") or {}
    if record.get("status") == "error":
        return problems if d.get("listing") == "hold" and d.get("kind") is None else ["error_but_not_hold"]
    packs = (record.get("computed") or {}).get("packs") or {}
    if d.get("pack") and packs.get(d["pack"], {}).get("out"):
        problems.append("chosen_pack_is_out")
    for pid, e in packs.items():
        if e.get("scores") is not None and sum(e["scores"].values()) != e.get("total"):
            problems.append(f"sum_mismatch:{pid}")
    if d.get("kind") == "variant" and not (record.get("computed") or {}).get("rule_4_5", {}).get("checked"):
        problems.append("rule_4_5_not_checked")
    if d.get("kind") == "missing" and not record.get("missing_pack"):
        problems.append("missing_without_missing_pack")
    expect = "allowed" if d.get("kind") in ("use", "variant") and not d.get("compliance_hold") else "hold"
    if d.get("listing") != expect:
        problems.append("listing_mismatch")
    return problems
