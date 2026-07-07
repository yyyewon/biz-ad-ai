from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Biz Ad AI Backend"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: str = "http://localhost:8501"
    output_dir: Path = Field(default=Path("outputs"))

    openai_api_key: str = Field(default="")
    openai_image_model: str = Field(default="gpt-image-1-mini")
    openai_image_size: str = Field(default="1024x1536")
    openai_text_model: str = Field(default="gpt-4o-mini")

    jwt_secret_key: str = Field(default="CHANGE_ME_DEV_ONLY_SECRET")
    jwt_expires_seconds: int = Field(default=60 * 60 * 24 * 7)
    kakao_client_id: str = Field(default="")
    kakao_client_secret: str = Field(default="")
    kakao_redirect_uri: str = Field(default="http://localhost:8010/api/v1/auth/kakao/callback")
    frontend_base_url: str = Field(default="http://localhost:8501")
    dev_tools_enabled: bool = Field(default=False)

    generation_max_concurrent: int = Field(default=2)
    generation_queue_timeout_seconds: float = Field(default=15.0)
    daily_generation_limit: int = Field(default=3)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return settings
