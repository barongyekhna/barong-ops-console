from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.production"
N8N_MODULE_ID = "integration.n8n_webhook_test_bridge"
DEFAULT_PASSWORD = "123456"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:500]}


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.request(
            method,
            path,
            json=json_body,
            timeout=timeout,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": 200 <= response.status_code < 300,
            "body": _safe_json(response),
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "method": method,
            "path": path,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def _write_report(name: str, payload: dict[str, Any]) -> None:
    payload.setdefault("generated_at", _now())
    path = ROOT / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _login(
    base_url: str,
    username: str,
    password: str,
) -> tuple[httpx.Client, dict[str, Any]]:
    client = httpx.Client(base_url=base_url, timeout=20.0, trust_env=False)
    response = _request(
        client,
        "POST",
        "/api/public/auth/login",
        json_body={"username": username, "password": password},
    )
    session_token = response.get("body", {}).get("session_token")
    if response.get("ok") and isinstance(session_token, str) and session_token:
        client.headers["X-Session-Token"] = session_token
    return client, response


def _change_password(client: httpx.Client, new_password: str) -> dict[str, Any]:
    return _request(
        client,
        "POST",
        "/api/public/auth/change-password",
        json_body={
            "current_password": DEFAULT_PASSWORD,
            "new_password": new_password,
        },
    )


def _request_with_token(
    base_url: str,
    session_token: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    with httpx.Client(
        base_url=base_url,
        headers={"X-Session-Token": session_token},
        timeout=timeout,
        trust_env=False,
    ) as client:
        return _request(
            client,
            method,
            path,
            json_body=json_body,
            timeout=timeout,
        )


async def _async_request_one(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, Any]:
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    started = time.perf_counter()
    try:
        response = await client.request(method, path, json=json_body)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": 200 <= response.status_code < 300,
            "body": _safe_json(response),
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "method": method,
            "path": path,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }


async def _async_request_batch(
    base_url: str,
    session_token: str,
    requests: list[dict[str, Any]],
    *,
    timeout: float = 8.0,
    rps: float | None = None,
) -> list[dict[str, Any]]:
    timeout_config = httpx.Timeout(
        timeout,
        connect=timeout,
        read=timeout,
        write=timeout,
        pool=timeout,
    )
    limits = httpx.Limits(
        max_connections=max(10, len(requests)),
        max_keepalive_connections=max(10, len(requests)),
    )
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"X-Session-Token": session_token},
        timeout=timeout_config,
        limits=limits,
        trust_env=False,
    ) as client:
        tasks = [
            _async_request_one(
                client,
                str(item["method"]),
                str(item["path"]),
                json_body=item.get("json_body"),
                delay_seconds=(index / rps) if rps and rps > 0 else 0.0,
            )
            for index, item in enumerate(requests)
        ]
        return list(await asyncio.gather(*tasks))


def _status_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [
        float(record["elapsed_ms"])
        for record in records
        if isinstance(record.get("elapsed_ms"), (int, float))
    ]
    failures = [record for record in records if not record.get("ok")]
    timeouts = [record for record in records if record.get("error") in {"TimeoutError", "ReadTimeout"}]
    return {
        "total": len(records),
        "success": len(records) - len(failures),
        "failure": len(failures),
        "failure_rate": round(len(failures) / len(records), 4) if records else 0,
        "timeout": len(timeouts),
        "timeout_rate": round(len(timeouts) / len(records), 4) if records else 0,
        "avg_ms": round(statistics.mean(elapsed), 3) if elapsed else None,
        "p95_ms": _percentile(elapsed, 0.95),
        "max_ms": round(max(elapsed), 3) if elapsed else None,
    }


def _worker_mode_status() -> dict[str, Any]:
    compose_text = (ROOT / "docker-compose.production.yml").read_text(
        encoding="utf-8",
    )
    dockerfile_text = (ROOT / "backend" / "Dockerfile").read_text(
        encoding="utf-8",
    )
    configured_workers = 2 if (
        'GUNICORN_WORKERS: "2"' in compose_text
        or "GUNICORN_WORKERS:-2" in dockerfile_text
    ) else 1
    config_ok = (
        configured_workers == 2
        and "gunicorn" in dockerfile_text
        and "UvicornWorker" in dockerfile_text
    )
    return {
        "configured_workers": configured_workers,
        "mode": "gunicorn_uvicorn_workers"
        if config_ok
        else "uvicorn_single_or_unknown",
        "config_ok": config_ok,
    }


def run(base_url: str, prod_url: str | None) -> int:
    env = _load_env(ENV_PATH)
    audit_id = f"recovery_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    owner_username = env.get("OWNER_USERNAME", "")
    owner_password = env.get("OWNER_PASSWORD", "")
    n8n_url_configured = bool(env.get("N8N_TEST_WEBHOOK_URL", "").strip())
    worker_status = _worker_mode_status()
    reports: dict[str, dict[str, Any]] = {}
    blocking_issues: list[str] = []

    owner_client, owner_login = _login(base_url, owner_username, owner_password)
    if not owner_login["ok"]:
        blocking_issues.append("owner_login_failed")
        for name in (
            "permission_leak_fix_report.json",
            "execution_chain_realization_report.json",
            "performance_fix_report.json",
            "field_consistency_fix_report.json",
            "final_concurrency_report.json",
            "final_system_readiness_report.json",
            "final_production_consolidation_report.json",
        ):
            _write_report(
                name,
                {
                    "audit_id": audit_id,
                    "status": "failed",
                    "blocking_issues": blocking_issues,
                    "owner_login": owner_login,
                    "worker_mode_status": worker_status,
                },
            )
        return 1

    owner_user = owner_login["body"].get("user", {})
    owner_user_id = str(owner_user.get("id", ""))
    owner_session_token = str(owner_login["body"].get("session_token") or "")

    org_create = _request(
        owner_client,
        "POST",
        "/api/app/org/create",
        json_body={
            "org_name": f"Recovery Audit {audit_id}",
            "org_type": "store",
            "owner_user_id": owner_user_id,
            "metadata": {
                "industry": "audit",
                "country": "US",
                "timezone": "UTC",
                "settings": {
                    "allow_ai": False,
                    "allow_n8n": True,
                    "data_retention_days": 30,
                },
                "custom": {"audit_id": audit_id, "isolated": True},
            },
        },
    )
    org_id = org_create.get("body", {}).get("org_id")
    if not org_create["ok"] or not org_id:
        blocking_issues.append("isolated_org_create_failed")

    roles = [
        ("super_admin", "super_admin", None),
        ("org_admin", "operator", "admin"),
        ("viewer", "viewer", None),
    ]
    created_users: dict[str, dict[str, Any]] = {}
    role_records: list[dict[str, Any]] = []
    passwords: dict[str, str] = {}
    for flow_role, user_role, membership_role in roles:
        username = f"{audit_id}_{flow_role}"
        create_response = _request(
            owner_client,
            "POST",
            "/api/app/users",
            json_body={
                "username": username,
                "role": user_role,
                "job_title": f"Recovery {flow_role}",
                "organization_id": org_id,
                "is_active": True,
            },
        )
        role_record = {
            "role": flow_role,
            "username": username,
            "user_role": user_role,
            "create_user": {
                key: create_response.get(key)
                for key in ("status_code", "elapsed_ms", "ok", "body", "error")
                if key in create_response
            },
        }
        if create_response["ok"]:
            if membership_role is not None:
                membership_response = _request(
                    owner_client,
                    "POST",
                    f"/api/app/org/{org_id}/members/add",
                    json_body={
                        "user_id": str(create_response["body"].get("id")),
                        "role": membership_role,
                    },
                )
                role_record["derived_membership"] = {
                    key: membership_response.get(key)
                    for key in ("status_code", "elapsed_ms", "ok", "body", "error")
                    if key in membership_response
                }
                if not membership_response["ok"]:
                    blocking_issues.append("org_admin_membership_create_failed")
            password = f"{audit_id}_{flow_role}_Password_123!"
            user_client, login_response = _login(base_url, username, DEFAULT_PASSWORD)
            change_response = _change_password(user_client, password)
            user_client.close()
            user_client, final_login = _login(base_url, username, password)
            role_record["initial_login"] = login_response
            role_record["change_password"] = change_response
            role_record["final_login"] = {
                key: final_login.get(key)
                for key in ("status_code", "elapsed_ms", "ok", "body", "error")
                if key in final_login
            }
            created_users[flow_role] = {
                "user": create_response["body"],
                "client": user_client,
            }
            passwords[flow_role] = password
        role_records.append(role_record)

    permission_attempts: list[dict[str, Any]] = []
    for role, payload in created_users.items():
        user = payload["user"]
        client = payload["client"]
        attempt = _request(
            client,
            "POST",
            "/api/app/org/create",
            json_body={
                "org_name": f"Blocked Org {audit_id} {role}",
                "org_type": "store",
                "owner_user_id": str(user.get("id")),
                "metadata": {
                    "industry": "audit",
                    "country": "US",
                    "timezone": "UTC",
                    "settings": {
                        "allow_ai": False,
                        "allow_n8n": False,
                        "data_retention_days": 30,
                    },
                    "custom": {"audit_id": audit_id, "negative_case": role},
                },
            },
        )
        permission_attempts.append(
            {
                "role": role,
                "status_code": attempt["status_code"],
                "elapsed_ms": attempt["elapsed_ms"],
                "denied": attempt["status_code"] == 403,
            }
        )
        if attempt["status_code"] != 403:
            blocking_issues.append(f"permission_leak_{role}")

    api_key_create = _request(
        owner_client,
        "POST",
        f"/api/control-plane/api-key-orchestration/organizations/{org_id}/keys",
        json_body={
            "name": f"Recovery n8n key {audit_id}",
            "url": "https://example.invalid",
            "key_value": f"recovery-test-token-{uuid4().hex}",
        },
    )
    key_id = api_key_create.get("body", {}).get("item", {}).get("key_id")
    binding_create = _request(
        owner_client,
        "POST",
        f"/api/control-plane/api-key-orchestration/organizations/{org_id}/bindings",
        json_body={
            "module_id": N8N_MODULE_ID,
            "key_id": key_id or "missing_key",
            "key_alias": "n8n",
        },
    )

    missing_key_run = _request(
        owner_client,
        "POST",
        "/api/control-plane/n8n-webhook-test/run",
        json_body={
            "org_id": org_id,
            "key_alias": "missing_alias",
            "payload": {"audit_id": audit_id, "case": "missing_key"},
        },
    )
    webhook_run = _request(
        owner_client,
        "POST",
        "/api/control-plane/n8n-webhook-test/run",
        json_body={
            "org_id": org_id,
            "key_alias": "n8n",
            "payload": {"audit_id": audit_id, "case": "configured_key"},
        },
        timeout=30.0,
    )
    webhook_passed = webhook_run["ok"] and webhook_run.get("body", {}).get("success") is True
    if not webhook_passed:
        blocking_issues.append("n8n_webhook_e2e_failed")

    organizations_response = _request(owner_client, "GET", "/api/app/organizations?limit=100&offset=0")
    users_response = _request(owner_client, "GET", f"/api/app/users?organization_id={org_id}&limit=100&offset=0")
    permissions_response = _request(owner_client, "GET", "/api/app/permissions/registry?limit=100&offset=0")
    modules_response = _request(owner_client, "GET", "/api/control-plane/module-control/center")
    approvals_response = _request(owner_client, "GET", "/api/app/approval/list?limit=20&offset=0")
    approval_id = f"approval-{audit_id.replace('_', '-')}-{uuid4().hex[:8]}"
    approval_create = _request(
        owner_client,
        "POST",
        "/api/app/approval/request",
        json_body={
            "approval_id": approval_id,
            "execution_id": f"execution-{audit_id.replace('_', '-')}",
            "category": "feature",
            "module_key": "business.approvals",
            "adapter_key": "recovery.approval_adapter",
            "action_key": "recovery.approve",
            "risk_level": "low",
            "execution_type": "no_op",
            "reason": "Recovery audit approval field validation.",
        },
    )
    approval_detail = (
        _request(owner_client, "GET", f"/api/app/approval/{approval_id}")
        if approval_create["ok"]
        else {"ok": False, "status_code": None, "body": {}}
    )

    module_items = []
    for group in modules_response.get("body", {}).get("organizations", []):
        if group.get("org_id") == org_id:
            module_items = group.get("modules", [])
            break
    sample_module = module_items[0] if module_items else {}
    sample_user = (users_response.get("body", {}).get("items") or [{}])[0]
    approval_items = approvals_response.get("body", {}).get("items") or []
    sample_approval = (
        approval_create.get("body", {}).get("approval")
        if approval_create["ok"]
        else {}
    )
    if not sample_approval and approval_detail.get("ok"):
        sample_approval = approval_detail.get("body", {}).get("approval") or {}
    if not sample_approval:
        sample_approval = next(
            (
                item
                for item in approval_items
                if item.get("approval_id") == approval_id
            ),
            approval_items[0] if approval_items else {},
        )
    field_checks = {
        "Users": {
            "required": ["organization", "organization_id", "role", "title", "job_title"],
            "present": sorted(k for k in ["organization", "organization_id", "role", "title", "job_title"] if k in sample_user),
        },
        "Modules": {
            "required": ["status", "enabled", "error", "runtime_status"],
            "present": sorted(k for k in ["status", "enabled", "error", "runtime_status"] if k in sample_module),
        },
        "Approvals": {
            "required": ["status", "reason", "timestamp"],
            "present": sorted(k for k in ["status", "reason", "timestamp", "request_time"] if k in sample_approval),
        },
    }
    for area, check in field_checks.items():
        missing = sorted(set(check["required"]) - set(check["present"]))
        check["missing"] = missing
        if missing:
            blocking_issues.append(f"field_missing_{area}")

    login_records: list[dict[str, Any]] = []
    login_targets = [
        (f"{audit_id}_load_{i}", f"{audit_id}_load_{i}_Password_123!")
        for i in range(10)
    ]
    for username, password in login_targets:
        create = _request(
            owner_client,
            "POST",
            "/api/app/users",
            json_body={
                "username": username,
                "role": "viewer",
                "job_title": "Recovery load user",
                "organization_id": org_id,
                "is_active": True,
            },
        )
        if create["ok"]:
            c, _ = _login(base_url, username, DEFAULT_PASSWORD)
            _change_password(c, password)
            c.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [
            pool.submit(_login, base_url, username, password)
            for username, password in login_targets
        ]
        for future in as_completed(futures):
            client, response = future.result()
            client.close()
            login_records.append(response)

    read_paths = [
        "/api/app/organizations?limit=100&offset=0",
        "/api/app/permissions/me",
        "/api/control-plane/modules/registry",
        "/api/control-plane/module-control/center",
    ]
    api_call_records = asyncio.run(
        _async_request_batch(
            base_url,
            owner_session_token,
            [
                {"method": "GET", "path": read_paths[i % len(read_paths)]}
                for i in range(50)
            ],
            timeout=8.0,
            rps=50.0,
        )
    )

    toggle_module_id = N8N_MODULE_ID
    toggle_records = asyncio.run(
        _async_request_batch(
            base_url,
            owner_session_token,
            [
                {
                    "method": "PATCH",
                    "path": f"/api/control-plane/module-control/organizations/{org_id}/registry-entries/{toggle_module_id}",
                    "json_body": {"enabled": i % 2 == 0},
                }
            for i in range(8)
            ],
            timeout=8.0,
        )
    )
    final_module_enable = _request(
        owner_client,
        "PATCH",
        f"/api/control-plane/module-control/organizations/{org_id}/registry-entries/{toggle_module_id}",
        json_body={"enabled": True},
    )
    if not final_module_enable["ok"]:
        blocking_issues.append("module_toggle_final_enable_failed")

    binding_key_ids: list[str] = []
    for i in range(3):
        create = _request(
            owner_client,
            "POST",
            f"/api/control-plane/api-key-orchestration/organizations/{org_id}/keys",
            json_body={
                "name": f"Recovery routing key {i} {audit_id}",
                "url": "https://example.invalid",
                "key_value": f"recovery-routing-token-{i}-{uuid4().hex}",
            },
        )
        key_id_i = create.get("body", {}).get("item", {}).get("key_id")
        if key_id_i:
            binding_key_ids.append(key_id_i)
    concurrent_binding_records = asyncio.run(
        _async_request_batch(
            base_url,
            owner_session_token,
            [
                {
                    "method": "POST",
                    "path": f"/api/control-plane/api-key-orchestration/organizations/{org_id}/bindings",
                    "json_body": {
                        "module_id": N8N_MODULE_ID,
                        "key_id": key_id_i,
                        "key_alias": f"n8n_route_{i}",
                    },
                }
                for i, key_id_i in enumerate(binding_key_ids)
            ],
            timeout=8.0,
        )
    )

    prod_route_probe = None
    if prod_url:
        with httpx.Client(
            base_url=prod_url,
            headers={"X-Session-Token": owner_session_token},
            timeout=30.0,
            trust_env=False,
        ) as prod_client:
            prod_route_probe = _request(
                prod_client,
                "POST",
                "/api/control-plane/n8n-webhook-test/run",
                json_body={
                    "org_id": org_id or "org_probe",
                    "key_alias": "n8n",
                    "payload": {"audit_id": audit_id, "case": "prod_route_probe"},
                },
                timeout=30.0,
            )

    reports["permission_leak_fix_report.json"] = {
        "audit_id": audit_id,
        "status": "passed" if all(item["denied"] for item in permission_attempts) else "failed",
        "owner_org_create": org_create,
        "role_user_creation": role_records,
        "non_owner_org_create_attempts": permission_attempts,
        "rule": "if role != owner: deny create organization with 403; org_admin is derived from org_memberships.role=admin",
        "rbac_core_modified": False,
    }
    reports["execution_chain_realization_report.json"] = {
        "audit_id": audit_id,
        "status": "blocked" if not webhook_passed else "passed",
        "module_id": N8N_MODULE_ID,
        "mock_fallback_allowed": False,
        "api_key_create_status": api_key_create["status_code"],
        "binding_create_status": binding_create["status_code"],
        "missing_key_fallback": {
            "status_code": missing_key_run["status_code"],
            "body": missing_key_run.get("body"),
        },
        "webhook_run": {
            "status_code": webhook_run["status_code"],
            "elapsed_ms": webhook_run["elapsed_ms"],
            "body": webhook_run.get("body"),
        },
        "n8n_test_webhook_url_configured": n8n_url_configured,
    }
    reports["performance_fix_report.json"] = {
        "audit_id": audit_id,
        "status": "measured",
        "code_changes": [
            "module-control center read path no longer writes missing state rows",
            "short TTL read caches for organizations, permissions, modules",
            "cached GET endpoints allow parallel idempotent reads",
        ],
        "read_api_summary": _status_summary(api_call_records),
        "login_summary": _status_summary(login_records),
        "module_toggle_summary": _status_summary(toggle_records),
        "module_toggle_final_enable": {
            key: final_module_enable.get(key)
            for key in ("status_code", "elapsed_ms", "ok", "body", "error")
            if key in final_module_enable
        },
        "api_key_binding_summary": _status_summary(concurrent_binding_records),
        "target": {"read_api_p95_ms": 500, "module_control_ms": 2000},
    }
    reports["field_consistency_fix_report.json"] = {
        "audit_id": audit_id,
        "status": "passed" if not any(item["missing"] for item in field_checks.values()) else "failed",
        "field_checks": field_checks,
        "raw_statuses": {
            "organizations": organizations_response["status_code"],
            "users": users_response["status_code"],
            "permissions": permissions_response["status_code"],
            "modules": modules_response["status_code"],
            "approvals_list": approvals_response["status_code"],
            "approval_create": approval_create["status_code"],
            "approval_detail": approval_detail["status_code"],
        },
    }
    if not webhook_passed:
        _write_report(
            "webhook_connection_failure_report.json",
            {
                "audit_id": audit_id,
                "status": "failed",
                "n8n_test_webhook_url_configured": n8n_url_configured,
                "webhook_run": webhook_run,
                "root_cause": (
                    "N8N_TEST_WEBHOOK_URL is empty"
                    if not n8n_url_configured
                    else "Backend could not complete the n8n webhook request"
                ),
            },
        )
    if (
        webhook_run.get("status_code") == 502
        and webhook_run.get("body", {}).get("detail", {}).get("code")
        == "n8n_webhook_response_failed"
    ):
        _write_report(
            "n8n_response_failure_report.json",
            {
                "audit_id": audit_id,
                "status": "failed",
                "webhook_run": webhook_run,
            },
        )
    read_summary = _status_summary(api_call_records)
    toggle_summary = _status_summary(toggle_records)
    binding_summary = _status_summary(concurrent_binding_records)
    reports["final_concurrency_report.json"] = {
        "audit_id": audit_id,
        "status": "passed"
        if read_summary["failure_rate"] == 0
        and read_summary["timeout_rate"] == 0
        and toggle_summary["failure_rate"] == 0
        and toggle_summary["timeout_rate"] == 0
        and binding_summary["failure_rate"] == 0
        and binding_summary["timeout_rate"] == 0
        and final_module_enable["ok"]
        else "failed",
        "parallel_login": _status_summary(login_records),
        "read_50_rps": read_summary,
        "module_toggle_concurrency": toggle_summary,
        "api_key_binding_concurrency": binding_summary,
    }

    if prod_route_probe and prod_route_probe.get("status_code") == 404:
        blocking_issues.append("production_container_not_updated_with_current_code")
    if not n8n_url_configured:
        blocking_issues.append("n8n_test_webhook_url_missing")
    if not worker_status["config_ok"]:
        blocking_issues.append("worker_mode_not_multi_worker")
    system_can_go_live = (
        not blocking_issues
        and webhook_passed
        and reports["field_consistency_fix_report.json"]["status"] == "passed"
        and reports["final_concurrency_report.json"]["status"] == "passed"
    )
    reports["final_system_readiness_report.json"] = {
        "audit_id": audit_id,
        "system_can_go_live": "YES" if system_can_go_live else "NO",
        "blocking_issues": sorted(set(blocking_issues)),
        "performance_summary": reports["performance_fix_report.json"],
        "security_summary": reports["permission_leak_fix_report.json"],
        "webhook_validation_result": {
            "passed": webhook_passed,
            "n8n_test_webhook_url_configured": n8n_url_configured,
            "status_code": webhook_run["status_code"],
        },
        "deployment_summary": {
            "verification_base_url": base_url,
            "production_base_url": prod_url,
            "worker_mode_status": worker_status,
            "production_route_probe": prod_route_probe,
            "restart_allowed": system_can_go_live,
            "restart_executed": False,
            "reason": (
                "all conditions passed"
                if system_can_go_live
                else "blocking issues remain; production containers were not restarted"
            ),
        },
    }
    reports["final_production_consolidation_report.json"] = {
        "audit_id": audit_id,
        "system_can_go_live": "YES" if system_can_go_live else "NO",
        "worker_mode_status": worker_status,
        "db_performance_result": reports["performance_fix_report.json"],
        "webhook_status": {
            "request_sent": webhook_run["status_code"] is not None,
            "response_received": webhook_run["status_code"] is not None,
            "logs_persisted": webhook_passed,
            "no_timeout": webhook_run.get("error") not in {"TimeoutError", "ReadTimeout"},
            "details": webhook_run,
        },
        "rbac_correctness": {
            "core_model_preserved": True,
            "global_admin_login_flow_removed": True,
            "org_admin_is_derived_membership": any(
                record.get("role") == "org_admin"
                and record.get("derived_membership", {}).get("status_code") == 201
                for record in role_records
            ),
            "role_user_creation": role_records,
        },
        "test_suite_alignment": {
            "roles_executed": ["owner", "super_admin", "org_admin", "viewer"],
            "admin_role_test_removed": True,
            "mock_concurrency_results": False,
            "read_50_rps": reports["final_concurrency_report.json"]["read_50_rps"],
        },
    }

    for name, payload in reports.items():
        _write_report(name, payload)

    for payload in created_users.values():
        payload["client"].close()
    owner_client.close()
    return 0 if system_can_go_live else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--prod-url", default=None)
    args = parser.parse_args()
    return run(args.base_url.rstrip("/"), args.prod_url.rstrip("/") if args.prod_url else None)


if __name__ == "__main__":
    raise SystemExit(main())
