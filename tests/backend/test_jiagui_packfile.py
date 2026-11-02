"""收包检查(M0 冻结版第二部分第 1、2、4、6 节;第五部分 verify / 只改进度):真包全过,坏包各拦在该拦的地方。unit。

fixtures/jiagui/ 里是交接 12、14 送来的五个真包(原样拷贝,带 .sha256)。"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("yaml")

from backend.app.modules.k_series.jiagui import packfile  # noqa: E402

pytestmark = pytest.mark.unit

FIX = Path(__file__).parent / "fixtures" / "jiagui"
REAL = ["sunny-pop-1.0.0", "sunny-pop-1.0.1", "warm-home-0.1.0", "household-outdoor-tools-0.1.0", "dark-hardcore-0.1.0"]


def real(name: str) -> tuple[bytes, str]:
    data = (FIX / f"{name}.tar.gz").read_bytes()
    sha = (FIX / f"{name}.tar.gz.sha256").read_text().split()[0]
    return data, sha


def files_of(name: str) -> dict[str, bytes]:
    data, sha = real(name)
    return packfile.verify(data, expected_sha256=sha, filename=f"{name}.tar.gz").files


def build(top: str, files: dict[str, bytes], *, manifest: bool = True, mode: int = 0o644, extra: list[tarfile.TarInfo] | None = None) -> tuple[bytes, str]:
    files = dict(files)
    if manifest:
        files["MANIFEST.sha256"] = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(files.items()) if k != "MANIFEST.sha256").encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tf.addfile(info, io.BytesIO(b"") if info.isfile() else None)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def rebuilt(name: str, **changes: bytes | None) -> tuple[bytes, str]:
    files = {k: v for k, v in files_of(name).items() if k != "MANIFEST.sha256"}
    for k, v in changes.items():
        k = k.replace("__", ".").replace("_slash_", "/")
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    return build(name, files)


def codes(out: packfile.Verified) -> set[str]:
    return {p["code"] for p in out.problems}


@pytest.mark.parametrize("name", REAL)
def test_the_real_packs_from_the_mac_pass(name: str) -> None:
    data, sha = real(name)
    out = packfile.verify(data, expected_sha256=sha, filename=f"{name}.tar.gz")
    assert out.ok, out.problems
    assert out.top == name and out.pack["id"] == name.rsplit("-", 1)[0] and out.pack["provides"] == ["routing"]
    assert set(out.manifest) == set(out.files) - {"MANIFEST.sha256"}


def test_sha256_must_match_the_sidecar() -> None:
    data, _ = real("dark-hardcore-0.1.0")
    out = packfile.verify(data, expected_sha256="0" * 64, filename="dark-hardcore-0.1.0.tar.gz")
    assert not out.ok and codes(out) == {"E.PACK.SHA256"}


def test_yaml_and_json_must_describe_the_same_pack() -> None:
    pack = json.loads(files_of("dark-hardcore-0.1.0")["pack.json"])
    pack["routing"]["categories"][0]["text"] = "偷偷改了"
    data, sha = rebuilt("dark-hardcore-0.1.0", pack__json=json.dumps(pack, ensure_ascii=False).encode())
    out = packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz")
    assert "E.PACK.YAML_JSON" in codes(out)
    # 只是键顺序、缩进不同 → 不算差异
    pack = json.loads(files_of("dark-hardcore-0.1.0")["pack.json"])
    data, sha = rebuilt("dark-hardcore-0.1.0", pack__json=json.dumps(dict(reversed(list(pack.items()))), ensure_ascii=False, indent=4).encode())
    assert packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz").ok


def test_manifest_must_list_every_file_with_the_right_hash() -> None:
    files = {k: v for k, v in files_of("dark-hardcore-0.1.0").items()}
    files["CHANGELOG.md"] = b"changed after manifest\n"
    data, sha = build("dark-hardcore-0.1.0", files, manifest=False)
    assert "E.PACK.MANIFEST" in codes(packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz"))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"tools_slash_x__py": b"print(1)\n"}, "E.PACK.CODE_FILE"),
        ({"refs_slash_a__png": b"\x89PNG"}, "E.PACK.REFS"),
    ],
)
def test_code_files_and_refs_are_refused(change: dict[str, bytes], code: str) -> None:
    data, sha = rebuilt("dark-hardcore-0.1.0", **change)
    assert code in codes(packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz"))


def test_unsafe_members_are_refused() -> None:
    files = {k: v for k, v in files_of("dark-hardcore-0.1.0").items() if k != "MANIFEST.sha256"}
    link = tarfile.TarInfo("dark-hardcore-0.1.0/evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    data, sha = build("dark-hardcore-0.1.0", files, extra=[link])
    assert "E.PACK.NOT_REGULAR" in codes(packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz"))
    escape = tarfile.TarInfo("dark-hardcore-0.1.0/../../escape.md")
    escape.size = 0
    data, sha = build("dark-hardcore-0.1.0", files, extra=[escape])
    assert "E.PACK.UNSAFE_PATH" in codes(packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz"))
    data, sha = build("dark-hardcore-0.1.0", files, mode=0o755)
    assert "E.PACK.EXECUTABLE" in codes(packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz"))


def test_yaml_only_the_json_compatible_subset() -> None:
    assert packfile.load_yaml("a: 1\nb: '2026-10-31'\n")[1] == []
    assert any("date" in p for p in packfile.load_yaml("a: 2026-10-31\n")[1])  # 日期没加引号
    assert any("锚点" in p for p in packfile.load_yaml("a: &x 1\nb: *x\n")[1])
    assert any("显式标签" in p for p in packfile.load_yaml("a: !!str 1\n")[1])
    assert any("合并键" in p for p in packfile.load_yaml("a: {b: 1}\nc:\n  <<: {b: 2}\n")[1])
    assert any("键重复" in p for p in packfile.load_yaml("a: 1\na: 2\n")[1])
    assert any("份文档" in p for p in packfile.load_yaml("a: 1\n---\nb: 2\n")[1])
    assert packfile.strict_equal({"a": 1}, {"a": 1.0}) and not packfile.strict_equal({"a": True}, {"a": 1}) and not packfile.strict_equal(["1"], [1])


def _lint(pack: dict[str, Any], files: dict[str, bytes] | None = None) -> list[str]:
    out = packfile.Verified(ok=True)
    packfile.lint(pack, files=files or {"CHANGELOG.md": b"", "style-card.md": b""}, top=f"{pack.get('id')}-{pack.get('version')}", filename="", out=out)
    return [p["text"] for p in out.problems]


def test_lint_catches_what_the_freeze_spec_lists() -> None:
    sunny = json.loads(files_of("sunny-pop-1.0.1")["pack.json"])
    assert _lint(sunny) == []
    bad = json.loads(json.dumps(sunny))
    bad["stage"] = "retired"  # 只含选包的包不能是 retired
    assert any("只含选包" in p for p in _lint(bad))
    bad = json.loads(json.dumps(sunny))
    bad["routing"]["thresholds"] = {"use_pct": 50, "variant_pct": 70}
    assert any("thresholds" in p for p in _lint(bad))
    bad = json.loads(json.dumps(sunny))
    bad["routing"]["variants"][0]["triggers"] = [{"q": "F9", "max_score": 1}]
    assert any("F9" in p for p in _lint(bad))
    bad = json.loads(json.dumps(sunny))
    bad["routing"]["fit_questions"][0]["scores"] = bad["routing"]["fit_questions"][0]["scores"][:2]
    assert any("F1" in p and "0、1、2" in p for p in _lint(bad))
    bad = json.loads(json.dumps(sunny))
    bad["routing"]["red_lines"].append({"id": "C01", "text": "撞了品类 id"})
    assert any("id 重复" in p for p in _lint(bad))
    bad = json.loads(json.dumps(sunny))
    bad["retired_ids"] = ["R07"]
    assert any("retired_ids" in p for p in _lint(bad))
    tools = json.loads(files_of("household-outdoor-tools-0.1.0")["pack.json"])
    assert _lint(tools) == []
    del tools["progress"]["doing"]
    assert any("progress 缺" in p for p in _lint(tools))


def test_full_packs_need_a_live_core_and_routing_only_packs_do_not() -> None:
    assert packfile.core_satisfies(">=2.0,<3", "2.0.0") and packfile.core_satisfies(">=2.0,<3", "2.9.1")
    assert not packfile.core_satisfies(">=2.0,<3", "3.0.0") and not packfile.core_satisfies(">=2.0,<3", None)
    pack = json.loads(files_of("dark-hardcore-0.1.0")["pack.json"])
    pack["provides"], pack["stage"] = ["routing", "images"], "usable"
    yaml_text = files_of("dark-hardcore-0.1.0")["pack.yaml"].decode().replace("provides: [routing]", "provides: [routing, images]").replace("stage: idea", "stage: usable")
    data, sha = rebuilt("dark-hardcore-0.1.0", pack__json=json.dumps(pack, ensure_ascii=False).encode(), pack__yaml=yaml_text.encode())
    out = packfile.verify(data, expected_sha256=sha, filename="dark-hardcore-0.1.0.tar.gz")
    assert "E.PACK.CORE" in codes(out)


def _verified(name: str) -> packfile.Verified:
    data, sha = real(name)
    return packfile.verify(data, expected_sha256=sha, filename=f"{name}.tar.gz")


def test_progress_only_needs_both_json_and_files_unchanged() -> None:
    v0 = _verified("household-outdoor-tools-0.1.0")
    new = json.loads(json.dumps(v0.pack))
    new["version"], new["progress"]["doing"] = "0.1.1", "老板拍板了决策稿,开始写包"
    manifest = dict(v0.manifest)
    manifest["pack.json"] = manifest["pack.yaml"] = manifest["CHANGELOG.md"] = "f" * 64
    assert packfile.progress_only(v0.pack, new, v0.manifest, manifest)
    # 改了品类 → 不算
    worse = json.loads(json.dumps(new))
    worse["routing"]["categories"].append({"id": "C11", "text": "新加的"})
    assert not packfile.progress_only(v0.pack, worse, v0.manifest, manifest)
    # 风格卡改了字 → 不算
    assert not packfile.progress_only(v0.pack, new, v0.manifest, {**manifest, "style-card.md": "e" * 64})
    # 真实的 sunny 1.0.0 → 1.0.1 改了 F2 和风格卡 → 不算,改了的条目点得出来
    a, b = _verified("sunny-pop-1.0.0"), _verified("sunny-pop-1.0.1")
    assert not packfile.progress_only(a.pack, b.pack, a.manifest, b.manifest)
    assert packfile.changed_ids(a.pack, b.pack) == {"added": [], "removed": [], "changed": ["F2"]}
