"""Configuration from environment variables (prefix ``WALTRIX_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WALTRIX_", env_file=".env", extra="ignore")

    environment: str = "development"  # development | test | production
    database_url: str = "postgresql://waltrix@127.0.0.1:4822/waltrix"
    # Exact origins allowed to call the API from a browser with credentials.
    cors_origins: list[str] = Field(default_factory=list)
    # Set True behind HTTPS. Forced on in production.
    cookie_secure: bool = False
    session_cookie_name: str = "waltrix_session"
    # Must match the public path of the API (e.g. "/shared/ide/proxy/4820/api" behind a prefix proxy).
    session_cookie_path: str = "/api"
    # Optional: serve the built dashboard (apps/web/dist) from the API process (single origin).
    web_dist: str | None = None
    # Requests per minute per credential (or per IP when unauthenticated).
    rate_limit_per_minute: int = 600
    login_rate_limit_per_minute: int = 10
    # Number of reverse proxies whose X-Forwarded-For we trust (0 = ignore header).
    trusted_proxy_count: int = 0
    log_level: str = "INFO"
    log_json: bool = True
    db_pool_size: int = 10

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
