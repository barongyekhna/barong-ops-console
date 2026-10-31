"""她去问卖家重量尺寸(10-29,B 期)。

老板的口径:**只有**详情页明确不可信(各规格同一个重量)或没有重量尺寸时才去问;固定模板直接发,不改词;首月一天最多 5 家(台账 sqh_1688_im);
老板驳回价格卡时提到重量/尺寸也算一次要问。卖家口头说的只当估算,写进规格时标 source=seller_said、「卖家口头」,永不当认证。

流程:_step_price_card 算完成本线 → needs_ask 有理由 → ask():扣台账 → 浏览器线程开旺旺发问 → draft.seller_chat.status=asked,价格卡先不出;
worker 每轮 poll_all():到点开旺旺读消息 → 新回复交给便宜模型抽成每规格的 重量/尺寸/一箱几个 → 写回 variants,作废还在等批的价格卡 →
流水线下一轮重出价格卡(why 里写明「卖家口头」);等满 SQH_SELLER_CHAT_WAIT_HOURS 没回 → timeout,价格卡照旧出并写「问了没回」。
状态都在 draft["seller_chat"],没有迁移。开关 SQH_SELLER_CHAT(默认关)。
卖家回图(标签照片/规格表截图/称重照片):浏览器带登录态把图下到 browser-dumps/seller-chat/,交读图档(fast=Haiku)转成文字,
和文字回复一起给抽数模型;一张都没读出字就继续等。语音在 1688 几乎不存在,不管。
卖家反问(10-30 老板拍板):答非所问/不说人话的不追问(「这种卖家不合作」);只有问「哪个款式/规格」「要多少件」这两类才回一句固定话,
一单只一次,不占每天 5 家的额度,永不发第三句。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import browser, cards, memory
from .constants import LA, seller_chat_enabled, seller_chat_poll_minutes, seller_chat_wait_hours
from .models import SqhDossier
from .pricing import SELLER_SAID, Line

logger = logging.getLogger(__name__)

STATUS_ASKED, STATUS_ANSWERED, STATUS_TIMEOUT, STATUS_FAILED = "asked", "answered", "timeout", "failed"
WEIGHT_WORDS = ("重量", "尺寸", "体积", "多重", "几克", "多少克", "公斤", "kg", "几斤", "长宽高", "装箱", "一箱", "外箱")
QUESTION_TEMPLATE = "您好,我是跨境卖家,想确认一下:{specs}每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?谢谢。"
# 10-31 老板拍板的两句(一字不改)。她先看图(photo_check):看到牌子才问 NEUTRAL,全是效果图才问 PHOTOS。
NEUTRAL_ASK = "能发没有印字、没有 logo 的中性货和中性包装吗？"
PHOTOS_ASK = "方便发几张产品实拍照片吗？手机随手拍就行，不要效果图。"
WEIGHT_PART = "{specs}每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?"
QUESTION_HEAD = "您好,我是跨境卖家,想确认一下:"
QUESTION_MAX = 480
PARSE_ASK = (
    "A 1688 supplier replied in Chinese to our question about per-variant package weight, package dimensions and carton quantity. "
    "Map the reply onto the variants listed. Reply JSON only: "
    '{"answers": [{"key": "v1", "weight_g": 350, "dims_cm": [12, 8, 6], "units_per_carton": 50}], "unclear": false}. '
    "Omit any field the seller did not state; omit variants the seller did not cover. weight in grams, dims in cm. "
    "If the seller gave one figure for all variants, apply it to every variant. If nothing usable was said, return {\"answers\": [], \"unclear\": true}. "
    "Also report whether the seller asked us a clarifying question we should answer, in \"seller_question\": "
    '{"kind": "which_variant" | "quantity" | "other" | "none", "quote": "<the seller\'s question verbatim, or empty>"}. '
    "which_variant = they ask which model/spec/style we mean or tell us to pick one; quantity = they ask how many pieces we want; "
    "other = some other real question; none = no question (greetings, auto-replies, '1', 'looking at it' are none). "
    "If our question also asked whether they can ship neutral goods (no printed logo or lettering, plain packaging), report "
    '"neutral_goods": "yes" | "no" | "not_answered" and quote their words in "neutral_quote"; use not_answered when they did not address it '
    "or we did not ask. Only weight/size/carton questions belong in answers."
)
# 卖家反问有用的问题(老板 10-30 拍板):只认两类,各一句固定话,一单只追答一次,永不发第三句;答非所问的不理。
FOLLOW_UP_TEMPLATES = {
    "which_variant": "就是这个链接的商品:{offer_url} 。要确认的是 {specs} 这几个规格,每个的包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个,麻烦了。",
    "quantity": "数量要看尺寸重量算好运费才能定,先按起订量了解。麻烦先告诉我 {specs} 每个的包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个,谢谢。",
}
USAGE_LABEL = "sqh_seller_chat"
IMAGE_ASK = (
    "This is a photo or screenshot a 1688 supplier sent in chat, answering our question about each variant's package weight (grams), "
    "package dimensions (cm, L×W×H) and units per carton. Transcribe into Chinese every weight, dimension and quantity figure visible, "
    "together with the variant name or label it belongs to, one item per line, exactly as written. Do not guess unreadable figures. "
    'Reply JSON only: {"text": "<lines>", "useful": true|false}. useful=false when the image holds no such figures.'
)
REPLY_IMAGES_PER_READ = 6  # 一次 poll 最多读几段图(和浏览器下载上限一致)
IMAGE_SEGMENTS_PER_IMAGE = 4  # 长截图切段后最多读几段


class SellerChatUnavailable(RuntimeError):
    """现在问不了(开关关着 / 浏览器没开 / 浏览器正等老板 / 没有卖家账号)。价格卡照旧出,why 里写一句。"""


# ---------------------------------------------------------------- 纯函数


def enabled() -> bool:
    return seller_chat_enabled()


def chat_of(draft: Any) -> dict[str, Any]:
    chat = (draft or {}).get("seller_chat") if isinstance(draft, dict) else None
    return dict(chat) if isinstance(chat, dict) else {}


def chat_topics(chat: dict[str, Any]) -> dict[str, bool]:
    """这次问了哪几件。老底账(10-31 之前)没有 topics,只问过重量尺寸。"""
    raw = chat.get("topics") if isinstance(chat.get("topics"), dict) else None
    if raw is None:
        return {"weights": True, "neutral": False, "photos": False}
    return {k: bool(raw.get(k)) for k in ("weights", "neutral", "photos")}


def pending(draft: Any) -> bool:
    """价格卡要不要等:只有问了重量尺寸、还在等,才等。只问无标货/实拍图的不挡价格卡。"""
    chat = chat_of(draft)
    return chat.get("status") == STATUS_ASKED and chat_topics(chat)["weights"]


def day_key(now: datetime) -> str:
    return now.astimezone(LA).date().isoformat()


def boss_wants_weight(reason: str | None) -> bool:
    text = (reason or "").lower()
    return any(word in text for word in WEIGHT_WORDS)


def _weight_reason(chat: dict[str, Any], lines: list[Line]) -> str | None:
    if chat.get("requested"):
        return "老板驳回价格卡时提到重量尺寸"
    missing = [line.name_zh or line.key for line in lines if line.weight_g is None]
    if missing:
        return f"详情页没有重量尺寸({'、'.join(missing[:3])}{'…' if len(missing) > 3 else ''})"
    if any("可能是乱填的" in (line.weight_note or "") for line in lines):
        return "每个规格都填了同一个重量,疑似乱填"
    guessed = [line for line in lines if "没写这个规格的重量" in (line.weight_note or "")]
    if guessed:
        return f"{len(guessed)} 个规格没写重量"
    return None


def ask_plan(draft: Any, lines: list[Line], *, now: datetime) -> tuple[str, dict[str, bool]] | None:
    """要不要去问、问哪几件:返回 (理由, topics),None = 不问。
    重量尺寸严格按老板的口径(自动最多问一次;老板驳回点名重量尺寸才会再问);
    无标货/实拍图只看 photo_check 的结论,一个品只顺带问这一次。"""
    from . import photo_check

    if not enabled():
        return None
    chat = chat_of(draft)
    status = chat.get("status")
    if status == STATUS_ASKED:
        return None  # 在等回复
    if not lines:
        return None
    requested = bool(chat.get("requested"))
    if not requested and (status in (STATUS_ANSWERED, STATUS_TIMEOUT, STATUS_FAILED) or chat.get("asked_day") == day_key(now)):
        return None
    weight_why = _weight_reason(chat, lines)
    photo = photo_check.topics(draft) if not chat.get("photo_topics_asked") else {"neutral": False, "photos": False}
    plan = {"weights": weight_why is not None, "neutral": photo["neutral"], "photos": photo["photos"]}
    if not any(plan.values()):
        return None
    reasons = [weight_why] if weight_why else []
    if plan["neutral"]:
        brand = str(((draft or {}).get("photo_audit") or {}).get("brand_text") or "").strip()
        reasons.append(f"图上产品有牌子{f'({brand[:30]})' if brand else ''},问能不能发无标货")
    if plan["photos"]:
        reasons.append("图全是效果图,要几张实拍")
    return ";".join(reasons), plan


def needs_ask(draft: Any, lines: list[Line], *, now: datetime) -> str | None:
    """要不要去问:返回理由,None = 不问(见 ask_plan)。"""
    plan = ask_plan(draft, lines, now=now)
    return plan[0] if plan else None


def build_question(variants: list[dict[str, Any]], topics: dict[str, bool] | None = None) -> str:
    """固定话术,不改词。只问重量尺寸时和 10-29 的原模板一字不差;多件一起问就编号。
    规格太多就只点名前几个,免得超过旺旺 500 字。"""
    topics = topics or {"weights": True}
    names = [str(v.get("name_zh") or "").strip() for v in variants if isinstance(v, dict)]
    names = [n for n in names if n]
    others = [text for key, text in (("neutral", NEUTRAL_ASK), ("photos", PHOTOS_ASK)) if topics.get(key)]

    def compose(specs: str) -> str:
        parts = ([WEIGHT_PART.format(specs=specs)] if topics.get("weights") else []) + others
        if len(parts) == 1:
            return QUESTION_HEAD + parts[0] + "谢谢。"
        return QUESTION_HEAD + "".join(f"{i}.{part}" for i, part in enumerate(parts, start=1)) + "谢谢。"

    specs = ""
    if names and topics.get("weights"):
        shown: list[str] = []
        for name in names:
            candidate = "、".join([*shown, name])
            if len(compose(candidate + " ")) > QUESTION_MAX - 20:
                break
            shown.append(name)
        rest = len(names) - len(shown)
        specs = "、".join(shown) + (f" 等共 {len(names)} 个规格" if rest > 0 else "") + " "
    return compose(specs)[:QUESTION_MAX]


def topics_text(topics: dict[str, bool]) -> str:
    parts = [label for key, label in (("weights", "每个规格的重量尺寸和装箱数"), ("neutral", "能不能发无标中性货"), ("photos", "要几张实拍图")) if topics.get(key)]
    return "、".join(parts) or "重量尺寸"


def parse_neutral(data: Any) -> dict[str, str] | None:
    """抽数模型顺带报的「能不能发无标货」:只认 yes / no。"""
    if not isinstance(data, dict):
        return None
    value = str(data.get("neutral_goods") or "").strip().lower()
    if value not in ("yes", "no"):
        return None
    return {"value": value, "quote": str(data.get("neutral_quote") or "")[:200]}


def _image_urls(message: dict[str, Any]) -> tuple[str, ...]:
    urls = []
    for item in message.get("images") or []:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url:
            urls.append(url)
    return tuple(urls)


def new_replies(messages: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """卖家的新消息 = 列表里不是自己发的、且发问那一刻还没有的。按 (nick, time, text, 图片地址) 认,不比时区。
    有文字或有图都算一条;老底账没有 images 字段,当空。"""
    seen = {(str(m.get("nick") or ""), str(m.get("time") or ""), str(m.get("text") or ""), _image_urls(m)) for m in baseline if isinstance(m, dict)}
    out = []
    for m in messages:
        if not isinstance(m, dict) or m.get("self"):
            continue
        key = (str(m.get("nick") or ""), str(m.get("time") or ""), str(m.get("text") or ""), _image_urls(m))
        if key in seen or not (key[2] or key[3]):
            continue
        images = [{"url": i.get("url"), "path": i.get("path")} for i in (m.get("images") or []) if isinstance(i, dict) and i.get("url")]
        out.append({"nick": key[0], "time": key[1], "text": key[2][:1000], "images": images})
    return out


def _read_image_segment(db: Session, prompt: str, segment: bytes) -> Any:
    from . import brain
    from .sourcing_1688 import _payload

    db.commit()  # 出网前放掉事务
    return brain._execute("fast", _payload(prompt, segment)["messages"], timeout=60, usage_label=USAGE_LABEL)


def read_images(db: Session, replies: list[dict[str, Any]], *, listing: str = "", reader: Callable[[Session, str, bytes], Any] | None = None) -> int:
    """把卖家回复里下下来的图(path)交给读图档转成文字,写进 image["read"]。读不了(额度降级/坏图/出错)写 None,不中断。返回读出字的张数。"""
    from .brain import parse_json
    from .sourcing_1688 import slice_image

    reader = reader or _read_image_segment
    prompt = IMAGE_ASK + (f"\n\nVariants we asked about:\n{listing}" if listing else "")
    budget = REPLY_IMAGES_PER_READ
    got = 0
    for reply in replies:
        for image in reply.get("images") or []:
            path = image.get("path") if isinstance(image, dict) else None
            if not path or budget <= 0:
                continue
            try:
                with open(path, "rb") as fh:
                    segments = slice_image(fh.read())[:IMAGE_SEGMENTS_PER_IMAGE]
            except Exception as exc:  # noqa: BLE001 —— 坏图
                image["read"], image["error"] = None, f"图打不开:{str(exc)[:80]}"
                continue
            lines: list[str] = []
            error = None
            for segment in segments:
                if budget <= 0:
                    break
                budget -= 1
                try:
                    result = reader(db, prompt, segment)
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)[:120]
                    break
                if isinstance(result, dict) and result.get("_ai_degraded"):
                    error = "读图档今天额度用完,图先读不了"
                    break
                data = parse_json(result) or {}
                text = str(data.get("text") or "").strip()
                if text:
                    lines.append(text)
            image["read"] = "\n".join(lines)[:500] or None
            if error:
                image["error"] = error
            if image["read"]:
                got += 1
    return got


def reply_text(replies: list[dict[str, Any]]) -> str:
    """给抽数模型看的回复原文:文字 + 每张图的转录(没读出来也写明,别让它脑补)。"""
    parts = []
    for m in replies:
        line = f"[{m.get('time') or ''}] {m.get('nick') or ''}: {m.get('text') or ''}".rstrip()
        for n, image in enumerate(m.get("images") or [], start=1):
            read = image.get("read") if isinstance(image, dict) else None
            line += f"\n  [图片{n} 转录] {read}" if read else f"\n  [图片{n} 没读出来]"
        parts.append(line)
    return "\n".join(parts)


def _num(value: Any, lo: float, hi: float) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def parse_answers(data: Any, variants: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """模型抽出来的 → 每规格一条,只留像样的数:重量 1g–50kg、尺寸 0.5–200cm 三个、一箱 1–10000 个。key 认 v1/v2…(和 cost_lines 一致)。"""
    keys = {f"v{i}" for i in range(1, len(variants) + 1)}
    out: dict[str, dict[str, Any]] = {}
    for item in (data or {}).get("answers") or [] if isinstance(data, dict) else []:
        if not isinstance(item, dict) or str(item.get("key")) not in keys:
            continue
        entry: dict[str, Any] = {}
        weight = _num(item.get("weight_g"), 1, 50_000)
        if weight is not None:
            entry["weight_g"] = weight
        dims = item.get("dims_cm")
        if isinstance(dims, list) and len(dims) == 3:
            parsed = [_num(d, 0.5, 200) for d in dims]
            if all(d is not None for d in parsed):
                entry["dims_cm"] = parsed
        carton = _num(item.get("units_per_carton"), 1, 10_000)
        if carton is not None:
            entry["units_per_carton"] = int(carton)
        if entry:
            out[str(item["key"])] = entry
    return out


def parse_question(data: Any) -> dict[str, str] | None:
    """抽数模型顺带报的「卖家反问」:只认 which_variant / quantity 两类(老板口径),其余当没问。"""
    if not isinstance(data, dict) or not isinstance(data.get("seller_question"), dict):
        return None
    kind = str(data["seller_question"].get("kind") or "").strip()
    if kind not in FOLLOW_UP_TEMPLATES:
        return None
    return {"kind": kind, "quote": str(data["seller_question"].get("quote") or "")[:200]}


def follow_up_text(kind: str, variants: list[dict[str, Any]], offer_url: str) -> str:
    """固定话术,不生成。规格太多只点前几个。"""
    names = [str(v.get("name_zh") or "").strip() for v in variants if isinstance(v, dict) and str(v.get("name_zh") or "").strip()]
    shown: list[str] = []
    for name in names:
        candidate = "、".join([*shown, name])
        if len(FOLLOW_UP_TEMPLATES[kind].format(offer_url=offer_url, specs=candidate)) > QUESTION_MAX - 30:
            break
        shown.append(name)
    specs = "、".join(shown) + (f" 等共 {len(names)} 个" if len(names) > len(shown) else "")
    return FOLLOW_UP_TEMPLATES[kind].format(offer_url=offer_url, specs=specs or "链接里的每个规格")[:QUESTION_MAX]


def apply_answers(variants: list[dict[str, Any]], answers: dict[str, dict[str, Any]], *, asked_at: str) -> int:
    """写回规格:source=seller_said、weight_source_note=「卖家口头」。只盖卖家说了的字段。返回改了几个规格。"""
    changed = 0
    for index, variant in enumerate(variants, start=1):
        entry = answers.get(f"v{index}")
        if not entry or not isinstance(variant, dict):
            continue
        variant.update({k: v for k, v in entry.items() if k in ("weight_g", "dims_cm", "units_per_carton")})
        variant["source"] = SELLER_SAID
        variant["weight_source_note"] = "卖家口头"
        variant["seller_said_at"] = asked_at
        changed += 1
    return changed


# ---------------------------------------------------------------- 落库


def _save_chat(db: Session, dossier: SqhDossier, chat: dict[str, Any], *, variants: list[dict[str, Any]] | None = None, supplier: dict[str, Any] | None = None, neutral: dict[str, Any] | None = None) -> None:
    draft = dict(dossier.draft) if isinstance(dossier.draft, dict) else {}
    draft["seller_chat"] = chat
    if neutral is not None:
        # 「货是不是无标」:作图圈牌子只认这里的 yes(卖家口头,标出处);没有 / no = 当有牌子。
        draft["neutral_goods"] = neutral
    if variants is not None:
        draft["variants"] = variants
    if supplier is not None:
        draft["supplier"] = supplier
    dossier.draft = draft
    db.add(dossier)
    db.flush()


def request(db: Session, dossier: SqhDossier, *, reason: str | None) -> None:
    """老板驳回价格卡时点名重量尺寸:记下来,下一次出价格卡前先去问。"""
    chat = chat_of(dossier.draft)
    if chat.get("status") == STATUS_ASKED:
        return
    chat.update({"requested": True, "boss_reason": (reason or "")[:500]})
    _save_chat(db, dossier, chat)


def _judge(db: Session, prompt: str) -> Any:
    from . import brain

    db.commit()  # 出网前放掉事务
    return brain._execute("fast", [{"role": "user", "content": prompt}], timeout=60, usage_label=USAGE_LABEL)


def ask(db: Session, dossier: SqhDossier, lines: list[Line], *, why: str, topics: dict[str, bool] | None = None, now: datetime | None = None, send: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """扣一次台账,去旺旺发问。成功后 draft.seller_chat.status=asked。
    拿不到浏览器 → SellerChatUnavailable;台账用完 → RAQuotaExhaustedError;发没发成 → browser.SellerChatError(台账已退)。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_1688_IM, refund, try_consume

    now = now or datetime.now(UTC)
    if not enabled():
        raise SellerChatUnavailable("问卖家的开关没开")
    if send is None:
        if not browser.enabled():
            raise SellerChatUnavailable("登录浏览器没开,问不了卖家")
        if browser.holding():
            raise SellerChatUnavailable("浏览器正等老板,这会儿问不了")
    draft = dict(dossier.draft) if isinstance(dossier.draft, dict) else {}
    variants = [v for v in draft.get("variants") or [] if isinstance(v, dict)]
    supplier = dict(draft.get("supplier") or {}) if isinstance(draft.get("supplier"), dict) else {}
    chat = chat_of(draft)
    topics = {k: bool((topics or {"weights": True}).get(k)) for k in ("weights", "neutral", "photos")}
    question = build_question(variants, topics)
    try_consume(db, PROVIDER_SQH_1688_IM, amount=1)
    db.commit()
    offer_url = str(draft.get("source_url") or dossier.source_url)
    try:
        sender = send or (lambda **kw: browser.get().ask_seller(**kw))
        result = sender(offer_url=offer_url, login_id=supplier.get("login_id") or None, offer_id=str(dossier.offer_id), text=question, dossier_id=dossier.id)
    except Exception as exc:  # noqa: BLE001 —— 没发成不算她问过:退台账、记一笔,让价格卡照旧出
        refund(db, PROVIDER_SQH_1688_IM, amount=1)
        detail = getattr(exc, "detail", {}) or {}
        chat.update({"status": STATUS_FAILED, "failed_at": now.isoformat(), "reason": str(exc)[:300], "dump": detail.get("dump"), "requested": False, "topics": topics})
        _save_chat(db, dossier, chat)
        memory.log_activity(db, f"1688 {dossier.offer_id}:想问卖家{topics_text(topics)}没问成({str(exc)[:80]})。", kind="error")
        db.commit()
        raise
    if result.get("login_id") and not supplier.get("login_id"):
        supplier["login_id"] = result["login_id"]
    chat = {
        "status": STATUS_ASKED,
        "asked_at": now.isoformat(),
        "asked_day": day_key(now),
        "checked_at": now.isoformat(),
        "question": question,
        "why": why,
        "topics": topics,
        "photo_topics_asked": bool(chat.get("photo_topics_asked") or topics["neutral"] or topics["photos"]),
        "im_url": result.get("im_url"),
        "login_id": result.get("login_id") or supplier.get("login_id"),
        "dump": result.get("dump"),
        "baseline": [{"nick": m.get("nick"), "time": m.get("time"), "text": m.get("text")} for m in (result.get("messages") or []) if isinstance(m, dict)][-50:],
        "replies": [],
        "requested": False,
        "boss_reason": chat.get("boss_reason"),
    }
    _save_chat(db, dossier, chat, supplier=supplier)
    memory.log_activity(db, f"1688 {dossier.offer_id}:{why},我在旺旺问了卖家{topics_text(topics)},等回复(最多等 {seller_chat_wait_hours():g} 小时)。", kind="work")
    db.commit()
    return chat


def due(chat: dict[str, Any], *, now: datetime) -> bool:
    if chat.get("status") != STATUS_ASKED:
        return False
    try:
        checked = datetime.fromisoformat(str(chat.get("checked_at") or chat.get("asked_at")))
    except ValueError:
        return True
    return (now - checked).total_seconds() >= seller_chat_poll_minutes() * 60


def timed_out(chat: dict[str, Any], *, now: datetime) -> bool:
    """等满 N 小时没回就超时;追答过一次的从追答那一刻重新数。"""
    try:
        asked = datetime.fromisoformat(str((chat.get("follow_up") or {}).get("at") or chat.get("asked_at")))
    except (TypeError, ValueError):
        return True
    return (now - asked).total_seconds() >= seller_chat_wait_hours() * 3600


def _retire_price_card(db: Session, dossier: SqhDossier, *, reason: str) -> bool:
    pipe = (dossier.draft or {}).get("pipeline") if isinstance(dossier.draft, dict) else None
    ref = ((pipe or {}).get("price") or {}).get("card_ref")
    card = cards.find_card(db, str(ref)) if ref else None
    return bool(card is not None and card.status == "pending" and cards.retire(db, card, reason=reason))


def _follow_up(db: Session, dossier: SqhDossier, chat: dict[str, Any], question: dict[str, str], variants: list[dict[str, Any]], *, now: datetime, send: Callable[..., dict[str, Any]] | None) -> str | None:
    """卖家反问有用的问题:回一句固定话(一单只一次),底账换成发完那一刻的全部消息,等待时间从现在重新数。不占每天 5 家的台账。
    发不出去(浏览器没开/正等老板/没发成)就当没追,照旧等。"""
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    offer_url = str(draft.get("source_url") or dossier.source_url)
    text = follow_up_text(question["kind"], variants, offer_url)
    if send is None:
        if not browser.enabled() or browser.holding():
            return None
        send = lambda **kw: browser.get().ask_seller(**kw)  # noqa: E731
    try:
        result = send(offer_url=offer_url, login_id=chat.get("login_id") or None, offer_id=str(dossier.offer_id), text=text, dossier_id=dossier.id)
    except Exception as exc:  # noqa: BLE001 —— 追答没发成不算追过,下轮若还没数就再试一次;记一笔
        memory.log_activity(db, f"1688 {dossier.offer_id}:卖家反问「{question['quote'][:40]}」,我想回一句没发成({str(exc)[:60]})。", kind="error")
        return None
    chat["follow_up"] = {"at": now.isoformat(), "kind": question["kind"], "quote": question["quote"], "text": text, "dump": result.get("dump")}
    chat["baseline"] = [{"nick": m.get("nick"), "time": m.get("time"), "text": m.get("text"), "images": [{"url": u} for u in (m.get("images") or []) if isinstance(u, str)] or [{"url": i.get("url")} for i in (m.get("images") or []) if isinstance(i, dict)]} for m in (result.get("messages") or []) if isinstance(m, dict)][-50:]
    chat["checked_at"] = now.isoformat()
    _save_chat(db, dossier, chat)
    memory.log_activity(db, f"1688 {dossier.offer_id}:卖家反问「{question['quote'][:40]}」,我回了一句({'说明是哪几个规格' if question['kind'] == 'which_variant' else '先按起订量了解'}),接着等,不再追第二次。", kind="work")
    db.commit()
    return "followed_up"


def _record_side_answers(chat: dict[str, Any], data: Any, replies: list[dict[str, Any]], topics: dict[str, bool], *, now: datetime) -> str:
    """无标货/实拍图的回答记进 chat:neutral(卖家口头,带原话)、seller_photos(卖家发来的图,本机路径)。返回一句人话,没说到就空。"""
    said: list[str] = []
    if topics["neutral"]:
        neutral = parse_neutral(data)
        if neutral:
            chat["neutral"] = {**neutral, "source": SELLER_SAID, "note": "卖家口头", "at": now.isoformat()}
            said.append("能发无标中性货" if neutral["value"] == "yes" else "发不了无标货")
    if topics["photos"]:
        photos = [i.get("path") for m in replies for i in (m.get("images") or []) if isinstance(i, dict) and i.get("path")]
        if photos:
            chat["seller_photos"] = list(dict.fromkeys([*(chat.get("seller_photos") or []), *photos]))[:20]
            said.append(f"发了 {len(photos)} 张图(还没核是不是实拍)")
    return "、".join(said)


def poll_one(db: Session, dossier: SqhDossier, *, now: datetime, read: Callable[..., list[dict[str, Any]]] | None = None, judge: Callable[[Session, str], Any] | None = None, image_reader: Callable[[Session, str, bytes], Any] | None = None, send: Callable[..., dict[str, Any]] | None = None) -> str:
    """看一份档案的旺旺:超时 → timeout;有新回复 → 抽数写回规格、作废旧价格卡;没回 → 记下看过的时间。返回做了什么。"""
    from .brain import parse_json

    chat = chat_of(dossier.draft)
    offer = dossier.offer_id
    if timed_out(chat, now=now):
        chat.update({"status": STATUS_TIMEOUT, "checked_at": now.isoformat()})
        _save_chat(db, dossier, chat)
        memory.log_activity(db, f"1688 {offer}:问卖家{topics_text(chat_topics(chat))},{seller_chat_wait_hours():g} 小时没回{',价格卡按详情页的数出' if chat_topics(chat)['weights'] else ''}。", kind="work")
        db.commit()
        return "timeout"
    reader = read or (lambda **kw: browser.get().read_seller_chat(**kw))
    dossier_id = dossier.id
    db.commit()  # 开旺旺要几十秒:先把事务放掉,不然主库的空闲事务超时会把连接掐断(10-29 16:40 实况)
    messages = reader(im_url=str(chat.get("im_url") or ""), offer_id=str(offer))
    dossier = db.get(SqhDossier, dossier_id, execution_options=SKIP_ORG_DATA_ISOLATION) or dossier
    replies = new_replies(messages, chat.get("baseline") or [])
    chat["checked_at"] = now.isoformat()
    if not replies:
        _save_chat(db, dossier, chat)
        db.commit()
        return "no_reply"
    draft = dict(dossier.draft) if isinstance(dossier.draft, dict) else {}
    variants = [dict(v) for v in draft.get("variants") or [] if isinstance(v, dict)]
    listing = "\n".join(f"v{i}: {v.get('name_zh') or ''}" for i, v in enumerate(variants, start=1))
    replies = replies[:20]
    pictures = sum(len(m.get("images") or []) for m in replies)
    read = read_images(db, replies, listing=listing, reader=image_reader) if pictures else 0
    chat["replies"] = [{**m, "images": [{k: v for k, v in i.items() if k in ("url", "path", "read", "error")} for i in m.get("images") or []]} for m in replies]
    topics = chat_topics(chat)
    if pictures and read == 0 and not any((m.get("text") or "").strip() for m in replies):
        side = _record_side_answers(chat, {}, replies, topics, now=now)
        if side and not topics["weights"]:
            # 只要了实拍图,卖家发了图:这就是回答
            chat.update({"status": STATUS_ANSWERED, "answered_at": now.isoformat()})
            _save_chat(db, dossier, chat)
            memory.log_activity(db, f"1688 {offer}:卖家回了——{side}。", kind="work")
            db.commit()
            return "answered"
        _save_chat(db, dossier, chat)  # 只回了图、一张都没读出字:继续等,不瞎填
        memory.log_activity(db, f"1688 {offer}:卖家回了 {pictures} 张图,一张都没读出字,我再等等。", kind="work")
        db.commit()
        return "unclear"
    result = (judge or _judge)(db, f"{PARSE_ASK}\n\nVariants:\n{listing}\n\nOur question:\n{chat.get('question') or ''}\n\nSeller reply:\n{reply_text(replies)}")
    data = parse_json(result)
    answers = parse_answers(data, variants)
    side = _record_side_answers(chat, data, replies, topics, now=now)
    if not topics["weights"]:
        # 只问了无标货/实拍图:说到其中一件(或发了图)就算回了;没说到就接着等,不追问。
        if side:
            chat.update({"status": STATUS_ANSWERED, "answered_at": now.isoformat()})
            _save_chat(db, dossier, chat, neutral=chat.get("neutral"))
            memory.log_activity(db, f"1688 {offer}:卖家回了——{side}。", kind="work")
        else:
            _save_chat(db, dossier, chat)
            memory.log_activity(db, f"1688 {offer}:卖家回了话但没说到无标货/实拍图,我再等等。", kind="work")
        db.commit()
        return "answered" if side else "unclear"
    if not answers:
        question = parse_question(data)
        if question and not chat.get("follow_up"):
            outcome = _follow_up(db, dossier, chat, question, variants, now=now, send=send)
            if outcome:
                return outcome
        _save_chat(db, dossier, chat, neutral=chat.get("neutral"))  # 回了但没说到数(客套/答非所问):继续等,不追问(老板:这种卖家不合作)
        memory.log_activity(db, f"1688 {offer}:卖家回了话{f'和 {pictures} 张图(读出 {read} 张)' if pictures else ''}但没给重量尺寸,我再等等。", kind="work")
        db.commit()
        return "unclear"
    changed = apply_answers(variants, answers, asked_at=str(chat.get("asked_at") or now.isoformat()))
    chat.update({"status": STATUS_ANSWERED, "answered_at": now.isoformat(), "answers": answers})
    _save_chat(db, dossier, chat, variants=variants, neutral=chat.get("neutral"))
    retired = _retire_price_card(db, dossier, reason="卖家回了重量尺寸,按新数重出")
    memory.log_activity(db, f"1688 {offer}:卖家回了 {changed} 个规格的重量尺寸{f'(含 {pictures} 张图,读出 {read} 张)' if pictures else ''}(口头说的,没凭证),我按新数重出价格卡{'(旧卡作废)' if retired else ''}{f';另外{side}' if side else ''}。", kind="work")
    db.commit()
    return "answered"


def poll_all(db: Session, *, now: datetime | None = None, read: Callable[..., list[dict[str, Any]]] | None = None, judge: Callable[[Session, str], Any] | None = None, image_reader: Callable[[Session, str, bytes], Any] | None = None, send: Callable[..., dict[str, Any]] | None = None) -> str | None:
    """worker 每轮叫一次:到点的档案里挑一份去旺旺看。一轮最多一单(开旺旺要几十秒)。"""
    from . import pipeline

    if not enabled():
        return None
    now = now or datetime.now(UTC)
    for dossier, _product in pipeline.managed(db):
        chat = chat_of(dossier.draft)
        if not due(chat, now=now):
            continue
        if not timed_out(chat, now=now) and read is None and (not browser.enabled() or browser.holding()):
            return None  # 浏览器没开 / 正等老板:下轮再看
        try:
            return poll_one(db, dossier, now=now, read=read, judge=judge, image_reader=image_reader, send=send)
        except browser.SellerChatBlocked:
            db.rollback()
            return "blocked"
        except Exception as exc:  # noqa: BLE001 —— 看一次失败不拖垮 tick;记一笔下轮再看
            db.rollback()
            logger.exception("seller chat poll failed dossier=%s", dossier.id)
            chat["checked_at"] = now.isoformat()
            _save_chat(db, dossier, chat)
            memory.log_activity(db, f"1688 {dossier.offer_id}:去旺旺看回复没看成({str(exc)[:80]}),下轮再看。", kind="error")
            db.commit()
            return "error"
    return None
