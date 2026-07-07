"""
OpenAI 이미지 생성 provider.

역할:
- backend/config/model.yaml의 openai.image_generation 설정을 사용한다.
- OpenAI 이미지 편집(images.edit)과 이미지 생성(images.generate)을 담당한다.
- 생성 결과를 서버 파일로 저장하지 않고 bytes로 반환한다.
- 실패 시 문자열/ValueError가 아니라 AppException을 발생시킨다.

주의:
- API Key는 .env / app.core.config에서 관리한다.
- 모델명, size, quality, output_format 등은 backend/config/model.yaml에서 관리한다.
"""

from __future__ import annotations

from typing import Any

import os

from loguru import logger
from openai import OpenAI

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_section
from app.services.providers.base import ImageGenerationProvider
from app.utils.image_bytes import bytes_to_named_file, decode_base64_to_image_bytes


class OpenAIImageProvider(ImageGenerationProvider):
    """
    OpenAI 이미지 생성 provider.

    반환 기준:
    - 기존: list[Path]
    - 변경: list[bytes]

    서버 디스크에 생성 이미지를 저장하지 않는다.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        size: str | None = None,
        quality: str | None = None,
        output_format: str | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> None:
        resolved = get_model_settings(
            role="image_generation",
            provider_name="openai",
            model_name=model,
        )

        self._model = str(model or resolved["model_name"])
        self._settings = model_settings or resolved["settings"]

        self._size = str(size or self._settings.get("size") or get_settings().openai_image_size)
        self._quality = quality or self._settings.get("quality")
        self._output_format = str(output_format or self._settings.get("output_format", "png"))

        self._api_key = api_key or self._resolve_api_key()

        if not self._api_key:
            raise AppException(
                errors.OPENAI_API_KEY_MISSING,
                detail={
                    "provider": "openai",
                    "role": "image_generation",
                    "model": self._model,
                },
            )

        self._client = OpenAI(api_key=self._api_key)

    @staticmethod
    def _resolve_api_key() -> str:
        """
        OpenAI API Key를 찾는다.

        우선순위:
        1. model.yaml의 openai.api_key_env 환경변수
        2. 기존 Settings.openai_api_key
        """

        openai_config = get_provider_section("openai")
        api_key_env = str(openai_config.get("api_key_env", "OPENAI_API_KEY"))

        return os.getenv(api_key_env) or get_settings().openai_api_key

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def size(self) -> str:
        return self._size

    @property
    def quality(self) -> str | None:
        return self._quality

    @property
    def output_format(self) -> str:
        return self._output_format

    def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
    ) -> list[bytes]:
        """
        입력 이미지를 기반으로 광고 이미지를 생성한다.

        파일 저장 없이 OpenAI SDK에 BytesIO file-like object를 전달하고,
        OpenAI 응답의 b64_json을 bytes로 변환해 반환한다.
        """

        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "openai",
                    "role": "image_generation",
                    "reason": "input_image_bytes_empty",
                },
            )

        output_images: list[bytes] = []

        logger.info(
            "openai_image_generation_started | model={} | size={} | quality={} | num_images={} | has_mask={}",
            self._model,
            self._size,
            self._quality,
            num_images,
            bool(mask_image_bytes),
        )

        try:
            for idx in range(num_images):
                image_file = bytes_to_named_file(
                    input_image_bytes,
                    filename=f"source_{idx + 1}.png",
                )

                if mask_image_bytes:
                    mask_file = bytes_to_named_file(
                        mask_image_bytes,
                        filename=f"mask_{idx + 1}.png",
                    )

                    result = self._client.images.edit(
                        **self._build_image_edit_kwargs(
                            image=image_file,
                            prompt=prompt,
                            mask=mask_file,
                        )
                    )
                else:
                    result = self._client.images.edit(
                        **self._build_image_edit_kwargs(
                            image=image_file,
                            prompt=prompt,
                        )
                    )

                output_images.append(self._extract_first_image_bytes(result=result))

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "openai_image_generation_failed | model={} | size={} | error={}",
                self._model,
                self._size,
                str(exc),
            )
            raise AppException(
                errors.OPENAI_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "openai",
                    "role": "image_generation",
                    "model": self._model,
                    "size": self._size,
                    "error": str(exc),
                },
            ) from exc

        logger.info(
            "openai_image_generation_completed | model={} | generated_count={}",
            self._model,
            len(output_images),
        )

        return output_images

    def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        """
        배경 이미지만 생성한다.

        파일 저장 없이 OpenAI 응답의 b64_json을 bytes로 변환해 반환한다.
        """

        output_images: list[bytes] = []

        logger.info(
            "openai_background_generation_started | model={} | size={} | quality={} | num_images={}",
            self._model,
            self._size,
            self._quality,
            num_images,
        )

        try:
            for _ in range(num_images):
                result = self._client.images.generate(
                    **self._build_image_generate_kwargs(prompt=prompt)
                )

                output_images.append(self._extract_first_image_bytes(result=result))

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "openai_background_generation_failed | model={} | size={} | error={}",
                self._model,
                self._size,
                str(exc),
            )
            raise AppException(
                errors.OPENAI_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "openai",
                    "role": "image_generation",
                    "model": self._model,
                    "size": self._size,
                    "error": str(exc),
                },
            ) from exc

        logger.info(
            "openai_background_generation_completed | model={} | generated_count={}",
            self._model,
            len(output_images),
        )

        return output_images

    def _build_image_edit_kwargs(
        self,
        *,
        image: Any,
        prompt: str,
        mask: Any | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "image": image,
            "prompt": prompt,
            "size": self._size,
        }

        if mask is not None:
            kwargs["mask"] = mask

        if self._quality:
            kwargs["quality"] = self._quality

        if self._output_format:
            kwargs["output_format"] = self._output_format

        return kwargs

    def _build_image_generate_kwargs(self, *, prompt: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "size": self._size,
        }

        if self._quality:
            kwargs["quality"] = self._quality

        if self._output_format:
            kwargs["output_format"] = self._output_format

        return kwargs

    def _extract_first_image_bytes(self, *, result: Any) -> bytes:
        """
        OpenAI Images API 응답에서 첫 번째 이미지 b64_json을 bytes로 변환한다.
        """

        image_b64 = result.data[0].b64_json

        if not image_b64:
            raise AppException(
                errors.OPENAI_IMAGE_RESPONSE_EMPTY,
                detail={
                    "provider": "openai",
                    "role": "image_generation",
                    "model": self._model,
                },
            )

        return decode_base64_to_image_bytes(image_b64)
