"""注册表的命令行(在 k-worker 里跑:那里有 PyYAML,也挂着持久卷)。

第一阶段走交接目录(交接 09 第 2b 节):老板在 Mac 那边同意后,Mac 把包放进交接目录,这边用一条命令登记成「待生效」;
苏青禾再给老板发「风格包待生效」卡,批了才生效。宿主机上用 scripts/jiagui_register_pack.sh 包一层(从 .sha256 读校验和、把包从标准输入喂进来)。

  register --filename <id>-<版本>.tar.gz --sha256 <hex> [--by 谁]  < 包     登记(检查不过 = 驳回,退出码 2)
  list                                                                 列出全部版本
  rollback <包 id> [--reason 原因] [--by 谁]                            生效的那版退回上一个停用版本
"""

from __future__ import annotations

import argparse
import json
import sys

from ....db.session import SessionLocal
from . import registry


def _print(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jiagui")
    sub = ap.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--filename", required=True)
    reg.add_argument("--sha256", required=True)
    reg.add_argument("--by", default="cli")
    sub.add_parser("list")
    rb = sub.add_parser("rollback")
    rb.add_argument("pack_id")
    rb.add_argument("--reason", default="")
    rb.add_argument("--by", default="cli")
    a = ap.parse_args(argv)

    db = SessionLocal()
    try:
        if a.cmd == "register":
            data = sys.stdin.buffer.read()
            try:
                out = registry.register(db, data=data, sha256=a.sha256, filename=a.filename, by=a.by)
            except registry.RegistryError as exc:
                db.rollback()
                _print({"ok": False, "code": exc.code, "message": exc.message})
                return 2
            db.commit()
            _print({"ok": out.ok, "created": out.created, **registry.describe(out.row), "report": out.report})
            return 0 if out.ok else 2
        if a.cmd == "list":
            _print([registry.describe(r) for r in registry.rows(db)])
            return 0
        if a.cmd == "rollback":
            try:
                old, new = registry.rollback(db, a.pack_id, by=a.by, reason=a.reason)
            except registry.RegistryError as exc:
                db.rollback()
                _print({"ok": False, "code": exc.code, "message": exc.message})
                return 2
            db.commit()
            _print({"ok": True, "from": old.version, "to": new.version})
            return 0
    finally:
        db.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
