from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Biz Ad AI Backend"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    output_dir: Path = Field(default=Path("outputs"))
    openai_api_key: str = Field(default="")
    openai_image_model: str = Field(default="gpt-image-1-mini")
    openai_image_size: str = Field(default="1024x1536")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return settings
