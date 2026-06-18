PRODUCTION_ENV_NAMES = frozenset({"production", "prod"})
STAGING_ENV_NAMES = frozenset({"staging", "stage"})
DEVELOPMENT_ENV_NAMES = frozenset(
    {"development", "dev", "local", "test", "testing"}
)


def _environment_value(settings_or_env: object) -> str | None:
    if settings_or_env is None or isinstance(settings_or_env, str):
        return settings_or_env
    value = getattr(settings_or_env, "app_env", None)
    return value if isinstance(value, str) else None


def normalize_environment(settings_or_env: object) -> str:
    value = _environment_value(settings_or_env)
    environment = (value or "development").strip().lower()
    if not environment:
        return "development"
    if environment in PRODUCTION_ENV_NAMES:
        return "production"
    if environment in STAGING_ENV_NAMES:
        return "staging"
    if environment in DEVELOPMENT_ENV_NAMES:
        return "development"
    return environment


def is_production(settings_or_env: object) -> bool:
    return normalize_environment(settings_or_env) == "production"


def is_staging(settings_or_env: object) -> bool:
    return normalize_environment(settings_or_env) == "staging"


def is_development(settings_or_env: object) -> bool:
    return normalize_environment(settings_or_env) == "development"


def is_production_like(settings_or_env: object) -> bool:
    return is_production(settings_or_env) or is_staging(settings_or_env)
