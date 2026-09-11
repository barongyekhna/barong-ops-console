#!/usr/bin/env python3
"""RD 系列 · TURN 中转体检。

**这个脚本存在的唯一理由是:coturn 配置没生效的时候,从外面完全看不出来。**

2026-09-11 首次部署踩过一次:配置文件权限写成了 `600 root:root`,coturn 以低权用户
`turnserver` 运行、读不了自己的配置,静默回落到默认值,于是变成一台开放中转。而
`systemctl is-active` 显示 `active`,STUN Binding 也照样成功——一切看起来都正常。

唯一能发现的办法就是这里做的事:发一个**不带任何凭据**的 Allocate 请求。它必须被拒。
如果它拿到了中转地址,那就是开放中转,立刻停服务。

用法:
    .venv/bin/python scripts/rd_turn_probe.py 45.76.173.147
    .venv/bin/python scripts/rd_turn_probe.py 45.76.173.147 64.177.117.249

退出码 0 = 该拒的拒了;非 0 = 有节点不对劲。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import socket
import struct
import sys

MAGIC = 0x2112A442
ALLOCATE = 0x0003
ALLOCATE_SUCCESS = 0x0103
ALLOCATE_ERROR = 0x0113
# 配置里写死的中转端口范围。分配到范围外的端口 = 配置没被读进去。
RELAY_PORT_MIN = 50000
RELAY_PORT_MAX = 50100


def _attr(kind: int, value: bytes) -> bytes:
    padding = (4 - len(value) % 4) % 4
    return struct.pack("!HH", kind, len(value)) + value + b"\x00" * padding


def _message(msg_type: int, txid: bytes, attrs: list[bytes], key: bytes | None = None) -> bytes:
    body = b"".join(attrs)
    if key is None:
        return struct.pack("!HHI12s", msg_type, len(body), MAGIC, txid) + body
    # MESSAGE-INTEGRITY 覆盖到它自己之前,但长度字段要把它那 24 字节算进去
    header = struct.pack("!HHI12s", msg_type, len(body) + 24, MAGIC, txid)
    digest = hmac.new(key, header + body, hashlib.sha1).digest()
    return header + body + _attr(0x0008, digest)


def _parse(data: bytes) -> tuple[int, dict[int, bytes]]:
    msg_type, length, _magic, _txid = struct.unpack("!HHI12s", data[:20])
    body, offset, attrs = data[20 : 20 + length], 0, {}
    while offset + 4 <= len(body):
        kind, size = struct.unpack("!HH", body[offset : offset + 4])
        attrs[kind] = body[offset + 4 : offset + 4 + size]
        offset += 4 + size + ((4 - size % 4) % 4)
    return msg_type, attrs


def _xor_address(value: bytes) -> tuple[str, int]:
    port = struct.unpack("!H", value[2:4])[0] ^ (MAGIC >> 16)
    raw = struct.unpack("!I", value[4:8])[0] ^ MAGIC
    return socket.inet_ntoa(struct.pack("!I", raw)), port


def check(host: str, port: int = 3478, timeout: float = 8.0) -> list[str]:
    """返回问题清单。空列表 = 这台节点没问题。"""
    problems: list[str] = []
    transport = _attr(0x0019, struct.pack("!BBBB", 17, 0, 0, 0))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(_message(ALLOCATE, os.urandom(12), [transport]), (host, port))
        msg_type, attrs = _parse(sock.recvfrom(4096)[0])
    except socket.timeout:
        return [f"{host}:{port} 没有应答(服务没起,或者端口没放行)"]
    finally:
        sock.close()

    if msg_type == ALLOCATE_SUCCESS:
        relayed = attrs.get(0x0016)
        where = ""
        if relayed and len(relayed) >= 8:
            address, relay_port = _xor_address(relayed)
            where = f" → {address}:{relay_port}"
            if not RELAY_PORT_MIN <= relay_port <= RELAY_PORT_MAX:
                problems.append(
                    f"{host} 分配的中转端口 {relay_port} 在 "
                    f"{RELAY_PORT_MIN}-{RELAY_PORT_MAX} 之外,说明配置根本没被读进去"
                )
        problems.append(
            f"{host} 是开放中转:不带凭据的 Allocate 拿到了中转地址{where}。"
            f"检查 /etc/turnserver.conf 是否为 root:turnserver 640,然后重启 coturn"
        )
        return problems

    if msg_type != ALLOCATE_ERROR:
        return [f"{host} 回了意外的应答类型 0x{msg_type:04x}"]

    code = attrs.get(0x0009, b"")
    number = code[2] * 100 + code[3] if len(code) >= 4 else 0
    if number != 401:
        problems.append(f"{host} 拒了,但错误码是 {number},预期 401")
    if 0x0014 not in attrs:
        problems.append(f"{host} 的质询里没有 REALM,配置可能不完整")
    return problems


def main(argv: list[str]) -> int:
    hosts = argv[1:] or ["45.76.173.147", "64.177.117.249"]
    failed = False
    for host in hosts:
        problems = check(host)
        if problems:
            failed = True
            for line in problems:
                print(f"✗ {line}")
        else:
            print(f"✓ {host} 正确要求认证(401 + REALM),不是开放中转")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
