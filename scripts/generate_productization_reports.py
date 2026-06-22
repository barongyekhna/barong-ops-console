from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

APPLICATION_PREFIX = "/api/app"
CONTROL_PLANE_PREFIX = "/api/control-plane"
PUBLIC_PREFIX = "/api/public"

TARGET_MODULE_KEYS = {
    "admin.users",
    "admin.organizations",
    "admin.modules",
    "business.approvals",
    "business.reviews",
}
PRODUCT_HIDDEN_MODULE_KEYS = {
    "admin.agents",
    "admin.permissions",
    "admin.settings",
    "experimental.foundation_demo",
    "integration.n8n_test_bridge",
    "system.errors",
    "system.memory_events",
    "system.operation_logs",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ast.unparse(node)
    return None


def call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return call_name(node.func)
    return ""


def normalize_path(*parts: str) -> str:
    text = "/".join(part.strip("/") for part in parts if part is not None)
    return "/" + text.strip("/")


def parse_router_file(path: Path) -> dict[str, Any]:
    tree = ast.parse(read(path), filename=str(path))
    routers: dict[str, dict[str, Any]] = {}
    routes: list[dict[str, Any]] = []
    public_functions: list[str] = []
    public_classes: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            public_functions.append(node.name)
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            public_classes.append(node.name)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if call_name(node.value.func).endswith("APIRouter"):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefix = ""
                        tags: list[str] = []
                        for kw in node.value.keywords:
                            if kw.arg == "prefix":
                                prefix = literal_string(kw.value) or ""
                            if kw.arg == "tags" and isinstance(kw.value, ast.List):
                                tags = [
                                    item.value
                                    for item in kw.value.elts
                                    if isinstance(item, ast.Constant)
                                    and isinstance(item.value, str)
                                ]
                        routers[target.id] = {"prefix": prefix, "tags": tags}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dependencies: list[str] = []
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if isinstance(default, ast.Call):
                dependencies.append(ast.unparse(default))
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute):
                continue
            method = func.attr.upper()
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"}:
                continue
            router_name = call_name(func.value)
            if router_name not in routers:
                continue
            route_path = literal_string(decorator.args[0]) if decorator.args else ""
            response_model = None
            for kw in decorator.keywords:
                if kw.arg == "response_model":
                    response_model = ast.unparse(kw.value)
            routes.append(
                {
                    "router": router_name,
                    "router_prefix": routers[router_name]["prefix"],
                    "method": method,
                    "path": route_path or "",
                    "function": node.name,
                    "dependencies": dependencies,
                    "response_model": response_model,
                    "source": rel(path),
                    "line": node.lineno,
                    "tags": routers[router_name]["tags"],
                }
            )

    return {
        "routers": routers,
        "routes": routes,
        "public_functions": public_functions,
        "public_classes": public_classes,
    }


def module_to_path(module: str) -> Path:
    if module.startswith("app."):
        module = module[4:]
    return BACKEND / "app" / Path(module.replace(".", "/") + ".py")


def parse_main_router_registrations() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    main_path = BACKEND / "app" / "main.py"
    tree = ast.parse(read(main_path), filename=str(main_path))
    import_aliases: dict[str, tuple[str, str]] = {}
    prefix_values = {
        "APPLICATION_API_PREFIX": APPLICATION_PREFIX,
        "CONTROL_PLANE_API_PREFIX": CONTROL_PLANE_PREFIX,
        "PUBLIC_API_PREFIX": PUBLIC_PREFIX,
    }
    registrations: list[dict[str, str]] = []
    direct_routes: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 1:
                module = f"app.{module}"
            elif node.level == 2:
                module = f"app.{module}"
            for alias in node.names:
                import_aliases[alias.asname or alias.name] = (module, alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node.func) == "app.include_router":
            if not node.args:
                continue
            alias = ast.unparse(node.args[0])
            module, router_var = import_aliases.get(alias, ("", alias))
            prefix = ""
            for kw in node.keywords:
                if kw.arg == "prefix":
                    if isinstance(kw.value, ast.Name):
                        prefix = prefix_values.get(kw.value.id, kw.value.id)
                    else:
                        prefix = literal_string(kw.value) or ast.unparse(kw.value)
            registrations.append(
                {
                    "alias": alias,
                    "module": module,
                    "router_var": router_var,
                    "prefix": prefix,
                    "source": rel(module_to_path(module)) if module else "",
                }
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (
                    isinstance(func, ast.Attribute)
                    and call_name(func.value) == "app"
                    and func.attr.upper() in {"GET", "POST", "PATCH", "PUT", "DELETE"}
                ):
                    direct_routes.append(
                        {
                            "method": func.attr.upper(),
                            "registered_path": literal_string(decorator.args[0]) if decorator.args else "",
                            "function": node.name,
                            "source": rel(main_path),
                            "line": node.lineno,
                            "dependencies": [],
                        }
                    )

    return registrations, direct_routes


def collect_backend_routes() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    router_files = sorted((BACKEND / "app" / "api").rglob("*.py"))
    parsed = {rel(path): parse_router_file(path) for path in router_files}
    registrations, direct_routes = parse_main_router_registrations()
    registered_routes = list(direct_routes)

    for registration in registrations:
        source = registration["source"]
        router_var = registration["router_var"]
        for route in parsed.get(source, {}).get("routes", []):
            if route["router"] != router_var:
                continue
            registered_path = normalize_path(
                registration["prefix"],
                route["router_prefix"],
                route["path"],
            )
            registered_routes.append(
                {
                    **route,
                    "api_layer": registration["prefix"],
                    "registered_path": registered_path,
                    "frontend_proxy_path": registered_path
                    .removeprefix(APPLICATION_PREFIX)
                    .removeprefix(CONTROL_PLANE_PREFIX)
                    .removeprefix(PUBLIC_PREFIX)
                    or "/",
                }
            )

    return registered_routes, registrations, parsed


def collect_services() -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for path in sorted((BACKEND / "app" / "services").glob("*.py")):
        parsed = parse_router_file(path)
        services.append(
            {
                "source": rel(path),
                "public_functions": parsed["public_functions"],
                "public_classes": parsed["public_classes"],
            }
        )
    return services


def collect_module_manifests() -> list[dict[str, Any]]:
    sys.path.insert(0, str(BACKEND))
    from app.core.modules import MODULE_MANIFESTS_V1  # noqa: PLC0415

    return [dict(item) for item in MODULE_MANIFESTS_V1]


def collect_frontend_api_calls() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"apiRequest(?:<[^>]+>)?\(\s*([`'\"])(.*?)(?<!\\)\1", re.S)
    for path in sorted((FRONTEND / "src").rglob("*.*")):
        if path.suffix not in {".ts", ".tsx", ".mjs"}:
            continue
        text = read(path)
        for match in pattern.finditer(text):
            raw = match.group(2)
            calls.append({"source": rel(path), "path": raw})
    return calls


def collect_proxy_allowlist() -> dict[str, Any]:
    path = FRONTEND / "src" / "app" / "api" / "backend" / "[...path]" / "route.ts"
    text = read(path)
    allow_sets: dict[str, list[str]] = {}
    for name, body in re.findall(r"const\s+(ALLOWED_[A-Z0-9_]+)\s*=\s*new Set\(\[(.*?)\]\);", text, re.S):
        allow_sets[name] = re.findall(r'"([^"]+)"', body)
    bootstrap_targets = re.findall(r'path:\s*\[([^\]]+)\]', text)
    bootstrap_paths = [
        "/".join(re.findall(r'"([^"]+)"', target))
        for target in bootstrap_targets
    ]
    return {
        "source": rel(path),
        "allow_sets": allow_sets,
        "capability_bootstrap_targets": bootstrap_paths,
        "dynamic_rules": [
            "users: GET/POST /users, GET /users/roles, GET/PATCH /users/{id}, POST /users/{id}/{disable|enable|reset-password}",
            "reviews: GET /reviews/module-registry, GET /reviews/organizations, GET /reviews/organizations/{id}/users, GET /reviews/organizations/{id}/users/{user_id}/actions",
            "approval: GET /approval/list, POST /approval/request, GET /approval/{id}, POST /approval/{id}/{approve|reject}",
            "org: POST /org/create, PATCH/DELETE /org/{id}, POST /org/{id}/{activate|suspend}, member add/remove",
            "permissions: GET /permissions/me, GET /permissions/registry, CRUD /permissions/users/{id}/assignments",
            "control-plane resources: GET/POST/GET-detail for modules and agents",
        ],
    }


def path_matches(api_namespace: str, path: str) -> bool:
    if api_namespace == "no_api":
        return False
    clean = path.split("?", 1)[0]
    clean = clean.removeprefix(APPLICATION_PREFIX).removeprefix(CONTROL_PLANE_PREFIX).removeprefix(PUBLIC_PREFIX)
    return clean == api_namespace or clean.startswith(f"{api_namespace}/")


def module_api_analysis(
    manifests: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    frontend_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for manifest in manifests:
        api_namespace = manifest["api_namespace"]
        backend_routes = [
            {
                "method": route["method"],
                "registered_path": route["registered_path"],
                "function": route["function"],
                "source": route["source"],
            }
            for route in routes
            if path_matches(api_namespace, route.get("registered_path", ""))
        ]
        frontend_bindings = [
            call for call in frontend_calls if path_matches(api_namespace, call["path"])
        ]
        missing: list[str] = []
        if manifest.get("no_api") or api_namespace == "no_api":
            missing.append("no_api_declared")
        elif not backend_routes:
            missing.append("backend_route_missing_for_manifest_api_namespace")
        if not frontend_bindings and not manifest.get("no_api"):
            missing.append("frontend_api_binding_missing")
        if manifest["module_key"] in PRODUCT_HIDDEN_MODULE_KEYS:
            missing.append("hidden_from_product_navigation")
        if manifest["navigation"].get("default_visible") is False:
            missing.append("navigation_default_visible_false")
        result.append(
            {
                "module_key": manifest["module_key"],
                "display_name": manifest["display_name"],
                "status": manifest["status"],
                "route_namespace": manifest["route_namespace"],
                "api_namespace": api_namespace,
                "no_api": manifest["no_api"],
                "frontend_route_targeted": manifest["module_key"] in TARGET_MODULE_KEYS,
                "backend_routes": backend_routes,
                "frontend_api_bindings": frontend_bindings,
                "missing_api_list": missing,
                "data_source": manifest.get("data_boundary", {}),
                "required_permissions": manifest.get("required_permissions", []),
                "permission_manifest": manifest.get("permission_manifest", []),
            }
        )
    return result


def route_exposed_by_frontend(route: dict[str, Any], calls: list[dict[str, Any]], proxy: dict[str, Any]) -> bool:
    frontend_path = route.get("frontend_proxy_path", "")
    for call in calls:
        raw = call["path"]
        static = raw.split("${", 1)[0].rstrip("/")
        if static and (frontend_path.startswith(static) or static.startswith(frontend_path.rstrip("/"))):
            return True
    allow_values = [item for values in proxy["allow_sets"].values() for item in values]
    compact = frontend_path.strip("/")
    return compact in allow_values or compact in proxy["capability_bootstrap_targets"]


def collect_navigation_modules() -> list[dict[str, str]]:
    text = read(FRONTEND / "src" / "lib" / "navigation.ts")
    records: list[dict[str, str]] = []
    blocks = re.findall(r"\{([^{}]*module_key:[^{}]*)\}", text, re.S)
    for block in blocks:
        module_key = re.search(r'module_key:\s*"([^"]+)"', block)
        label = re.search(r'label:\s*"([^"]+)"', block)
        href = re.search(r'href:\s*"([^"]+)"', block)
        if module_key:
            records.append(
                {
                    "module_key": module_key.group(1),
                    "label": label.group(1) if label else "",
                    "href": href.group(1) if href else "",
                }
            )
    return records


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    generated_at = now_iso()
    routes, router_registrations, parsed_route_files = collect_backend_routes()
    services = collect_services()
    manifests = collect_module_manifests()
    frontend_calls = collect_frontend_api_calls()
    proxy = collect_proxy_allowlist()
    modules = module_api_analysis(manifests, routes, frontend_calls)
    navigation_modules = collect_navigation_modules()

    exposed_routes = [
        route for route in routes if route_exposed_by_frontend(route, frontend_calls, proxy)
    ]
    unexposed_routes = [
        route for route in routes if not route_exposed_by_frontend(route, frontend_calls, proxy)
    ]
    permission_control_points = [
        {
            "method": route["method"],
            "registered_path": route["registered_path"],
            "function": route["function"],
            "source": route["source"],
            "dependencies": route.get("dependencies", []),
        }
        for route in routes
        if route.get("dependencies")
    ]
    permission_control_points.extend(
        [
            {
                "type": "middleware",
                "source": "backend/app/main.py",
                "name": "enforce_control_plane_isolation",
                "summary": "Control-plane routes require authenticated session and PermissionDecisionEngine platform metadata decision.",
            },
            {
                "type": "middleware",
                "source": "backend/app/middleware/permission.py",
                "name": "enforce_permission_isolation",
                "summary": "API app/control-plane requests with org/module context are checked by services.permission_isolation.check_permission.",
            },
            {
                "type": "module_registry",
                "source": "backend/app/core/modules.py",
                "name": "permission_manifest",
                "summary": "Each registered module declares required_permissions and permission_manifest entries.",
            },
        ]
    )

    workflow_sources = [
        "backend/app/core/workflow_registry.py",
        "backend/app/services/workflow_registry_system.py",
        "backend/app/services/module_workflow_binding_engine.py",
        "backend/app/services/approval_workflow_engine.py",
        "backend/app/services/approval_rule_engine.py",
        "backend/app/api/routes/workflow_registry.py",
        "backend/app/api/routes/module_workflow_bindings.py",
        "backend/app/api/routes/approval.py",
    ]
    workflow_routes = [
        route
        for route in routes
        if route["source"] in workflow_sources
        or any(marker in route["registered_path"] for marker in ["workflow", "approval"])
    ]

    target_status = [
        module for module in modules if module["module_key"] in TARGET_MODULE_KEYS
    ]
    critical_missing = [
        module
        for module in target_status
        if "backend_route_missing_for_manifest_api_namespace" in module["missing_api_list"]
        or "frontend_api_binding_missing" in module["missing_api_list"]
    ]

    exposed_report = {
        "generated_at": generated_at,
        "basis": "Generated by scripts/generate_productization_reports.py from current backend/frontend source code.",
        "backend_routes": routes,
        "router_registrations": router_registrations,
        "service_layer": services,
        "module_registry": manifests,
        "module_api_analysis": modules,
        "permission_control_points": permission_control_points,
        "workflow_system": {
            "sources": workflow_sources,
            "routes": workflow_routes,
            "services": [service for service in services if service["source"] in workflow_sources],
        },
        "frontend_api_calls": frontend_calls,
        "frontend_proxy_exposure": proxy,
        "current_exposed_to_frontend": exposed_routes,
        "backend_exists_but_not_exposed_to_frontend": unexposed_routes,
    }
    write_json(ROOT / "exposed_backend_capabilities_report.json", exposed_report)

    frontend_report = {
        "generated_at": generated_at,
        "basis": "Generated from current source plus productization edits in this run.",
        "productized_target_modules": sorted(TARGET_MODULE_KEYS),
        "frontend_navigation_modules": navigation_modules,
        "backend_registry_module_keys": [manifest["module_key"] for manifest in manifests],
        "frontend_registry_alignment": {
            "navigation_modules_not_in_backend_registry": sorted(
                {
                    item["module_key"]
                    for item in navigation_modules
                    if item["module_key"]
                    not in {manifest["module_key"] for manifest in manifests}
                }
            ),
            "backend_registry_modules_not_in_product_navigation": sorted(
                {
                    manifest["module_key"]
                    for manifest in manifests
                    if manifest["module_key"]
                    not in {item["module_key"] for item in navigation_modules}
                }
            ),
            "hidden_technical_modules": sorted(PRODUCT_HIDDEN_MODULE_KEYS),
        },
        "ui_productization_controls": {
            "language": "目标页面、首页、导航、空状态和错误兜底已中文化。",
            "technical_fields_hidden": [
                "用户页移除了权限面板入口和用户 ID 展示。",
                "组织页不再展示 owner_user_id，未匹配时显示业务文案。",
                "功能区页不展示 module_key/api_namespace/route_namespace/reason 原文。",
                "审计页不展示 related_object_type/related_object。",
                "技术运维模块从产品导航隐藏，保留在后端暴露报告。",
            ],
            "pagination_default": 10,
            "error_messages": ["暂无数据", "加载失败，请稍后重试"],
        },
        "modified_frontend_files": [
            "frontend/src/lib/navigation.ts",
            "frontend/src/lib/frontend-capability-state.ts",
            "frontend/src/components/user-management-panel.tsx",
            "frontend/src/components/organization-product-view.tsx",
            "frontend/src/components/module-registry-product-view.tsx",
            "frontend/src/components/review-audit-view.tsx",
            "frontend/src/components/approval-product-view.tsx",
            "frontend/src/components/operations-dashboard.tsx",
            "frontend/src/app/(console)/dashboard/page.tsx",
            "frontend/src/app/(console)/users/page.tsx",
            "frontend/src/app/(console)/organizations/page.tsx",
            "frontend/src/app/api/backend/[...path]/route.ts",
        ],
    }
    write_json(ROOT / "frontend_ui_productization_report.json", frontend_report)

    missing_report = {
        "generated_at": generated_at,
        "basis": "Missing items are derived from route registry, module registry, frontend API calls and proxy allowlist.",
        "no_missing_critical_bindings": len(critical_missing) == 0,
        "critical_missing_bindings": critical_missing,
        "module_missing_feature_analysis": modules,
        "backend_routes_not_exposed_to_frontend": unexposed_routes,
        "frontend_hidden_instead_of_fake_ui": sorted(PRODUCT_HIDDEN_MODULE_KEYS),
        "notes": [
            "Planned/no_api modules are reported and are not converted into fake UI.",
            "Technical control-plane and operation-log pages are hidden from product navigation instead of being presented to business users.",
        ],
    }
    write_json(ROOT / "missing_feature_analysis_report.json", missing_report)

    permission_report = {
        "generated_at": generated_at,
        "basis": "Derived from backend role helpers, permission service concepts, route dependencies and module manifests.",
        "role_mapping": {
            "owner": {
                "scope": "全部权限",
                "code_basis": [
                    "backend/app/core/roles.py:is_owner_role",
                    "backend/app/services/permission_service.py:EffectivePermissions.is_owner_full_access",
                    "frontend/src/lib/permissions.ts:createOwnerFullAccessPermissions",
                ],
            },
            "super_admin": {
                "scope": "所属组织",
                "code_basis": [
                    "backend/app/schemas/user.py:is_user_manager_role",
                    "backend/app/api/routes/users.py:non-owner list is constrained by org_context/organization_id",
                    "frontend/src/components/permission-route-guard.tsx:super_admin user route exception only for productized user management",
                ],
            },
            "user": {
                "scope": "限制访问",
                "code_basis": [
                    "backend/app/services/module_registry.py:build_module_access_state missing permissions lock/hide modules",
                    "backend/app/middleware/permission.py:enforce_permission_isolation",
                    "frontend/src/lib/frontend-capability-state.ts:hidden/locked state handling",
                ],
            },
        },
        "module_permissions": [
            {
                "module_key": module["module_key"],
                "required_permissions": module["required_permissions"],
                "permission_manifest": module["permission_manifest"],
            }
            for module in modules
        ],
        "route_permission_control_points": permission_control_points,
        "ui_enforcement": {
            "hidden_technical_modules": sorted(PRODUCT_HIDDEN_MODULE_KEYS),
            "productized_routes": sorted(TARGET_MODULE_KEYS),
            "guard_file": "frontend/src/components/permission-route-guard.tsx",
        },
    }
    write_json(ROOT / "permission_mapping_report.json", permission_report)

    print(
        json.dumps(
            {
                "generated": [
                    "frontend_ui_productization_report.json",
                    "exposed_backend_capabilities_report.json",
                    "missing_feature_analysis_report.json",
                    "permission_mapping_report.json",
                ],
                "critical_missing_bindings": len(critical_missing),
                "backend_routes": len(routes),
                "frontend_api_calls": len(frontend_calls),
                "modules": len(manifests),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
