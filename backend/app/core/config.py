"""
.env 기반 애플리케이션 설정.

이 파일의 역할:
- 비밀값 관리
- 배포 환경별 값 관리
- 앱 실행 설정 관리

예:
- OPENAI_API_KEY
- HF_TOKEN
- JWT_SECRET_KEY
- KAKAO_CLIENT_ID
- CORS_ALLOWED_ORIGINS
- FRONTEND_BASE_URL
- OUTPUT_DIR
- 생성 제한값

주의:
- 모델 선택, provider 조합, temperature, image size, HF model_id 같은
  실험 파라미터는 여기서 관리하지 않는다.
- 모델 관련 설정은 backend/config/model.yaml에서 관리한다.

구분:
.env / app/core/config.py
→ 비밀값, 배포환경값, 앱 설정

backend/config/model.yaml
→ 모델 선택, provider 조합, 실험 파라미터
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    .env 파일에서 읽는 런타임 설정.

    이 Settings는 모델 실험 설정이 아니라
    앱 실행 환경과 민감정보를 관리한다.
    """

    # ============================================================
    # App settings
    # ============================================================

    app_name: str = "Biz Ad AI Backend"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    # ============================================================
    # CORS / frontend settings
    # ============================================================

    cors_allowed_origins: str = "http://localhost:8501"
    frontend_base_url: str = "http://localhost:8501"

    # ============================================================
    # Provider secrets
    # ============================================================
    #
    # 모델명, temperature, image size 등은 model.yaml에서 관리한다.
    # API Key / Token만 .env에서 관리한다.

    openai_api_key: str = Field(default="")
    hf_token: str = Field(default="")

    # ============================================================
    # Legacy OpenAI fallback settings
    # ============================================================
    #
    # 이전 코드 호환용 fallback 값이다.
    # 신규 로직에서는 backend/config/model.yaml 값을 우선 사용한다.
    # 안정화 이후 제거 가능하다.

    # openai_image_model: str = Field(default="gpt-image-1-mini")
    # openai_image_size: str = Field(default="1024x1536")
    # openai_text_model: str = Field(default="gpt-4o-mini")

    # ============================================================
    # Auth / JWT settings
    # ============================================================

    jwt_secret_key: str = Field(default="")
    jwt_expires_seconds: int = Field(default=60 * 60 * 24 * 7)

    # ============================================================
    # Kakao login settings
    # ============================================================

    kakao_client_id: str = Field(default="")
    kakao_client_secret: str = Field(default="")
    kakao_redirect_uri: str = Field(
        default="http://localhost:8010/api/v1/auth/kakao/callback"
    )

    # ============================================================
    # Dev / quota settings
    # ============================================================

    dev_tools_enabled: bool = Field(default=False)
    generation_max_concurrent: int = Field(default=2)
    generation_queue_timeout_seconds: float = Field(default=15.0)
    daily_generation_limit: int = Field(default=3)

    # ============================================================
    # Model loading / warmup safety
    # ============================================================

    # Heavy models are lazy-loaded by default so starting the API process does
    # not consume the host's RAM before it can serve health checks.
    model_warmup_enabled: bool = Field(default=False)
    warmup_hf_image_enabled: bool = Field(default=True)
    warmup_poster_vlm_enabled: bool = Field(default=False)
    warmup_food_classifier_enabled: bool = Field(default=False)
    warmup_poster_layout_enabled: bool = Field(default=True)

    # Set to 0 to disable the pre-load system RAM guard explicitly.
    model_load_min_available_ram_gb: float = Field(default=6.0, ge=0.0)

    # CPU offload lowers VRAM use but can increase system RAM pressure.
    hf_image_cpu_offload_enabled: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Settings singleton을 반환한다.

    현재 서버는 생성 이미지를 디스크에 저장하지 않는다.
    """

    settings = Settings()
    return settings
