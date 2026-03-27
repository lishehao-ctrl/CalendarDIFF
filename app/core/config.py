from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_api_key: str = "dev-api-key-change-me"
    app_secret_key: str = "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk="
    public_web_origins: str = "http://localhost:8200,http://127.0.0.1:8200"
    frontend_app_base_url: str | None = None

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_test"
    evidence_dir: str = "./evidence"
    enable_notifications: bool = True

    schema_guard_enabled: bool = True

    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 20.0
    http_max_retries: int = 2

    oauth_public_base_url: str | None = None
    oauth_route_prefix: str = ""
    oauth_session_route_template: str = "/sources/{source_id}/oauth-sessions"
    oauth_callback_route_template: str = "/oauth/callbacks/{provider}"
    oauth_callback_require_api_key: bool = False
    oauth_state_ttl_minutes: int = 10
    oauth_token_encryption_key: str | None = None
    auth_rate_limit_max_requests: int = 10
    auth_rate_limit_window_seconds: int = 60
    mutation_rate_limit_max_requests: int = 30
    mutation_rate_limit_window_seconds: int = 60
    mcp_public_require_bearer_token: bool = True
    webhook_max_body_bytes: int = 65536
    webhook_metadata_preview_max_bytes: int = 2048

    gmail_oauth_client_secrets_file: str | None = None
    gmail_oauth_scope: str = "https://www.googleapis.com/auth/gmail.readonly"
    gmail_oauth_access_type: str = "offline"
    gmail_oauth_prompt: str = "consent"
    gmail_oauth_include_granted_scopes: bool = True
    gmail_api_base_url: str = "https://gmail.googleapis.com/gmail/v1/users/me"
    gmail_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    gmail_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    gmail_secondary_filter_mode: str = "off"
    gmail_secondary_filter_provider: str = "noop"
    gmail_secondary_filter_min_confidence: float = 0.995
    gmail_secondary_filter_endpoint_url: str | None = Field(default=None)
    gmail_secondary_filter_api_token: str | None = Field(default=None)
    gmail_secondary_filter_timeout_seconds: float = 8.0
    gmail_secondary_filter_max_input_chars: int = 1200
    gmail_secondary_filter_min_batch_size: int = 11
    gmail_message_parse_cache_enabled: bool = True
    gmail_purpose_mode_cache_enabled: bool = True
    gmail_purpose_mode_fingerprint_reuse_enabled: bool = True
    calendar_component_parse_cache_enabled: bool = True
    llm_base_url: str | None = None
    llm_responses_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float | None = None
    llm_max_retries: int | None = None
    llm_max_input_chars: int | None = None
    llm_extra_body_json: str | None = None
    ingestion_llm_session_cache_enabled: bool = True
    agent_generation_mode: str = "deterministic"
    llm_price_qwen_us_main_input_per_1m_usd: float | None = None
    llm_price_qwen_us_main_cached_input_per_1m_usd: float | None = None
    llm_price_qwen_us_main_output_per_1m_usd: float | None = None
    llm_price_qwen_us_chat_input_per_1m_usd: float | None = None
    llm_price_qwen_us_chat_cached_input_per_1m_usd: float | None = None
    llm_price_qwen_us_chat_output_per_1m_usd: float | None = None
    llm_request_window_seconds: int = 60
    llm_max_requests_per_window: int = 480
    llm_gateway_trace_persistence_enabled: bool = True

    redis_url: str | None = None
    ingest_service_enable_scheduler: bool = True
    llm_queue_stream_key: str = "llm:parse:stream"
    llm_queue_group: str = "llm-parse-workers"
    llm_queue_consumer_poll_ms: int = 500
    llm_worker_concurrency: int = 12
    llm_retry_base_seconds: int = 30
    llm_retry_max_seconds: int = 600
    llm_retry_jitter_seconds: int = 5
    llm_max_retry_attempts: int = 6
    llm_claim_timeout_seconds: int = 300
    gmail_parse_max_workers: int = 12
    gmail_fetch_metadata_max_workers: int = 12
    gmail_continuation_max_message_ids: int = 5000
    gmail_continuation_max_matched_buffer: int = 2000
    gmail_connector_chunk_max_seconds: float = 30.0
    ics_max_payload_bytes: int = 2 * 1024 * 1024
    ics_max_components: int = 5000
    ics_parse_max_seconds: float = 10.0

    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_use_tls: bool = False
    smtp_from_name: str | None = Field(default="CalendarDIFF")
    smtp_from_email: str = Field(default="no-reply@example.com")
    notify_sink_mode: str = "smtp"
    notify_jsonl_path: str = "data/smoke/notify_sink.jsonl"

    default_email: str | None = Field(default=None)
    app_base_url: str | None = None
    public_api_base_url: str | None = None

    digest_fixed_timezone: str = "America/Los_Angeles"
    digest_fixed_times: str = "09:00,18:00"

    default_changes_limit: int = 50
    max_changes_limit: int = 200
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_timezone_name: str = "America/Los_Angeles"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
