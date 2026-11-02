"""苏青禾选风格包(M2a;M0 冻结版第三部分;老板 11-02 批:选包用 Opus)。

「模型只判、代码定」:
1. 代码先从注册表(生效的包)画好答卷——每个可用的包的每条红线、每道适配题、每条先例,每个在做的、未立包的包,
   全部写成「id → 空格子」的对象(不是列表),每格 reason 在前、hit/score/same_kind/match 在后(交接 17 第 2 节的骨架做法)。
   11-02 离线考第一遍用列表画答卷,9 题里 5 题模型把「未立包」的包挪进「在做」的列表、或者把某一题抄了两遍;
   改成按 id 当键的对象以后,挪位置、抄重复这两类错在结构上就没有了。在做的和未立包的也合成一张表(other_packs),代码按注册表的 stage 分回去。
2. 模型只往空里填。代码校验(键一个不多一个不少、分数只能 0/1/2、理由不能空),格式不对同一份提示词重问一次;
   过了校验,代码把答卷换算成标准的 jiagui-judgement/1(列表、in_progress / idea_packs 分开),和 Mac 那边同一个接口。
3. 结论由 jiagui.route.decide() 算:用 / 变体 / 缺包 / 两个包同分问老板。降级档(DeepSeek 顶班)判的不算数。

和合规门的分工:G01–G06 那类「不做」的品已经被合规门挡在前面;答卷里的 compliance(宣称合规)这一格控制台不填,
宣称由读稿改稿和 K 的证据门管,所以 compliance_hold 在控制台恒为 false(交接 18 里告诉 Mac)。

结论之后:
- use / variant:记下包 id、版本、变体,出图那一段照这个做(作图指令现在还停着);
- missing:这个品不上架、等包;按缺的包合并发「缺风格包」卡(同一个缺包不重复提,除非又多了品在等它);
- ask_owner:发「选包要你定」卡,老板选一个。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...k_series.jiagui import registry, route
from .constants import USAGE_LABEL
from .models import SqhRouteRecord

logger = logging.getLogger(__name__)

_X = SKIP_ORG_DATA_ISOLATION
ROUTE_ROLE = "judge"  # 11-02 老板批:选包用 Opus
ROUTE_USAGE_LABEL = f"{USAGE_LABEL}.route"
ROUTE_TIMEOUT_SECONDS = 180.0
MAX_CALLS = 2
PICK_CARD_KIND = "route_pick"
MISSING_CARD_KIND = "route_missing"
OK_KINDS = ("use", "variant")
BRAND = {"allowed_styles": []}  # 品牌卡不限包
PURPOSE_PIPELINE = "pipeline"
PURPOSE_REPLAY = "replay"
DOC_LIMIT = 12000
STAGE_LABELS = {"usable": "可用", "planning": "规划中", "collecting": "收参考", "idea": "未立包", "retired": "停用"}

RouteCall = Callable[[Session, str], dict[str, Any]]


# ---------------------------------------------------------------- 骨架(纯函数)


def _usable(view: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in view if p.get("stage") == "usable"]


def _in_progress(view: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in view if p.get("stage") in route.IN_PROGRESS_STAGES]


def _ideas(view: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in view if p.get("stage") == route.IDEA]


def _r(pack: dict[str, Any]) -> dict[str, Any]:
    return pack.get("routing") if isinstance(pack.get("routing"), dict) else {}


def _others(view: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _in_progress(view) + _ideas(view)


def skeleton(view: list[dict[str, Any]], *, product_id: str, price: str = "") -> dict[str, Any]:
    """画好的答卷(给模型填的那一份)。所有条目都是「id → 格子」,模型只填 reason / hit / score / same_kind / match / category / id。"""
    return {
        "product": {"id": product_id, "category": "", "price": price, "audience": "", "main_scene": ""},
        "packs": {
            p["id"]: {
                "category_match": {"reason": "", "id": None},
                "precedents": {
                    str(x["id"]): {"product": x.get("product"), "verdict": x.get("verdict"), "reason": "", "same_kind": None} for x in _r(p).get("precedents") or []
                },
                "red_lines": {str(x["id"]): {"rule": x.get("text"), "reason": "", "hit": None} for x in _r(p).get("red_lines") or []},
                "scores": {str(q["id"]): {"question": q.get("text"), "reason": "", "score": None} for q in _r(p).get("fit_questions") or []},
                "variant_pick": {"reason": "", "id": None},
            }
            for p in _usable(view)
        },
        "other_packs": {
            p["id"]: {"name": p.get("name"), "stage": STAGE_LABELS.get(str(p.get("stage")), p.get("stage")), "reason": "", "match": None, "category": None}
            for p in _others(view)
        },
        "new_pack": None,
        "notes": "",
    }


def to_judgement(filled: dict[str, Any], view: list[dict[str, Any]], *, product_id: str, price: str = "") -> dict[str, Any]:
    """校验过的答卷 → 标准 jiagui-judgement/1(条目按包里的顺序排成列表;在做的 / 未立包的按注册表 stage 分开)。"""
    packs: dict[str, Any] = {}
    for p in _usable(view):
        j = filled["packs"][p["id"]]
        r = _r(p)
        packs[p["id"]] = {
            "category_match": {"id": j["category_match"].get("id"), "reason": j["category_match"].get("reason")},
            "precedents": [{"id": str(x["id"]), "same_kind": j["precedents"][str(x["id"])]["same_kind"], "reason": j["precedents"][str(x["id"])]["reason"]} for x in r.get("precedents") or []],
            "red_lines": [{"id": str(x["id"]), "hit": j["red_lines"][str(x["id"])]["hit"], "reason": j["red_lines"][str(x["id"])]["reason"]} for x in r.get("red_lines") or []],
            "scores": [{"q": str(q["id"]), "score": j["scores"][str(q["id"])]["score"], "reason": j["scores"][str(q["id"])]["reason"]} for q in r.get("fit_questions") or []],
            "variant_pick": {"id": (j.get("variant_pick") or {}).get("id"), "reason": (j.get("variant_pick") or {}).get("reason")},
        }
    others = filled.get("other_packs") or {}

    def rows(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"pack": p["id"], "match": others[p["id"]]["match"], "category": others[p["id"]].get("category") if others[p["id"]]["match"] else None, "reason": others[p["id"]]["reason"]} for p in group]

    product = filled.get("product") if isinstance(filled.get("product"), dict) else {}
    return {
        "schema": "jiagui-judgement/1",
        "product": {**product, "id": product_id, **({"price": price} if price else {})},
        "packs": packs,
        "in_progress": rows(_in_progress(view)),
        "idea_packs": rows(_ideas(view)),
        "compliance": [],  # 宣称合规不在这里判(见文件头)
        "new_pack": filled.get("new_pack"),
        "notes": filled.get("notes"),
    }


def pack_brief(p: dict[str, Any]) -> str:
    r = _r(p)
    lines = [f"### 包 {p['id']}(中文名:{p.get('name', p['id'])};{STAGE_LABELS.get(str(p.get('stage')), p.get('stage'))};版本 {p.get('version')})"]
    if r.get("summary"):
        lines.append(f"一句话:{r['summary']}")
    lines.append("适合的品类(category_match / category 只能填这些 id):")
    lines += [f"- {c['id']}:{c['text']}" for c in r.get("categories") or []]
    if r.get("not_for"):
        lines.append("不适合:")
        lines += [f"- {c['id']}:{c['text']}" for c in r["not_for"]]
    if p.get("stage") == "usable":
        lines.append("红线(命中任何一条,这个包出局):")
        lines += [f"- {x['id']}:{x['text']}" for x in r.get("red_lines") or []]
        lines.append("适配题(每题 0/1/2 分):")
        for q in r.get("fit_questions") or []:
            crit = ";".join(f"{s['score']} 分 = {s['text']}" for s in q.get("scores") or [])
            lines.append(f"- {q['id']}:{q['text']}({crit})")
        if r.get("scoring_note"):
            lines.append(f"打分口径:{r['scoring_note']}")
        lines.append("变体:")
        for v in r.get("variants") or []:
            trig = "、".join(f"{t['q']} ≤ {t['max_score']} 分" for t in v.get("triggers") or []) or "无"
            lines.append(f"- {v['id']}({v.get('name')};对应:{trig}):{v.get('text', '')}")
        lines.append("先例:")
        for x in r.get("precedents") or []:
            verdict = {"pass": "用了", "pass_predicted": "预计能用", "partial": "部分能用", "fail": "不用"}.get(str(x.get("verdict")), x.get("verdict"))
            lines.append(f"- {x['id']}:{x.get('product')} → {verdict}" + (f"({x['note']})" if x.get("note") else ""))
    progress = p.get("progress")
    if isinstance(progress, dict) and progress:
        lines.append(f"进度:{json.dumps(progress, ensure_ascii=False)}")
    return "\n".join(lines)


RULES = (
    "## 老板定的规矩\n"
    "- 一个品的场景图、海报图只用一个风格包。\n"
    "- 没有合适风格包的品不上架,等包做好(老板 10-31)。\n"
    "- 现有可用的包只够到变体档,而有一个还在做的包对口时,等那个包,不拿现有包凑合(老板 10-31「一律等更对口的包」)——这条由代码算,你只要把「在做的包对不对口」判准。\n"
    "- 按这个品的主要使用场景和主要卖点判;两个分数之间拿不准时取低分,在理由里写明。\n"
)

HOW_TO_FILL = (
    "## 怎么填\n"
    "下面是一份已经画好的答卷。原样返回这个 JSON,只填空:\n"
    "- product:category、audience、main_scene 各用一句话写这个品是什么、主要卖给谁、主要在哪用;price 已经写好,不要改。\n"
    "- packs 里的每个可用的包(条目都按 id 列好了,每个 id 下面填一格):\n"
    "  - category_match:先写 reason,再填 id——这个品对上了这个包「适合的品类」里的哪一条;一条都对不上填 null。\n"
    "  - precedents:每个先例 id 下先写 reason,再填 same_kind(true 或 false)——这个品和那条先例是不是同一类产品。\n"
    "  - red_lines:每条红线 id 下先写 reason,再填 hit(true 或 false)。\n"
    "  - scores:每道题 id 下先写 reason(写清为什么是这个分、不是相邻的分),再填 score(只能是 0、1、2)。\n"
    "  - variant_pick:先写 reason,再填 id——万一总分落在变体档,这个品最贴的是哪个变体(从这个包的变体里挑一个 id);用不用由代码定。\n"
    "- other_packs:还在做的包、还没立包的包。每个包 id 下先写 reason,再填 match(true 或 false)。只看品类对不对口(它「适合的品类」和「不适合」):"
    "「不适合」里点名的品类就是 false;不看那个包的红线,也不管那个包现在能不能用——对口就是 true。match 是 true 时 category 填对上的那条品类 id,否则 category 填 null。\n"
    "- new_pack:只有所有包(可用的、在做的、未立包的)都对不上时,才把 null 改成 "
    '{"name": "建议的包名", "categories": ["管哪些品类"], "references": "去哪找参考", "images": ["要哪几类图"]};否则保持 null。\n'
    "- notes:给老板看的一两句要点。\n"
    "- 键(各个 id)和抄好的文字一个都不要改;不要加键,不要删键。\n"
    "只输出这一个 JSON 对象,不要别的文字。\n"
)


def build_prompt(facts: str, view: list[dict[str, Any]], skel: dict[str, Any], docs: dict[str, str] | None = None) -> str:
    background = ""
    if docs:
        background = "## 风格卡(背景材料;和上面条目的说法不一致时,以上面的条目为准)\n" + "\n\n".join(
            f"<<<{name}>>>\n{text.strip()}\n<<<完>>>" for name, text in docs.items()
        ) + "\n\n"
    return (
        "你是苏青禾,Barong Yekhna 独立站(美国市场)的运营总管。现在给一个品选风格包:只交判断,不下结论——"
        "用哪个包、用不用变体、是不是缺包,由代码按阈值和规矩算。你要做的是把每一条判准、理由写清。\n\n"
        "品牌:Barong Yekhna,市场是美国,品牌色铜橙 #CB6127、青蓝 #9BC6D6、白;品牌不限风格包。只判场景图和海报图用哪个包。\n\n"
        + RULES
        + "\n## 注册表里生效的风格包\n"
        + "\n\n".join(pack_brief(p) for p in view)
        + "\n\n"
        + background
        + HOW_TO_FILL
        + f"\n## 答卷\n{json.dumps(skel, ensure_ascii=False, indent=1)}\n\n"
        + f"## 这个品的资料\n{facts.strip()}"
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _cells(got: Any, want: dict[str, Any], where: str, problems: list[str]) -> dict[str, dict[str, Any]]:
    """一组「id → 格子」:键一个不多一个不少。返回能用的格子。"""
    if not isinstance(got, dict):
        problems.append(f"{where} 不是对象")
        return {}
    if sorted(got) != sorted(want):
        problems.append(f"{where} 的 id 不对:要 {sorted(want)},给的是 {sorted(got)}")
    return {k: v for k, v in got.items() if k in want and isinstance(v, dict)}


def validate(filled: Any, skel: dict[str, Any], view: list[dict[str, Any]]) -> list[str]:
    """答卷格式问题清单;空 = 合格。语义(分数越界、id 不在包里)换算后 decide 第 0 步还会再查一遍。"""
    if not isinstance(filled, dict):
        return ["不是 JSON 对象"]
    problems: list[str] = []
    packs = _cells(filled.get("packs"), skel["packs"], "packs", problems)
    by_id = {p["id"]: p for p in view}
    for pid, j in packs.items():
        want = skel["packs"][pid]
        r = _r(by_id[pid])
        for rid, cell in _cells(j.get("red_lines"), want["red_lines"], f"{pid}.red_lines", problems).items():
            if not isinstance(cell.get("hit"), bool):
                problems.append(f"{pid}.{rid} 的 hit 不是 true/false")
            if not _nonempty(cell.get("reason")):
                problems.append(f"{pid}.{rid} 没写理由")
        for qid, cell in _cells(j.get("scores"), want["scores"], f"{pid}.scores", problems).items():
            if type(cell.get("score")) is not int or cell["score"] not in (0, 1, 2):
                problems.append(f"{pid}.{qid} 的 score 不是 0/1/2")
            if not _nonempty(cell.get("reason")):
                problems.append(f"{pid}.{qid} 没写理由")
        for xid, cell in _cells(j.get("precedents"), want["precedents"], f"{pid}.precedents", problems).items():
            if not isinstance(cell.get("same_kind"), bool):
                problems.append(f"{pid}.{xid} 的 same_kind 不是 true/false")
            if not _nonempty(cell.get("reason")):
                problems.append(f"{pid}.{xid} 没写理由")
        cm = j.get("category_match")
        if not isinstance(cm, dict) or "id" not in cm:
            problems.append(f"{pid}.category_match 缺了")
        elif cm.get("id") is not None and str(cm["id"]) not in route._ids(r.get("categories")):
            problems.append(f"{pid}.category_match 填了不存在的品类 {cm.get('id')}")
        vp = j.get("variant_pick")
        if vp is not None and not isinstance(vp, dict):
            problems.append(f"{pid}.variant_pick 不是对象")
        elif isinstance(vp, dict) and vp.get("id") is not None and str(vp["id"]) not in route._ids(r.get("variants")):
            problems.append(f"{pid}.variant_pick 填了不存在的变体 {vp.get('id')}")
    for pid, cell in _cells(filled.get("other_packs"), skel["other_packs"], "other_packs", problems).items():
        if not isinstance(cell.get("match"), bool):
            problems.append(f"other_packs.{pid} 的 match 不是 true/false")
        elif cell["match"] and str(cell.get("category")) not in route._ids(_r(by_id.get(pid, {})).get("categories")):
            problems.append(f"other_packs.{pid} 判了对口却没填对品类 id")
        if not _nonempty(cell.get("reason")):
            problems.append(f"other_packs.{pid} 没写理由")
    new_pack = filled.get("new_pack")
    if new_pack is not None and not (isinstance(new_pack, dict) and _nonempty(new_pack.get("name"))):
        problems.append("new_pack 要么是 null,要么带 name")
    return problems


def missing_key(missing: dict[str, Any] | None) -> str | None:
    """缺包按「缺的包」合并:在做的/未立包的按包 id;要新做的按建议包名。"""
    if not isinstance(missing, dict):
        return None
    kind = str(missing.get("kind") or "")
    if kind in ("in_progress", "idea") and missing.get("pack"):
        return f"{kind}:{missing['pack']}"
    name = str(((missing.get("suggestion") or {}) if isinstance(missing.get("suggestion"), dict) else {}).get("name") or "未命名")
    slug = re.sub(r"\s+", "", name).lower()[:80]
    return f"new:{slug}"


def summary(record: dict[str, Any]) -> dict[str, Any]:
    """一份 jiagui-route/1 → 落库和比对用的几个字段。"""
    d = record.get("decision") or {}
    registry_rows = {r["id"]: r for r in record.get("registry") or []}
    pack = d.get("pack")
    return {
        "decision_kind": d.get("kind"),
        "pack_id": pack,
        "pack_version": (registry_rows.get(pack) or {}).get("version") if pack else None,
        "variant": d.get("variant"),
        "missing_key": missing_key(record.get("missing_pack")) if d.get("kind") == "missing" else None,
        "packs": d.get("packs"),
    }


def headline(record: dict[str, Any], view: list[dict[str, Any]] | None = None) -> str:
    names = {p["id"]: p.get("name") or p["id"] for p in view or []}
    d = record.get("decision") or {}
    computed = (record.get("computed") or {}).get("packs") or {}
    kind = d.get("kind")

    def score(pid: str) -> str:
        row = computed.get(pid) or {}
        return f"{row.get('total')}/{row.get('max')}" if row.get("total") is not None else "出局"

    if kind == "use":
        return f"用「{names.get(d['pack'], d['pack'])}」({score(d['pack'])})"
    if kind == "variant":
        return f"用「{names.get(d['pack'], d['pack'])}」的变体 {d.get('variant')}({score(d['pack'])})"
    if kind == "ask_owner":
        return "两个包同分,要老板选:" + "、".join(f"「{names.get(p, p)}」{score(p)}" for p in d.get("packs") or [])
    mp = record.get("missing_pack") or {}
    if mp.get("kind") in ("in_progress", "idea"):
        return f"缺包,等「{names.get(mp.get('pack'), mp.get('pack'))}」({STAGE_LABELS.get(str(mp.get('stage')), mp.get('stage'))})"
    return f"缺包,要新做一个:{((mp.get('suggestion') or {}) if isinstance(mp.get('suggestion'), dict) else {}).get('name') or '(没写名字)'}"


def out_reasons(record: dict[str, Any], view: list[dict[str, Any]]) -> list[str]:
    """每个可用的包为什么不行(引用红线/先例的 id 和原文)——缺包卡上要写清楚。"""
    by_id = {p["id"]: p for p in view}
    lines: list[str] = []
    for pid, row in ((record.get("computed") or {}).get("packs") or {}).items():
        name = (by_id.get(pid) or {}).get("name") or pid
        out = row.get("out")
        if out:
            items = _r(by_id.get(pid) or {}).get("red_lines" if out.get("by") == "red_line" else "precedents") or []
            text = next((x.get("text") or x.get("product") for x in items if str(x.get("id")) == str(out.get("id"))), "")
            lines.append(f"「{name}」出局:{out.get('id')} {text}".strip())
        elif row.get("tier") == "none":
            lines.append(f"「{name}」只有 {row.get('total')}/{row.get('max')} 分,不到变体档")
        elif row.get("tier") == "variant":
            lines.append(f"「{name}」{row.get('total')}/{row.get('max')} 分,只到变体档")
    return lines


# ---------------------------------------------------------------- 判一次(出网)


def docs_for(view: list[dict[str, Any]]) -> dict[str, str]:
    """可用的包带上风格卡当背景(在做的包风格卡还没定稿,不带)。读不到就不带,不挡选包。"""
    out: dict[str, str] = {}
    for p in _usable(view):
        for name in p.get("docs") or []:
            text = registry.read_doc(str(p["id"]), str(p.get("version")), str(name), limit=DOC_LIMIT)
            if text:
                out[f"{p['id']}/{name}"] = text
    return out


def _default_call(db: Session, prompt: str) -> dict[str, Any]:
    from . import brain

    db.commit()  # 出网前放掉事务
    return brain._execute(ROUTE_ROLE, [{"role": "user", "content": prompt}], timeout=ROUTE_TIMEOUT_SECONDS, usage_label=ROUTE_USAGE_LABEL)


def judge(
    db: Session,
    facts: str,
    view: list[dict[str, Any]],
    *,
    product_id: str,
    price: str = "",
    call: RouteCall | None = None,
    docs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """选一次包。返回 {status: pass|error, record?, calls, error?, registry_fp}。"""
    from .brain import parse_json

    fp = registry.fingerprint(view)
    base = {"registry_fp": fp, "calls": 0}
    if not view:
        return {**base, "status": "error", "error": "注册表里还没有生效的风格包"}
    call = call or _default_call
    skel = skeleton(view, product_id=product_id, price=price)
    prompt = build_prompt(facts, view, skel, docs if docs is not None else docs_for(view))
    problems: list[str] = []
    for attempt in range(1, MAX_CALLS + 1):
        base["calls"] = attempt
        try:
            raw = call(db, prompt)
        except Exception as exc:  # noqa: BLE001 —— 没判成不拖垮调用方
            logger.warning("style route call failed: %s", exc)
            return {**base, "status": "error", "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
        if isinstance(raw, dict) and raw.get("_ai_degraded"):
            return {**base, "status": "error", "error": "Claude 额度用完,降级档判的不算数"}
        filled = parse_json(raw)
        problems = validate(filled, skel, view)
        if problems:
            continue
        judgement = to_judgement(filled, view, product_id=product_id, price=price)
        record = route.decide(judgement, view, BRAND, [])
        if record["status"] == "error":
            problems = [f"{record['error']['code']}: {record['error']['detail']}"]
            continue
        bad = route.validate(record)
        if bad:  # 判定代码自己的问题,不是模型的——别重问,直接报
            return {**base, "status": "error", "error": f"判定结果没过自检:{bad}"}
        return {**base, "status": "pass", "record": record}
    return {**base, "status": "error", "error": "两次答卷格式都不对:" + ";".join(problems)[:300]}


# ---------------------------------------------------------------- 记录


def save(
    db: Session,
    *,
    dossier_id: int,
    sku: str,
    result: dict[str, Any],
    facts: str,
    price: dict[str, Any] | None,
    purpose: str = PURPOSE_PIPELINE,
    replay_for: int | None = None,
) -> SqhRouteRecord:
    record = result["record"]
    s = summary(record)
    row = SqhRouteRecord(
        dossier_id=dossier_id,
        sku=(sku or "")[:32],
        purpose=purpose,
        replay_for=replay_for,
        registry_fp=result["registry_fp"],
        price=price or {},
        facts=facts,
        decision_kind=str(s["decision_kind"]),
        pack_id=s["pack_id"],
        pack_version=s["pack_version"],
        variant=s["variant"],
        missing_key=s["missing_key"],
        record=record,
        calls=int(result.get("calls") or 1),
    )
    db.add(row)
    db.flush()
    return row


def current(db: Session, dossier_id: int) -> SqhRouteRecord | None:
    return db.scalar(
        select(SqhRouteRecord)
        .where(SqhRouteRecord.dossier_id == dossier_id, SqhRouteRecord.purpose == PURPOSE_PIPELINE)
        .order_by(SqhRouteRecord.id.desc())
        .limit(1),
        execution_options=_X,
    )


def effective_kind(row: SqhRouteRecord | None) -> str | None:
    """老板在同分卡上选了包 → 按「用」算。"""
    if row is None:
        return None
    if row.decision_kind == "ask_owner" and row.owner_pick:
        return "use"
    return row.decision_kind


def chosen(row: SqhRouteRecord | None) -> dict[str, Any] | None:
    """出图那一段要用的:包 id、版本、变体。没定下来 = None。"""
    if row is None or effective_kind(row) not in OK_KINDS:
        return None
    pack = row.owner_pick or row.pack_id
    version = next((r.get("version") for r in (row.record or {}).get("registry") or [] if r.get("id") == pack), row.pack_version)
    return {"pack": pack, "version": version, "variant": None if row.owner_pick else row.variant}


def price_moved(used: dict[str, Any] | None, now: dict[str, Any] | None) -> bool:
    """选包时用的价和现在的价差出 1 美元以上(老板改了价)→ 价格带那题可能变,要重判。"""
    if not used or not now:
        return False
    try:
        return abs(float(used.get("low")) - float(now.get("low"))) > 1 or abs(float(used.get("high")) - float(now.get("high"))) > 1
    except (TypeError, ValueError):
        return False


def price_text(price: dict[str, Any] | None) -> str:
    if not price or price.get("low") is None:
        return ""
    low, high = float(price["low"]), float(price.get("high") or price["low"])
    text = f"${low:.2f}" if abs(high - low) < 0.005 else f"${low:.2f}–${high:.2f}"
    return text + ("(已定价)" if price.get("source") == "applied" else "(价格卡上的建议价,老板还没批)")


# ---------------------------------------------------------------- 卡:同分要老板选


def raise_pick_card(db: Session, *, row: SqhRouteRecord, view: list[dict[str, Any]], title_hint: str) -> Any:
    from . import cards

    names = {p["id"]: p.get("name") or p["id"] for p in view}
    packs = list((row.record.get("decision") or {}).get("packs") or [])
    first = packs[0] if packs else ""
    card, _ = cards.create_card(
        db,
        dedupe_key=f"route_pick:{row.id}",
        kind=PICK_CARD_KIND,
        title=f"选包要你定:{title_hint}"[:60],
        conclusion=(
            f"{headline(row.record, view)}。按家规两个包一样好,由你选。"
            f"批 = 用「{names.get(first, first)}」;驳 = 写上你要用哪个包(写包名就行)。"
        ),
        why="\n".join(out_reasons(row.record, view)) or "",
        if_not="不选,这个品的图先不做。",
        reversible=True,
        confidence="medium",
        evidence={"route_record_id": row.id, "dossier_id": row.dossier_id, "sku": row.sku, "packs": packs, "names": {p: names.get(p, p) for p in packs}},
    )
    row.card_ref = card.ref
    db.add(row)
    db.flush()
    return card


def after_pick(db: Session, card: Any, *, decision: str) -> dict[str, Any]:
    from . import memory

    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    row = db.get(SqhRouteRecord, int(evidence.get("route_record_id") or 0), execution_options=_X)
    if row is None:
        return {"ok": False, "note": "找不到这份选包记录了。"}
    packs = [str(p) for p in evidence.get("packs") or []]
    names = evidence.get("names") if isinstance(evidence.get("names"), dict) else {}
    pick = None
    if decision == "approve":
        pick = packs[0] if packs else None
    else:
        reason = str(card.decision_reason or "").lower()

        def named(p: str) -> bool:
            name = str(names.get(p) or "").strip().lower()
            return p.lower() in reason or (bool(name) and name in reason)

        hits = [p for p in packs if named(p)]
        pick = hits[0] if len(hits) == 1 else None  # 写了两个包名 = 没说清,不猜
    if pick is None:
        return {"ok": False, "note": "没认出你要用哪个包;下次重判时我再问你。"}
    row.owner_pick = pick
    db.add(row)
    db.flush()
    memory.log_activity(db, f"{row.sku}:老板选了风格包「{names.get(pick, pick)}」。", kind="decision")
    return {"ok": True, "note": f"好,{row.sku} 用「{names.get(pick, pick)}」。"}


# ---------------------------------------------------------------- 缺包清单 + 缺包卡


def missing_report(db: Session, *, dossier_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """按缺的包合并、按等待的品数从多到少排(冻结版第三部分第 6 节)。只看每个品最新的一份记录。"""
    q = select(SqhRouteRecord).where(SqhRouteRecord.purpose == PURPOSE_PIPELINE).order_by(SqhRouteRecord.id)
    latest: dict[int, SqhRouteRecord] = {}
    for row in db.scalars(q, execution_options=_X):
        latest[row.dossier_id] = row
    groups: dict[str, dict[str, Any]] = {}
    for dossier_id, row in latest.items():
        if dossier_ids is not None and dossier_id not in dossier_ids:
            continue
        if row.decision_kind != "missing" or not row.missing_key:
            continue
        mp = (row.record or {}).get("missing_pack") or {}
        g = groups.setdefault(
            row.missing_key,
            {"key": row.missing_key, "kind": mp.get("kind"), "pack": mp.get("pack"), "stage": mp.get("stage"), "progress": mp.get("progress"), "suggestion": mp.get("suggestion"), "products": []},
        )
        g["products"].append({"dossier_id": dossier_id, "sku": row.sku, "route_record_id": row.id, "why": out_reasons(row.record or {}, [])})
    return sorted(groups.values(), key=lambda g: (-len(g["products"]), g["key"]))


def _missing_card_text(group: dict[str, Any], names: dict[str, str]) -> tuple[str, str, str]:
    skus = "、".join(p["sku"] for p in group["products"])
    n = len(group["products"])
    if group["kind"] in ("in_progress", "idea"):
        name = names.get(group["pack"], group["pack"])
        title = f"缺风格包:{n} 个品在等「{name}」"
        state = "还在做" if group["kind"] == "in_progress" else "还没立包(只有名字和参考)"
        progress = group.get("progress") if isinstance(group.get("progress"), dict) else {}
        doing = progress.get("doing") or "、".join(progress.get("next") or [])
        lead = f"{skus} 最对口的风格包是「{name}」,它{state}" + (f"(进度:{doing})" if doing else "") + "。"
    else:
        s = group.get("suggestion") if isinstance(group.get("suggestion"), dict) else {}
        title = f"缺风格包:{n} 个品要一个新包「{s.get('name') or '未命名'}」"
        lead = (
            f"{skus} 现有的包都不合适,也没有在做的包对口。建议新做一个「{s.get('name') or '未命名'}」:"
            f"管 {('、'.join(s.get('categories') or []) or '?')};参考去 {s.get('references') or '?'} 找;要 {('、'.join(s.get('images') or []) or '?')}。"
        )
    conclusion = lead + "按你 10-31 定的规矩,这几个品先不上架、等包做好;价格、文案我照常往下做。批 = 知道了;驳 = 写一句你的意思(比如这类不做了),我记下来,转给桌面那边。"
    return title, conclusion, lead


def raise_missing_cards(db: Session, *, view: list[dict[str, Any]] | None = None, dossier_ids: list[int] | None = None) -> list[str]:
    """把缺包清单发成卡:同一个缺包、同样多的品只发一次;又多了品在等 → 发新卡、旧卡作废;没品在等了 → 旧卡作废。返回新卡短号。"""
    from . import cards
    from .models import SqhCard

    view = view if view is not None else registry.view(db)
    names = {p["id"]: p.get("name") or p["id"] for p in view}
    report = missing_report(db, dossier_ids=dossier_ids)
    pending = list(db.scalars(select(SqhCard).where(SqhCard.kind == MISSING_CARD_KIND, SqhCard.status == "pending"), execution_options=_X))
    live_keys = {g["key"] for g in report}
    for card in pending:
        if (card.evidence or {}).get("missing_key") not in live_keys:
            cards.retire(db, card, reason="这个缺包已经没有品在等了(包好了,或者那几个品不做了)。")
    new_refs: list[str] = []
    for group in report:
        n = len(group["products"])
        title, conclusion, _ = _missing_card_text(group, names)
        card, created = cards.create_card(
            db,
            dedupe_key=f"route_missing:{group['key']}:{n}"[:160],
            kind=MISSING_CARD_KIND,
            title=title[:60],
            conclusion=conclusion,
            why="\n".join(f"{p['sku']}:" + ";".join(p["why"]) for p in group["products"] if p["why"]),
            if_not="不看也没关系,这几个品照样等包;包做好了我会重新给它们选包。",
            reversible=True,
            confidence="high",
            evidence={"missing_key": group["key"], "kind": group["kind"], "pack": group["pack"], "stage": group["stage"], "progress": group["progress"], "suggestion": group["suggestion"], "products": group["products"]},
        )
        if not created:
            continue
        new_refs.append(card.ref)
        for old in pending:
            if old.id != card.id and (old.evidence or {}).get("missing_key") == group["key"]:
                cards.retire(db, old, reason=f"又多了品在等这个包,合并进新卡 #{card.ref}。")
    db.flush()
    return new_refs


def after_missing(db: Session, card: Any, *, decision: str) -> dict[str, Any]:
    from . import memory

    if decision == "approve":
        return {"ok": True, "note": "好,这几个品等包。"}
    memory.record(
        db,
        kind="observation",
        subject=f"缺包:{card.title}",
        body=f"老板对缺包卡 #{card.ref} 的意思:{card.decision_reason or ''}(下一份交接转给 Mac)",
        refs={"card_ref": card.ref, "missing_key": (card.evidence or {}).get("missing_key")},
        source="human",
    )
    return {"ok": True, "note": "记下了,下一份交接我转给桌面那边。"}
