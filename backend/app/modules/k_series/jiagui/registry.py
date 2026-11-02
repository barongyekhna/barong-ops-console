"""风格包注册表(M0 冻结版第五部分;交接 09 第 2b 节)。

- 登记(register):收包检查全过 → 文件放进持久卷 packs/<id>/<版本>/(放进去就不再改)→ 一行「待生效」。
  检查没过 → 一行「驳回」(驳回人 system,原因 = 检查报告),文件不落盘;同版本修好再发可以覆盖这行。
- 生效(activate):老板批了待生效卡才调;只改进度的新版本由苏青禾自动调(老板 10-31:只改进度不用批)。
  同一个包 id 只留一个生效,旧的那版变「停用」。
- 退回(rollback):把生效指回上一个停用的版本,一步完成。已经出过图的品照旧按它记下的版本。
- 视图(view):给选包用——每个生效的包的 pack.json,按 stage 排好。

这个文件不 import PyYAML(登记那一步才在函数里用 packfile),后端、苏青禾、k-worker 都能 import。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .models import ACTIVE, PENDING, REJECTED, RETIRED, JiaguiCoreVersion, JiaguiPack, JiaguiPackCheck

_X = SKIP_ORG_DATA_ISOLATION
DEFAULT_ROOT = "/var/lib/barong/k-media/jiagui"
SYSTEM = "system"
STAGE_ORDER = {"usable": 0, "planning": 1, "collecting": 1, "idea": 2, "retired": 9}


class RegistryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def root() -> Path:
    return Path(os.getenv("JIAGUI_ROOT") or DEFAULT_ROOT)


def pack_dir(pack_id: str, version: str) -> Path:
    return root() / "packs" / pack_id / version


# ---------------------------------------------------------------- 读


def active_core(db: Session) -> str | None:
    return db.scalar(select(JiaguiCoreVersion.version).where(JiaguiCoreVersion.status == ACTIVE), execution_options=_X)


def get(db: Session, pack_id: str, version: str) -> JiaguiPack | None:
    return db.scalar(select(JiaguiPack).where(JiaguiPack.pack_id == pack_id, JiaguiPack.version == version), execution_options=_X)


def active_row(db: Session, pack_id: str) -> JiaguiPack | None:
    return db.scalar(select(JiaguiPack).where(JiaguiPack.pack_id == pack_id, JiaguiPack.status == ACTIVE), execution_options=_X)


def rows(db: Session, *, status: str | None = None) -> list[JiaguiPack]:
    q = select(JiaguiPack).order_by(JiaguiPack.pack_id, JiaguiPack.created_at)
    if status:
        q = q.where(JiaguiPack.status == status)
    return list(db.scalars(q, execution_options=_X))


def view(db: Session, *, replace: JiaguiPack | None = None) -> list[dict[str, Any]]:
    """选包用的注册表视图:每个生效的包一份 pack.json。replace = 把这一行当成生效版本(待生效卡的「装了它会怎样」)。"""
    packs = {r.pack_id: r for r in rows(db, status=ACTIVE)}
    if replace is not None:
        packs[replace.pack_id] = replace
    out = [dict(r.pack_json) for r in packs.values() if isinstance(r.pack_json, dict)]
    return sorted(out, key=lambda p: (STAGE_ORDER.get(str(p.get("stage")), 5), str(p.get("id"))))


def fingerprint(registry_view: list[dict[str, Any]]) -> str:
    """注册表的指纹:哪些包、哪一版、什么 stage。选包记录存它,注册表一变就知道记录旧了。"""
    raw = json.dumps(sorted((str(p.get("id")), str(p.get("version")), str(p.get("stage"))) for p in registry_view), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def read_doc(pack_id: str, version: str, name: str, *, limit: int = 20000) -> str | None:
    """包里的文档(风格卡)给模型当背景。只认包内相对路径,跳不出包目录。"""
    base = pack_dir(pack_id, version).resolve()
    path = (base / name).resolve()
    if base not in path.parents or not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def checks(db: Session, row: JiaguiPack) -> list[JiaguiPackCheck]:
    return list(db.scalars(select(JiaguiPackCheck).where(JiaguiPackCheck.pack_row_id == row.id).order_by(JiaguiPackCheck.id), execution_options=_X))


def add_check(db: Session, row: JiaguiPack, *, kind: str, ok: bool, result: dict[str, Any], cost_usd: float = 0.0) -> JiaguiPackCheck:
    check = JiaguiPackCheck(pack_row_id=row.id, kind=kind, ok=ok, result=result, cost_usd=round(float(cost_usd or 0), 4))
    db.add(check)
    db.flush()
    return check


# ---------------------------------------------------------------- 登记


def _store_files(pack_id: str, version: str, files: dict[str, bytes], manifest: dict[str, str]) -> Path:
    """原子落盘:先写临时目录再改名。目录已经在了:内容一样就当成功(重放同一条命令),不一样就拒绝(放进去就不再改)。"""
    target = pack_dir(pack_id, version)
    if target.exists():
        existing = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob("*") if p.is_file()}
        wanted = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
        if existing != wanted:
            raise RegistryError("E.PACK.DIR_EXISTS", f"{target} 已经有一份内容不同的包,版本放进去就不再改,要改请发新版本")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=target.parent))
    try:
        for rel, data in files.items():
            dest = (tmp / rel).resolve()
            if tmp.resolve() not in dest.parents:
                raise RegistryError("E.PACK.UNSAFE_PATH", f"路径不安全:{rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o444)
        tmp.chmod(0o755)  # mkdtemp 建的是 0700;苏青禾的 worker 也要读风格卡
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target


@dataclass
class Registered:
    row: JiaguiPack
    created: bool
    ok: bool
    report: dict[str, Any]


def register(db: Session, *, data: bytes, sha256: str, filename: str, by: str) -> Registered:
    """收一个包:检查 → 落盘 → 待生效(或驳回)。同一个包同一版本、同一个 sha256 再登记一次 = 什么都不做。"""
    from . import packfile  # noqa: PLC0415 —— 要 PyYAML,只在 k-worker 里

    result = packfile.verify(data, expected_sha256=sha256, filename=filename, active_core=active_core(db))
    pack = result.pack if isinstance(result.pack, dict) else {}
    pack_id = str(pack.get("id") or filename.removesuffix(".tar.gz").rsplit("-", 1)[0])[:64]
    version = str(pack.get("version") or (filename.removesuffix(".tar.gz").rsplit("-", 1) + ["?"])[1])[:32]
    existing = get(db, pack_id, version)
    if existing is not None:
        if existing.sha256 == result.sha256 and existing.status != REJECTED:
            return Registered(row=existing, created=False, ok=True, report={"note": "同一个包已经登记过了", "status": existing.status})
        if existing.status != REJECTED or existing.decided_by != SYSTEM:
            raise RegistryError("E.PACK.VERSION_TAKEN", f"{pack_id} {version} 已经登记过(状态 {existing.status}),内容不同;版本号用过就不能再用,请发新版本")
    report = result.summary()
    previous = active_row(db, pack_id)
    row = existing or JiaguiPack(pack_id=pack_id, version=version)
    row.name = str(pack.get("name") or "")[:120]
    row.stage = str(pack.get("stage") or "")[:16]
    row.provides = list(pack.get("provides") or [])
    row.core_req = str(pack.get("core") or "")[:64]
    row.sha256 = result.sha256
    row.source = filename[:200]
    row.pack_json = pack
    row.manifest = result.manifest
    row.registered_by = by[:64]
    row.previous_version = previous.version if previous is not None else None
    if result.ok:
        try:
            _store_files(pack_id, version, result.files, result.manifest)
        except RegistryError as exc:
            result.fail(exc.code, exc.message)
            report = result.summary()
    if result.ok:
        row.status = PENDING
        row.progress_only = previous is not None and packfile.progress_only(previous.pack_json, pack, previous.manifest, result.manifest)
        report["changed_ids"] = packfile.changed_ids(previous.pack_json if previous is not None else None, pack)
        row.decided_by = row.decision_reason = row.decided_at = None
    else:
        row.status = REJECTED
        row.progress_only = False
        row.decided_by = SYSTEM
        row.decision_reason = "自动检查没过:" + ";".join(p["text"] for p in result.problems)[:2000]
        row.decided_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    report["progress_only"] = row.progress_only
    report["previous_version"] = row.previous_version
    add_check(db, row, kind="verify", ok=result.ok, result=report)
    return Registered(row=row, created=existing is None, ok=result.ok, report=report)


# ---------------------------------------------------------------- 生效 / 驳回 / 退回


def activate(db: Session, row: JiaguiPack, *, by: str, reason: str | None = None) -> JiaguiPack | None:
    """待生效 → 生效;同一个包原来生效的那版 → 停用。返回被换下来的那一行。"""
    if row.status != PENDING:
        raise RegistryError("E.PACK.NOT_PENDING", f"{row.pack_id} {row.version} 状态是 {row.status},不是待生效")
    now = datetime.now(UTC)
    old = active_row(db, row.pack_id)
    if old is not None:
        old.status = RETIRED
        db.add(old)
        db.flush()  # 先让旧的下来,部分唯一索引才放得进新的
    db.execute(
        update(JiaguiPack)
        .where(JiaguiPack.id == row.id, JiaguiPack.status == PENDING)
        .values(status=ACTIVE, decided_by=by[:64], decision_reason=reason, decided_at=now),
        execution_options=_X,
    )
    db.flush()
    db.refresh(row)
    return old


def reject(db: Session, row: JiaguiPack, *, by: str, reason: str) -> None:
    if row.status != PENDING:
        raise RegistryError("E.PACK.NOT_PENDING", f"{row.pack_id} {row.version} 状态是 {row.status},不是待生效")
    row.status = REJECTED
    row.decided_by = by[:64]
    row.decision_reason = reason
    row.decided_at = datetime.now(UTC)
    db.add(row)
    db.flush()


def _version_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def rollback(db: Session, pack_id: str, *, by: str, reason: str = "") -> tuple[JiaguiPack, JiaguiPack]:
    """生效的那版 → 停用;比它旧的、最近停用的那版 → 生效。返回 (换下来的, 换上去的)。"""
    current = active_row(db, pack_id)
    if current is None:
        raise RegistryError("E.PACK.NO_ACTIVE", f"{pack_id} 现在没有生效的版本")
    older = [r for r in rows(db, status=RETIRED) if r.pack_id == pack_id and _version_key(r.version) < _version_key(current.version)]
    if not older:
        raise RegistryError("E.PACK.NO_OLDER", f"{pack_id} 没有更旧的停用版本可以退回")
    target = max(older, key=lambda r: _version_key(r.version))
    now = datetime.now(UTC)
    current.status = RETIRED
    current.decision_reason = f"退回到 {target.version}" + (f":{reason}" if reason else "")
    db.add(current)
    db.flush()
    target.status = ACTIVE
    target.decided_by = by[:64]
    target.decided_at = now
    target.decision_reason = f"从 {current.version} 退回" + (f":{reason}" if reason else "")
    db.add(target)
    db.flush()
    return current, target


def describe(row: JiaguiPack) -> dict[str, Any]:
    pack = row.pack_json if isinstance(row.pack_json, dict) else {}
    r = pack.get("routing") or {}
    return {
        "pack_id": row.pack_id,
        "version": row.version,
        "name": row.name,
        "status": row.status,
        "stage": row.stage,
        "provides": row.provides,
        "categories": [f"{c.get('id')} {c.get('text')}" for c in r.get("categories") or [] if isinstance(c, dict)],
        "not_for": [f"{c.get('id')} {c.get('text')}" for c in r.get("not_for") or [] if isinstance(c, dict)],
        "progress": pack.get("progress"),
        "previous_version": row.previous_version,
        "progress_only": row.progress_only,
        "card_ref": row.card_ref,
        "sha256": row.sha256,
        "decided_by": row.decided_by,
        "decision_reason": row.decision_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
