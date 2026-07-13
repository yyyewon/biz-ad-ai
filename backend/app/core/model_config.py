"""
backend/config/model.yaml 기반 모델 설정 로더.

역할:
- backend/config/model.yaml을 읽는다.
- active_profile 기준으로 현재 provider 조합을 반환한다.
- text_generation / image_generation 역할별 provider를 반환한다.
- provider별 기본 모델 설정을 반환한다.
- OpenAI / HuggingFace / Hybrid 실험을 위한 공통 설정 접근점을 제공한다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CONFIG_PATH = BACKEND_ROOT / "config" / "model.yaml"


def _candidate_config_paths() -> list[Path]:
    """
    model.yaml 후보 경로를 반환한다.

    우선순위:
    1. MODEL_CONFIG_PATH 환경변수
    2. backend/config/model.yaml
    3. Docker 컨테이너 기준 /app/config/model.yaml
    """

    candidates: list[Path] = []

    env_path = os.getenv("MODEL_CONFIG_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())

    candidates.append(DEFAULT_MODEL_CONFIG_PATH)
    candidates.append(Path("/app/config/model.yaml"))

    return candidates


def resolve_model_config_path() -> Path:
    """
    실제 사용할 model.yaml 경로를 찾는다.
    """

    candidates = _candidate_config_paths()

    for path in candidates:
        if path.exists():
            return path

    raise AppException(
        errors.MODEL_CONFIG_NOT_FOUND,
        detail={
            "searched_paths": [str(path) for path in candidates],
            "hint": "backend/config/model.yaml 또는 MODEL_CONFIG_PATH 값을 확인하세요.",
        },
    )


@lru_cache(maxsize=1)
def load_model_config() -> dict[str, Any]:
    """
    model.yaml 전체를 읽어서 dict로 반환한다.

    서버 실행 중에는 캐시된다.
    설정 파일을 수정한 뒤에는 서버 재시작 또는 reload_model_config()가 필요하다.
    """

    config_path = resolve_model_config_path()

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}

    except yaml.YAMLError as exc:
        raise AppException(
            errors.MODEL_CONFIG_INVALID_YAML,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise AppException(
            errors.MODEL_CONFIG_LOAD_FAILED,
            detail=str(exc),
        ) from exc

    if not isinstance(config, dict):
        raise AppException(
            errors.MODEL_CONFIG_INVALID_TYPE,
            detail={"config_path": str(config_path)},
        )

    validate_model_config(config)

    logger.info("model_config_loaded | path={}", str(config_path))

    return config


def reload_model_config() -> dict[str, Any]:
    """
    개발/테스트 중 캐시를 비우고 model.yaml을 다시 읽는다.
    """

    load_model_config.cache_clear()
    return load_model_config()


def validate_model_config(config: dict[str, Any]) -> None:
    """
    model.yaml의 최소 필수 구조를 검증한다.
    """

    required_top_keys = {
        "version",
        "active_profile",
        "profiles",
        "runtime",
        "output_image",
        "image_preprocess",
        "logging",
        "openai",
        "hf",
    }

    missing_top_keys = required_top_keys - set(config.keys())

    if missing_top_keys:
        raise AppException(
            errors.MODEL_CONFIG_MISSING_KEYS,
            detail={"missing_keys": sorted(missing_top_keys)},
        )

    active_profile = config.get("active_profile")
    profiles = config.get("profiles")

    if not isinstance(profiles, dict) or not profiles:
        raise AppException(
            errors.MODEL_PROFILES_INVALID,
            detail={"profiles": profiles},
        )

    if active_profile not in profiles:
        raise AppException(
            errors.MODEL_ACTIVE_PROFILE_NOT_FOUND,
            detail={
                "active_profile": active_profile,
                "available_profiles": list(profiles.keys()),
            },
        )

    valid_providers = {"openai", "hf"}

    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise AppException(
                errors.MODEL_PROFILE_INVALID,
                detail={
                    "profile_name": profile_name,
                    "profile": profile,
                },
            )

        for role_key in ["text_generation_provider", "image_generation_provider"]:
            provider_name = profile.get(role_key)

            if provider_name not in valid_providers:
                raise AppException(
                    errors.MODEL_PROVIDER_INVALID,
                    detail={
                        "profile_name": profile_name,
                        "role_key": role_key,
                        "provider_name": provider_name,
                        "valid_providers": sorted(valid_providers),
                    },
                )


def get_model_config(section: str | None = None, default: Any = None) -> Any:
    """
    전체 config 또는 특정 section을 반환한다.

    예:
    - get_model_config()
    - get_model_config("openai")
    - get_model_config("hf")
    """

    config = load_model_config()

    if section is None:
        return config

    return config.get(section, default)


def get_active_profile_name() -> str:
    """
    현재 active_profile 이름을 반환한다.
    """

    config = load_model_config()
    return str(config["active_profile"])


def get_profiles() -> dict[str, Any]:
    """
    profiles 전체를 반환한다.
    """

    config = load_model_config()
    profiles = config["profiles"]

    if not isinstance(profiles, dict):
        raise AppException(
            errors.MODEL_PROFILES_INVALID,
            detail={"profiles": profiles},
        )

    return profiles


def get_active_profile() -> dict[str, Any]:
    """
    active_profile에 해당하는 provider 조합을 반환한다.
    """

    active_profile_name = get_active_profile_name()
    profiles = get_profiles()

    profile = profiles.get(active_profile_name)

    if not isinstance(profile, dict):
        raise AppException(
            errors.MODEL_ACTIVE_PROFILE_INVALID,
            detail={
                "active_profile": active_profile_name,
                "profile": profile,
            },
        )

    return profile


def get_provider_name(role: str) -> str:
    """
    현재 active_profile에서 특정 역할의 provider 이름을 반환한다.

    role options:
    - text_generation
    - image_generation
    """

    profile = get_active_profile()
    key = f"{role}_provider"

    provider_name = profile.get(key)

    if not provider_name:
        raise AppException(
            errors.MODEL_PROVIDER_NOT_SET,
            detail={
                "role": role,
                "expected_key": key,
                "active_profile": get_active_profile_name(),
                "profile": profile,
            },
        )

    return str(provider_name)


def get_provider_section(provider_name: str) -> dict[str, Any]:
    """
    provider 전체 설정을 반환한다.

    provider_name options:
    - openai
    - hf
    """

    config = load_model_config()
    provider_config = config.get(provider_name)

    if not isinstance(provider_config, dict):
        raise AppException(
            errors.MODEL_PROVIDER_SECTION_NOT_FOUND,
            detail={
                "provider_name": provider_name,
                "available_top_keys": list(config.keys()),
            },
        )

    return provider_config


def get_role_section(provider_name: str, role: str) -> dict[str, Any]:
    """
    provider 내부의 역할별 설정을 반환한다.

    예:
    - get_role_section("openai", "text_generation")
    - get_role_section("hf", "image_generation")
    """

    provider_config = get_provider_section(provider_name)
    role_config = provider_config.get(role)

    if not isinstance(role_config, dict):
        raise AppException(
            errors.MODEL_ROLE_SECTION_NOT_FOUND,
            detail={
                "provider_name": provider_name,
                "role": role,
                "available_keys": list(provider_config.keys()),
            },
        )

    return role_config


def get_model_settings(
    role: str,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    역할별 실제 사용할 모델 설정을 반환한다.

    provider_name을 생략하면 active_profile 기준 provider를 사용한다.
    model_name을 생략하면 해당 role의 default_model을 사용한다.

    반환 예:
    {
      "provider": "openai",
      "role": "text_generation",
      "model_name": "gpt-4o-mini",
      "settings": {...}
    }
    """

    if provider_name is None:
        provider_name = get_provider_name(role)

    role_config = get_role_section(provider_name, role)

    selected_model_name = model_name or role_config.get("default_model")

    if not selected_model_name:
        raise AppException(
            errors.MODEL_DEFAULT_MODEL_NOT_SET,
            detail={
                "provider_name": provider_name,
                "role": role,
            },
        )

    models = role_config.get("models", {})

    if not isinstance(models, dict):
        raise AppException(
            errors.MODEL_LIST_INVALID,
            detail={
                "provider_name": provider_name,
                "role": role,
                "models": models,
            },
        )

    selected_model_settings = models.get(selected_model_name)

    if not isinstance(selected_model_settings, dict):
        raise AppException(
            errors.MODEL_SETTINGS_NOT_FOUND,
            detail={
                "provider_name": provider_name,
                "role": role,
                "model_name": selected_model_name,
                "available_models": list(models.keys()),
            },
        )

    return {
        "provider": provider_name,
        "role": role,
        "model_name": str(selected_model_name),
        "settings": selected_model_settings,
    }


def get_text_generation_settings() -> dict[str, Any]:
    """
    현재 active_profile 기준 광고 문구 생성 모델 설정을 반환한다.
    """

    return get_model_settings("text_generation")


def get_image_generation_settings() -> dict[str, Any]:
    """
    현재 active_profile 기준 광고 이미지 생성 모델 설정을 반환한다.
    """

    return get_model_settings("image_generation")


def get_image_preprocess_settings() -> dict[str, Any]:
    """
    이미지 전처리 설정을 반환한다.
    """

    config = load_model_config()
    settings = config.get("image_preprocess", {})

    if not isinstance(settings, dict):
        raise AppException(
            errors.IMAGE_PREPROCESS_CONFIG_INVALID,
            detail={"image_preprocess": settings},
        )

    return settings


def get_output_image_settings() -> dict[str, Any]:
    """
    최종 출력 이미지 설정을 반환한다.
    """

    config = load_model_config()
    settings = config.get("output_image", {})

    if not isinstance(settings, dict):
        raise AppException(
            errors.OUTPUT_IMAGE_CONFIG_INVALID,
            detail={"output_image": settings},
        )

    return settings


def get_variant_image_size(variant: str) -> str:
    """
    model.yaml output_image.variant_sizes에서 유형별 해상도를 반환한다.
    """

    settings = get_output_image_settings()
    variant_sizes = settings.get("variant_sizes")

    if not isinstance(variant_sizes, dict):
        raise AppException(
            errors.OUTPUT_IMAGE_CONFIG_INVALID,
            detail={"missing": "output_image.variant_sizes"},
        )

    size = variant_sizes.get(variant)
    if not size:
        raise AppException(
            errors.OUTPUT_IMAGE_CONFIG_INVALID,
            detail={
                "missing_variant": variant,
                "variant_sizes": variant_sizes,
            },
        )

    return str(size)


def get_performance_logging_settings() -> dict[str, Any]:
    """
    성능 로그 설정을 반환한다.
    """

    config = load_model_config()

    logging_config = config.get("logging", {})
    if not isinstance(logging_config, dict):
        raise AppException(
            errors.PERFORMANCE_LOGGING_CONFIG_INVALID,
            detail={"logging": logging_config},
        )

    performance_config = logging_config.get("performance", {})
    if not isinstance(performance_config, dict):
        raise AppException(
            errors.PERFORMANCE_LOGGING_CONFIG_INVALID,
            detail={"performance": performance_config},
        )

    return performance_config