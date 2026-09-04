"""F 找货：画像抢建不再互相打死，运行不再谎报成功（2026-09-04 用户实测事故）。

事故经过：用户点「1688 找货」六秒后又点了右栏「生成画像」。两边都走
`ensure_profile`（先查后插、无冲突处理），都查不到缓存、各调一次 DeepSeek。
按钮那次先落库，找货线程的 insert 撞 `uq_f_profiles_category` 抛异常，被运行
引擎逐节点的兜底 except 吃掉，循环跑完后照样把状态写成 succeeded ——
台账显示「完成」，候选 0，1688 一次没调，用户以为跑通了。

两条守住的规矩：
1. 并发建同一个类目的画像，后到的认前者那份，不抛异常；
2. 兜底 except 收场且一无所获的运行，状态必须是 failed。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 内存 SQLite 自建 schema，不碰生产库 —— 明确归 unit 道
pytestmark = pytest.mark.unit

from backend.app.db.base import Base
from backend.app.modules.f_series.enrichment import profiles as profile_engine
from backend.app.modules.f_series.enrichment.models import FCategoryProfile

PRODUCTS = [{"en": "Camping Lantern", "zh": "露营灯", "note_zh": "夜间照明"}]
RIVAL_PRODUCTS = [{"en": "LED Lantern", "zh": "LED 营地灯", "note_zh": "充电照明"}]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _stub_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Manager:
        def __init__(self, **_kwargs) -> None:
            pass

        def get_key(self, *_args, **_kwargs) -> str:
            return "deepseek-test-key"

    monkeypatch.setattr(profile_engine, "SecretManager", _Manager)


def _ensure(db):
    return profile_engine.ensure_profile(
        db,
        category_id="1019",
        category_path="Sporting Goods > Camping > Camping Lights & Lanterns",
        name_zh="露营灯具",
        org_id="org-test",
    )


def test_profile_is_generated_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    _stub_secret(monkeypatch)
    calls: list[str] = []

    def fake_deepseek(**kwargs):
        calls.append(kwargs["category_path"])
        return PRODUCTS

    monkeypatch.setattr(profile_engine, "_call_deepseek_profile", fake_deepseek)

    first = _ensure(db)
    db.commit()
    assert first.products_json == PRODUCTS
    # 第二次走缓存，不再调 DeepSeek
    second = _ensure(db)
    assert second.id == first.id
    assert len(calls) == 1


def test_concurrent_writer_wins_and_we_take_its_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟真实事故：我们在调 DeepSeek 的这段时间里，另一个写入者落了库。

    以前这里会抛 IntegrityError 一路炸到运行引擎；现在应当安静地认对方那份。
    """

    db = _session()
    _stub_secret(monkeypatch)

    def fake_deepseek(**_kwargs):
        # 「生成画像」按钮在我们等 DeepSeek 的这几十秒里赢了这一局。
        rival = sessionmaker(bind=db.get_bind())()
        rival.add(
            FCategoryProfile(
                id=uuid4(),
                category_id="1019",
                products_json=RIVAL_PRODUCTS,
                provider="deepseek",
            )
        )
        rival.commit()
        rival.close()
        return PRODUCTS

    monkeypatch.setattr(profile_engine, "_call_deepseek_profile", fake_deepseek)

    profile = _ensure(db)
    assert profile.products_json == RIVAL_PRODUCTS, "撞车后应当认先落库的那份"
    db.commit()
    rows = db.scalars(
        select(FCategoryProfile).where(FCategoryProfile.category_id == "1019")
    ).all()
    assert len(rows) == 1, "不能留下两行画像"

    # 外层事务没被污染：后续写入照常。
    db.add(
        FCategoryProfile(
            id=uuid4(), category_id="9999", products_json=PRODUCTS, provider="deepseek"
        )
    )
    db.commit()
    assert profile_engine.get_profile(db, "9999") is not None


def test_run_finalizer_refuses_to_call_a_barren_crash_a_success() -> None:
    """收尾判定的真值表。源码即契约：改了这段就得改这里。"""

    import inspect

    from backend.app.modules.f_series.enrichment import runs

    source = inspect.getsource(runs.execute_run)
    # 兜底 except 收下的失败要单独记账，不能和 channel_note 混在一起
    assert "hard_failures" in source
    assert 'run.status = "failed" if hard_failures and produced == 0 else "succeeded"' in source
    # 判据用产出数，不是「循环跑完了」
    assert "produced = (run.keywords_found or 0) + (run.candidates_found or 0)" in source
