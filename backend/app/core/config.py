from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
