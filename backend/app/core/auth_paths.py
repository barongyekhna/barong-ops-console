AUTH_ME_PATHS = frozenset(("/auth/me", "/api/public/auth/me"))


def is_auth_me_path(path: str) -> bool:
    return path in AUTH_ME_PATHS
