from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values come from the environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Cisco Security Automation Platform"
    csap_version: str = "0.9.0"
    environment: Literal["development", "staging", "production"] = "production"
    log_level: str = "INFO"
    # Interactive API docs enumerate every endpoint; opt in when you need them.
    enable_api_docs: bool = False

    database_url: str
    redis_url: str

    secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    access_token_expire_minutes: int = 60
    jwt_algorithm: str = "HS256"

    data_dir: str = "/data"
    public_url: str = "https://localhost"

    csap_admin_email: str = "admin@example.com"
    csap_admin_password: str = Field(min_length=12)

    @field_validator("secret_key", "credential_encryption_key", "csap_admin_password")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be set; run scripts/install.sh to generate secrets")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
