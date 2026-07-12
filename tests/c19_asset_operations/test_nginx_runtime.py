from __future__ import annotations

import contextlib
import http.client
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "deploy/nginx/ops.barongyekhna.com.conf.template"


class _RecordingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(("127.0.0.1", 0), handler)
        self.records: list[dict[str, Any]] = []


class _QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _record(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.server.records.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        return body


class _AuthHandler(_QuietHandler):
    def do_GET(self) -> None:
        self._record()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _GatewayHandler(_QuietHandler):
    def _reply(self, *, include_body: bool = True) -> None:
        self._record()
        body = f"gateway:{self.command}:{self.path}".encode()
        self.send_response(201 if self.command == "PUT" else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_PUT(self) -> None:
        self._reply()

    def do_GET(self) -> None:
        self._reply()

    def do_HEAD(self) -> None:
        self._reply(include_body=False)


class _FrontendHandler(_QuietHandler):
    def do_GET(self) -> None:
        self._record()
        if self.path in {
            "/api/backend/c19/events",
            "/api/backend/c19/moments/events",
        }:
            body = b"event: ready\ndata: {\"next_cursor\":null}\n\n"
            content_type = "text/event-stream"
        else:
            body = b"frontend-fallback"
            content_type = "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def _mock_server(
    handler: type[BaseHTTPRequestHandler],
) -> Iterator[_RecordingServer]:
    server = _RecordingServer(handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _derive_runtime_config(
    tmp_path: Path,
    *,
    listen_port: int,
    auth_port: int,
    gateway_port: int,
    frontend_port: int,
) -> Path:
    document = TEMPLATE.read_text(encoding="utf-8")
    maps = re.findall(r"(?ms)^map .*?^}\n?", document)
    servers = re.findall(r"(?ms)^server \{\n.*?^}\n?", document)
    assert len(maps) == 1, "the runtime test expects the template's upgrade map"
    assert len(servers) == 2, "the runtime test expects HTTP and HTTPS server blocks"

    server = servers[1]
    original_listeners = (
        "    listen 443 ssl http2;\n"
        "    listen [::]:443 ssl http2;\n"
    )
    assert original_listeners in server
    server = server.replace(
        original_listeners,
        f"    listen 127.0.0.1:{listen_port};\n",
        1,
    )
    server = re.sub(
        r"(?m)^    ssl_certificate(?:_key)? [^;]+;\n",
        "",
        server,
    )

    upstream_replacements = {
        "http://127.0.0.1:8000": f"http://127.0.0.1:{auth_port}",
        "http://127.0.0.1:8092": f"http://127.0.0.1:{gateway_port}",
        "http://127.0.0.1:3000": f"http://127.0.0.1:{frontend_port}",
    }
    for original, replacement in upstream_replacements.items():
        assert original in server
        server = server.replace(original, replacement)

    nginx_root = tmp_path / "nginx"
    nginx_root.mkdir()
    for name in ("body", "proxy"):
        (nginx_root / name).mkdir()

    def quoted(path: Path) -> str:
        return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'

    config = "\n".join(
        (
            "worker_processes 1;",
            f"pid {quoted(nginx_root / 'nginx.pid')};",
            f"error_log {quoted(nginx_root / 'error.log')} notice;",
            "events { worker_connections 64; }",
            "http {",
            "    access_log off;",
            f"    client_body_temp_path {quoted(nginx_root / 'body')};",
            f"    proxy_temp_path {quoted(nginx_root / 'proxy')};",
            maps[0],
            server,
            "}",
            "",
        )
    )
    config_path = nginx_root / "nginx.conf"
    config_path.write_text(config, encoding="utf-8")
    return config_path


def _request(
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        response_body = response.read()
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response_body,
        )
    finally:
        connection.close()


def _wait_for_nginx(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"isolated nginx exited with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("isolated nginx did not bind its temporary port")


def test_nginx_template_routes_and_credentials_at_runtime(tmp_path: Path) -> None:
    nginx = shutil.which("nginx")
    if nginx is None:
        pytest.skip("nginx binary is unavailable; isolated template runtime test skipped")

    try:
        listen_port = _unused_local_port()
    except PermissionError:
        pytest.skip("local sockets are blocked by this test sandbox")
    with (
        _mock_server(_AuthHandler) as auth,
        _mock_server(_GatewayHandler) as gateway,
        _mock_server(_FrontendHandler) as frontend,
    ):
        config = _derive_runtime_config(
            tmp_path,
            listen_port=listen_port,
            auth_port=auth.server_port,
            gateway_port=gateway.server_port,
            frontend_port=frontend.server_port,
        )
        prefix = str(config.parent) + "/"
        syntax = subprocess.run(
            [nginx, "-t", "-p", prefix, "-c", str(config)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert syntax.returncode == 0, syntax.stderr

        process = subprocess.Popen(
            [
                nginx,
                "-p",
                prefix,
                "-c",
                str(config),
                "-g",
                "daemon off; master_process off;",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_nginx(process, listen_port)
            upload_ticket = "A" * 43
            download_ticket = "B" * 43
            upload_path = f"/api/backend/c19-assets/u/{upload_ticket}"
            download_path = f"/api/backend/c19-assets/d/{download_ticket}"
            browser_headers = {
                "Cookie": "barong_session=session-secret",
                "Authorization": "Bearer browser-secret",
                "X-Session-Token": "legacy-session-secret",
            }

            status, _, body = _request(
                listen_port,
                "PUT",
                upload_path,
                body=b"unbuffered-upload",
                headers={**browser_headers, "Content-Type": "application/octet-stream"},
            )
            assert status == 201
            assert body == f"gateway:PUT:{upload_path}".encode()

            status, _, body = _request(
                listen_port,
                "GET",
                download_path,
                headers=browser_headers,
            )
            assert status == 200
            assert body == f"gateway:GET:{download_path}".encode()

            status, response_headers, body = _request(
                listen_port,
                "HEAD",
                download_path,
                headers=browser_headers,
            )
            assert status == 200
            assert int(response_headers["content-length"]) > 0
            assert body == b""

            auth_count = len(auth.records)
            gateway_count = len(gateway.records)
            for malformed in (
                "/api/backend/c19-assets",
                f"/api/backend/c19-assets/u/{'A' * 42}",
                f"/api/backend/c19-assets/d/{'B' * 44}",
                f"/api/backend/c19-assets/d/{'C' * 42}.",
                f"/api/c19-assets/u/{upload_ticket}",
                f"/api/c19-assets/d/{download_ticket}",
            ):
                status, _, body = _request(
                    listen_port,
                    "GET",
                    malformed,
                    headers=browser_headers,
                )
                assert status == 404
                assert body != b"frontend-fallback"
            assert len(auth.records) == auth_count
            assert len(gateway.records) == gateway_count

            expected_transfers = (
                ("PUT", upload_path),
                ("GET", download_path),
                ("HEAD", download_path),
            )
            assert len(auth.records) == len(expected_transfers)
            for record, (original_method, original_uri) in zip(
                auth.records, expected_transfers, strict=True
            ):
                assert record["method"] == "GET"
                assert record["path"] == "/api/app/c19/assets/transfers/authorize"
                assert record["headers"]["cookie"] == browser_headers["Cookie"]
                assert "authorization" not in record["headers"]
                assert "x-session-token" not in record["headers"]
                assert record["headers"]["x-c19-transfer-method"] == original_method
                assert record["headers"]["x-c19-transfer-uri"] == original_uri
                assert record["body"] == b""

            assert len(gateway.records) == len(expected_transfers)
            for record, (method, path) in zip(
                gateway.records, expected_transfers, strict=True
            ):
                assert (record["method"], record["path"]) == (method, path)
                for credential in ("cookie", "authorization", "x-session-token"):
                    assert credential not in record["headers"]

            # Valid byte requests terminate at the gateway, and malformed byte
            # paths terminate at Nginx. Neither class reaches the Next fallback.
            assert frontend.records == []

            sse_cookie = "barong_session=sse-session-secret"
            status, response_headers, body = _request(
                listen_port,
                "GET",
                "/api/backend/c19/events",
                headers={"Cookie": sse_cookie, "Accept": "text/event-stream"},
            )
            assert status == 200
            assert response_headers["content-type"].startswith("text/event-stream")
            assert b"event: ready" in body
            assert frontend.records[-1]["path"] == "/api/backend/c19/events"
            assert frontend.records[-1]["headers"]["cookie"] == sse_cookie

            status, response_headers, body = _request(
                listen_port,
                "GET",
                "/api/backend/c19/moments/events",
                headers={"Cookie": sse_cookie, "Accept": "text/event-stream"},
            )
            assert status == 200
            assert response_headers["content-type"].startswith("text/event-stream")
            assert b"event: ready" in body
            assert frontend.records[-1]["path"] == "/api/backend/c19/moments/events"
            assert frontend.records[-1]["headers"]["cookie"] == sse_cookie
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr is not None:
                stderr = process.stderr.read().decode(errors="replace")
                assert process.returncode in (0, -15), stderr
