"""收包时的自动检查(M0 冻结版第二部分第 1、2、4、6 节,第五部分 `jiagui pack verify`)。

顺序:核对 sha256 → 安全解包(只认普通文件、不许跳出目录、不许可执行、拒收代码文件和 refs/)→ MANIFEST.sha256 逐个对
→ 自己把 pack.yaml 转一遍,和包里的 pack.json 比「解析后的结构」(不比字节)→ lint(必填项、stage 和 provides 的组合、
id 不重复、适配题 0/1/2 都有说明、阈值、变体触发条件引用的题都在、progress 按 stage 填、docs 文件都在)→ core 版本。

要 PyYAML:只在 k-worker 里调(后端主镜像不装)。PyYAML 在函数里才 import,别的模块 import 这个文件不受影响。
任何一步不过 = 不收,不会自己生效。只改进度的判定(progress_only)也在这里,纯函数。
"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import tarfile
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "jiagui-pack/1"
STAGES = ("idea", "collecting", "planning", "usable", "retired")
ROUTING_ONLY_STAGES = ("idea", "collecting", "planning", "usable")
FULL_STAGES = ("usable", "retired")
PRECEDENT_VERDICTS = ("pass", "pass_predicted", "partial", "fail")
REJECT_EXT = (".py", ".pyc", ".js", ".mjs", ".cjs", ".sh", ".so", ".dylib", ".exe")
MAX_BYTES = 20 * 1024 * 1024  # 不含字体
MAX_TAR_BYTES = 200 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MANIFEST = "MANIFEST.sha256"
# 只改进度时允许变的:pack.json 里这三个键;文件里这三个
PROGRESS_KEYS = ("version", "progress", "changelog")
PROGRESS_FILES = ("pack.yaml", "pack.json", "CHANGELOG.md")


@dataclass
class Verified:
    ok: bool
    problems: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pack: dict[str, Any] | None = None
    manifest: dict[str, str] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)  # 包内相对路径 → 内容(不含顶层目录)
    top: str = ""
    sha256: str = ""

    def fail(self, code: str, text: str) -> None:
        self.ok = False
        self.problems.append({"code": code, "text": text})

    def summary(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems, "warnings": self.warnings, "top": self.top, "sha256": self.sha256, "files": sorted(self.files)}


# ---------------------------------------------------------------- YAML:只认能原样转成 JSON 的写法


def _yaml_events_problems(text: str) -> list[str]:
    """锚点 / 别名 / 显式标签 / 合并键 / 多文档 —— 冻结版第二部分第 1 节不许用的写法。"""
    import yaml  # noqa: PLC0415 —— 只有 k-worker 装了

    problems: list[str] = []
    docs = 0
    for ev in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(ev, yaml.DocumentStartEvent):
            docs += 1
        if isinstance(ev, yaml.AliasEvent):
            problems.append(f"用了别名 *{ev.anchor}")
        anchor = getattr(ev, "anchor", None)
        if anchor and not isinstance(ev, yaml.AliasEvent):
            problems.append(f"用了锚点 &{anchor}")
        # 解析事件里 tag 只在写了显式标签(!!str、!foo)时才有值;普通写法是 None
        if isinstance(ev, (yaml.ScalarEvent, yaml.MappingStartEvent, yaml.SequenceStartEvent)) and ev.tag is not None:
            problems.append(f"用了显式标签 {ev.tag}")
        if isinstance(ev, yaml.ScalarEvent) and ev.value == "<<" and ev.style is None:
            problems.append("用了合并键 <<")
    if docs > 1:
        problems.append(f"一个文件写了 {docs} 份文档")
    return sorted(set(problems))


def _plain_types(value: Any, path: str = "$") -> list[str]:
    """值只能是字符串、整数、小数、布尔、空值、列表、字典(键必须是字符串)。日期不加引号会被读成日期对象 → 报错。"""
    if value is None or isinstance(value, (str, bool, int, float)):
        return []
    if isinstance(value, list):
        out: list[str] = []
        for i, item in enumerate(value):
            out += _plain_types(item, f"{path}[{i}]")
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if not isinstance(k, str):
                out.append(f"{path} 的键 {k!r} 不是字符串")
                continue
            out += _plain_types(v, f"{path}.{k}")
        return out
    return [f"{path} 是 {type(value).__name__}(只许字符串/数/布尔/空/列表/字典;日期要加引号)"]


def _unique_key_loader():  # noqa: ANN202
    import yaml  # noqa: PLC0415

    class Loader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):  # noqa: ANN001, ANN202
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"键重复:{key!r}", key_node.start_mark)
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    return Loader


def load_yaml(text: str) -> tuple[Any, list[str]]:
    import yaml  # noqa: PLC0415

    problems = _yaml_events_problems(text)
    try:
        data = yaml.load(text, Loader=_unique_key_loader())  # noqa: S506 —— SafeLoader 子类,只多一条「键不许重复」
    except yaml.YAMLError as exc:
        return None, [*problems, f"YAML 读不了:{str(exc)[:200]}"]
    problems += _plain_types(data)
    if not problems:
        roundtrip = json.loads(json.dumps(data, ensure_ascii=False))
        if not strict_equal(roundtrip, data):
            problems.append("转成 JSON 再转回来,内容变了")
    return data, problems


def strict_equal(a: Any, b: Any) -> bool:
    """解析后的结构比较:键顺序不算,但 true 和 1、1 和 "1" 算不一样(Python 的 == 会把 True 当 1)。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


# ---------------------------------------------------------------- 解包


def _safe_members(tf: tarfile.TarFile, out: Verified) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    tops: set[str] = set()
    for m in tf.getmembers():
        name = m.name
        norm = posixpath.normpath(name)
        if name.startswith("/") or norm.startswith("..") or "/../" in f"/{norm}/" or "\\" in name:
            out.fail("E.PACK.UNSAFE_PATH", f"路径不安全:{name}")
            continue
        parts = norm.split("/")
        tops.add(parts[0])
        if m.isdir():
            continue
        if not m.isfile():
            out.fail("E.PACK.NOT_REGULAR", f"不是普通文件(链接/设备):{name}")
            continue
        if m.mode & 0o111:
            out.fail("E.PACK.EXECUTABLE", f"带可执行权限:{name}")
        rel = "/".join(parts[1:])
        if not rel:
            out.fail("E.PACK.LAYOUT", f"文件不在顶层目录里:{name}")
            continue
        if rel.lower().endswith(REJECT_EXT):
            out.fail("E.PACK.CODE_FILE", f"包里不许有代码文件:{rel}")
        if "refs" in rel.split("/")[:-1]:
            out.fail("E.PACK.REFS", f"包里不许有 refs/(别家的参考图):{rel}")
        fh = tf.extractfile(m)
        files[rel] = fh.read() if fh is not None else b""
    if len(tops) != 1:
        out.fail("E.PACK.LAYOUT", f"顶层目录应该只有一个,实际:{sorted(tops)}")
    else:
        out.top = next(iter(tops))
    size = sum(len(v) for k, v in files.items() if not k.startswith("fonts/"))
    if size > MAX_BYTES:
        out.fail("E.PACK.TOO_BIG", f"包体积(不含字体){size / 1024 / 1024:.1f} MB,上限 20 MB")
    return files


def _manifest(files: dict[str, bytes], out: Verified) -> dict[str, str]:
    raw = files.get(MANIFEST)
    if raw is None:
        out.fail("E.PACK.MANIFEST", "缺 MANIFEST.sha256")
        return {}
    listed: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line.strip())
        if not m:
            out.fail("E.PACK.MANIFEST", f"MANIFEST 这一行看不懂:{line[:80]}")
            continue
        path = m.group(2).strip()
        if path in listed:
            out.fail("E.PACK.MANIFEST", f"MANIFEST 里重复列了 {path}")
        listed[path] = m.group(1)
    actual = {k for k in files if k != MANIFEST}
    for path in sorted(actual - set(listed)):
        out.fail("E.PACK.MANIFEST", f"文件没列进 MANIFEST:{path}")
    for path in sorted(set(listed) - actual):
        out.fail("E.PACK.MANIFEST", f"MANIFEST 列了但包里没有:{path}")
    for path in sorted(actual & set(listed)):
        if hashlib.sha256(files[path]).hexdigest() != listed[path]:
            out.fail("E.PACK.MANIFEST", f"sha256 对不上:{path}")
    return listed


# ---------------------------------------------------------------- lint


def _ids(items: Any) -> list[str]:
    return [str(i.get("id")) for i in items or [] if isinstance(i, dict)]


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def core_satisfies(req: str, core: str | None) -> bool:
    """core: ">=2.0,<3" 这种。没有生效的基座 → False。"""
    if not core or not VERSION_RE.match(core):
        return False
    have = _version_tuple(core)
    for part in [p.strip() for p in (req or "").split(",") if p.strip()]:
        m = re.match(r"^(>=|<=|<|>|==)\s*(\d+(?:\.\d+){0,2})$", part)
        if not m:
            return False
        want = tuple(int(x) for x in m.group(2).split("."))
        want = want + (0,) * (3 - len(want))
        op = m.group(1)
        ok = {">=": have >= want, "<=": have <= want, "<": have < want, ">": have > want, "==": have == want}[op]
        if not ok:
            return False
    return True


def lint(pack: Any, *, files: dict[str, bytes], top: str, filename: str, out: Verified) -> None:
    if not isinstance(pack, dict):
        out.fail("E.PACK.LINT", "pack.json 不是对象")
        return
    if pack.get("schema") != SCHEMA:
        out.fail("E.PACK.LINT", f"schema 应该是 {SCHEMA},给的是 {pack.get('schema')!r}")
    for key in ("id", "name", "version", "stage", "provides", "core", "routing", "retired_ids", "changelog"):
        if key not in pack:
            out.fail("E.PACK.LINT", f"缺必填项 {key}")
    pid, version = str(pack.get("id") or ""), str(pack.get("version") or "")
    if not ID_RE.match(pid):
        out.fail("E.PACK.LINT", f"id {pid!r} 不合格(小写英文、数字、连字符)")
    if not VERSION_RE.match(version):
        out.fail("E.PACK.LINT", f"version {version!r} 不是 主.次.补")
    if top and top != f"{pid}-{version}":
        out.fail("E.PACK.LINT", f"顶层目录 {top} 和 id/版本 {pid}-{version} 对不上")
    if filename and filename.removesuffix(".tar.gz") != f"{pid}-{version}":
        out.fail("E.PACK.LINT", f"文件名 {filename} 和 id/版本 {pid}-{version} 对不上")
    stage, provides = pack.get("stage"), pack.get("provides")
    if stage not in STAGES:
        out.fail("E.PACK.LINT", f"stage {stage!r} 不认识")
    if provides == ["routing"]:
        if stage not in ROUTING_ONLY_STAGES:
            out.fail("E.PACK.LINT", f"只含选包的包不能是 stage={stage}")
    elif isinstance(provides, list) and sorted(provides) == ["images", "routing"]:
        if stage not in FULL_STAGES:
            out.fail("E.PACK.LINT", f"完整包只能是 usable / retired,给的是 {stage}")
    else:
        out.fail("E.PACK.LINT", f"provides {provides!r} 只能是 [routing] 或 [routing, images]")
    r = pack.get("routing") if isinstance(pack.get("routing"), dict) else {}
    if not r:
        out.fail("E.PACK.LINT", "routing 缺了或不是对象")
    if not _ids(r.get("categories")):
        out.fail("E.PACK.LINT", "routing.categories 是空的")
    all_ids: list[str] = []
    for key in ("categories", "not_for", "red_lines", "fit_questions", "variants", "precedents"):
        items = r.get(key) or []
        if not isinstance(items, list):
            out.fail("E.PACK.LINT", f"routing.{key} 不是列表")
            continue
        for item in items:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                out.fail("E.PACK.LINT", f"routing.{key} 里有条目没有 id")
        all_ids += _ids(items)
    dup = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if dup:
        out.fail("E.PACK.LINT", f"包内 id 重复:{dup}")
    reused = sorted(set(all_ids) & {str(x) for x in pack.get("retired_ids") or []})
    if reused:
        out.fail("E.PACK.LINT", f"复用了 retired_ids 里的 id:{reused}")
    if stage == "usable":
        for key in ("red_lines", "fit_questions", "thresholds", "variants", "precedents"):
            if not r.get(key):
                out.fail("E.PACK.LINT", f"可用的包 routing.{key} 不能空")
    q_ids = set(_ids(r.get("fit_questions")))
    for q in r.get("fit_questions") or []:
        scores = sorted(int(s.get("score", -1)) for s in q.get("scores") or [] if isinstance(s, dict) and isinstance(s.get("score"), int) and str(s.get("text") or "").strip())
        if scores != [0, 1, 2]:
            out.fail("E.PACK.LINT", f"适配题 {q.get('id')} 的 0、1、2 分没有都写说明")
    th = r.get("thresholds")
    if th is not None:
        use, var = (th or {}).get("use_pct"), (th or {}).get("variant_pct")
        if not (type(use) is int and type(var) is int and 0 <= var < use <= 100):
            out.fail("E.PACK.LINT", f"thresholds 要两个 0–100 的整数且 use_pct > variant_pct,给的是 {th}")
    for v in r.get("variants") or []:
        for t in v.get("triggers") or []:
            if str(t.get("q")) not in q_ids:
                out.fail("E.PACK.LINT", f"变体 {v.get('id')} 的触发条件引用了不存在的题 {t.get('q')}")
            if type(t.get("max_score")) is not int or not 0 <= t["max_score"] <= 2:
                out.fail("E.PACK.LINT", f"变体 {v.get('id')} 的 max_score 不是 0–2 的整数")
    for p in r.get("precedents") or []:
        if p.get("verdict") not in PRECEDENT_VERDICTS:
            out.fail("E.PACK.LINT", f"先例 {p.get('id')} 的 verdict {p.get('verdict')!r} 不认识")
    progress = pack.get("progress")
    if stage in ("collecting", "planning"):
        missing = [k for k in ("done", "doing", "next", "as_of") if not (isinstance(progress, dict) and progress.get(k))]
        if missing:
            out.fail("E.PACK.LINT", f"{stage} 的包 progress 缺 {missing}")
    elif stage == "idea":
        missing = [k for k in ("next", "as_of") if not (isinstance(progress, dict) and progress.get(k))]
        if missing:
            out.fail("E.PACK.LINT", f"idea 的包 progress 缺 {missing}")
    for doc in pack.get("docs") or []:
        if str(doc) not in files:
            out.fail("E.PACK.LINT", f"docs 里写了 {doc},包里没有")
    if str(pack.get("changelog") or "") and str(pack["changelog"]) not in files:
        out.fail("E.PACK.LINT", f"changelog 写了 {pack['changelog']},包里没有")


# ---------------------------------------------------------------- 总入口


def verify(data: bytes, *, expected_sha256: str, filename: str, active_core: str | None = None) -> Verified:
    out = Verified(ok=True)
    out.sha256 = hashlib.sha256(data).hexdigest()
    if out.sha256 != (expected_sha256 or "").strip().lower():
        out.fail("E.PACK.SHA256", f"sha256 对不上:算出 {out.sha256[:12]}…,给的 {(expected_sha256 or '')[:12]}…")
        return out
    if len(data) > MAX_TAR_BYTES:
        out.fail("E.PACK.TOO_BIG", "压缩包太大")
        return out
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            files = _safe_members(tf, out)
    except (tarfile.TarError, OSError, EOFError) as exc:
        out.fail("E.PACK.TAR", f"解不开:{str(exc)[:160]}")
        return out
    out.files = files
    out.manifest = _manifest(files, out)
    if "pack.yaml" not in files or "pack.json" not in files:
        out.fail("E.PACK.LAYOUT", "包里要同时有 pack.yaml 和 pack.json")
        return out
    try:
        packed = json.loads(files["pack.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        out.fail("E.PACK.JSON", f"pack.json 读不了:{str(exc)[:160]}")
        return out
    try:
        from_yaml, yaml_problems = load_yaml(files["pack.yaml"].decode("utf-8"))
    except UnicodeDecodeError:
        out.fail("E.PACK.YAML", "pack.yaml 不是 UTF-8")
        return out
    for p in yaml_problems:
        out.fail("E.PACK.YAML", p)
    if from_yaml is not None and not strict_equal(from_yaml, packed):
        out.fail("E.PACK.YAML_JSON", "pack.yaml 转出来的结构和包里的 pack.json 不一致(两边解析器读出的东西不一样),拒收")
    out.pack = packed
    lint(packed, files=files, top=out.top, filename=filename, out=out)
    if isinstance(packed, dict) and "images" in (packed.get("provides") or []) and not core_satisfies(str(packed.get("core") or ""), active_core):
        out.fail("E.PACK.CORE", f"完整包要基座 {packed.get('core')},控制台现在生效的基座是 {active_core or '没有'}(M1 交付后才有)")
    return out


def progress_only(old_pack: dict[str, Any] | None, new_pack: dict[str, Any], old_manifest: dict[str, str] | None, new_manifest: dict[str, str]) -> bool:
    """只改了进度(老板 10-31:只改进度不用批),两条都满足才算(11 第 1.2c 节):
    1. pack.json 除了 version、progress、changelog 以外完全一样;
    2. MANIFEST 里除了 pack.yaml、pack.json、CHANGELOG.md 以外没有任何文件变化(风格卡改了字也不算)。"""
    if not isinstance(old_pack, dict) or not isinstance(old_manifest, dict):
        return False
    strip = lambda p: {k: v for k, v in p.items() if k not in PROGRESS_KEYS}  # noqa: E731
    if not strict_equal(strip(old_pack), strip(new_pack)):
        return False
    rest = lambda m: {k: v for k, v in m.items() if k not in PROGRESS_FILES}  # noqa: E731
    return rest(old_manifest) == rest(new_manifest)


def changed_ids(old_pack: dict[str, Any] | None, new_pack: dict[str, Any]) -> dict[str, list[str]]:
    """和上一版比:加了、删了、文字改了的条目 id(给待生效卡写「改了哪些条」)。"""
    def index(pack: dict[str, Any] | None) -> dict[str, str]:
        r = (pack or {}).get("routing") or {}
        out: dict[str, str] = {}
        for key in ("categories", "not_for", "red_lines", "fit_questions", "variants", "precedents"):
            for item in r.get(key) or []:
                if isinstance(item, dict) and item.get("id") is not None:
                    out[str(item["id"])] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        for key in ("thresholds", "scoring_note", "summary"):
            if key in r:
                out[key] = json.dumps(r[key], ensure_ascii=False, sort_keys=True)
        return out

    old, new = index(old_pack), index(new_pack)
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(k for k in set(old) & set(new) if old[k] != new[k]),
    }
