"""殷承岳的护栏:候选由代码查表得出,模型选了候选外的 id 一律作废;拿不准就说拿不准。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.modules.agent_series.yinchengyue import classifier
from backend.app.modules.agent_series.yinchengyue.brain import (
    KeywordHint,
    RawChoice,
    build_choice_messages,
    parse_choice,
    parse_keyword_hint,
)
from backend.app.modules.agent_series.yinchengyue.classifier import Candidate, classify, shortlist, validate_choice, zh_fragments

pytestmark = pytest.mark.unit

ROWS = [
    # id, name, name_zh, full_path, parent, level, is_leaf
    ("988", "Sporting Goods", "运动用品", "Sporting Goods", None, 1, 0),
    ("1011", "Outdoor Recreation", "户外休闲", "Sporting Goods > Outdoor Recreation", "988", 2, 0),
    ("1013", "Camping & Hiking", "露营与徒步", "Sporting Goods > Outdoor Recreation > Camping & Hiking", "1011", 3, 0),
    ("1014", "Camping Cookware", "露营炊具", "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware", "1013", 4, 1),
    ("1015", "Portable Cooking Stoves", "便携式炉具", "Sporting Goods > Outdoor Recreation > Camping & Hiking > Portable Cooking Stoves", "1013", 4, 1),
    ("536", "Home & Garden", "家居与园艺", "Home & Garden", None, 1, 0),
    ("668", "Kitchen & Dining", "厨房与餐厅", "Home & Garden > Kitchen & Dining", "536", 2, 0),
    ("672", "Cookware", "炊具", "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware", "668", 4, 0),
    ("4502", "Skillets & Frying Pans", "煎锅", "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware > Skillets & Frying Pans", "672", 5, 1),
    ("3336", "Thermoses", "保温瓶", "Home & Garden > Kitchen & Dining > Food & Beverage Carriers > Thermoses", "668", 4, 1),
    ("1019", "Camping Lights & Lanterns", "营地灯/灯具", "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Lights & Lanterns", "1013", 4, 1),
    ("4060", "Cocktail & Barware Tool Sets", "调酒工具套装", "Home & Garden > Kitchen & Dining > Barware > Cocktail & Barware Tool Sets", "668", 4, 1),
]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE k_category_google (id TEXT PRIMARY KEY, name TEXT, name_zh TEXT, full_path TEXT, "
            "parent_id TEXT, level INTEGER, is_leaf BOOLEAN)"
        ))
        for row in ROWS:
            conn.execute(
                text("INSERT INTO k_category_google (id, name, name_zh, full_path, parent_id, level, is_leaf) VALUES (:id, :name, :zh, :path, :parent, :level, :leaf)"),
                {"id": row[0], "name": row[1], "zh": row[2], "path": row[3], "parent": row[4], "level": row[5], "leaf": row[6]},
            )
    with Session(engine) as session:
        yield session


def _cand(cid: str) -> Candidate:
    row = next(r for r in ROWS if r[0] == cid)
    return Candidate(id=row[0], name=row[1], full_path=row[3], name_zh=row[2], level=row[5], is_leaf=bool(row[6]))


# ---------------------------------------------------------------- 解析(模型输出容错)


def test_parse_keyword_hint_accepts_dict_raw_json_and_fenced_json():
    direct = parse_keyword_hint({"is_product_question": True, "keywords_en": ["camping cookware", "camping cookware", " Thermos ", ""]})
    assert direct.keywords_en == ["camping cookware", "Thermos"]
    wrapped = parse_keyword_hint({"content": '```json\n{"is_product_question": true, "keywords_en": "solar lantern"}\n```'})
    assert wrapped.keywords_en == ["solar lantern"]
    garbage = parse_keyword_hint({"content": "not json at all"})
    assert garbage.is_product_question is False and garbage.keywords_en == []
    too_many = parse_keyword_hint({"keywords_en": [f"k{i}" for i in range(20)]})
    assert len(too_many.keywords_en) == 6


def test_parse_choice_normalizes_confidence_and_caps_alternates():
    raw = parse_choice({"chosen_id": 1014, "confidence": "HIGH", "reason_zh": "x", "alternates": [{"id": 1015, "reason": "a"}, {"id": "672"}, {"id": "9"}, {"id": "8"}]})
    assert raw.chosen_id == "1014" and raw.confidence == "high"
    assert [a.id for a in raw.alternates] == ["1015", "672", "9", "8"]
    assert parse_choice({"content": "{}"}).chosen_id == "NONE"
    assert parse_choice({"confidence": "sure"}).confidence == "low"


# ---------------------------------------------------------------- 候选


def test_zh_fragments_cover_whole_runs_and_windows_without_latin():
    frags = zh_fragments("露营炊具套装 aluminum 304不锈钢")
    assert "露营炊具套装" in frags and "炊具" in frags and "不锈钢" in frags
    assert all(all("一" <= ch <= "鿿" for ch in f) for f in frags)
    assert zh_fragments("camping cookware") == []


def test_shortlist_prefers_leaves_and_merges_english_and_chinese_hits(db):
    ranked = shortlist(db, keywords_en=["camping cookware", "cookware"], raw_text="露营炊具套装")
    ids = [c.id for c in ranked]
    assert ids[0] == "1014", ids  # 英文名+路径+中文名三处命中的叶子排第一
    assert ids.index("1014") < ids.index("672")  # 叶子先于非叶子
    assert len(ids) == len(set(ids))  # 去重
    assert all(isinstance(c, Candidate) for c in ranked)


def test_shortlist_respects_limit_and_ignores_too_short_keywords(db):
    ranked = shortlist(db, keywords_en=["a", "ab", "cookware"], raw_text="", limit=2)
    assert len(ranked) == 2
    assert shortlist(db, keywords_en=[], raw_text="") == []


def test_shortlist_falls_back_to_all_tokens_and_head_noun(db):
    # 整句 "camping lantern" 在树里不存在;两个词都在 "Camping Lights & Lanterns" 里 → 命中。
    ids = [c.id for c in shortlist(db, keywords_en=["camping lantern"], raw_text="太阳能露营灯")]
    assert ids and ids[0] == "1019"
    # 单词 "thermos" 单数化后命中 "Thermoses"。
    assert "3336" in [c.id for c in shortlist(db, keywords_en=["steel thermos"], raw_text="")]


# ---------------------------------------------------------------- 校验


def test_validate_choice_rejects_ids_outside_shortlist():
    cands = [_cand("1014"), _cand("1015"), _cand("672")]
    chosen, alts = validate_choice(RawChoice(chosen_id="4502", confidence="high", reason_zh="编的"), cands)
    assert chosen is None and alts == []
    chosen, alts = validate_choice(
        RawChoice(chosen_id="1014", alternates=[{"id": "1014", "reason_zh": "重复"}, {"id": "999", "reason_zh": "外来"}, {"id": "1015", "reason_zh": "炉头为主"}, {"id": "672", "reason_zh": "家用"}, {"id": "1015", "reason_zh": "再来一次"}]),
        cands,
        keywords_en=["camping cookware"],
    )
    assert chosen is not None and chosen.id == "1014"
    # 672 Cookware 与主选不同大类,但名字带着用户的关键词 cookware → 留下
    assert [(c.id, why) for c, why in alts] == [("1015", "炉头为主"), ("672", "家用")]


def test_validate_choice_drops_unrelated_alternates():
    cands = [_cand("1014"), _cand("4060"), _cand("1015")]
    chosen, alts = validate_choice(
        RawChoice(chosen_id="1014", alternates=[{"id": "4060", "reason_zh": "户外调酒"}, {"id": "1015", "reason_zh": "炉头"}]),
        cands,
        keywords_en=["camping cookware", "portable stove"],
    )
    assert chosen is not None
    assert [c.id for c, _ in alts] == ["1015"]  # 调酒工具套装既不同大类、名字也不沾关键词 → 丢掉


# ---------------------------------------------------------------- 主流程


def test_classify_ok_path_uses_real_candidate_and_breadcrumb(db):
    calls: dict[str, object] = {}

    def extract(text_in):
        return KeywordHint(is_product_question=True, product_en="camping cookware set", keywords_en=["camping cookware", "portable cooking stove", "cookware"])

    def choose(text_in, hint, candidates):
        calls["candidates"] = [c.id for c in candidates]
        assert "1014 | Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware | 露营炊具" in build_choice_messages(text_in, hint, candidates)[1]["content"]
        return RawChoice(chosen_id="1014", confidence="high", reason_zh="户外炉具+锅具", alternates=[{"id": "1015", "reason_zh": "以炉头为主"}])

    verdict = classify(db, "露营炊具套装,铝锅加折叠炉具", extract=extract, choose=choose)
    assert verdict.status == "ok"
    assert verdict.chosen is not None and verdict.chosen.name == "Camping Cookware"
    assert verdict.path == ["Sporting Goods", "Outdoor Recreation", "Camping & Hiking", "Camping Cookware"]
    assert [c.id for c, _ in verdict.alternates] == ["1015"]
    assert "1014" in calls["candidates"] and verdict.shortlist_size == len(calls["candidates"])


def test_classify_treats_foreign_id_and_none_as_no_answer(db):
    extract = lambda t: KeywordHint(is_product_question=True, keywords_en=["cookware"])  # noqa: E731
    foreign = classify(db, "x", extract=extract, choose=lambda t, h, c: RawChoice(chosen_id="4444444", confidence="high", reason_zh="幻觉"))
    assert foreign.status == "none" and foreign.chosen is None and foreign.shortlist_size > 0
    none = classify(db, "x", extract=extract, choose=lambda t, h, c: RawChoice(chosen_id="NONE"))
    assert none.status == "none"


def test_classify_short_circuits_non_product_and_empty_shortlist(db):
    chit = classify(db, "你好", extract=lambda t: KeywordHint(is_product_question=False), choose=lambda *a: pytest.fail("不该走到第二步"))
    assert chit.status == "none" and chit.shortlist_size == 0
    empty = classify(db, "zzz", extract=lambda t: KeywordHint(is_product_question=True, keywords_en=["quantum flux"]), choose=lambda *a: pytest.fail("候选为空不该问模型"))
    assert empty.status == "none"


def test_classify_reports_offline_when_either_model_step_fails(db):
    def boom(*args):
        raise TimeoutError("flash 没回")

    first = classify(db, "x", extract=boom, choose=lambda *a: RawChoice())
    assert first.status == "offline" and "extract" in first.error
    second = classify(db, "x", extract=lambda t: KeywordHint(keywords_en=["cookware"]), choose=boom)
    assert second.status == "offline" and "choose" in second.error and second.shortlist_size > 0
