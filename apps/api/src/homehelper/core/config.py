from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    release_id: str = "dev"

    # Repo-relative by default (commands run from the repo root); a mounted volume in containers.
    data_dir: Path = Path("data")
    releases_dir: Path = Path("releases")
    web_whitelist_path: Path = Path("config/web_whitelist.yaml")
    # Knowledge-base snapshot to serve; None = the newest `ready` kb_version (spec §10.3, §17.3).
    kb_version: str | None = None

    database_url: str = "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    llama_cloud_api_key: SecretStr = SecretStr("")
    cohere_api_key: SecretStr = SecretStr("")
    tavily_api_key: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")  # `tutorials` uses mock videos when empty

    # MCP servers (spec §12.1). "mock" serves `data/mock/` from memory with no external calls;
    # "real" uses Postgres mock tables and external APIs where a key is configured.
    mcp_mode: Literal["real", "mock"] = "real"
    # When set, the mounted `/mcp/*` endpoints require `Authorization: Bearer <token>`.
    mcp_auth_token: SecretStr = SecretStr("")

    # Web API (spec §13.2, §18.1). An empty session secret is only allowed locally and in tests.
    session_secret: SecretStr = SecretStr("")
    session_max_age_s: int = 7 * 24 * 3600
    admin_token: SecretStr = SecretStr("")
    # Browser origins allowed to call the API (CORS) and to send write requests (Origin check).
    cors_origins: list[str] = ["http://localhost:3000"]
    # Turn guards (spec §18.1): messages per IP and per user, and the daily LLM spend cap in USD
    # (spec Q7; 0 disables it). Over the cap the API answers in maintenance mode.
    rate_limit_per_hour: int = 30
    rate_limit_per_day: int = 100
    login_rate_limit_per_hour: int = 20  # demo logins per IP (each guest login is a new user)
    daily_spend_cap_usd: float = 5.0

    # OpenCode Go subscription gateway; eval experiments only, via `opencode_go/...` model
    # overrides (docs/SPEC.md §9.1). Never a default in models.yaml.
    opencode_go_api_key: SecretStr = SecretStr("")
    opencode_go_base_url: str = "https://opencode.ai/inference/go"

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )

    @property
    def manuals_dir(self) -> Path:
        return self.data_dir / "manuals"

    @property
    def mock_dir(self) -> Path:
        return self.data_dir / "mock"

    def provider_api_keys(self) -> dict[str, str]:
        """LiteLLM provider name → API key, for providers that are configured."""
        keys = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "opencode_go": self.opencode_go_api_key,
        }
        values = {provider: key.get_secret_value() for provider, key in keys.items()}
        return {provider: value for provider, value in values.items() if value}

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
