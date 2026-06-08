from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_DATABASE_URL = (
    "postgresql+psycopg://"
    "barong_console_example:barong_console_example"
    "@db:5432/barong_console_example"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_name: str = "barong-ops-console-backend"
    app_env: str = "development"
    app_version: str = "0.1.0"
    database_url: str = EXAMPLE_DATABASE_URL
    auth_token_secret: SecretStr | None = None
    auth_token_expire_minutes: int = Field(default=60, gt=0, le=1440)
    owner_username: str | None = None
    owner_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
