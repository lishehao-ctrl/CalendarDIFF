from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    app_api_key: str = "dev-api-key-change-me"
    app_secret_key: str = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff"
    evidence_dir: str = "./evidence"
    enable_notifications: bool = False

    default_sync_interval_minutes: int = 15
    scheduler_tick_seconds: int = 60
    disable_scheduler: bool = False

    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 20.0
    http_max_retries: int = 2

    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    smtp_from_email: str = "no-reply@example.com"

    default_notify_email: str | None = None
    app_base_url: str | None = None

    global_scheduler_lock_key: int = Field(default=947123)
    source_lock_namespace: int = Field(default=947124)

    default_changes_limit: int = 50
    max_changes_limit: int = 200


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
