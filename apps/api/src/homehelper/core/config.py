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

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )

    @property
    def manuals_dir(self) -> Path:
        return self.data_dir / "manuals"

    def provider_api_keys(self) -> dict[str, str]:
        """LiteLLM provider name → API key, for providers that are configured."""
        keys = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }
        values = {provider: key.get_secret_value() for provider, key in keys.items()}
        return {provider: value for provider, value in values.items() if value}

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
