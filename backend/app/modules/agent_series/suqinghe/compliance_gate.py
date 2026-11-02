"""独立站合规门(11-02,老板拍板):1688 来的货先过门,碰上清单就不做。

规矩(清单本身在 compliance_gate.json,带版本和老板原话;改清单要老板点头):
- 只管 1688 来的货:她自己抓的、老板在聊天里给的 1688 链接,一律过门(「1688一律过门无论是我给的还是他抓的」)。
  工厂自己的货(自产品)不过门——苏青禾的档案全是 1688 来的,自产品以后从别的入口进来,见 ``applies``。
- G01 OTC 药品含防晒、G02 FDA 管的医疗器械和号称治疗康复的、G03 婴儿和 12 岁以下儿童用品、G04 软体家具、
  G05 化妆品、G06 食品——碰上任何一条就不做;锂电池、驱蚊不挡。
- 清单里没有、但看着要专门监管的类别 → 发卡问老板,她不自己判。

怎么判(「模型只判、代码定」,交接 17 的骨架做法):代码先把答卷画好——六条规则的 id 和顺序写死、每条留 reason(先写)和 hit
(后填)两个空,外加一格「清单外但看着要管」;模型只往空里填。代码校验(id 一个不多一个不少、hit 必须是 true/false、
reason 不能空),格式不对同一份提示词重问一次;再不对就算「没判成」。结论由代码算:任一条 hit → drop;否则清单外 hit → ask;
都没有 → pass。额度降级(DeepSeek 顶班)判的不算数,也记「没判成」——毙不毙一个品不交给便宜档。

三处用到它:
1. 找货初筛(picks):留下的候选先过门,不过的不取数据、不发选品卡,在 F 候选上标红(automation_blocked,老板在 F 页面仍能手动放行)。
2. 建档(dossiers._complete):1688 页面读完、建档卡发出之前。drop → 档案 dropped + 一张合规卡;ask → 档案 gate_ask + 一张合规卡。
3. 流水线(pipeline):已经建进 K、还没过过门的品(合规门上线前建的),第一步先补判;drop/ask 就停在那,发同样的卡。

合规卡(kind compliance_gate):批 = 同意她的结论(不做);驳 = 放行(要写一句为什么),档案接着发建档卡 / 流水线接着往下推。
人的命令高于程序:一键就能放行,放行和理由都记在档案 draft["compliance_gate"]["override"]。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .constants import USAGE_LABEL

logger = logging.getLogger(__name__)

_X = SKIP_ORG_DATA_ISOLATION
RULES_FILE = Path(__file__).with_name("compliance_gate.json")
GATE_CARD_KIND = "compliance_gate"
GATE_USAGE_LABEL = f"{USAGE_LABEL}.gate"  # 记在她名下(她的个人闸按 suqinghe.* 算)
GATE_ROLE = "judge"  # 毙不毙一个品用判断档(选包同档,11-02 老板批 Opus)
GATE_TIMEOUT_SECONDS = 120.0
MAX_CALLS = 2  # 格式不对重问一次
SOURCE_1688 = "1688"
SOURCE_FACTORY = "factory"
# 档案状态:合规门毙掉的 / 清单外等老板定的
DOSSIER_DROPPED = "dropped"
DOSSIER_GATE_ASK = "gate_ask"
PASSING = {"pass", "skip", "override"}
WAITING = {"drop", "ask"}

GateFn = Callable[[Session, str], dict[str, Any]]


# ---------------------------------------------------------------- 清单


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    ids = [str(r["id"]) for r in data["rules"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("compliance_gate.json: 规则 id 重复或为空")
    return data


def rule_text(rule_id: str) -> str:
    for r in rules()["rules"]:
        if r["id"] == rule_id:
            return str(r["text"])
    return rule_id


def applies(source: str | None) -> bool:
    """1688 来的一律过门;只有明确标了 factory(工厂自己的货)的才跳过。来源不明按 1688 算(宁严勿松)。"""
    return (source or SOURCE_1688) != SOURCE_FACTORY


# ---------------------------------------------------------------- 骨架、提示词、校验、结论(纯函数)


def skeleton(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or rules()
    return {
        "rules": [{"id": r["id"], "rule": r["text"], "reason": "", "hit": None} for r in data["rules"]],
        "outside_list": {"reason": "", "category": "", "hit": None},
    }


def build_prompt(facts: str, data: dict[str, Any] | None = None) -> str:
    data = data or rules()
    rule_lines = "\n".join(
        f"- {r['id']} {r['text']}(例:{'、'.join(r.get('examples') or [])})" for r in data["rules"]
    )
    not_blocked = "\n".join(f"- {line}" for line in data.get("not_blocked") or [])
    return (
        "你是苏青禾,Barong Yekhna 独立站(美国市场)的运营总管。现在过「合规门」:判断这件 1688 来的货碰没碰老板定的不做清单。"
        "只判这件货本身是什么、给谁用、卖点说它能干什么;不管能不能卖得好。\n\n"
        f"## 不做清单(碰上任何一条就不做)\n{rule_lines}\n\n"
        f"## 明确不挡的(碰上这些也不算命中)\n{not_blocked}\n\n"
        f"## 清单外的一格\n{data.get('outside_list', '')}\n\n"
        "## 怎么填\n"
        "下面是一份已经画好的答卷。原样返回这个 JSON,只填空:\n"
        "- 每条规则先写 reason(一句话,说清这件货为什么碰/没碰这一条),再填 hit(true 或 false);\n"
        "- id、rule 的文字、条目顺序一个字都不要改,不要加条目、不要删条目;\n"
        "- outside_list:清单六条都没碰、但它属于要专门监管或认证才能卖的类别时,hit 填 true、category 写是什么类别;否则 hit 填 false、category 留空;\n"
        "- 拿不准的,在 reason 里写清拿不准什么,按更可能的那边填。\n"
        "只输出这一个 JSON 对象,不要别的文字。\n\n"
        f"## 答卷\n{json.dumps(skeleton(data), ensure_ascii=False, indent=1)}\n\n"
        f"## 这件货的资料\n{facts.strip()}"
    )


def validate(filled: Any, data: dict[str, Any] | None = None) -> list[str]:
    """答卷格式问题清单;空 = 合格。"""
    data = data or rules()
    if not isinstance(filled, dict):
        return ["不是 JSON 对象"]
    problems: list[str] = []
    want = [r["id"] for r in data["rules"]]
    got = filled.get("rules")
    if not isinstance(got, list):
        return ["rules 不是列表"]
    got_ids = [str(r.get("id")) if isinstance(r, dict) else "?" for r in got]
    if got_ids != want:
        problems.append(f"规则 id 不对:要 {want},给的是 {got_ids}")
    for r in got:
        if not isinstance(r, dict):
            continue
        if not isinstance(r.get("hit"), bool):
            problems.append(f"{r.get('id')} 的 hit 不是 true/false")
        if not str(r.get("reason") or "").strip():
            problems.append(f"{r.get('id')} 没写理由")
    outside = filled.get("outside_list")
    if not isinstance(outside, dict) or not isinstance(outside.get("hit"), bool):
        problems.append("outside_list.hit 不是 true/false")
    elif outside.get("hit") and not str(outside.get("category") or "").strip():
        problems.append("outside_list 判了 true 却没写类别")
    return problems


def decide(filled: dict[str, Any]) -> dict[str, Any]:
    """答卷(已经校验过)→ 结论。纯代码,不让模型下结论。"""
    hits = [
        {"id": str(r["id"]), "text": rule_text(str(r["id"])), "reason": str(r.get("reason") or "").strip()[:300]}
        for r in filled["rules"]
        if r.get("hit") is True
    ]
    outside = filled.get("outside_list") or {}
    if hits:
        status = "drop"
    elif outside.get("hit") is True:
        status = "ask"
    else:
        status = "pass"
    return {
        "status": status,
        "hits": hits,
        "outside": {"category": str(outside.get("category") or "").strip()[:80], "reason": str(outside.get("reason") or "").strip()[:300]} if outside.get("hit") else None,
        "reasons": {str(r["id"]): str(r.get("reason") or "").strip()[:300] for r in filled["rules"]},
    }


# ---------------------------------------------------------------- 判一次(出网)


def _default_call(db: Session, prompt: str) -> dict[str, Any]:
    from . import brain

    db.commit()  # 出网前放掉事务
    return brain._execute(GATE_ROLE, [{"role": "user", "content": prompt}], timeout=GATE_TIMEOUT_SECONDS, usage_label=GATE_USAGE_LABEL)


def judge(db: Session, facts: str, *, call: GateFn | None = None, now: datetime | None = None, source: str = SOURCE_1688) -> dict[str, Any]:
    """过一次门。返回记录(存进档案 draft["compliance_gate"]):
    status = pass / drop / ask / skip(自产品) / error(没判成:额度降级、接口出错、两次格式都不对)。"""
    from .brain import parse_json

    data = rules()
    base = {"version": int(data["version"]), "source": source, "judged_at": (now or datetime.now(UTC)).isoformat()}
    if not applies(source):
        return {**base, "status": "skip", "hits": [], "outside": None, "calls": 0}
    call = call or _default_call
    prompt = build_prompt(facts, data)
    problems: list[str] = []
    for attempt in range(1, MAX_CALLS + 1):
        try:
            raw = call(db, prompt)
        except Exception as exc:  # noqa: BLE001 —— 没判成不拖垮调用方,记「没判成」,下一轮再判
            logger.warning("compliance gate call failed: %s", exc)
            return {**base, "status": "error", "error": f"{exc.__class__.__name__}: {str(exc)[:160]}", "calls": attempt}
        if isinstance(raw, dict) and raw.get("_ai_degraded"):
            return {**base, "status": "error", "error": "Claude 额度用完,降级档判的不算数", "calls": attempt}
        filled = parse_json(raw)
        problems = validate(filled, data)
        if not problems:
            return {**base, **decide(filled), "calls": attempt}
    return {**base, "status": "error", "error": "两次答卷格式都不对:" + ";".join(problems)[:300], "calls": MAX_CALLS}


# ---------------------------------------------------------------- 资料


def _field(draft: dict[str, Any], key: str) -> Any:
    item = (draft.get("fields") or {}).get(key)
    return item.get("value") if isinstance(item, dict) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _texts(value: Any) -> list[str]:
    """[{"text": ...}] 或 ["..."] → 字符串列表;别的形状(计数、None、字典)→ 空。"""
    out: list[str] = []
    for item in _list(value):
        text = item.get("text") if isinstance(item, dict) else item if isinstance(item, str) else None
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def dossier_facts(draft: dict[str, Any], capture: dict[str, Any] | None = None, *, name_en: str | None = None) -> str:
    """建档草稿 → 给合规门看的资料:标题、英文名、类目、属性、规格、详情图上读到的字。不含进价、链接、卖家名。"""
    capture = capture or {}
    category = _field(draft, "category")
    category_text = ""
    if isinstance(category, dict):
        category_text = " / ".join(str(category.get(k) or "") for k in ("path", "name_zh") if category.get(k))
    attrs = [
        f"{a.get('name')}: {a.get('value')}"
        for a in _list(draft.get("other_attributes"))
        if isinstance(a, dict) and a.get("name") and a.get("value") not in (None, "")
    ]
    specs = [
        f"{key}: {item.get('value')}{(' ' + str(item['unit'])) if item.get('unit') else ''}"
        for key, item in (draft.get("specs") if isinstance(draft.get("specs"), dict) else {}).items()
        if isinstance(item, dict) and item.get("value") not in (None, "")
    ]
    variants = [str(v.get("name_zh") or v.get("name_en") or "") for v in _list(draft.get("variants")) if isinstance(v, dict)]
    # 11-02 热修:线上档案里 image_read.facts 是「读到几条」的计数,不是列表;读到的字在 material.features / material.claims 里
    # (流水线收卖点素材那一步写的)。每个字段都先看类型再用,读不懂的跳过,不能让一个字段把整步打挂。
    image_read = draft.get("image_read") if isinstance(draft.get("image_read"), dict) else {}
    material = draft.get("material") if isinstance(draft.get("material"), dict) else {}
    facts = _texts(image_read.get("facts")) + _texts(material.get("features"))
    claims = _texts(material.get("claims"))
    lines = [
        f"中文标题:{_field(draft, 'name_zh') or capture.get('title_zh') or ''}",
        f"英文名:{name_en or _field(draft, 'name_en') or ''}",
        f"类目:{category_text}",
        f"规格(变体):{' / '.join(v for v in variants if v) or '只有一个'}",
        f"属性:{';'.join(attrs[:30]) or '(没有)'}",
        f"参数:{';'.join(specs[:30]) or '(没有)'}",
        f"详情图上读到的字:{';'.join(facts[:60]) or '(没有)'}",
    ]
    if claims:
        lines.append(f"卖点说法:{';'.join(claims[:20])}")
    if isinstance(draft.get("summary_zh"), str) and draft["summary_zh"].strip():
        lines.append(f"她写的档案摘要:{draft['summary_zh']}")
    return "\n".join(lines)


def candidate_facts(row: Any) -> str:
    """F 候选池的一行 → 资料(初筛时只有这些)。"""
    specs = row.structured_specs_json if isinstance(getattr(row, "structured_specs_json", None), dict) else {}
    spec_text = ";".join(f"{k}: {v}" for k, v in list(specs.items())[:20] if v not in (None, ""))
    return "\n".join(
        (
            f"1688 标题:{getattr(row, 'title', '') or ''}",
            f"F 画像(当初搜货的目标):{getattr(row, 'profile_product_zh', '') or ''} / {getattr(row, 'profile_product_en', '') or ''}",
            f"1688 类目:{getattr(row, 'category_path', '') or ''}",
            f"参数:{spec_text or '(没有)'}",
        )
    )


# ---------------------------------------------------------------- 状态


def record(draft: Any) -> dict[str, Any] | None:
    gate = (draft or {}).get("compliance_gate") if isinstance(draft, dict) else None
    return gate if isinstance(gate, dict) else None


def state(draft: Any) -> str | None:
    """档案现在的合规门状态:None(还没判/没判成) / pass / skip / override(老板放行) / drop / ask。"""
    gate = record(draft)
    if gate is None:
        return None
    if isinstance(gate.get("override"), dict):
        return "override"
    status = str(gate.get("status") or "")
    return status if status in PASSING | WAITING else None


def headline(gate: dict[str, Any]) -> str:
    if gate.get("status") == "drop":
        return "、".join(f"{h['id']}({h['text']})" for h in gate.get("hits") or [])
    if gate.get("status") == "ask":
        return f"清单外但看着要管:{(gate.get('outside') or {}).get('category') or '?'}"
    return str(gate.get("status") or "")


# ---------------------------------------------------------------- 卡


def raise_card(db: Session, *, dossier: Any, gate: dict[str, Any], stage: str, title_hint: str) -> Any:
    """drop / ask 发一张合规卡。批 = 同意她的结论(不做);驳 = 放行(写一句为什么)。"""
    from . import cards

    status = gate["status"]
    name = (title_hint or dossier.offer_id)[:30]
    if status == "drop":
        lead = "；".join(f"{h['id']}「{h['text']}」:{h['reason']}" for h in gate.get("hits") or [])
        title = f"合规门不做:{name}"
        conclusion = f"这件货碰了老板定的不做清单,我不做它。{lead}"
    else:
        outside = gate.get("outside") or {}
        title = f"合规门要你定:{name}"
        conclusion = f"这件货不在不做清单里,但看着是要专门监管的「{outside.get('category') or '?'}」类,我倾向不做。{outside.get('reason') or ''}"
    where = "建档卡先不发" if stage == "dossier" else "这个品在 K 里先停着,不往下推"
    card, _ = cards.create_card(
        db,
        dedupe_key=f"gate:{dossier.id}:v{gate.get('version')}:{gate.get('judged_at', '')[:19]}",
        kind=GATE_CARD_KIND,
        title=title,
        conclusion=conclusion + f" 批 = 同意,不做;驳 = 判错了、放行(写一句为什么),我接着做。",
        why=f"1688 offer {dossier.offer_id};清单 v{gate.get('version')}(老板 11-01/11-02 定:1688 来的一律过门)。{where}。",
        if_not="不批也不驳,这个品就一直停着。",
        reversible=True,
        confidence="high" if status == "drop" else "medium",
        evidence={"dossier_id": dossier.id, "offer_id": dossier.offer_id, "stage": stage, "gate": {k: gate.get(k) for k in ("version", "status", "hits", "outside", "judged_at")}},
    )
    return card


def after_decision(db: Session, card: Any, *, decision: str, actor: Any) -> dict[str, Any]:
    """合规卡决定之后。批 = 照她的结论不做;驳 = 放行(老板的命令高于程序)。"""
    from . import memory
    from .models import SqhDossier

    evidence = card.evidence if isinstance(card.evidence, dict) else {}
    dossier = db.get(SqhDossier, int(evidence.get("dossier_id") or 0), execution_options=_X) if evidence.get("dossier_id") else None
    if dossier is None:
        return {"ok": False, "note": "找不到这份档案了。"}
    draft = dict(dossier.draft) if isinstance(dossier.draft, dict) else {}
    gate = dict(record(draft) or {})
    stage = evidence.get("stage")
    if decision == "approve":
        if dossier.status == DOSSIER_GATE_ASK:
            dossier.status = DOSSIER_DROPPED
        gate["confirmed"] = {"by": str(getattr(actor, "id", "") or ""), "at": datetime.now(UTC).isoformat(), "card_ref": card.ref}
        draft["compliance_gate"] = gate
        dossier.draft = draft
        db.add(dossier)
        db.flush()
        memory.log_activity(db, f"{dossier.offer_id}:合规门不做,老板同意了。", kind="dossier")
        return {"ok": True, "note": "好,这件不做了。"}
    gate["override"] = {"by": str(getattr(actor, "id", "") or ""), "at": datetime.now(UTC).isoformat(), "reason": card.decision_reason or "", "card_ref": card.ref}
    draft["compliance_gate"] = gate
    dossier.draft = draft
    db.add(dossier)
    db.flush()
    memory.log_activity(db, f"{dossier.offer_id}:老板放行了合规门({card.decision_reason or ''}),接着做。", kind="dossier")
    if stage == "dossier" and dossier.status in (DOSSIER_DROPPED, DOSSIER_GATE_ASK):
        from .dossiers import issue_dossier_card

        issue_dossier_card(db, dossier)
        return {"ok": True, "note": "好,放行了,建档卡我这就发。"}
    return {"ok": True, "note": "好,放行了,这个品接着往下推。"}


# ---------------------------------------------------------------- 找货初筛:F 候选标红


def flag_candidate(row: Any, gate: dict[str, Any]) -> None:
    """不过门的 F 候选:在 F 的红线字段上记一笔并挡住自动链路(F 的老规矩:只标记不毙掉,老板在 F 页面仍能手动放行)。"""
    flags = [f for f in (row.red_flags_json or []) if isinstance(f, dict) and f.get("type") != "sqh_compliance_gate"]
    flags.append(
        {
            "type": "sqh_compliance_gate",
            "gate": str(gate["status"]),
            "version": str(gate.get("version")),
            "reason": f"苏青禾合规门:{headline(gate)}"[:300],
        }
    )
    row.red_flags_json = flags
    row.automation_blocked = True
