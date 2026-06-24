LIGHTWEIGHT_CONTROL_PLANE_PATHS = frozenset(
    (
        "/api/control-plane/modules/me",
        "/api/control-plane/modules/registry",
        "/api/control-plane/module-control/center",
    )
)

FULL_SECURITY_PIPELINE_PREFIXES = (
    "/api/app/users",
    "/api/app/permissions",
    "/api/app/reviews",
    "/api/app/approval",
    "/api/app/approvals",
)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def is_lightweight_control_plane_path(path: str) -> bool:
    return path in LIGHTWEIGHT_CONTROL_PLANE_PATHS


def is_full_security_pipeline_path(path: str) -> bool:
    return any(
        _path_matches_prefix(path, prefix)
        for prefix in FULL_SECURITY_PIPELINE_PREFIXES
    )
