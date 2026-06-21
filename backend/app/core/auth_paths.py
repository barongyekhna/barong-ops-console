AUTH_LOGIN_PATHS = frozenset(("/auth/login", "/api/public/auth/login"))
AUTH_ME_PATHS = frozenset(("/auth/me", "/api/public/auth/me"))


def is_auth_login_path(path: str) -> bool:
    return path in AUTH_LOGIN_PATHS


def is_auth_me_path(path: str) -> bool:
    return path in AUTH_ME_PATHS
