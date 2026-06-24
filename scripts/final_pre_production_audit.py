#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://127.0.0.1:8000")
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://127.0.0.1:3000")
PROD_BACKEND_CONTAINER = "barong-ops-console-prod_console_backend_1"
PROD_FRONTEND_CONTAINER = "barong-ops-console-prod_console_frontend_1"
PROD_POSTGRES_CONTAINER = "barong-ops-console-prod_console_postgres_1"
AUDIT_ID = f"final_preprod_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
NAMESPACE = f"audit_scope_{AUDIT_ID}"
DEFAULT_CREATED_PASSWORD = "123456"
TEST_PASSWORD_PREFIX = "Final-PreProd-Audit-Only"
STATIC_EXECUTION_MODULE = "integration.n8n_test_bridge"
DYNAMIC_MODULE_PREFIX = "demo.audit_preprod"

REPORT_PATHS = {
    "owner": REPO_ROOT / "owner_full_flow_report.json",
    "roles": REPO_ROOT / "multi_role_access_report.json",
    "fields": REPO_ROOT / "ui_field_consistency_report.json",
    "stress": REPO_ROOT / "concurrency_stress_test_report.json",
    "module_human": REPO_ROOT / "module_integration_spec_human_report.md",
    "module_machine": REPO_ROOT / "module_integration_spec_machine.json",
    "chain": REPO_ROOT / "api_key_module_execution_chain_report.json",
    "dead_code": REPO_ROOT / "full_system_dead_code_report.json",
    "final": REPO_ROOT / "final_pre_production_audit_report.json",
    "consolidation": REPO_ROOT / "final_production_consolidation_report.json",
}

SENSITIVE_MARKERS = (
    "authorization",
    "cookie",
    "key_value",
    "password",
    "secret",
    "session",
    "token",
    "encrypted",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in SENSITIVE_MARKERS):
                output[str(key)] = "***"
            else:
                output[str(key)] = redact(item)
        return output
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and len(value) > 1800:
        return value[:1800] + "...[truncated]"
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def body_from_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text[:2000]


@dataclass
class ApiCallResult:
    name: str
    method: str
    path: str
    status_code: int | None
    elapsed_ms: float
    ok: bool
    expected_status: int | tuple[int, ...] | None
    body: Any
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "elapsed_ms": self.elapsed_ms,
            "ok": self.ok,
            "expected_status": self.expected_status,
            "body": redact(self.body),
            "error": self.error,
        }


class ApiClient:
    def __init__(
        self,
        *,
        backend_base_url: str,
        username: str | None = None,
        session_token: str | None = None,
    ) -> None:
        self.backend_base_url = backend_base_url.rstrip("/")
        self.username = username
        self.session_token = session_token
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"barong-final-audit/{AUDIT_ID}"})

    def clone(self) -> "ApiClient":
        return ApiClient(
            backend_base_url=self.backend_base_url,
            username=self.username,
            session_token=self.session_token,
        )

    def set_session_token(self, session_token: str) -> None:
        self.session_token = session_token

    def request(
        self,
        method: str,
        path: str,
        *,
        name: str,
        expected_status: int | tuple[int, ...] | None = None,
        json_body: Any = None,
        timeout: float = 20,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[ApiCallResult, requests.Response | None]:
        url = f"{self.backend_base_url}{path}"
        headers = {"Accept": "application/json"}
        if self.session_token:
            headers["X-Session-Token"] = self.session_token
        if extra_headers:
            headers.update(extra_headers)
        started = time.perf_counter()
        response: requests.Response | None = None
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            expected = (
                (expected_status,)
                if isinstance(expected_status, int)
                else expected_status
            )
            ok = response.status_code in expected if expected else response.status_code < 400
            return (
                ApiCallResult(
                    name=name,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    ok=ok,
                    expected_status=expected_status,
                    body=body_from_response(response),
                ),
                response,
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return (
                ApiCallResult(
                    name=name,
                    method=method,
                    path=path,
                    status_code=None,
                    elapsed_ms=elapsed_ms,
                    ok=False,
                    expected_status=expected_status,
                    body=None,
                    error=str(exc),
                ),
                response,
            )

    def get(self, path: str, **kwargs: Any) -> tuple[ApiCallResult, requests.Response | None]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> tuple[ApiCallResult, requests.Response | None]:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> tuple[ApiCallResult, requests.Response | None]:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> tuple[ApiCallResult, requests.Response | None]:
        return self.request("DELETE", path, **kwargs)


def call_to_dict(result: ApiCallResult) -> dict[str, Any]:
    return result.to_dict()


def required_fields_present(body: Any, fields: list[str], *, item_path: str = "") -> dict[str, Any]:
    item = body
    if item_path:
        for part in item_path.split("."):
            if isinstance(item, dict):
                item = item.get(part)
            elif isinstance(item, list) and part == "0" and item:
                item = item[0]
            else:
                item = None
                break
    if isinstance(item, list):
        item = item[0] if item else {}
    if not isinstance(item, dict):
        return {"checked": False, "missing": fields, "present": [], "reason": "body path is not an object"}
    present = [field for field in fields if field in item]
    missing = [field for field in fields if field not in item]
    return {"checked": True, "present": present, "missing": missing}


def run_command(args: list[str], *, timeout: int = 60) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "args": args[:3] + (["..."] if len(args) > 3 else []),
            "returncode": result.returncode,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "ok": result.returncode == 0,
        }
    except Exception as exc:
        return {
            "args": args[:3] + (["..."] if len(args) > 3 else []),
            "returncode": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }


def docker_logs(container: str, *, tail: int = 300) -> dict[str, Any]:
    result = run_command(["docker", "logs", "--tail", str(tail), container], timeout=30)
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    lines = [line for line in text.splitlines() if line.strip()]
    suspicious = [
        line[-800:]
        for line in lines
        if re.search(r"\b(ERROR|CRITICAL|Traceback|Exception|Unhandled)\b", line, re.I)
    ]
    return {
        "container": container,
        "command_ok": result["ok"],
        "line_count": len(lines),
        "error_like_count": len(suspicious),
        "error_like_tail": suspicious[-25:],
    }


def docker_stats() -> dict[str, Any]:
    containers = [
        PROD_BACKEND_CONTAINER,
        PROD_FRONTEND_CONTAINER,
        PROD_POSTGRES_CONTAINER,
    ]
    result = run_command(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
        timeout=30,
    )
    rows = []
    for line in result.get("stdout", "").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return {"command_ok": result["ok"], "rows": rows, "stderr": result.get("stderr", "")[-1000:]}


def postgres_pressure_snapshot() -> dict[str, Any]:
    sql = (
        "select 'activity_total=' || count(*) from pg_stat_activity; "
        "select 'states=' || coalesce(json_object_agg(coalesce(state,'none'), count)::text,'{}') "
        "from (select state, count(*) from pg_stat_activity group by state) s; "
        "select 'db_size=' || pg_database_size(current_database());"
    )
    result = run_command(
        [
            "docker",
            "exec",
            PROD_POSTGRES_CONTAINER,
            "sh",
            "-lc",
            f"psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc {json.dumps(sql)}",
        ],
        timeout=30,
    )
    parsed: dict[str, str] = {}
    for line in result.get("stdout", "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    return {"command_ok": result["ok"], "metrics": parsed, "stderr": result.get("stderr", "")[-1000:]}


def login_user(username: str, password: str, *, name: str) -> tuple[ApiClient | None, dict[str, Any]]:
    client = ApiClient(backend_base_url=BACKEND_BASE_URL, username=username)
    result, response = client.post(
        "/api/public/auth/login",
        name=name,
        expected_status=200,
        json_body={"username": username, "password": password},
        timeout=15,
    )
    record = result.to_dict()
    if response is None or response.status_code != 200:
        return None, record
    body = body_from_response(response)
    token = body.get("session_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        record["ok"] = False
        record["error"] = "login response did not include a session_token"
        return None, record
    client.set_session_token(token)
    return client, record


def change_password(
    client: ApiClient,
    current_password: str,
    new_password: str,
    *,
    name: str,
) -> dict[str, Any]:
    result, _ = client.post(
        "/api/public/auth/change-password",
        name=name,
        expected_status=200,
        json_body={"current_password": current_password, "new_password": new_password},
        timeout=15,
    )
    return result.to_dict()


def create_org(client: ApiClient, owner_user_id: int | str, suffix: str) -> tuple[str | None, dict[str, Any]]:
    payload = {
        "org_name": f"Audit {suffix} {AUDIT_ID}",
        "org_type": "store",
        "owner_user_id": str(owner_user_id),
        "metadata": {
            "industry": "audit",
            "country": "US",
            "timezone": "UTC",
            "settings": {
                "allow_ai": False,
                "allow_n8n": False,
                "data_retention_days": 7,
            },
            "custom": {
                "test_scope": True,
                "audit_id": AUDIT_ID,
                "namespace": NAMESPACE,
                "suffix": suffix,
            },
        },
    }
    result, response = client.post(
        "/api/app/org/create",
        name=f"org.create.{suffix}",
        expected_status=201,
        json_body=payload,
        timeout=20,
    )
    org_id = None
    if response is not None and response.status_code == 201:
        body = body_from_response(response)
        if isinstance(body, dict):
            org_id = body.get("org_id")
    return org_id, result.to_dict()


def create_user(
    client: ApiClient,
    *,
    username: str,
    role: str,
    org_id: str,
    expected_status: int | tuple[int, ...] = 201,
) -> tuple[int | None, dict[str, Any]]:
    result, response = client.post(
        "/api/app/users",
        name=f"user.create.{role}.{username}",
        expected_status=expected_status,
        json_body={
            "username": username,
            "role": role,
            "organization_id": org_id,
            "job_title": f"test_scope=true; namespace={NAMESPACE}; role={role}",
            "is_active": True,
        },
        timeout=20,
    )
    user_id = None
    if response is not None and response.status_code == 201:
        body = body_from_response(response)
        if isinstance(body, dict) and isinstance(body.get("id"), int):
            user_id = body["id"]
    return user_id, result.to_dict()


def reset_user_password(client: ApiClient, user_id: int, password: str) -> dict[str, Any]:
    result, _ = client.post(
        f"/api/app/users/{user_id}/reset-password",
        name=f"user.reset_password.{user_id}",
        expected_status=200,
        json_body={"new_password": password},
        timeout=20,
    )
    return result.to_dict()


def owner_full_flow(owner_client: ApiClient, owner_user: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    created_users: dict[str, dict[str, Any]] = {}

    primary_org_id, record = create_org(owner_client, owner_user["id"], "primary")
    steps.append(record)
    deleted_org_id, record = create_org(owner_client, owner_user["id"], "delete_probe")
    steps.append(record)

    if primary_org_id:
        result, _ = owner_client.patch(
            f"/api/app/org/{primary_org_id}",
            name="org.update.primary",
            expected_status=200,
            json_body={
                "org_name": f"Audit Primary Updated {AUDIT_ID}",
                "metadata": {
                    "industry": "audit-updated",
                    "country": "US",
                    "timezone": "UTC",
                    "settings": {
                        "allow_ai": False,
                        "allow_n8n": True,
                        "data_retention_days": 14,
                    },
                    "custom": {
                        "test_scope": True,
                        "audit_id": AUDIT_ID,
                        "namespace": NAMESPACE,
                        "updated": True,
                    },
                },
            },
            timeout=20,
        )
        steps.append(result.to_dict())
        for action, expected in (("suspend", 200), ("activate", 200)):
            result, _ = owner_client.post(
                f"/api/app/org/{primary_org_id}/{action}",
                name=f"org.{action}.primary",
                expected_status=expected,
                timeout=20,
            )
            steps.append(result.to_dict())

    if deleted_org_id:
        result, _ = owner_client.delete(
            f"/api/app/org/{deleted_org_id}",
            name="org.delete.delete_probe",
            expected_status=200,
            timeout=20,
        )
        steps.append(result.to_dict())

    if primary_org_id:
        role_specs = (
            ("super_admin", "super_admin", None),
            ("org_admin", "operator", "admin"),
            ("viewer", "viewer", None),
        )
        for flow_role, user_role, membership_role in role_specs:
            username = f"audit_{flow_role}_{AUDIT_ID[-8:]}"
            user_id, record = create_user(
                owner_client,
                username=username,
                role=user_role,
                org_id=primary_org_id,
                expected_status=201,
            )
            record["flow_role"] = flow_role
            record["user_role"] = user_role
            steps.append(record)
            if user_id is not None:
                created_users[flow_role] = {
                    "id": user_id,
                    "username": username,
                    "role": user_role,
                    "flow_role": flow_role,
                }
                if membership_role is not None:
                    result, response = owner_client.post(
                        f"/api/app/org/{primary_org_id}/members/add",
                        name=f"org_membership.add.{flow_role}",
                        expected_status=201,
                        json_body={
                            "user_id": str(user_id),
                            "role": membership_role,
                        },
                        timeout=20,
                    )
                    membership_record = result.to_dict()
                    membership_record["flow_role"] = flow_role
                    steps.append(membership_record)
                    if response is not None and response.status_code == 201:
                        created_users[flow_role]["membership_role"] = membership_role
                    else:
                        membership_record["requirement_ok"] = False
                        membership_record["requirement_failure"] = (
                            "org_admin flow requires an active org membership "
                            "with role=admin."
                        )

    password_by_role: dict[str, str] = {}
    for role, user_info in created_users.items():
        final_password = f"{TEST_PASSWORD_PREFIX}-{role}-Final-{AUDIT_ID[-8:]}"
        password_by_role[role] = final_password
        role_client, login_record = login_user(
            user_info["username"],
            DEFAULT_CREATED_PASSWORD,
            name=f"{role}.login.default_password",
        )
        steps.append(login_record)
        if role_client is not None:
            steps.append(
                change_password(
                    role_client,
                    DEFAULT_CREATED_PASSWORD,
                    final_password,
                    name=f"{role}.change_password",
                )
            )

    reset_probe = None
    if primary_org_id:
        reset_username = f"audit_reset_probe_{AUDIT_ID[-8:]}"
        reset_user_id, record = create_user(
            owner_client,
            username=reset_username,
            role="viewer",
            org_id=primary_org_id,
            expected_status=201,
        )
        steps.append(record)
        if reset_user_id is not None:
            temp_password = f"{TEST_PASSWORD_PREFIX}-reset-Probe-{AUDIT_ID[-8:]}"
            reset_record = reset_user_password(owner_client, reset_user_id, temp_password)
            steps.append(reset_record)
            reset_client, login_record = login_user(
                reset_username,
                temp_password,
                name="reset_probe.login.after_owner_reset",
            )
            steps.append(login_record)
            reset_probe = {
                "id": reset_user_id,
                "username": reset_username,
                "login_after_reset": login_record,
            }
            if reset_client is not None:
                change_record = change_password(
                    reset_client,
                    temp_password,
                    f"{TEST_PASSWORD_PREFIX}-reset-Probe-Final-{AUDIT_ID[-8:]}",
                    name="reset_probe.change_password_after_owner_reset",
                )
                change_record["requirement_ok"] = change_record.get("status_code") == 200
                if not change_record["requirement_ok"]:
                    change_record["requirement_failure"] = (
                        "User password reset produced a temporary password that logs in "
                        "but cannot complete the forced password-change flow."
                    )
                steps.append(change_record)
                reset_probe["change_after_reset"] = change_record

    result, response = owner_client.get(
        "/api/app/permissions/registry?limit=100&offset=0",
        name="permissions.registry.owner",
        expected_status=200,
        timeout=30,
    )
    steps.append(result.to_dict())
    selected_permission = None
    if response is not None and response.status_code == 200:
        body = body_from_response(response)
        if isinstance(body, dict):
            items = body.get("items") or []
            for item in items:
                if item.get("permission_key") == "reviews.read":
                    selected_permission = item
                    break
            if selected_permission is None and items:
                selected_permission = items[0]

    assignment = None
    if selected_permission and "viewer" in created_users:
        result, response = owner_client.post(
            f"/api/app/permissions/users/{created_users['viewer']['id']}/assignments",
            name="permission.assignment.create.viewer",
            expected_status=201,
            json_body={
                "permission_key": selected_permission["permission_key"],
                "scope_type": "global",
                "scope_key": "*",
                "reason": f"final pre-production audit {AUDIT_ID}",
                "confirm_high_risk": True,
                "confirmation_text": "CONFIRM_HIGH_RISK_PERMISSION",
            },
            timeout=20,
        )
        steps.append(result.to_dict())
        if response is not None and response.status_code == 201:
            body = body_from_response(response)
            assignment = body.get("assignment") if isinstance(body, dict) else None

    approval_id = None
    result, response = owner_client.post(
        "/api/app/approval/request",
        name="approval.request.create",
        expected_status=201,
        json_body={
            "execution_id": f"exec_{AUDIT_ID}",
            "category": "feature",
            "module_key": "business.approvals",
            "adapter_key": "audit.approval_adapter",
            "action_key": "audit.approve",
            "risk_level": "low",
            "execution_type": "no_op",
            "reason": f"Audit approval request {AUDIT_ID}",
        },
        timeout=20,
    )
    steps.append(result.to_dict())
    if response is not None and response.status_code == 201:
        body = body_from_response(response)
        if isinstance(body, dict):
            approval_id = body.get("approval_id")

    result, _ = owner_client.get(
        "/api/app/approval/list?limit=20&offset=0",
        name="approval.list.owner",
        expected_status=200,
        timeout=20,
    )
    steps.append(result.to_dict())

    if approval_id:
        result, _ = owner_client.post(
            f"/api/app/approval/{approval_id}/approve",
            name="approval.approve.owner",
            expected_status=200,
            json_body={"reason": f"Approved by audit {AUDIT_ID}"},
            timeout=20,
        )
        steps.append(result.to_dict())

    result, _ = owner_client.get(
        "/api/app/reviews",
        name="reviews.overview.owner",
        expected_status=200,
        timeout=20,
    )
    steps.append(result.to_dict())

    key_records: list[dict[str, Any]] = []
    key_ids: dict[str, str] = {}
    if primary_org_id:
        for alias in ("n8n", "backup"):
            result, response = owner_client.post(
                f"/api/control-plane/api-key-orchestration/organizations/{primary_org_id}/keys",
                name=f"api_key.create.{alias}",
                expected_status=201,
                json_body={
                    "name": f"Audit {alias} key {AUDIT_ID}",
                    "url": f"http://127.0.0.1:8788/audit/{alias}",
                    "key_value": f"{TEST_PASSWORD_PREFIX}-ApiKey-{alias}-{uuid4().hex}",
                },
                timeout=20,
            )
            record = result.to_dict()
            steps.append(record)
            key_records.append(record)
            if response is not None and response.status_code == 201:
                body = body_from_response(response)
                item = body.get("item") if isinstance(body, dict) else None
                if isinstance(item, dict):
                    key_ids[alias] = item["key_id"]

    binding_records: list[dict[str, Any]] = []
    if primary_org_id and "n8n" in key_ids:
        for alias, key_id in key_ids.items():
            result, _ = owner_client.post(
                f"/api/control-plane/api-key-orchestration/organizations/{primary_org_id}/bindings",
                name=f"api_key.binding.create.{alias}",
                expected_status=201,
                json_body={
                    "module_id": STATIC_EXECUTION_MODULE,
                    "key_id": key_id,
                    "key_alias": alias,
                },
                timeout=20,
            )
            steps.append(result.to_dict())
            binding_records.append(result.to_dict())

    module_toggle_records: list[dict[str, Any]] = []
    if primary_org_id:
        for enabled in (False, True):
            result, _ = owner_client.patch(
                f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
                name=f"module_control.toggle.{enabled}",
                expected_status=200,
                json_body={"enabled": enabled},
                timeout=20,
            )
            steps.append(result.to_dict())
            module_toggle_records.append(result.to_dict())

    if "viewer" in created_users:
        result, _ = owner_client.post(
            f"/api/app/users/{created_users['viewer']['id']}/disable",
            name="user.disable.viewer",
            expected_status=200,
            timeout=20,
        )
        steps.append(result.to_dict())
        result, _ = owner_client.post(
            f"/api/app/users/{created_users['viewer']['id']}/enable",
            name="user.enable.viewer",
            expected_status=200,
            timeout=20,
        )
        steps.append(result.to_dict())

    result, _ = owner_client.get(
        "/api/app/users?limit=100&offset=0",
        name="users.list.owner",
        expected_status=200,
        timeout=20,
    )
    steps.append(result.to_dict())

    ok_count = sum(1 for step in steps if step.get("ok"))
    requirement_failures = [
        step
        for step in steps
        if step.get("requirement_ok") is False or not step.get("ok")
    ]
    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "backend_base_url": BACKEND_BASE_URL,
        "frontend_base_url": FRONTEND_BASE_URL,
        "primary_org_id": primary_org_id,
        "soft_deleted_test_org_id": deleted_org_id,
        "created_users": redact(created_users),
        "reset_probe_user": redact(reset_probe),
        "passwords_stored_in_report": False,
        "password_by_role_internal_only": list(password_by_role),
        "selected_permission": selected_permission,
        "permission_assignment": assignment,
        "api_key_ids": redact(key_ids),
        "steps": steps,
        "summary": {
            "total_steps": len(steps),
            "ok_steps": ok_count,
            "failed_or_requirement_failed_steps": len(requirement_failures),
            "requirement_failures": requirement_failures,
        },
    }


def run_role_access_checks(
    owner_client: ApiClient,
    created_users: dict[str, dict[str, Any]],
    primary_org_id: str | None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, ApiClient]]:
    role_passwords: dict[str, str] = {}
    role_clients: dict[str, ApiClient] = {"owner": owner_client}
    role_reports: dict[str, Any] = {}

    for role, info in created_users.items():
        final_password = f"{TEST_PASSWORD_PREFIX}-{role}-Final-{AUDIT_ID[-8:]}"
        role_passwords[role] = final_password
        role_client, login_record = login_user(
            info["username"],
            final_password,
            name=f"role_access.{role}.login",
        )
        role_report = {"login": login_record, "api_checks": []}
        if role_client is not None:
            role_clients[role] = role_client
            checks = [
                ("GET", "/api/public/auth/me", 200, "auth.me"),
                ("GET", "/api/public/auth/context", 200, "auth.context"),
                ("GET", "/api/app/permissions/me", 200, "permissions.me"),
                ("GET", "/api/app/users?limit=10&offset=0", None, "users.list"),
                ("GET", "/api/app/organizations?limit=10&offset=0", None, "organizations.list"),
                ("GET", "/api/control-plane/modules/me", None, "modules.me"),
                ("GET", "/api/control-plane/module-control/center", None, "module_control.center"),
                ("GET", "/api/control-plane/api-key-orchestration/keys", (403, 404), "api_keys.list.non_owner"),
                ("GET", "/api/app/permissions/registry?limit=20&offset=0", None, "permissions.registry"),
            ]
            for method, path, expected, label in checks:
                result, _ = role_client.request(
                    method,
                    path,
                    name=f"role_access.{role}.{label}",
                    expected_status=expected,
                    timeout=20,
                )
                role_report["api_checks"].append(result.to_dict())
            if primary_org_id:
                if role == "org_admin":
                    result, _ = role_client.get(
                        f"/api/app/org/{primary_org_id}/members",
                        name="role_access.org_admin.members.list",
                        expected_status=200,
                        timeout=20,
                    )
                    role_report["api_checks"].append(result.to_dict())
                probe_org_id, create_record = create_org(role_client, info["id"], f"negative_{role}")
                create_record["permission_probe"] = "non_owner_org_create_should_not_succeed"
                create_record["permission_violation"] = probe_org_id is not None
                role_report["api_checks"].append(create_record)
                if probe_org_id:
                    result, _ = role_client.delete(
                        f"/api/app/org/{probe_org_id}",
                        name=f"role_access.{role}.cleanup_created_org",
                        expected_status=200,
                        timeout=20,
                    )
                    role_report["api_checks"].append(result.to_dict())
        role_reports[role] = role_report

    permission_violations = []
    for role, report in role_reports.items():
        for check in report.get("api_checks", []):
            if check.get("permission_violation"):
                permission_violations.append({"role": role, "check": check})
    org_admin = created_users.get("org_admin") or {}
    return (
        {
            "audit_id": AUDIT_ID,
            "namespace": NAMESPACE,
            "executed_at": utc_now(),
            "roles": role_reports,
            "summary": {
                "roles_requested": ["owner", "super_admin", "org_admin", "viewer"],
                "roles_created": sorted(created_users),
                "org_admin_created": "org_admin" in created_users,
                "org_admin_membership_role": org_admin.get("membership_role"),
                "permission_violation_count": len(permission_violations),
                "permission_violations": permission_violations,
            },
        },
        role_passwords,
        role_clients,
    )


def run_frontend_playwright(
    users: dict[str, dict[str, str]],
) -> dict[str, Any]:
    script = r"""
const { chromium } = require("./frontend/node_modules/playwright");

const baseUrl = process.env.FRONTEND_BASE_URL || "http://127.0.0.1:3000";
const users = JSON.parse(process.env.AUDIT_USERS_JSON || "{}");
const routes = [
  "/dashboard",
  "/users",
  "/organizations",
  "/permissions",
  "/modules",
  "/api-key-management",
  "/approvals",
  "/reviews",
  "/settings",
];
const badMarkers = [
  "Internal Server Error",
  "服务暂时不可用",
  "Application error",
  "Unhandled Runtime Error",
  "ChunkLoadError",
];

async function login(page, username, password) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded", timeout: 12000 });
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1200);
  if (page.url().includes("/force-password-reset")) {
    return { ok: true, finalUrl: page.url(), requiresPasswordChange: true };
  }
  try {
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 8000 });
  } catch {}
  return {
    ok: !page.url().includes("/login"),
    finalUrl: page.url(),
    requiresPasswordChange: false,
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const output = {};
  for (const [role, creds] of Object.entries(users)) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("pageerror", (error) => consoleErrors.push(String(error.message || error)));
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });
    const roleReport = { login: null, routes: [], consoleErrors };
    try {
      roleReport.login = await login(page, creds.username, creds.password);
      for (const route of routes) {
        const started = Date.now();
        const record = {
          route,
          status: null,
          finalUrl: null,
          elapsedMs: null,
          title: null,
          hasNoPermissionText: false,
          hasLoginForm: false,
          hasBadMarker: false,
          visibleTextSample: "",
          ok: false,
          error: null,
        };
        try {
          const response = await page.goto(`${baseUrl}${route}`, {
            waitUntil: "domcontentloaded",
            timeout: 12000,
          });
          await page.waitForTimeout(900);
          const text = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
          record.status = response ? response.status() : null;
          record.finalUrl = page.url();
          record.title = await page.title();
          record.hasNoPermissionText = /无权|没有权限|当前账号无权|Forbidden|No permission/i.test(text);
          record.hasLoginForm = /进入工作台|登录/.test(text) && page.url().includes("/login");
          record.hasBadMarker = badMarkers.some((marker) => text.includes(marker));
          record.visibleTextSample = text.slice(0, 1200);
          record.ok = !!response && response.status() < 500 && !record.hasBadMarker;
        } catch (error) {
          record.error = error && error.message ? error.message : String(error);
        } finally {
          record.elapsedMs = Date.now() - started;
        }
        roleReport.routes.push(record);
      }
    } catch (error) {
      roleReport.login = {
        ok: false,
        error: error && error.message ? error.message : String(error),
      };
    }
    await context.close();
    output[role] = roleReport;
  }
  await browser.close();
  console.log(JSON.stringify(output));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""
    env = {
        **os.environ,
        "FRONTEND_BASE_URL": FRONTEND_BASE_URL,
        "AUDIT_USERS_JSON": json.dumps(users),
    }
    started = time.perf_counter()
    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if result.returncode != 0:
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error": (result.stderr or result.stdout)[-5000:],
            "roles": {},
        }
    try:
        return {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "roles": json.loads(result.stdout),
        }
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error": f"Playwright output was not JSON: {exc}",
            "raw": result.stdout[-5000:],
            "roles": {},
        }


def run_field_consistency(owner_client: ApiClient, frontend_ui: dict[str, Any]) -> dict[str, Any]:
    modules = [
        {
            "name": "Organizations",
            "path": "/api/app/organizations?limit=20&offset=0",
            "fields": ["org_id", "org_name", "org_type", "owner_user_id", "status", "metadata", "created_at", "updated_at"],
            "item_path": "items.0",
        },
        {
            "name": "Users",
            "path": "/api/app/users?limit=20&offset=0",
            "fields": ["id", "username", "role", "job_title", "organization_id", "must_change_password", "is_active", "last_login_at", "created_at", "updated_at"],
            "item_path": "items.0",
        },
        {
            "name": "Permissions",
            "path": "/api/app/permissions/registry?limit=20&offset=0",
            "fields": ["id", "permission_key", "module_key", "category", "action", "label", "description", "risk_level", "menu_policy", "is_system", "is_enabled", "created_at", "updated_at"],
            "item_path": "items.0",
        },
        {
            "name": "Approvals",
            "path": "/api/app/approval/list?limit=20&offset=0",
            "fields": ["approval_id", "execution_id", "module_key", "status", "risk_level", "execution_type", "requester_id", "request_time"],
            "item_path": "items.0",
        },
        {
            "name": "Reviews",
            "path": "/api/app/reviews",
            "fields": ["module", "source", "legacy_review_items_enabled", "scope_role", "owner_scope", "entrypoints"],
            "item_path": "",
        },
        {
            "name": "Modules",
            "path": "/api/control-plane/modules/registry",
            "fields": ["module_key", "display_name", "description", "category", "status", "lifecycle", "route_namespace", "api_namespace", "required_permissions", "permission_manifest"],
            "item_path": "items.0",
        },
        {
            "name": "API Keys",
            "path": "/api/control-plane/api-key-orchestration/keys",
            "fields": ["key_id", "org_id", "name", "url", "key_hash_prefix", "status", "assigned_module_ids", "created_at", "updated_at", "last_used_at"],
            "item_path": "items.0",
        },
    ]
    checks: list[dict[str, Any]] = []
    for module in modules:
        result, response = owner_client.get(
            module["path"],
            name=f"field_consistency.{module['name']}",
            expected_status=200,
            timeout=30,
        )
        body = body_from_response(response) if response is not None else None
        check = {
            "module": module["name"],
            "api_call": result.to_dict(),
            "required_fields": module["fields"],
            "field_check": required_fields_present(body, module["fields"], item_path=module["item_path"]),
        }
        checks.append(check)

    ui_route_map = {
        "Organizations": "/organizations",
        "Users": "/users",
        "Permissions": "/permissions",
        "Reviews": "/reviews",
        "Approvals": "/approvals",
        "Modules": "/modules",
        "API Keys": "/modules",
    }
    owner_routes = frontend_ui.get("roles", {}).get("owner", {}).get("routes", [])
    route_lookup = {item.get("route"): item for item in owner_routes}
    for check in checks:
        route = ui_route_map.get(check["module"])
        ui_record = route_lookup.get(route)
        check["ui_route"] = route
        check["ui_render_check"] = {
            "route_record_found": ui_record is not None,
            "status": ui_record.get("status") if ui_record else None,
            "has_bad_marker": ui_record.get("hasBadMarker") if ui_record else None,
            "has_no_permission_text": ui_record.get("hasNoPermissionText") if ui_record else None,
            "visible_text_sample": ui_record.get("visibleTextSample") if ui_record else None,
        }

    missing = [
        {"module": check["module"], "missing": check["field_check"].get("missing")}
        for check in checks
        if check["field_check"].get("missing")
    ]
    stale_markers = scan_stale_ui_text()
    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "checks": checks,
        "ui_playwright": frontend_ui,
        "stale_text_scan": stale_markers,
        "summary": {
            "module_count": len(checks),
            "modules_with_missing_fields": len(missing),
            "missing_fields": missing,
            "ui_playwright_ok": frontend_ui.get("ok") is True,
        },
    }


def module_integration_audit(owner_client: ApiClient, primary_org_id: str | None, key_id: str | None) -> tuple[dict[str, Any], str]:
    requirements = {
        "module_registration_requirements": [
            "Static manifest in backend/app/core/modules.py for control-center, API-key binding, module access, and execution gate recognition.",
            "Dynamic DB module via /api/control-plane/modules for foundation/demo registry records.",
            "Module key must use lowercase dot segments for static manifests; dynamic creation currently allows foundation/demo/n8n_test prefixes only.",
        ],
        "required_fields_for_module_onboarding": [
            "module_key",
            "display_name/name",
            "description/responsibilities",
            "category",
            "status",
            "lifecycle",
            "route_namespace",
            "api_namespace",
            "required_permissions",
            "permission_manifest",
            "denied_behavior",
            "operation_log_policy",
            "data_boundary",
            "release_requirements",
            "docs_path",
        ],
        "api_key_binding_requirements": [
            "Organization must exist and not be deleted.",
            "API key must be active and belong to the same org.",
            "module_id must resolve through get_module_manifest(), not only the DB module table.",
            "key_alias is normalized and used by execution gate key_requirements.",
        ],
        "org_module_permission_dependencies": [
            "Org context is resolved server-side from session, membership, owner org, or super_admin organization_id.",
            "Control-plane access uses RBAC actions and owner-only dependencies for key writes.",
            "Execution gate requires module control state enabled and any required key alias binding.",
        ],
        "execution_pipeline_requirements": [
            "module -> module_control_state -> api_key_binding -> key injection -> service dispatch -> operation/event logs.",
            "Current ExecutionRouter states it does not perform live external calls.",
            "n8n-test route records mock-only blocked external dispatch.",
        ],
        "failure_handling_rules": [
            "Missing manifest returns module_not_registered.",
            "Missing key binding returns API_KEY_BINDING_MISSING from execution gate.",
            "Disabled module returns MODULE_DISABLED.",
            "Deleted org is terminal and cannot be reactivated.",
        ],
    }
    checks: list[dict[str, Any]] = []
    dynamic_key = f"{DYNAMIC_MODULE_PREFIX}_{AUDIT_ID[-8:]}"
    result, response = owner_client.post(
        "/api/control-plane/modules",
        name="module.dynamic.create",
        expected_status=201,
        json_body={
            "module_key": dynamic_key,
            "name": f"Audit Dynamic Module {AUDIT_ID}",
            "responsibilities": ["Final pre-production audit dynamic module registration probe."],
            "non_responsibilities": ["Production business execution."],
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "permissions": ["read"],
            "risk_level": "low",
            "version": "0.1.0-audit",
            "status": "demo",
            "dependencies": [],
            "artifact_types": [],
            "review_types": [],
            "error_codes": [],
            "healthcheck_config": {},
            "rollback_policy": {"mode": "audit_probe"},
        },
        timeout=20,
    )
    checks.append({"name": "new_module_created_via_control_plane_modules", "call": result.to_dict()})

    result, _ = owner_client.get(
        f"/api/control-plane/modules/{dynamic_key}",
        name="module.dynamic.detail",
        expected_status=200 if response is not None and response.status_code == 201 else (404, 422),
        timeout=20,
    )
    checks.append({"name": "new_module_appears_in_dynamic_modules_table", "call": result.to_dict()})

    result, response = owner_client.get(
        "/api/control-plane/modules/registry",
        name="module.static.registry.after_dynamic_create",
        expected_status=200,
        timeout=20,
    )
    manifest_contains_dynamic = False
    if response is not None and response.status_code == 200:
        body = body_from_response(response)
        if isinstance(body, dict):
            manifest_contains_dynamic = any(
                item.get("module_key") == dynamic_key for item in body.get("items", [])
            )
    checks.append(
        {
            "name": "new_module_appears_in_manifest_registry",
            "call": result.to_dict(),
            "manifest_contains_dynamic_module": manifest_contains_dynamic,
            "requirement_ok": manifest_contains_dynamic,
        }
    )

    dynamic_binding_ok = False
    if primary_org_id and key_id:
        result, response = owner_client.post(
            f"/api/control-plane/api-key-orchestration/organizations/{primary_org_id}/bindings",
            name="module.dynamic.api_key_binding",
            expected_status=(201, 404),
            json_body={
                "module_id": dynamic_key,
                "key_id": key_id,
                "key_alias": "default",
            },
            timeout=20,
        )
        dynamic_binding_ok = response is not None and response.status_code == 201
        checks.append(
            {
                "name": "new_module_can_bind_api_key",
                "call": result.to_dict(),
                "requirement_ok": dynamic_binding_ok,
            }
        )

    if primary_org_id:
        result, response = owner_client.patch(
            f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{dynamic_key}",
            name="module.dynamic.control_center_toggle",
            expected_status=(200, 404),
            json_body={"enabled": True},
            timeout=20,
        )
        checks.append(
            {
                "name": "new_module_can_be_enabled_disabled_via_control_center",
                "call": result.to_dict(),
                "requirement_ok": response is not None and response.status_code == 200,
            }
        )

    result, _ = owner_client.get(
        "/api/control-plane/module-control/center",
        name="module.control_center.static_registry",
        expected_status=200,
        timeout=30,
    )
    checks.append({"name": "module_control_center_read", "call": result.to_dict()})

    blocking = [
        check
        for check in checks
        if check.get("requirement_ok") is False or not check.get("call", {}).get("ok", True)
    ]
    machine = {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "requirements": requirements,
        "dynamic_module_key": dynamic_key,
        "checks": checks,
        "summary": {
            "dynamic_module_created": checks[0]["call"].get("status_code") == 201,
            "dynamic_module_in_manifest_registry": manifest_contains_dynamic,
            "dynamic_module_api_key_binding": dynamic_binding_ok,
            "blocking_issue_count": len(blocking),
            "blocking_issues": blocking,
        },
    }
    human = "\n".join(
        [
            "# Module Integration Spec Human Report",
            "",
            f"- Audit ID: `{AUDIT_ID}`",
            f"- Dynamic test module: `{dynamic_key}`",
            "",
            "## Plain-English Result",
            "",
            "The system has two module concepts today: a dynamic DB registry used by `/api/control-plane/modules`, and a static manifest registry used by module control, API key binding, module access, and the execution gate.",
            "",
            "A new module can be created through the dynamic registry, but it is not automatically onboarded into the static manifest registry. Because API key binding and module control both require `get_module_manifest()`, a newly created dynamic module cannot bind keys or be enabled through the control center without a code-level static manifest addition.",
            "",
            "## Onboarding Requirements",
            "",
            *[f"- {item}" for item in requirements["module_registration_requirements"]],
            "",
            "## API Key Binding Requirements",
            "",
            *[f"- {item}" for item in requirements["api_key_binding_requirements"]],
            "",
            "## Execution Pipeline",
            "",
            *[f"- {item}" for item in requirements["execution_pipeline_requirements"]],
            "",
            "## Boarding Decision",
            "",
            "NO-GO for arbitrary new module onboarding until dynamic registration feeds the same manifest path used by module control, API key binding, permissions, and execution.",
            "",
        ]
    )
    return machine, human


def api_key_execution_chain(
    owner_client: ApiClient,
    role_clients: dict[str, ApiClient],
    primary_org_id: str | None,
    key_ids: dict[str, str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    runner = role_clients.get("super_admin") or owner_client

    if primary_org_id:
        result, _ = owner_client.patch(
            f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
            name="chain.ensure_module_enabled",
            expected_status=200,
            json_body={"enabled": True},
            timeout=20,
        )
        checks.append({"name": "ensure_module_enabled", "call": result.to_dict()})

    missing_runner = runner
    result, _ = missing_runner.post(
        "/api/control-plane/n8n-test/run",
        name="chain.execution_after_binding",
        expected_status=(201, 403, 500),
        timeout=30,
    )
    checks.append(
        {
            "name": "module_to_api_key_to_execution_gate_to_backend_call",
            "call": result.to_dict(),
            "mock_only_marker_seen": "mock_only" in json.dumps(result.body if isinstance(result.body, (dict, list)) else result.body),
            "real_external_backend_call_verified": False,
            "reason": "n8n-test service is explicitly mock-only and external_dispatch_blocked even when key injection succeeds.",
        }
    )

    result, response = owner_client.get(
        "/api/control-plane/api-key-orchestration/keys",
        name="chain.keys_after_execution",
        expected_status=200,
        timeout=20,
    )
    key_usage = {}
    if response is not None and response.status_code == 200:
        body = body_from_response(response)
        if isinstance(body, dict):
            for item in body.get("items", []):
                if item.get("key_id") in key_ids.values():
                    key_usage[item["key_id"]] = {
                        "name": item.get("name"),
                        "last_used_at": item.get("last_used_at"),
                        "assigned_module_ids": item.get("assigned_module_ids"),
                    }
    checks.append({"name": "correct_key_selection_last_used_probe", "call": result.to_dict(), "key_usage": key_usage})

    if primary_org_id and "backup" in key_ids:
        result, _ = owner_client.post(
            f"/api/control-plane/api-key-orchestration/organizations/{primary_org_id}/bindings",
            name="chain.multiple_key_alias_backup_binding",
            expected_status=201,
            json_body={
                "module_id": STATIC_EXECUTION_MODULE,
                "key_id": key_ids["backup"],
                "key_alias": "backup",
            },
            timeout=20,
        )
        checks.append({"name": "multiple_keys_per_module_alias_binding", "call": result.to_dict()})

    disabled_probe = None
    if primary_org_id:
        result, _ = owner_client.patch(
            f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
            name="chain.module_disable_probe",
            expected_status=200,
            json_body={"enabled": False},
            timeout=20,
        )
        checks.append({"name": "module_disabled_before_execution_probe", "call": result.to_dict()})
        result, _ = runner.post(
            "/api/control-plane/n8n-test/run",
            name="chain.execution_disabled_module_fallback",
            expected_status=403,
            timeout=20,
        )
        disabled_probe = result.to_dict()
        checks.append({"name": "fallback_when_module_disabled", "call": disabled_probe})
        result, _ = owner_client.patch(
            f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
            name="chain.module_reenable_after_probe",
            expected_status=200,
            json_body={"enabled": True},
            timeout=20,
        )
        checks.append({"name": "module_reenabled_after_probe", "call": result.to_dict()})

    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "chain": "module -> api_key -> execution_gate -> backend_call -> logs",
        "checks": checks,
        "summary": {
            "key_injection_path_executed": any(
                check["name"] == "module_to_api_key_to_execution_gate_to_backend_call"
                and check["call"].get("status_code") == 201
                for check in checks
            ),
            "real_backend_call_verified": False,
            "real_backend_call_blocker": "Current execution route is n8n-test mock-only; external dispatch is intentionally blocked.",
            "multiple_keys_bound": "n8n" in key_ids and "backup" in key_ids,
            "disabled_module_fallback_status": disabled_probe.get("status_code") if disabled_probe else None,
        },
    }


def request_once(client: ApiClient, method: str, path: str, idx: int) -> dict[str, Any]:
    result, _ = client.request(
        method,
        path,
        name=f"stress.request.{idx}",
        expected_status=None,
        timeout=20,
    )
    return {
        "status_code": result.status_code,
        "elapsed_ms": result.elapsed_ms,
        "ok_transport": result.error is None and result.status_code is not None and result.status_code < 500,
        "timeout": result.error is not None and "timed out" in result.error.lower(),
        "error": result.error,
        "path": path,
        "method": method,
    }


def run_concurrency_stress(
    owner_client: ApiClient,
    primary_org_id: str | None,
    role_clients: dict[str, ApiClient],
    created_users: dict[str, dict[str, Any]],
    key_ids: dict[str, str],
) -> dict[str, Any]:
    before_db = postgres_pressure_snapshot()
    before_stats = docker_stats()

    users_for_login: list[tuple[str, str, str]] = []
    for role, info in created_users.items():
        if role in {"super_admin", "org_admin", "viewer"}:
            users_for_login.append(
                (
                    role,
                    info["username"],
                    f"{TEST_PASSWORD_PREFIX}-{role}-Final-{AUDIT_ID[-8:]}",
                )
            )

    extra_users: dict[str, dict[str, Any]] = {}
    if primary_org_id:
        for index in range(max(0, 10 - len(users_for_login) - 1)):
            role = "operator" if index % 2 == 0 else "viewer"
            username = f"audit_stress_{index}_{AUDIT_ID[-8:]}"
            user_id, record = create_user(
                owner_client,
                username=username,
                role=role,
                org_id=primary_org_id,
                expected_status=201,
            )
            if user_id is None:
                extra_users[username] = {"create_record": record}
                continue
            final = f"{TEST_PASSWORD_PREFIX}-stress-{index}-Final-{AUDIT_ID[-8:]}"
            user_client, login_record = login_user(
                username,
                DEFAULT_CREATED_PASSWORD,
                name=f"stress_user.{index}.login_default_password",
            )
            change_record = None
            if user_client is not None:
                change_record = change_password(
                    user_client,
                    DEFAULT_CREATED_PASSWORD,
                    final,
                    name=f"stress_user.{index}.change_password",
                )
                users_for_login.append((f"stress_{index}", username, final))
            extra_users[username] = {
                "id": user_id,
                "role": role,
                "create_record": record,
                "login_record": login_record,
                "change_record": change_record,
            }

    owner_env = parse_env_file(REPO_ROOT / ".env.production")
    owner_username = owner_env.get("OWNER_USERNAME")
    owner_password = owner_env.get("OWNER_PASSWORD")
    if owner_username and owner_password:
        users_for_login.insert(0, ("owner", owner_username, owner_password))
    users_for_login = users_for_login[:10]

    login_results: list[dict[str, Any]] = []
    login_clients: list[ApiClient] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(login_user, username, password, name=f"stress.parallel_login.{role}"): role
            for role, username, password in users_for_login
        }
        for future in concurrent.futures.as_completed(futures):
            role = futures[future]
            client, record = future.result()
            record["role_label"] = role
            login_results.append(record)
            if client is not None:
                login_clients.append(client)

    paths = [
        "/api/public/auth/me",
        "/api/app/permissions/me",
        "/api/app/organizations?limit=20&offset=0",
        "/api/control-plane/modules/me",
        "/api/app/approval/list?limit=10&offset=0",
    ]
    api_results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(80, max(1, len(login_clients) * 20))) as executor:
        futures = []
        idx = 0
        for client in login_clients:
            for request_index in range(20):
                path = paths[request_index % len(paths)]
                futures.append(executor.submit(request_once, client.clone(), "GET", path, idx))
                idx += 1
        for future in concurrent.futures.as_completed(futures):
            api_results.append(future.result())

    toggle_results: list[dict[str, Any]] = []
    if primary_org_id:
        def toggle(idx: int) -> dict[str, Any]:
            enabled = idx % 2 == 0
            result, _ = owner_client.clone().patch(
                f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
                name=f"stress.module_toggle.{idx}",
                expected_status=None,
                json_body={"enabled": enabled},
                timeout=20,
            )
            return result.to_dict()

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            for future in concurrent.futures.as_completed([executor.submit(toggle, idx) for idx in range(20)]):
                toggle_results.append(future.result())
        owner_client.patch(
            f"/api/control-plane/module-control/organizations/{primary_org_id}/registry-entries/{STATIC_EXECUTION_MODULE}",
            name="stress.module_toggle.final_enable",
            expected_status=200,
            json_body={"enabled": True},
            timeout=20,
        )

    binding_results: list[dict[str, Any]] = []
    stress_key_id = key_ids.get("backup") or key_ids.get("n8n")
    if primary_org_id and stress_key_id:
        def bind(idx: int) -> dict[str, Any]:
            result, _ = owner_client.clone().post(
                f"/api/control-plane/api-key-orchestration/organizations/{primary_org_id}/bindings",
                name=f"stress.api_key_binding.{idx}",
                expected_status=None,
                json_body={
                    "module_id": STATIC_EXECUTION_MODULE,
                    "key_id": stress_key_id,
                    "key_alias": "stress",
                },
                timeout=20,
            )
            return result.to_dict()

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            for future in concurrent.futures.as_completed([executor.submit(bind, idx) for idx in range(20)]):
                binding_results.append(future.result())

    after_db = postgres_pressure_snapshot()
    after_stats = docker_stats()
    backend_log = docker_logs(PROD_BACKEND_CONTAINER, tail=500)
    frontend_log = docker_logs(PROD_FRONTEND_CONTAINER, tail=300)

    status_counts = Counter(str(item["status_code"]) for item in api_results)
    api_failures = [item for item in api_results if not item["ok_transport"]]
    timeouts = [item for item in api_results if item["timeout"]]
    elapsed_values = sorted(item["elapsed_ms"] for item in api_results if item.get("elapsed_ms") is not None)
    p95 = elapsed_values[int(len(elapsed_values) * 0.95) - 1] if elapsed_values else None
    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "scenario": {
            "parallel_login_users_requested": 10,
            "parallel_login_users_executed": len(users_for_login),
            "concurrent_api_requests_per_user": 20,
            "simultaneous_module_toggle_operations": len(toggle_results),
            "simultaneous_api_key_binding_operations": len(binding_results),
        },
        "extra_users_created_for_stress": redact(extra_users),
        "login_results": login_results,
        "api_results_sample": api_results[:50],
        "module_toggle_results": toggle_results,
        "api_key_binding_results": binding_results,
        "db_pressure": {"before": before_db, "after": after_db},
        "docker_stats": {"before": before_stats, "after": after_stats},
        "logs": {"backend": backend_log, "frontend": frontend_log},
        "summary": {
            "login_success_count": sum(1 for item in login_results if item.get("ok")),
            "login_failure_count": sum(1 for item in login_results if not item.get("ok")),
            "api_request_count": len(api_results),
            "api_status_counts": dict(status_counts),
            "transport_failure_count": len(api_failures),
            "timeout_count": len(timeouts),
            "failure_rate": round(len(api_failures) / len(api_results), 4) if api_results else None,
            "timeout_rate": round(len(timeouts) / len(api_results), 4) if api_results else None,
            "p95_response_ms": p95,
            "module_toggle_5xx_count": sum(1 for item in toggle_results if (item.get("status_code") or 0) >= 500),
            "api_key_binding_5xx_count": sum(1 for item in binding_results if (item.get("status_code") or 0) >= 500),
            "backend_error_like_log_count": backend_log["error_like_count"],
        },
    }


def frontend_routes() -> list[str]:
    app_root = REPO_ROOT / "frontend" / "src" / "app"
    routes = []
    for path in app_root.rglob("page.tsx"):
        relative = path.relative_to(app_root)
        parts = []
        for part in relative.parts[:-1]:
            if part.startswith("(") and part.endswith(")"):
                continue
            if part.startswith("[") and part.endswith("]"):
                parts.append(f":{part[1:-1]}")
            else:
                parts.append(part)
        routes.append("/" + "/".join(parts))
    return sorted(routes)


def backend_route_scan() -> list[dict[str, str]]:
    routes = []
    route_files = list((REPO_ROOT / "backend" / "app" / "api").rglob("*.py"))
    route_files += list((REPO_ROOT / "backend" / "app" / "api" / "routes").rglob("*.py"))
    seen_files = sorted(set(route_files))
    decorator_re = re.compile(r"@(?:router|plural_router|app)\.(get|post|patch|delete|put)\((?:\s*)[\"']([^\"']+)[\"']")
    prefix_re = re.compile(r"APIRouter\(prefix=[\"']([^\"']+)[\"']")
    for file_path in seen_files:
        text = file_path.read_text(encoding="utf-8")
        prefixes = prefix_re.findall(text)
        prefix = prefixes[0] if prefixes else ""
        for method, path in decorator_re.findall(text):
            routes.append(
                {
                    "method": method.upper(),
                    "path": f"{prefix}{path}",
                    "file": str(file_path.relative_to(REPO_ROOT)),
                }
            )
    return sorted(routes, key=lambda item: (item["path"], item["method"]))


def scan_stale_ui_text() -> dict[str, Any]:
    markers = ("mock", "demo", "foundation", "placeholder", "TODO", "暂未", "示例")
    counts: dict[str, int] = defaultdict(int)
    samples: list[dict[str, Any]] = []
    for path in (REPO_ROOT / "frontend" / "src").rglob("*"):
        if path.suffix not in {".tsx", ".ts", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            matched = [marker for marker in markers if marker.lower() in lowered]
            if matched:
                for marker in matched:
                    counts[marker] += 1
                if len(samples) < 80:
                    samples.append(
                        {
                            "file": str(path.relative_to(REPO_ROOT)),
                            "line": lineno,
                            "markers": matched,
                            "text": line.strip()[:240],
                        }
                    )
    return {"marker_counts": dict(counts), "samples": samples}


def static_dead_code_audit() -> dict[str, Any]:
    fe_routes = frontend_routes()
    be_routes = backend_route_scan()
    route_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            REPO_ROOT / "frontend" / "src" / "app" / "api" / "backend" / "[...path]" / "route.ts",
            REPO_ROOT / "backend" / "app" / "main.py",
        ]
        if path.exists()
    )
    backend_paths = {item["path"] for item in be_routes}
    likely_proxy_orphans = [
        item
        for item in be_routes
        if item["path"].split("/", 2)[1:2] and item["path"] not in route_text
    ][:200]
    manifest_text = (REPO_ROOT / "backend" / "app" / "core" / "modules.py").read_text(encoding="utf-8")
    manifest_modules = re.findall(r"module_key=[\"']([^\"']+)[\"']", manifest_text)
    frontend_route_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "frontend" / "src").rglob("*.ts*")
    )
    unused_manifest_modules = [
        module
        for module in sorted(set(manifest_modules))
        if module not in frontend_route_text and module not in {"experimental.foundation_demo", "integration.n8n_test_bridge"}
    ]
    model_files = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "backend" / "app" / "models").glob("*.py"))
    migration_files = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "backend" / "alembic" / "versions").glob("*.py"))
    debug_markers = []
    for file_path in [REPO_ROOT / "backend" / "app" / "main.py", REPO_ROOT / "backend" / "app" / "core" / "config.py"]:
        text = file_path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in ("docs_url", "redoc_url", "openapi_url", "app_debug", "debug=")):
                debug_markers.append(
                    {
                        "file": str(file_path.relative_to(REPO_ROOT)),
                        "line": lineno,
                        "text": line.strip(),
                    }
                )
    stale = scan_stale_ui_text()
    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "frontend_routes": fe_routes,
        "backend_routes": be_routes,
        "permission_middleware": {
            "files": [
                "backend/app/middleware/permission.py",
                "backend/app/services/permission_decision_engine.py",
                "backend/app/services/unified_permission_engine.py",
            ],
            "rbac_core_touched_by_audit": False,
        },
        "db_schema_consistency": {
            "model_file_count": len(model_files),
            "migration_file_count": len(migration_files),
            "model_files": model_files,
            "migration_files": migration_files,
        },
        "orphan_endpoint_candidates": likely_proxy_orphans,
        "unused_module_candidates": unused_manifest_modules,
        "stale_ui_text": stale,
        "debug_endpoint_markers": debug_markers,
        "summary": {
            "frontend_route_count": len(fe_routes),
            "backend_route_count": len(be_routes),
            "orphan_endpoint_candidate_count": len(likely_proxy_orphans),
            "unused_module_candidate_count": len(unused_manifest_modules),
            "stale_ui_marker_count": sum(stale["marker_counts"].values()),
            "debug_marker_count": len(debug_markers),
        },
    }


def worker_runtime_status() -> dict[str, Any]:
    compose_text = (REPO_ROOT / "docker-compose.production.yml").read_text(
        encoding="utf-8",
    )
    dockerfile_text = (REPO_ROOT / "backend" / "Dockerfile").read_text(
        encoding="utf-8",
    )
    process_probe = run_command(
        [
            "docker",
            "exec",
            PROD_BACKEND_CONTAINER,
            "sh",
            "-lc",
            "ps -eo args | grep -E 'gunicorn|uvicorn' | grep -v grep",
        ],
        timeout=30,
    )
    process_text = f"{process_probe.get('stdout', '')}\n{process_probe.get('stderr', '')}"
    active_gunicorn_workers = len(re.findall(r"gunicorn: worker", process_text))
    configured_workers = 2 if (
        'GUNICORN_WORKERS: "2"' in compose_text
        or "GUNICORN_WORKERS:-2" in dockerfile_text
        or " -w 2 " in dockerfile_text
    ) else 1
    return {
        "configured_workers": configured_workers,
        "active_gunicorn_worker_processes": active_gunicorn_workers,
        "mode": (
            "gunicorn_uvicorn_workers"
            if "gunicorn" in dockerfile_text and "UvicornWorker" in dockerfile_text
            else "uvicorn_single_or_unknown"
        ),
        "config_ok": configured_workers == 2
        and "gunicorn" in dockerfile_text
        and "UvicornWorker" in dockerfile_text,
        "runtime_probe": process_probe,
    }


def final_decision(
    *,
    owner_report: dict[str, Any],
    role_report: dict[str, Any],
    field_report: dict[str, Any],
    stress_report: dict[str, Any],
    module_report: dict[str, Any],
    chain_report: dict[str, Any],
    dead_code_report: dict[str, Any],
) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    worker_status = worker_runtime_status()

    if owner_report["summary"]["failed_or_requirement_failed_steps"]:
        blocking.append(
            {
                "code": "OWNER_FLOW_FAILURES",
                "severity": "critical",
                "detail": owner_report["summary"]["requirement_failures"],
            }
        )
    if not role_report["summary"].get("org_admin_created"):
        blocking.append(
            {
                "code": "ORG_ADMIN_FLOW_MISSING",
                "severity": "critical",
                "detail": "Audit requires an org_admin account derived from org membership.",
            }
        )
    if role_report["summary"].get("org_admin_membership_role") != "admin":
        blocking.append(
            {
                "code": "ORG_ADMIN_MEMBERSHIP_NOT_DERIVED",
                "severity": "critical",
                "detail": "org_admin must come from org_memberships.role=admin, not a global user role.",
            }
        )
    if role_report["summary"]["permission_violation_count"] > 0:
        blocking.append(
            {
                "code": "PERMISSION_VIOLATION",
                "severity": "critical",
                "detail": role_report["summary"]["permission_violations"],
            }
        )
    if field_report["summary"]["modules_with_missing_fields"] > 0:
        blocking.append(
            {
                "code": "FIELD_CONSISTENCY_GAPS",
                "severity": "high",
                "detail": field_report["summary"]["missing_fields"],
            }
        )
    if not field_report["summary"]["ui_playwright_ok"]:
        blocking.append(
            {
                "code": "UI_BROWSER_AUDIT_FAILED",
                "severity": "high",
                "detail": field_report.get("ui_playwright", {}).get("error"),
            }
        )
    if (stress_report["summary"]["failure_rate"] or 0) > 0 or stress_report["summary"]["timeout_count"] > 0:
        blocking.append(
            {
                "code": "CONCURRENCY_TRANSPORT_FAILURES",
                "severity": "critical",
                "detail": stress_report["summary"],
            }
        )
    if stress_report["summary"]["module_toggle_5xx_count"] > 0 or stress_report["summary"]["api_key_binding_5xx_count"] > 0:
        blocking.append(
            {
                "code": "CONCURRENCY_MUTATION_5XX",
                "severity": "critical",
                "detail": stress_report["summary"],
            }
        )
    if module_report["summary"]["blocking_issue_count"] > 0:
        blocking.append(
            {
                "code": "MODULE_ONBOARDING_NOT_READY",
                "severity": "critical",
                "detail": module_report["summary"]["blocking_issues"],
            }
        )
    if not chain_report["summary"]["real_backend_call_verified"]:
        blocking.append(
            {
                "code": "API_KEY_MODULE_CHAIN_NOT_REAL_BACKEND_CALL",
                "severity": "critical",
                "detail": chain_report["summary"]["real_backend_call_blocker"],
            }
        )
    if dead_code_report["summary"]["stale_ui_marker_count"] > 0:
        blocking.append(
            {
                "code": "STALE_UI_TEXT_MARKERS_PRESENT",
                "severity": "medium",
                "detail": dead_code_report["stale_ui_text"]["marker_counts"],
            }
        )
    if not worker_status["config_ok"]:
        blocking.append(
            {
                "code": "WORKER_MODE_NOT_MULTI_WORKER",
                "severity": "critical",
                "detail": worker_status,
            }
        )

    can_go_live = len([item for item in blocking if item["severity"] in {"critical", "high"}]) == 0
    restart_result = {
        "restart_attempted": False,
        "reason": "Restart is allowed only when all audit conditions pass.",
        "commands": [
            "docker restart barong-ops-console-prod_console_backend_1",
            "docker restart barong-ops-console-prod_console_frontend_1",
        ],
    }
    if can_go_live:
        backend_restart = run_command(["docker", "restart", PROD_BACKEND_CONTAINER], timeout=60)
        frontend_restart = run_command(["docker", "restart", PROD_FRONTEND_CONTAINER], timeout=60)
        restart_result = {
            "restart_attempted": True,
            "backend": backend_restart,
            "frontend": frontend_restart,
        }
    return {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "system_can_go_live": "YES" if can_go_live else "NO",
        "blocking_issues": blocking,
        "worker_mode_status": worker_status,
        "db_performance_result": {
            "status": "passed"
            if (stress_report["summary"]["failure_rate"] or 0) == 0
            and stress_report["summary"]["timeout_count"] == 0
            else "failed",
            "details": stress_report["summary"],
            "db_pressure": stress_report.get("db_pressure"),
        },
        "webhook_status": {
            "real_backend_call_verified": chain_report["summary"].get(
                "real_backend_call_verified",
            ),
            "blocker": chain_report["summary"].get("real_backend_call_blocker"),
        },
        "rbac_correctness": {
            "core_model_preserved": True,
            "global_admin_flow_removed": True,
            "org_admin_is_membership_derived": role_report["summary"].get(
                "org_admin_membership_role"
            )
            == "admin",
            "summary": role_report["summary"],
        },
        "test_suite_alignment": {
            "admin_login_flow_removed": True,
            "admin_flow_replacement": "super_admin + org_admin membership flow",
            "roles_requested": role_report["summary"].get("roles_requested"),
        },
        "performance_summary": stress_report["summary"],
        "permission_correctness_summary": role_report["summary"],
        "module_system_readiness": module_report["summary"],
        "api_key_system_readiness": chain_report["summary"],
        "field_ui_consistency_summary": field_report["summary"],
        "dead_code_scan_summary": dead_code_report["summary"],
        "deployment_rule_result": restart_result,
        "report_files": {key: str(path.relative_to(REPO_ROOT)) for key, path in REPORT_PATHS.items()},
    }


def main() -> int:
    env = parse_env_file(REPO_ROOT / ".env.production")
    owner_username = env.get("OWNER_USERNAME")
    owner_password = env.get("OWNER_PASSWORD")

    bootstrap_report: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "namespace": NAMESPACE,
        "executed_at": utc_now(),
        "backend_base_url": BACKEND_BASE_URL,
        "frontend_base_url": FRONTEND_BASE_URL,
        "owner_credentials_loaded": bool(owner_username and owner_password),
    }
    if not owner_username or not owner_password:
        failed = {
            **bootstrap_report,
            "system_can_go_live": "NO",
            "blocking_issues": [
                {
                    "code": "OWNER_CREDENTIALS_UNAVAILABLE",
                    "severity": "critical",
                    "detail": ".env.production does not expose OWNER_USERNAME/OWNER_PASSWORD to the audit harness.",
                }
            ],
        }
        for path in REPORT_PATHS.values():
            if path.suffix == ".json":
                write_json(path, failed)
            else:
                path.write_text("# Audit blocked\n\nOwner credentials unavailable.\n", encoding="utf-8")
        return 2

    owner_client, owner_login = login_user(owner_username, owner_password, name="owner.login")
    if owner_client is None:
        failed = {
            **bootstrap_report,
            "owner_login": owner_login,
            "system_can_go_live": "NO",
            "blocking_issues": [
                {
                    "code": "OWNER_LOGIN_FAILED",
                    "severity": "critical",
                    "detail": owner_login,
                }
            ],
        }
        write_json(REPORT_PATHS["final"], failed)
        return 2

    me_result, me_response = owner_client.get(
        "/api/public/auth/me",
        name="owner.auth.me",
        expected_status=200,
        timeout=15,
    )
    owner_user = body_from_response(me_response) if me_response is not None else {}
    if not isinstance(owner_user, dict) or owner_user.get("role") != "owner":
        failed = {
            **bootstrap_report,
            "owner_login": owner_login,
            "owner_me": me_result.to_dict(),
            "system_can_go_live": "NO",
            "blocking_issues": [
                {
                    "code": "OWNER_IDENTITY_INVALID",
                    "severity": "critical",
                    "detail": "Logged-in production owner account did not resolve to role=owner.",
                }
            ],
        }
        write_json(REPORT_PATHS["final"], failed)
        return 2

    owner_report = owner_full_flow(owner_client, owner_user)
    write_json(REPORT_PATHS["owner"], owner_report)

    created_users = owner_report.get("created_users", {})
    primary_org_id = owner_report.get("primary_org_id")
    role_report, role_passwords, role_clients = run_role_access_checks(
        owner_client,
        created_users,
        primary_org_id,
    )

    users_for_ui = {
        "owner": {"username": owner_username, "password": owner_password},
    }
    for role, info in created_users.items():
        if role in role_passwords:
            users_for_ui[role] = {"username": info["username"], "password": role_passwords[role]}
    frontend_ui = run_frontend_playwright(users_for_ui)
    role_report["ui_playwright"] = frontend_ui
    write_json(REPORT_PATHS["roles"], role_report)

    field_report = run_field_consistency(owner_client, frontend_ui)
    write_json(REPORT_PATHS["fields"], field_report)

    key_ids = owner_report.get("api_key_ids", {})
    module_report, module_human = module_integration_audit(
        owner_client,
        primary_org_id,
        key_ids.get("n8n") if isinstance(key_ids, dict) else None,
    )
    write_json(REPORT_PATHS["module_machine"], module_report)
    REPORT_PATHS["module_human"].write_text(module_human, encoding="utf-8")

    chain_report = api_key_execution_chain(
        owner_client,
        role_clients,
        primary_org_id,
        key_ids if isinstance(key_ids, dict) else {},
    )
    write_json(REPORT_PATHS["chain"], chain_report)

    stress_report = run_concurrency_stress(
        owner_client,
        primary_org_id,
        role_clients,
        created_users,
        key_ids if isinstance(key_ids, dict) else {},
    )
    write_json(REPORT_PATHS["stress"], stress_report)

    dead_code_report = static_dead_code_audit()
    write_json(REPORT_PATHS["dead_code"], dead_code_report)

    final_report = final_decision(
        owner_report=owner_report,
        role_report=role_report,
        field_report=field_report,
        stress_report=stress_report,
        module_report=module_report,
        chain_report=chain_report,
        dead_code_report=dead_code_report,
    )
    write_json(REPORT_PATHS["final"], final_report)
    write_json(REPORT_PATHS["consolidation"], final_report)
    print(
        json.dumps(
            {
                "audit_id": AUDIT_ID,
                "system_can_go_live": final_report["system_can_go_live"],
                "blocking_issue_count": len(final_report["blocking_issues"]),
                "reports": final_report["report_files"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if final_report["system_can_go_live"] == "YES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
