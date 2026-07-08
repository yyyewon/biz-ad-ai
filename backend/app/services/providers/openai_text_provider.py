"""
OpenAI 텍스트 생성 provider.

역할:
- backend/config/model.yaml의 openai.text_generation 설정을 사용한다.
- gpt-4o-mini 계열은 chat_completions 방식으로 호출한다.
- gpt-5 계열처럼 responses API가 필요한 모델은 responses 방식으로 호출한다.
- 실패 시 문자열을 반환하지 않고 AppException을 발생시킨다.

주의:
- API Key는 .env / app.core.config에서 관리한다.
- 모델명, api_type, temperature, max_tokens 등은 backend/config/model.yaml에서 관리한다.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger
from openai import OpenAI

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_section


class OpenAITextProvider:
    """
    OpenAI 텍스트 생성 provider.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> None:
        resolved = get_model_settings(
            role="text_generation",
            provider_name="openai",
            model_name=model_name,
        )

        self.model_name = str(model_name or resolved["model_name"])
        self.model_settings = model_settings or resolved["settings"]
        self.api_key = api_key or self._resolve_api_key()

        if not self.api_key:
            raise AppException(
                errors.OPENAI_API_KEY_MISSING,
                detail={
                    "provider": "openai",
                    "role": "text_generation",
                    "model": self.model_name,
                },
            )

        self.client = OpenAI(api_key=self.api_key)

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

    def generate_text(
        self,
        prompt: str,
        system_instruction: str = "너는 친절하고 유능한 카피라이터야.",
    ) -> str:
        """
        모델 설정의 api_type에 따라 OpenAI 텍스트 생성을 수행한다.
        """

        api_type = str(self.model_settings.get("api_type", "chat_completions"))

        logger.info(
            "openai_text_generation_started | model={} | api_type={}",
            self.model_name,
            api_type,
        )

        try:
            if api_type == "chat_completions":
                result = self._generate_with_chat_completions(
                    prompt=prompt,
                    system_instruction=system_instruction,
                )

            elif api_type == "responses":
                result = self._generate_with_responses(
                    prompt=prompt,
                    system_instruction=system_instruction,
                )

            else:
                raise AppException(
                    errors.PROVIDER_NOT_SUPPORTED,
                    detail={
                        "provider": "openai",
                        "role": "text_generation",
                        "model": self.model_name,
                        "api_type": api_type,
                        "supported_api_types": ["chat_completions", "responses"],
                    },
                )

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "openai_text_generation_failed | model={} | api_type={} | error={}",
                self.model_name,
                api_type,
                str(exc),
            )
            raise AppException(
                errors.OPENAI_TEXT_GENERATION_FAILED,
                detail={
                    "provider": "openai",
                    "role": "text_generation",
                    "model": self.model_name,
                    "api_type": api_type,
                    "error": str(exc),
                },
            ) from exc

        if not result:
            raise AppException(
                errors.OPENAI_TEXT_RESPONSE_EMPTY,
                detail={
                    "provider": "openai",
                    "role": "text_generation",
                    "model": self.model_name,
                    "api_type": api_type,
                },
            )

        logger.info(
            "openai_text_generation_completed | model={} | api_type={} | output_chars={}",
            self.model_name,
            api_type,
            len(result),
        )

        return result

    def _generate_with_chat_completions(
        self,
        *,
        prompt: str,
        system_instruction: str,
    ) -> str:
        """
        Chat Completions API 방식 호출.
        """

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            temperature=float(self.model_settings.get("temperature", 0.7)),
            max_tokens=int(self.model_settings.get("max_tokens", 800)),
        )

        content = response.choices[0].message.content

        return (content or "").strip()

    def _generate_with_responses(
        self,
        *,
        prompt: str,
        system_instruction: str,
    ) -> str:
        """
        Responses API 방식 호출.

        gpt-5 계열 설정을 YAML에서 분리해서 관리하기 위한 경로다.
        """

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
        }

        max_output_tokens = self.model_settings.get("max_output_tokens")
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = int(max_output_tokens)

        reasoning_effort = self.model_settings.get("reasoning_effort")
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": str(reasoning_effort)}

        verbosity = self.model_settings.get("verbosity")
        if verbosity:
            kwargs["text"] = {"verbosity": str(verbosity)}

        response = self.client.responses.create(**kwargs)

        return self._extract_responses_text(response)

    @staticmethod
    def _extract_responses_text(response: Any) -> str:
        """
        Responses API 응답에서 텍스트를 안전하게 추출한다.
        """

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = getattr(response, "output", None)
        if not output:
            return ""

        chunks: list[str] = []

        for item in output:
            content = getattr(item, "content", None)

            if content is None and isinstance(item, dict):
                content = item.get("content")

            if not content:
                continue

            for content_item in content:
                text = getattr(content_item, "text", None)

                if text is None and isinstance(content_item, dict):
                    text = content_item.get("text")

                if isinstance(text, str) and text:
                    chunks.append(text)

        return "\n".join(chunks).strip()
