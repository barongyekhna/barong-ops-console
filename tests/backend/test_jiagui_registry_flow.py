"""风格包注册表 + 苏青禾选包(M2a)真库流程。integration。

- 交接目录的四个包登记 → 待生效 → 她发卡(还没有品选过包)→ 老板批三张、驳一张 → 生效视图;
- 检查不过 = 驳回、不落盘,同版本修好再发可以;已登记的版本换内容 = 拒收;
- 只改进度的新版本自动生效不发卡,跟着每天那条提醒说一句;改了品类的要发卡;退回一步回到旧版;库里一个包只能一个生效;
- 待生效卡上的试算:已经选过包的品按「装了它以后」重判,结论变了点出来;
- 流水线:价格卡发出去、注册表定了就选包(Opus 打桩)→ 缺包卡按缺的包合并;注册表变了 / 价动了一美元以上 → 重判。
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

pytest.importorskip("yaml")

from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.models.user import User  # noqa: E402
from backend.app.modules.agent_series.suqinghe import cards, pipeline, style_packs, style_route  # noqa: E402
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier, SqhRouteRecord  # noqa: E402
from backend.app.modules.k_series.jiagui import registry  # noqa: E402
from backend.app.modules.k_series.jiagui.models import JiaguiCoreVersion, JiaguiPack, JiaguiPackCheck  # noqa: E402
from backend.app.services.data_isolation import without_org_data_isolation  # noqa: E402
from tests.backend.test_suqinghe_cards_api import people  # noqa: E402,F401
from tests.backend.test_suqinghe_dossiers_api import clean  # noqa: E402,F401
from tests.backend.test_suqinghe_pipeline import built  # noqa: E402,F401

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent / "fixtures" / "jiagui"
HANDOFF = ["sunny-pop-1.0.1", "household-outdoor-tools-0.1.0", "warm-home-0.1.0", "dark-hardcore-0.1.0"]


def _wipe() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        for model in (JiaguiPackCheck, JiaguiPack, JiaguiCoreVersion, SqhRouteRecord):
            db.execute(delete(model))
        db.commit()


@pytest.fixture
def reg(people, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JIAGUI_ROOT", str(tmp_path / "jiagui"))
    _wipe()
    yield people
    _wipe()


def _real(name: str) -> tuple[bytes, str]:
    return (FIX / f"{name}.tar.gz").read_bytes(), (FIX / f"{name}.tar.gz.sha256").read_text().split()[0]


def _files(name: str) -> dict[str, bytes]:
    data, _ = _real(name)
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                fh = tf.extractfile(m)
                out[m.name.split("/", 1)[1]] = fh.read() if fh else b""
    return out


def _pack(top: str, files: dict[str, bytes]) -> tuple[bytes, str]:
    files = {k: v for k, v in files.items() if k != "MANIFEST.sha256"}
    files["MANIFEST.sha256"] = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(files.items())).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size, info.mode = len(data), 0o644
            tf.addfile(info, io.BytesIO(data))
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def _household(version: str, *, doing: str, extra_category: str | None = None) -> tuple[bytes, str]:
    """在真包 0.1.0 上改版本号和进度(可选加一个品类),yaml 和 json 一起改。"""
    files = _files("household-outdoor-tools-0.1.0")
    pack = json.loads(files["pack.json"])
    pack["version"], pack["progress"]["doing"] = version, doing
    y = files["pack.yaml"].decode()
    y = y.replace("version: 0.1.0", f"version: {version}").replace(
        "  doing: 等老板拍板决策稿 v1（包名和 id、户外装备的边界、画面方向、人物、热水棒主图等 10 条）", f"  doing: {doing}"
    )
    if extra_category:
        pack["routing"]["categories"].append({"id": "C11", "text": extra_category})
        y = y.replace("    - {id: C10, text: 12V 电池平台}\n", f"    - {{id: C10, text: 12V 电池平台}}\n    - {{id: C11, text: {extra_category}}}\n")
    files["pack.json"] = (json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    files["pack.yaml"] = y.encode()
    files["CHANGELOG.md"] = files["CHANGELOG.md"] + f"\n## {version}\n\n- 进度:{doing}\n".encode()
    return _pack(f"household-outdoor-tools-{version}", files)


def _register(name: str, blob: tuple[bytes, str] | None = None) -> registry.Registered:
    data, sha = blob or _real(name)
    with without_org_data_isolation(), SessionLocal() as db:
        out = registry.register(db, data=data, sha256=sha, filename=f"{name}.tar.gz", by="test")
        db.commit()
        db.refresh(out.row)
        db.expunge(out.row)
        return out


def _tick(call=None) -> dict[str, Any] | None:
    with without_org_data_isolation(), SessionLocal() as db:
        return style_packs.tick(db, call=call)


def _decide(ref: str, decision: str, owner: int, reason: str | None = None) -> dict[str, Any]:
    with without_org_data_isolation(), SessionLocal() as db:
        out = cards.decide_card(db, card_id=ref, decision=decision, actor=db.get(User, owner), channel="web", reason=reason)
        db.commit()
        return out.execution or {}


def _card(ref: str) -> SqhCard:
    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        db.expunge(card)
        return card


def _status() -> dict[str, str]:
    with without_org_data_isolation(), SessionLocal() as db:
        return {f"{r.pack_id}-{r.version}": r.status for r in registry.rows(db)}


def _go_live(names: list[str], owner: int) -> None:
    for name in names:
        assert _register(name).ok
    for _ in names:
        out = _tick()
        assert out and out.get("card")
        _decide(out["card"], "approve", owner)


def test_handoff_packs_go_pending_then_the_boss_approves(reg, tmp_path) -> None:
    owner = reg["owner"]
    for name in HANDOFF:
        out = _register(name)
        assert out.ok and out.created and out.row.status == "pending", out.report
        stored = tmp_path / "jiagui" / "packs" / out.row.pack_id / out.row.version
        assert (stored / "pack.json").is_file() and not ((stored / "pack.json").stat().st_mode & 0o222)  # 放进去就不再改
        assert stored.stat().st_mode & 0o005 == 0o005  # 别的 worker(苏青禾)也读得到风格卡
    assert not _register("sunny-pop-1.0.1").created  # 同一个包再登记一次:什么都不做
    with without_org_data_isolation(), SessionLocal() as db:
        assert registry.view(db) == [] and style_packs.has_pending(db)
    refs = []
    for _ in HANDOFF:
        out = _tick()
        assert out and out["card"]
        refs.append(out["card"])
    assert _tick() is None  # 每个包只发一张
    sunny = _card(refs[0])
    assert sunny.kind == style_packs.PACK_CARD_KIND and sunny.title == "风格包待生效:「阳光冲击」1.0.1"
    assert "现在还没有品选过包" in sunny.conclusion and "管:C01 饮料零食" in sunny.conclusion and "F2" in sunny.why  # 带着 CHANGELOG
    assert sunny.evidence["checks"] == [{"kind": "verify", "ok": True}, {"kind": "replay", "ok": True}]
    for ref in refs[:3]:
        assert "生效了" in _decide(ref, "approve", owner)["note"]
    assert "不生效" in _decide(refs[3], "reject", owner, reason="暗调硬核先不登记")["note"]
    assert _status() == {"dark-hardcore-0.1.0": "rejected", "household-outdoor-tools-0.1.0": "active", "sunny-pop-1.0.1": "active", "warm-home-0.1.0": "active"}
    with without_org_data_isolation(), SessionLocal() as db:
        view = registry.view(db)
        assert [p["id"] for p in view] == ["sunny-pop", "household-outdoor-tools", "warm-home"] and not style_packs.has_pending(db)
        assert "R07" in json.dumps(view, ensure_ascii=False)
        assert "暗调硬核先不登记" in db.scalar(select(JiaguiPack.decision_reason).where(JiaguiPack.pack_id == "dark-hardcore"))


def test_a_pack_that_fails_the_check_is_rejected_and_never_stored(reg, tmp_path) -> None:
    files = _files("dark-hardcore-0.1.0")
    pack = json.loads(files["pack.json"])
    pack["routing"]["categories"][0]["text"] = "和 yaml 不一样"
    bad = _pack("dark-hardcore-0.1.0", {**files, "pack.json": json.dumps(pack, ensure_ascii=False).encode()})
    out = _register("dark-hardcore-0.1.0", bad)
    assert not out.ok and out.row.status == "rejected" and out.row.decided_by == "system" and "pack.yaml" in out.row.decision_reason
    assert not (tmp_path / "jiagui" / "packs" / "dark-hardcore").exists()
    assert _tick() is None  # 不发卡
    fixed = _register("dark-hardcore-0.1.0")  # 同版本修好再发:覆盖那行
    assert fixed.ok and fixed.row.status == "pending" and fixed.row.id == out.row.id
    other = _pack("dark-hardcore-0.1.0", {**_files("dark-hardcore-0.1.0"), "CHANGELOG.md": b"# changed\n"})
    with without_org_data_isolation(), SessionLocal() as db, pytest.raises(registry.RegistryError) as exc:
        registry.register(db, data=other[0], sha256=other[1], filename="dark-hardcore-0.1.0.tar.gz", by="test")
    assert exc.value.code == "E.PACK.VERSION_TAKEN"


def test_progress_only_goes_live_quietly_other_changes_need_a_card_and_rollback_works(reg) -> None:
    owner = reg["owner"]
    _go_live(["household-outdoor-tools-0.1.0"], owner)
    up = _register("household-outdoor-tools-0.1.1", _household("0.1.1", doing="老板拍板了决策稿,开始写包"))
    assert up.ok and up.row.progress_only and up.row.previous_version == "0.1.0"
    out = _tick()
    assert out == {"pack": "household-outdoor-tools", "version": "0.1.1", "auto": True}
    assert _status() == {"household-outdoor-tools-0.1.0": "retired", "household-outdoor-tools-0.1.1": "active"}
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.scalar(select(SqhCard.id).where(SqhCard.kind == style_packs.PACK_CARD_KIND, SqhCard.status == "pending")) is None
        notes = style_packs.progress_notes(db, since=None)
        assert notes == ["风格包「家务户外工具」进度更新到 0.1.1"]
        assert style_packs.progress_notes(db, since=datetime.now(UTC).astimezone(style_packs.LA).date()) == []
    from backend.app.modules.agent_series.suqinghe.worker_main import reminder_text

    assert "进度更新到 0.1.1,已自动生效,不用你批" in reminder_text(3, notes=notes)
    # 加了一个品类 → 不是只改进度,要卡
    more = _register("household-outdoor-tools-0.2.0", _household("0.2.0", doing="加了品类", extra_category="电动割草机"))
    assert more.ok and not more.row.progress_only
    out = _tick()
    card = _card(out["card"])
    assert card.title == "风格包待生效:「家务户外工具」0.1.1→0.2.0" and "加了 C11" in card.conclusion
    _decide(out["card"], "approve", owner)
    # 退回一步:0.2.0 → 0.1.1
    with without_org_data_isolation(), SessionLocal() as db:
        old, new = registry.rollback(db, "household-outdoor-tools", by="test", reason="新品类先不要")
        db.commit()
        assert (old.version, new.version) == ("0.2.0", "0.1.1")
    assert _status()["household-outdoor-tools-0.1.1"] == "active" and _status()["household-outdoor-tools-0.2.0"] == "retired"
    # 库里兜底:同一个包两个生效 → 拒
    with without_org_data_isolation(), SessionLocal() as db, pytest.raises(IntegrityError):
        db.execute(update(JiaguiPack).where(JiaguiPack.pack_id == "household-outdoor-tools").values(status="active"))
        db.flush()


# ---------------------------------------------------------------- 选包:打桩的「Opus」按骨架填


def _skeleton_of(prompt: str) -> dict[str, Any]:
    return json.loads(prompt.split("## 答卷\n", 1)[1].split("\n\n## 这个品的资料", 1)[0])


def _filler(*, hits: tuple[str, ...] = (), scores: list[int] | None = None, progress: dict[str, str] | None = None, seen: list[str] | None = None):
    def call(db, prompt: str) -> dict[str, Any]:
        if seen is not None:
            seen.append(prompt)
        skel = _skeleton_of(prompt)
        skel["product"].update(category="电钻电池", audience="DIY 的人", main_scene="车库")
        for j in skel["packs"].values():
            j["category_match"] = {"reason": "-", "id": None}
            for rid, cell in j["red_lines"].items():
                cell.update(reason="-", hit=rid in hits)
            for cell, s in zip(j["scores"].values(), scores or [2] * len(j["scores"]), strict=True):
                cell.update(reason="-", score=s)
            for cell in j["precedents"].values():
                cell.update(reason="-", same_kind=False)
            j["variant_pick"] = {"reason": "-", "id": None}
        for pid, cell in skel["other_packs"].items():
            cat = (progress or {}).get(pid)
            cell.update(reason="-", match=cat is not None, category=cat)
        return skel

    return call


def test_replay_on_the_pending_card_points_out_products_whose_route_changes(reg) -> None:
    owner = reg["owner"]
    _go_live(["sunny-pop-1.0.1", "household-outdoor-tools-0.1.0"], owner)
    with without_org_data_isolation(), SessionLocal() as db:
        view = registry.view(db)
        result = style_route.judge(db, "中文标题:12V 电钻电池", view, product_id="PTB-001", price="$29.99", call=_filler(hits=("R07",), progress={"household-outdoor-tools": "C10"}), docs={})
        assert result["status"] == "pass"
        style_route.save(db, dossier_id=999001, sku="PTB-001", result=result, facts="中文标题:12V 电钻电池", price={"low": 29.99, "high": 29.99, "source": "card"})
        db.commit()
    # 新版本:试算时「Opus」改判成不踩红线、满分 → 结论从缺包变成用阳光冲击
    assert _register("household-outdoor-tools-0.2.0", _household("0.2.0", doing="加品类", extra_category="电池")).ok
    out = _tick(call=_filler())
    card = _card(out["card"])
    assert "装了它以后选包结果会变的品:PTB-001 缺包,等「家务户外工具」(规划中) → 用「阳光冲击」(12/12)" in card.conclusion
    assert card.evidence["replay"]["products"][0]["changed"] is True
    with without_org_data_isolation(), SessionLocal() as db:
        replays = list(db.scalars(select(SqhRouteRecord).where(SqhRouteRecord.purpose == "replay")))
        assert len(replays) == 1 and style_route.current(db, 999001).decision_kind == "missing"  # 试算不算数


def _plant_price_card(dossier_id: int, price: float) -> str:
    with without_org_data_isolation(), SessionLocal() as db:
        card, _ = cards.create_card(
            db,
            dedupe_key=f"k_price:test:{dossier_id}:{price}",
            kind=pipeline.PRICE_CARD_KIND,
            title=f"定价 ${price}",
            conclusion="测试",
            evidence={"variants": [{"key": "v1", "include": True, "price": price}, {"key": "v2", "include": False, "price": 99.0}]},
        )
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "pipeline": {**(dossier.draft.get("pipeline") or {}), "price": {"card_ref": card.ref}}}
        db.commit()
        return card.ref


def _route_view(dossier_id: int) -> dict[str, bool]:
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        product = next(p for d, p in pipeline.managed(db) if d.id == dossier_id)
        v = pipeline.build_view(db, dossier, product)
        return {"due": v.route_due, "hold": v.route_hold}


def test_pipeline_routes_after_the_price_card_and_merges_missing_packs(reg, built, monkeypatch) -> None:  # noqa: F811
    dossier_id, product_id, owner = built
    assert _route_view(dossier_id) == {"due": False, "hold": True}  # 注册表空着:不判,作图那段等着
    _go_live(["sunny-pop-1.0.1", "household-outdoor-tools-0.1.0"], owner)
    assert _register("dark-hardcore-0.1.0").ok
    _plant_price_card(dossier_id, 29.99)
    assert _route_view(dossier_id) == {"due": False, "hold": True}  # 还有待生效的包:等注册表定下来
    _decide(_tick()["card"], "approve", owner)
    assert _route_view(dossier_id) == {"due": True, "hold": True}

    seen: list[str] = []
    monkeypatch.setattr(style_route, "_default_call", _filler(hits=("R07",), progress={"household-outdoor-tools": "C09"}, seen=seen))
    out = pipeline.run_step(dossier_id, "route")
    assert out["ok"] and "缺包,等「家务户外工具」(规划中)" in out["note"] and "缺包卡 #" in out["note"], out
    assert "售价:$29.99(价格卡上的建议价" in seen[0] and "1688" not in seen[0].split("## 这个品的资料", 1)[1]
    with without_org_data_isolation(), SessionLocal() as db:
        rec = style_route.current(db, dossier_id)
        assert rec.decision_kind == "missing" and rec.missing_key == "in_progress:household-outdoor-tools" and rec.price == {"low": 29.99, "high": 29.99, "source": "card"}
        missing = db.scalar(select(SqhCard).where(SqhCard.kind == style_route.MISSING_CARD_KIND))
        assert missing.status == "pending" and missing.title.startswith("缺风格包:1 个品在等「家务户外工具」")
        assert "先不上架、等包做好;价格、文案我照常往下做" in missing.conclusion and "R07" in missing.why
        assert style_route.raise_missing_cards(db) == []  # 同一个缺包、同样多的品:不重复发
        db.commit()
    assert _route_view(dossier_id) == {"due": False, "hold": True}
    # 老板改价改到 $39.99:价格带那题可能变 → 重判
    _plant_price_card(dossier_id, 39.99)
    assert _route_view(dossier_id)["due"] is True
    monkeypatch.setattr(style_route, "_default_call", _filler())
    assert "用「阳光冲击」(12/12)" in pipeline.run_step(dossier_id, "route")["note"]
    assert _route_view(dossier_id) == {"due": False, "hold": False}
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.scalar(select(SqhCard.status).where(SqhCard.kind == style_route.MISSING_CARD_KIND)) == "stale"  # 没品在等了,缺包卡作废
        assert style_route.chosen(style_route.current(db, dossier_id)) == {"pack": "sunny-pop", "version": "1.0.1", "variant": None}
    # 注册表变了(新版本生效)→ 还没排图的品重判
    assert _register("household-outdoor-tools-0.1.1", _household("0.1.1", doing="写包中")).ok
    assert _tick()["auto"] is True
    assert _route_view(dossier_id) == {"due": True, "hold": True}
