from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_api_key: str = "dev-api-key-change-me"
    app_secret_key: str = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_test"
    evidence_dir: str = "./evidence"
    enable_notifications: bool = True

    default_sync_interval_minutes: int = 15
    scheduler_tick_seconds: int = 60
    disable_scheduler: bool = False
    schema_guard_enabled: bool = True
    scheduler_instance_id: str | None = None
    sync_runs_retention_days: int = 30

    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 20.0
    http_max_retries: int = 2

    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: str | None = None
    gmail_oauth_redirect_uri: str | None = None
    gmail_oauth_scope: str = "https://www.googleapis.com/auth/gmail.readonly"

    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_USERNAME", "SMTP_USER"))
    smtp_password: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_PASSWORD", "SMTP_PASS"))
    smtp_use_tls: bool = False
    smtp_from_email: str = Field(
        default="no-reply@example.com", validation_alias=AliasChoices("SMTP_FROM_EMAIL", "SMTP_FROM")
    )

    default_notify_email: str | None = Field(
        default=None, validation_alias=AliasChoices("DEFAULT_NOTIFY_EMAIL", "SMTP_TO")
    )
    app_base_url: str | None = None

    global_scheduler_lock_key: int = Field(default=947123)
    input_lock_namespace: int = Field(default=947124)
    digest_scheduler_lock_key: int = Field(default=947125)
    digest_fixed_timezone: str = "America/Los_Angeles"
    digest_fixed_times: str = "09:00,18:00"

    default_changes_limit: int = 50
    max_changes_limit: int = 200


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
