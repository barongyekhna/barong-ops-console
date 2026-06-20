from __future__ import annotations

import re
from collections.abc import Iterable

from ..schemas.approval import ApprovalCategory, ApprovalDisplayInfo

CONTROL_PLANE_CATEGORY: ApprovalCategory = "control_plane"
FEATURE_CATEGORY: ApprovalCategory = "feature"

CONTROL_PLANE_MODULE_PREFIXES = (
    "admin.",
    "system.",
    "core.",
    "permission.",
    "permissions.",
)
CONTROL_PLANE_MARKERS = (
    "architecture",
    "permission",
    "permissions",
    "rbac",
    "module.bind",
    "module_binding",
    "module-access",
    "module_access",
    "settings",
)
C_SERIES_PATTERN = re.compile(r"^(?:c|C)(?:-?series|[0-9]{1,3}[a-zA-Z]?)")

ACTION_LABELS = {
    "business.products.placeholder.prepare": "准备产品上架草稿",
    "business.products.prepare": "准备产品上架草稿",
    "business.products.submit": "提交产品上架审批",
    "business.reviews.decision": "提交业务评审结论",
    "admin.permissions.manage": "调整权限配置",
    "admin.users.manage": "调整用户或账号配置",
    "admin.modules.manage": "接入或调整业务模块",
    "modules.manage": "接入或调整业务模块",
    "system.architecture.change": "提交系统架构变更",
}

MODULE_LABELS = {
    "business.approvals": "审批",
    "business.products": "产品",
    "business.reviews": "评审",
    "business.artifacts": "资料",
    "admin.permissions": "权限",
    "admin.users": "用户",
    "admin.modules": "模块",
    "system.settings": "系统设置",
}

STATUS_LABELS = {
    "pending": "待审批",
    "approved": "已同意",
    "rejected": "已拒绝",
    "auto_approved": "已自动通过",
}

RISK_LABELS = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}


def approval_category_from_keys(
    *,
    module_key: str,
    action_key: str | None = None,
    adapter_key: str | None = None,
    explicit_category: str | None = None,
) -> ApprovalCategory:
    if explicit_category in {CONTROL_PLANE_CATEGORY, FEATURE_CATEGORY}:
        return explicit_category  # type: ignore[return-value]

    values = [module_key, action_key or "", adapter_key or ""]
    normalized_values = [value.strip() for value in values if value.strip()]
    lowered = " ".join(value.lower() for value in normalized_values)
    module = module_key.strip()

    if any(C_SERIES_PATTERN.match(value) for value in normalized_values):
        return CONTROL_PLANE_CATEGORY
    if module.startswith(CONTROL_PLANE_MODULE_PREFIXES):
        return CONTROL_PLANE_CATEGORY
    if any(marker in lowered for marker in CONTROL_PLANE_MARKERS):
        return CONTROL_PLANE_CATEGORY
    return FEATURE_CATEGORY


def approval_category_label(category: str) -> str:
    if category == CONTROL_PLANE_CATEGORY:
        return "主控审批"
    return "功能审批"


def approval_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "待审批")


def approval_risk_label(risk_level: str) -> str:
    return RISK_LABELS.get(risk_level, "标准风险")


def approval_module_label(module_key: str, category: str) -> str:
    if module_key in MODULE_LABELS:
        return MODULE_LABELS[module_key]
    lowered = module_key.lower()
    if category == CONTROL_PLANE_CATEGORY:
        if "permission" in lowered:
            return "权限"
        if "module" in lowered:
            return "模块接入"
        if "architecture" in lowered or lowered.startswith(("c", "system.")):
            return "系统架构"
        return "系统主控"
    if lowered.startswith("k") or "knowledge" in lowered:
        return "知识"
    if lowered.startswith("p") or "product" in lowered:
        return "产品"
    if lowered.startswith("business."):
        return "业务"
    return "业务"


def approval_action_label(action_key: str, module_key: str, category: str) -> str:
    if action_key in ACTION_LABELS:
        return ACTION_LABELS[action_key]

    lowered = f"{module_key} {action_key}".lower()
    if category == CONTROL_PLANE_CATEGORY:
        if "permission" in lowered or "rbac" in lowered:
            return "提交权限变更审批"
        if "module" in lowered:
            return "提交模块接入审批"
        if "architecture" in lowered or "system" in lowered:
            return "提交系统架构变更"
        return "提交系统级操作审批"
    if "knowledge" in lowered or lowered.startswith("k"):
        return "提交知识内容审批"
    if "product" in lowered or lowered.startswith("p"):
        return "准备产品上架草稿"
    if "review" in lowered:
        return "提交业务评审审批"
    return "提交业务模块审批"


def approval_display_info(
    *,
    module_key: str,
    action_key: str,
    category: str,
    status: str,
    risk_level: str,
) -> ApprovalDisplayInfo:
    module_label = approval_module_label(module_key, category)
    action_label = approval_action_label(action_key, module_key, category)
    return ApprovalDisplayInfo(
        title=action_label,
        category_label=approval_category_label(category),
        module_label=module_label,
        action_label=action_label,
        status_label=approval_status_label(status),
        risk_label=approval_risk_label(risk_level),
        summary=f"{module_label}模块已完成草稿，即将提交审批",
    )


def module_permission_tokens(permission_keys: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for permission_key in permission_keys:
        module_segment = permission_key.split(".", 1)[0].strip().lower()
        if module_segment and module_segment != "*":
            tokens.add(module_segment)
    return tokens


def module_key_matches_permission_tokens(
    module_key: str,
    tokens: Iterable[str],
) -> bool:
    normalized = module_key.strip().lower()
    if not normalized:
        return False
    module_parts = {
        part
        for segment in normalized.split(".")
        for part in (segment, *segment.split("_"))
        if part
    }
    for token in tokens:
        token = token.strip().lower()
        if not token:
            continue
        if token in module_parts:
            return True
        if normalized == token or normalized.endswith(f".{token}"):
            return True
    return False
